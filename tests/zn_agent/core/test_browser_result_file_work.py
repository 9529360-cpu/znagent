from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.natural_file_work_resident import NaturalFileWorkResidentRuntime
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger


TASK = (
    "检查当前页面链接的两个参考页，确认它们一致的 release code，然后找到这里昨天改过、"
    "名字像报价的那个 txt，把待确认改成查到的 release code，保存后再读回来确认"
)


class BrowserResultFileWorkTests(unittest.TestCase):
    @staticmethod
    def _stamp_yesterday(path: Path) -> None:
        now = datetime.now().astimezone()
        stamp = datetime.combine(
            now.date() - timedelta(days=1),
            time(12),
            tzinfo=now.tzinfo,
        ).timestamp()
        os.utime(path, (stamp, stamp))

    def test_normal_browser_result_file_task_is_recognized_without_engineering_targets(self) -> None:
        event = SimpleNamespace(
            kind="desktop_user_event",
            task=TASK,
            payload={"workspace_path": "/authorized"},
        )
        request = NaturalFileWorkResidentRuntime._natural_browser_result_file_request(event)
        self.assertEqual(
            request,
            {
                "workspace_path": "/authorized",
                "name_hint": "报价",
                "old_text": "待确认",
            },
        )

    def test_one_work_researches_then_edits_exact_file_and_rereads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            target = workspace / "客户报价-华东.txt"
            other = workspace / "客户报价-华南.txt"
            target.write_text("项目：A\n发布代码：待确认\n", encoding="utf-8")
            other.write_text("项目：B\n发布代码：已有\n", encoding="utf-8")
            self._stamp_yesterday(target)
            self._stamp_yesterday(other)

            resident = build_resident_runtime(
                config={"model": {}},
                store_path=base / "kernel.db",
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            ledger.create_thread(thread_id="browser-file")
            ledger.attach_workspace("browser-file", workspace)

            initial = {
                "url": "https://account.example.test/draft",
                "title": "Draft account",
                "observed_at": "2026-09-01T05:00:00+00:00",
                "references": [
                    {"href": "https://source-a.example.test/release", "text": "Reference release note"},
                    {"href": "https://source-b.example.test/registry", "text": "Reference release registry"},
                ],
            }
            research = {
                "release_code": "BUILD-91A7F",
                "sources": [
                    {
                        "source_url": "https://source-a.example.test/release",
                        "evidence_url": "https://source-a.example.test/release",
                        "release_code": "BUILD-91A7F",
                        "observed_at": "2026-09-01T05:00:01+00:00",
                    },
                    {
                        "source_url": "https://source-b.example.test/registry",
                        "evidence_url": "https://source-b.example.test/registry/detail",
                        "release_code": "BUILD-91A7F",
                        "observed_at": "2026-09-01T05:00:02+00:00",
                    },
                ],
            }
            fresh_tab = {
                "tab_id": 7,
                "url": "https://account.example.test/draft",
                "title": "Draft account refreshed",
                "observed_at": "2026-09-01T05:00:03+00:00",
            }

            try:
                with (
                    patch.object(
                        resident.user_browser_extension,
                        "authorized_tab",
                        return_value=SimpleNamespace(tab_id=7),
                    ),
                    patch.object(
                        resident,
                        "_discover_authorized_reference_context",
                        return_value=initial,
                    ) as discover,
                    patch.object(
                        resident,
                        "_research_managed_references",
                        return_value=research,
                    ) as managed_research,
                    patch.object(
                        resident,
                        "probe_user_browser_extension_tab",
                        return_value=fresh_tab,
                    ) as resense,
                ):
                    snapshot, run = ledger.submit("browser-file", TASK)

                self.assertTrue(run.success, run)
                self.assertEqual(run.model_invocations, 0)
                self.assertEqual(
                    target.read_text(encoding="utf-8"),
                    "项目：A\n发布代码：BUILD-91A7F\n",
                )
                self.assertEqual(
                    other.read_text(encoding="utf-8"),
                    "项目：B\n发布代码：已有\n",
                )
                discover.assert_called_once_with()
                managed_research.assert_called_once()
                self.assertGreaterEqual(len(managed_research.call_args.args[0]), 2)
                resense.assert_called_once_with()

                event = run.event
                facts = resident.investigator.current(event.event_id).facts
                self.assertEqual(
                    facts["natural_file_candidate_comparison"]["selected"]["path"],
                    str(target.resolve()),
                )
                research_state = facts.get(resident._BROWSER_FILE_RESEARCH_STATE_KEY)
                self.assertIsInstance(research_state, dict)
                self.assertEqual(research_state["release_code"], "BUILD-91A7F")
                self.assertEqual(len(research_state["sources"]), 2)

                actions = [
                    item
                    for item in reversed(resident.body.recent_actions(512))
                    if item.event_id == event.event_id
                ]
                self.assertEqual(sum(item.kind == "write_text" for item in actions), 1)
                write_at = next(i for i, item in enumerate(actions) if item.kind == "write_text")
                rereads = [item for item in actions[write_at + 1 :] if item.kind == "read_text"]
                self.assertTrue(rereads)
                self.assertEqual(rereads[-1].output, "项目：A\n发布代码：BUILD-91A7F\n")
                self.assertEqual([item.role for item in snapshot[1]], ["user", "zn", "activity"])
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
