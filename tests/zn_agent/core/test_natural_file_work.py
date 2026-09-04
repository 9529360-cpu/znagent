from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, time, timedelta
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger

TASK = "找到这里昨天改过、名字像报价的那个 txt，把草稿改成最终版，保存后再读回来确认"


class NaturalFileWorkAcceptanceTests(unittest.TestCase):
    @staticmethod
    def _stamp(path: Path, days: int) -> None:
        now = datetime.now().astimezone()
        stamp = datetime.combine(now.date() + timedelta(days=days), time(12), tzinfo=now.tzinfo).timestamp()
        os.utime(path, (stamp, stamp))

    @staticmethod
    def _setup(base: Path, workspace: Path, thread: str):
        resident = build_resident_runtime(config={"model": {}}, store_path=base / "kernel.db")
        ledger = RecoveryBoundedWorkLedger(resident)
        ledger.create_thread(thread_id=thread)
        ledger.attach_workspace(thread, workspace)
        return resident, ledger

    @staticmethod
    def _actions(resident, event_id: str):
        return [x for x in reversed(resident.body.recent_actions(512)) if x.event_id == event_id]

    @staticmethod
    def _run_to_terminal(resident, event_id: str):
        for _ in range(192):
            done = resident.result_for(event_id)
            if done is not None:
                return done
            result = resident.live_once()
            if result is not None and result.event.event_id == event_id:
                return result
        raise AssertionError(f"event did not terminate: {resident.store.get_working_state()}")

    def test_plain_work_compares_candidates_edits_and_freshly_rereads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); workspace = base / "authorized"; workspace.mkdir()
            target = workspace / "客户报价-华东.txt"
            other = workspace / "客户报价-华南.txt"
            today = workspace / "客户报价-华北.txt"
            old = workspace / "客户报价-历史.txt"
            wrong = workspace / "客户合同.txt"
            values = {
                target: "项目：A\n状态：草稿\n",
                other: "项目：B\n状态：最终版\n",
                today: "项目：C\n状态：草稿\n",
                old: "项目：D\n状态：草稿\n",
                wrong: "项目：E\n状态：草稿\n",
            }
            for path, text in values.items(): path.write_text(text, encoding="utf-8")
            for path, days in ((target,-1),(other,-1),(today,0),(old,-3),(wrong,-1)): self._stamp(path, days)
            nested = workspace / "nested"; nested.mkdir()
            decoy = nested / "客户报价-隐藏.txt"; decoy.write_text("状态：草稿\n", encoding="utf-8"); self._stamp(decoy,-1)

            resident, ledger = self._setup(base, workspace, "file-work")
            snapshot, run = ledger.submit("file-work", TASK)
            self.assertTrue(run.success, run)
            self.assertEqual(run.model_invocations, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "项目：A\n状态：最终版\n")
            self.assertEqual(other.read_text(encoding="utf-8"), values[other])
            self.assertEqual(today.read_text(encoding="utf-8"), values[today])
            self.assertEqual(old.read_text(encoding="utf-8"), values[old])
            self.assertEqual(wrong.read_text(encoding="utf-8"), values[wrong])
            self.assertEqual(decoy.read_text(encoding="utf-8"), "状态：草稿\n")

            event = run.event
            self.assertEqual(event.kind, "desktop_user_event")
            for key in ("path","file","content","text","body_action","native_action"):
                self.assertNotIn(key, event.payload)
            facts = resident.investigator.current(event.event_id).facts
            discovery = facts["natural_file_candidates"]
            comparison = facts["natural_file_candidate_comparison"]
            self.assertTrue(discovery["complete"])
            self.assertEqual(discovery["matching_name_count"], 4)
            self.assertEqual(discovery["yesterday_candidate_count"], 2)
            self.assertEqual(comparison["selected"]["path"], str(target.resolve()))
            self.assertEqual(
                {x["path"]: x["source_count"] for x in comparison["candidates"]},
                {str(target.resolve()): 1, str(other.resolve()): 0},
            )

            actions = self._actions(resident, event.event_id)
            self.assertEqual(sum(x.kind == "list_directory" for x in actions), 1)
            self.assertEqual(sum(x.kind == "write_text" for x in actions), 1)
            self.assertFalse([x for x in actions if x.kind.startswith("browser_")])
            write_at = next(i for i,x in enumerate(actions) if x.kind == "write_text")
            before = [str(x.data.get("path") or "") for x in actions[:write_at] if x.kind == "read_text"]
            self.assertIn(str(target.resolve()), before); self.assertIn(str(other.resolve()), before)
            after = [x for x in actions[write_at+1:] if x.kind == "read_text"]
            self.assertTrue(after); self.assertEqual(after[-1].output, "项目：A\n状态：最终版\n")
            self.assertEqual([x.role for x in snapshot[1]], ["user","zn","activity"])
            resident.store.close()

    def test_ambiguous_candidates_are_compared_then_stop_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); workspace=base/"authorized"; workspace.mkdir()
            files=[]
            for name,text in (("客户报价-A.txt","状态：草稿\n"),("客户报价-B.txt","状态：草稿\n"),("客户报价-C.txt","状态：最终版\n")):
                path=workspace/name; path.write_text(text,encoding="utf-8"); self._stamp(path,-1); files.append(path)
            resident,ledger=self._setup(base,workspace,"ambiguous")
            _,run=ledger.submit("ambiguous",TASK)
            self.assertFalse(run.success); self.assertEqual(run.model_invocations,0)
            self.assertIn("more than one",run.reason.lower())
            actions=self._actions(resident,run.event.event_id)
            self.assertFalse([x for x in actions if x.kind=="write_text"])
            read_paths={str(x.data.get("path") or "") for x in actions if x.kind=="read_text"}
            for path in files: self.assertIn(str(path.resolve()),read_paths)
            resident.store.close()

    def test_file_identity_change_after_read_blocks_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); workspace=base/"authorized"; workspace.mkdir()
            target=workspace/"客户报价-A.txt"; other=workspace/"客户报价-B.txt"
            target.write_text("状态：草稿\n",encoding="utf-8"); other.write_text("状态：最终版\n",encoding="utf-8")
            self._stamp(target,-1); self._stamp(other,-1)
            resident,ledger=self._setup(base,workspace,"race")
            _,event=ledger.start("race",TASK)
            for _ in range(128):
                state=resident.store.get_working_state()
                if state.current_event_id==event.event_id and state.stage=="native_action": break
                self.assertIsNone(resident.live_once())
            else: self.fail("natural file Work did not reach native_action")
            target.write_text("状态：外部更新\n",encoding="utf-8")
            run=self._run_to_terminal(resident,event.event_id)
            self.assertFalse(run.success); self.assertEqual(run.model_invocations,0)
            self.assertIn("identity no longer matches",run.reason.lower())
            self.assertEqual(target.read_text(encoding="utf-8"),"状态：外部更新\n")
            self.assertFalse([x for x in self._actions(resident,event.event_id) if x.kind=="write_text"])
            resident.store.close()

    def test_bounds_and_ambiguous_replacement_position_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); workspace=base/"authorized"; workspace.mkdir()
            for i in range(65): (workspace/f"候选-{i:03d}.txt").write_text("状态：最终版\n",encoding="utf-8")
            target=workspace/"客户报价-目标.txt"; target.write_text("状态：草稿\n",encoding="utf-8"); self._stamp(target,-1)
            resident,ledger=self._setup(base,workspace,"bounded")
            _,run=ledger.submit("bounded",TASK)
            self.assertFalse(run.success); self.assertIn("bounded",run.reason.lower())
            self.assertFalse([x for x in self._actions(resident,run.event.event_id) if x.kind=="write_text"])
            resident.store.close()

        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); workspace=base/"authorized"; workspace.mkdir()
            target=workspace/"客户报价-A.txt"; target.write_text("草稿\n中间\n草稿\n",encoding="utf-8"); self._stamp(target,-1)
            resident,ledger=self._setup(base,workspace,"position")
            _,run=ledger.submit("position",TASK)
            self.assertFalse(run.success); self.assertEqual(run.model_invocations,0)
            self.assertIn("more than once",run.reason.lower())
            self.assertEqual(target.read_text(encoding="utf-8"),"草稿\n中间\n草稿\n")
            resident.store.close()


if __name__ == "__main__": unittest.main()
