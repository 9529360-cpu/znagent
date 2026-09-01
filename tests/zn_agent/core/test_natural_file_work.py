from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, time, timedelta
from pathlib import Path

from zn_agent.core import ExecutionPath
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger


TASK = (
    "找到这里昨天改过、名字像报价的那个 txt，"
    "把草稿改成最终版，保存后再读回来确认"
)


class NaturalFileWorkAcceptanceTests(unittest.TestCase):
    @staticmethod
    def _stamp(path: Path, day_offset: int) -> None:
        local_now = datetime.now().astimezone()
        target_date = local_now.date() + timedelta(days=day_offset)
        when = datetime.combine(target_date, time(hour=12), tzinfo=local_now.tzinfo)
        stamp = when.timestamp()
        os.utime(path, (stamp, stamp))

    @staticmethod
    def _event_actions(resident, event_id: str):
        return [
            item
            for item in reversed(resident.body.recent_actions(512))
            if item.event_id == event_id
        ]

    @staticmethod
    def _run_to_terminal(resident, event_id: str, limit: int = 192):
        for _ in range(limit):
            completed = resident.result_for(event_id)
            if completed is not None:
                return completed
            result = resident.live_once()
            if result is not None and result.event.event_id == event_id:
                return result
        state = resident.store.get_working_state()
        raise AssertionError(
            f"event did not terminate; stage={state.stage} next={state.next_action}"
        )

    @staticmethod
    def _advance_until_stage(resident, event_id: str, stage: str, limit: int = 128) -> None:
        for _ in range(limit):
            state = resident.store.get_working_state()
            if state.current_event_id == event_id and state.stage == stage:
                return
            result = resident.live_once()
            if result is not None:
                raise AssertionError(f"event reached terminal result before {stage}: {result}")
        state = resident.store.get_working_state()
        raise AssertionError(
            f"event did not reach stage {stage}; stage={state.stage} next={state.next_action}"
        )

    @staticmethod
    def _plain_work(base: Path, workspace: Path, *, thread_id: str):
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=base / "kernel.db",
        )
        ledger = RecoveryBoundedWorkLedger(resident)
        thread = ledger.create_thread(thread_id=thread_id)
        ledger.attach_workspace(thread.thread_id, workspace)
        return resident, ledger, thread

    def test_plain_work_compares_multiple_yesterday_candidates_edits_and_freshly_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()

            target = workspace / "客户报价-华东.txt"
            yesterday_other = workspace / "客户报价-华南.txt"
            today = workspace / "客户报价-华北.txt"
            old = workspace / "客户报价-历史.txt"
            wrong_name = workspace / "客户合同.txt"

            target.write_text("项目：A\n状态：草稿\n", encoding="utf-8")
            yesterday_other.write_text("项目：B\n状态：最终版\n", encoding="utf-8")
            today.write_text("项目：C\n状态：草稿\n", encoding="utf-8")
            old.write_text("项目：D\n状态：草稿\n", encoding="utf-8")
            wrong_name.write_text("项目：E\n状态：草稿\n", encoding="utf-8")
            self._stamp(target, -1)
            self._stamp(yesterday_other, -1)
            self._stamp(today, 0)
            self._stamp(old, -3)
            self._stamp(wrong_name, -1)

            nested = workspace / "nested"
            nested.mkdir()
            nested_decoy = nested / "客户报价-隐藏.txt"
            nested_decoy.write_text("状态：草稿\n", encoding="utf-8")
            self._stamp(nested_decoy, -1)

            before = {
                item.name: item.read_text(encoding="utf-8")
                for item in workspace.iterdir()
                if item.is_file()
            }
            nested_before = nested_decoy.read_text(encoding="utf-8")

            resident, ledger, thread = self._plain_work(
                base,
                workspace,
                thread_id="natural-file-work",
            )
            snapshot, run = ledger.submit(thread.thread_id, TASK)

            self.assertTrue(run.success, run)
            self.assertEqual(run.execution_path, ExecutionPath.BODY)
            self.assertEqual(run.model_invocations, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "项目：A\n状态：最终版\n")
            for name, text in before.items():
                if name != target.name:
                    self.assertEqual((workspace / name).read_text(encoding="utf-8"), text)
            self.assertEqual(nested_decoy.read_text(encoding="utf-8"), nested_before)

            event = run.event
            self.assertEqual(event.kind, "desktop_user_event")
            self.assertEqual(event.task, TASK)
            self.assertEqual(event.payload["workspace_path"], str(workspace.resolve()))
            for forbidden in ("path", "file", "content", "text", "body_action", "native_action"):
                self.assertNotIn(forbidden, event.payload)
            self.assertNotIn(target.name, TASK)
            self.assertNotIn(str(target), TASK)

            investigation = resident.investigator.current(event.event_id)
            self.assertIsNotNone(investigation)
            assert investigation is not None
            discovery = investigation.facts.get("natural_file_candidates")
            comparison = investigation.facts.get("natural_file_candidate_comparison")
            identity = investigation.facts.get("natural_file_identity")
            self.assertIsInstance(discovery, dict)
            self.assertIsInstance(comparison, dict)
            self.assertIsInstance(identity, dict)
            assert isinstance(discovery, dict)
            assert isinstance(comparison, dict)
            assert isinstance(identity, dict)
            self.assertTrue(discovery["candidate_set_complete"])
            self.assertEqual(discovery["matching_name_count"], 4)
            self.assertEqual(discovery["yesterday_candidate_count"], 2)
            self.assertTrue(comparison["complete"])
            self.assertEqual(comparison["selected"]["path"], str(target.resolve()))
            self.assertEqual(
                {row["path"]: row["source_count"] for row in comparison["candidates"]},
                {
                    str(target.resolve()): 1,
                    str(yesterday_other.resolve()): 0,
                },
            )
            self.assertTrue(identity["digest_complete"])
            self.assertEqual(identity["path"], str(target.resolve()))

            actions = self._event_actions(resident, event.event_id)
            self.assertEqual(len([item for item in actions if item.kind == "list_directory"]), 1)
            self.assertEqual(len([item for item in actions if item.kind == "write_text"]), 1)
            self.assertFalse([item for item in actions if item.kind.startswith("browser_")])
            reads = [item for item in actions if item.kind == "read_text"]
            reads_before_write = []
            write_index = next(i for i, item in enumerate(actions) if item.kind == "write_text")
            for item in actions[:write_index]:
                if item.kind == "read_text":
                    reads_before_write.append(str(item.data.get("path") or ""))
            self.assertIn(str(target.resolve()), reads_before_write)
            self.assertIn(str(yesterday_other.resolve()), reads_before_write)
            self.assertGreaterEqual(len(reads), 4)
            later_reads = [item for item in actions[write_index + 1 :] if item.kind == "read_text"]
            self.assertTrue(later_reads)
            self.assertEqual(later_reads[-1].output, "项目：A\n状态：最终版\n")
            if os.name == "nt":
                write = next(item for item in actions if item.kind == "write_text")
                self.assertTrue(str(write.data.get("write_strategy") or ""))

            self.assertEqual([message.role for message in snapshot[1]], ["user", "zn", "activity"])
            self.assertEqual(snapshot[1][0].text, TASK)
            self.assertEqual(snapshot[1][1].text, str(target.resolve()))
            resident.store.close()

    def test_plain_work_stops_when_two_yesterday_candidates_still_match_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            first = workspace / "客户报价-A.txt"
            second = workspace / "客户报价-B.txt"
            third = workspace / "客户报价-C.txt"
            first.write_text("项目：A\n状态：草稿\n", encoding="utf-8")
            second.write_text("项目：B\n状态：草稿\n", encoding="utf-8")
            third.write_text("项目：C\n状态：最终版\n", encoding="utf-8")
            for target in (first, second, third):
                self._stamp(target, -1)

            resident, ledger, thread = self._plain_work(
                base,
                workspace,
                thread_id="natural-file-ambiguous",
            )
            snapshot, run = ledger.submit(thread.thread_id, TASK)

            self.assertFalse(run.success)
            self.assertEqual(run.execution_path, ExecutionPath.BUDGET_BLOCKED)
            self.assertEqual(run.model_invocations, 0)
            self.assertIn("more than one", run.reason.lower())
            self.assertEqual(first.read_text(encoding="utf-8"), "项目：A\n状态：草稿\n")
            self.assertEqual(second.read_text(encoding="utf-8"), "项目：B\n状态：草稿\n")
            self.assertEqual(third.read_text(encoding="utf-8"), "项目：C\n状态：最终版\n")

            actions = self._event_actions(resident, run.event.event_id)
            self.assertEqual(len([item for item in actions if item.kind == "list_directory"]), 1)
            self.assertFalse([item for item in actions if item.kind == "write_text"])
            compared = {
                str(item.data.get("path") or "")
                for item in actions
                if item.kind == "read_text"
            }
            self.assertIn(str(first.resolve()), compared)
            self.assertIn(str(second.resolve()), compared)
            self.assertIn(str(third.resolve()), compared)
            self.assertFalse([item for item in actions if item.kind.startswith("browser_")])
            self.assertEqual([message.role for message in snapshot[1]], ["user", "zn", "activity"])
            resident.store.close()

    def test_external_change_after_selected_read_blocks_stale_overwrite_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            target = workspace / "客户报价-华东.txt"
            other = workspace / "客户报价-华南.txt"
            target.write_text("项目：A\n状态：草稿\n", encoding="utf-8")
            other.write_text("项目：B\n状态：最终版\n", encoding="utf-8")
            self._stamp(target, -1)
            self._stamp(other, -1)

            resident, ledger, thread = self._plain_work(
                base,
                workspace,
                thread_id="natural-file-race",
            )
            _, event = ledger.start(thread.thread_id, TASK)
            self._advance_until_stage(resident, event.event_id, "native_action")

            target.write_text("项目：A\n状态：外部更新\n", encoding="utf-8")
            run = self._run_to_terminal(resident, event.event_id)

            self.assertFalse(run.success)
            self.assertEqual(run.model_invocations, 0)
            self.assertIn("identity no longer matches", run.reason.lower())
            self.assertEqual(target.read_text(encoding="utf-8"), "项目：A\n状态：外部更新\n")
            actions = self._event_actions(resident, event.event_id)
            self.assertFalse([item for item in actions if item.kind == "write_text"])
            resident.store.close()

    def test_workspace_enumeration_bound_refuses_incomplete_top_level_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            for index in range(65):
                path = workspace / f"候选-{index:03d}.txt"
                path.write_text("状态：最终版\n", encoding="utf-8")
                self._stamp(path, -1)
            target = workspace / "客户报价-目标.txt"
            target.write_text("状态：草稿\n", encoding="utf-8")
            self._stamp(target, -1)

            resident, ledger, thread = self._plain_work(
                base,
                workspace,
                thread_id="natural-file-bounded",
            )
            _, run = ledger.submit(thread.thread_id, TASK)

            self.assertFalse(run.success)
            self.assertEqual(run.execution_path, ExecutionPath.BUDGET_BLOCKED)
            self.assertEqual(run.model_invocations, 0)
            self.assertIn("bounded", run.reason.lower())
            self.assertEqual(target.read_text(encoding="utf-8"), "状态：草稿\n")
            actions = self._event_actions(resident, run.event.event_id)
            self.assertEqual(len([item for item in actions if item.kind == "list_directory"]), 1)
            self.assertFalse([item for item in actions if item.kind == "write_text"])
            resident.store.close()

    def test_multiple_source_occurrences_stop_without_guessing_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            target = workspace / "客户报价-华东.txt"
            target.write_text("草稿\n中间\n草稿\n", encoding="utf-8")
            self._stamp(target, -1)

            resident, ledger, thread = self._plain_work(
                base,
                workspace,
                thread_id="natural-file-position",
            )
            _, run = ledger.submit(thread.thread_id, TASK)

            self.assertFalse(run.success)
            self.assertEqual(run.model_invocations, 0)
            self.assertIn("more than once", run.reason.lower())
            self.assertEqual(target.read_text(encoding="utf-8"), "草稿\n中间\n草稿\n")
            actions = self._event_actions(resident, run.event.event_id)
            self.assertFalse([item for item in actions if item.kind == "write_text"])
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
