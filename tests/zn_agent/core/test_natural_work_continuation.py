from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work import WorkMessage
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


class NaturalWorkContinuationTests(unittest.TestCase):
    @staticmethod
    def _runtime(path: Path):
        return build_resident_runtime(config={"model": {}}, store_path=path)

    def test_latest_reference_reuses_exact_active_event_from_an_empty_ui_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._runtime(db)
            try:
                ledger = RecoveryBoundedWorkLedger(resident)
                control = RestoreAwareWorkControl(ledger)
                ledger.create_thread(thread_id="real-work", title="Real work")
                _, event = ledger.start("real-work", "unfinished resident task")
                ledger.create_thread(thread_id="ui-shell", title="New work")

                snapshot, resumed = control.start("ui-shell", "刚才那个继续")

                self.assertEqual(snapshot[0].thread_id, "real-work")
                self.assertEqual(resumed.event_id, event.event_id)
                self.assertEqual(resumed.task, "unfinished resident task")
                self.assertEqual(ledger.get_run(event.event_id).thread_id, "real-work")
                self.assertEqual(ledger.list_messages("ui-shell"), [])
                messages = ledger.list_messages("real-work")
                self.assertEqual([item.text for item in messages], ["unfinished resident task", "刚才那个继续"])
                self.assertTrue(messages[-1].detail["continuation"])
                self.assertFalse(messages[-1].detail["new_resident_event"])

                progress = control.progress("ui-shell", event.event_id)
                self.assertEqual(progress["thread_id"], "real-work")
                self.assertEqual(progress["event_id"], event.event_id)
                self.assertFalse(progress["terminal"])
            finally:
                resident.store.close()

    def test_active_reference_does_not_silently_drop_new_followup_instruction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(Path(tmp) / "kernel.db")
            try:
                ledger = RecoveryBoundedWorkLedger(resident)
                control = RestoreAwareWorkControl(ledger)
                ledger.create_thread(thread_id="active", title="Active")
                _, event = ledger.start("active", "unfinished resident task")
                ledger.create_thread(thread_id="shell", title="New work")

                with self.assertRaisesRegex(ValueError, "still active"):
                    control.start("shell", "刚才那个继续，再做另一件事")

                self.assertEqual(ledger._active_run_for_thread("active").event_id, event.event_id)
                self.assertEqual(ledger.list_messages("shell"), [])
                self.assertEqual(
                    [item.text for item in ledger.list_messages("active")],
                    ["unfinished resident task"],
                )
            finally:
                resident.store.close()

    def test_rpc_work_start_can_resolve_continuation_to_another_durable_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(Path(tmp) / "kernel.db")
            server = ResidentRpcServer(resident=resident)
            try:
                created = server.handle(
                    {"id": "create-real", "method": "work_create", "params": {"thread_id": "real", "title": "Real"}}
                )
                self.assertTrue(created["ok"])
                started = server.handle(
                    {"id": "start-real", "method": "work_start", "params": {"thread_id": "real", "task": "unfinished rpc task"}}
                )
                self.assertTrue(started["ok"])
                event_id = started["result"]["progress"]["event_id"]
                shell = server.handle(
                    {"id": "create-shell", "method": "work_create", "params": {"thread_id": "shell", "title": "New work"}}
                )
                self.assertTrue(shell["ok"])

                resumed = server.handle(
                    {"id": "resume", "method": "work_start", "params": {"thread_id": "shell", "task": "刚才那个继续"}}
                )

                self.assertTrue(resumed["ok"])
                self.assertEqual(resumed["result"]["thread"]["id"], "real")
                self.assertEqual(resumed["result"]["progress"]["thread_id"], "real")
                self.assertEqual(resumed["result"]["progress"]["event_id"], event_id)
                self.assertFalse(resumed["result"]["progress"]["terminal"])
                self.assertEqual(server.work.list_messages("shell"), [])
            finally:
                resident.store.close()

    def test_restart_keeps_the_same_work_event_for_natural_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = self._runtime(db)
            ledger = RecoveryBoundedWorkLedger(first)
            ledger.create_thread(thread_id="persistent", title="Persistent work")
            _, event = ledger.start("persistent", "unfinished across restart")
            event_id = event.event_id
            first.store.close()

            restored = self._runtime(db)
            try:
                restored_ledger = RecoveryBoundedWorkLedger(restored)
                restored_ledger.create_thread(thread_id="fresh-ui", title="New work")
                control = RestoreAwareWorkControl(restored_ledger)

                snapshot, resumed = control.start("fresh-ui", "上次那个继续")

                self.assertEqual(snapshot[0].thread_id, "persistent")
                self.assertEqual(resumed.event_id, event_id)
                self.assertEqual(restored_ledger.get_run(event_id).thread_id, "persistent")
                self.assertIsNone(restored_ledger.get_run(resumed.event_id).finalized_at)
            finally:
                restored.store.close()

    def test_completed_work_with_explicit_followup_starts_fresh_event_in_same_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(Path(tmp) / "kernel.db")
            try:
                ledger = RecoveryBoundedWorkLedger(resident)
                control = RestoreAwareWorkControl(ledger)
                ledger.create_thread(thread_id="project", title="Project")
                _, first = ledger.submit("project", "unknown completed project step")
                previous_event_id = first.event.event_id
                previous_finalized_at = ledger.get_run(previous_event_id).finalized_at
                previous_outcome = resident.store.get_event_outcome(previous_event_id)
                self.assertIsNotNone(previous_finalized_at)
                self.assertIsNotNone(previous_outcome)
                ledger.create_thread(thread_id="shell", title="New work")

                snapshot, followup = control.start(
                    "shell",
                    "刚才那个继续，再检查当前结果并处理下一步",
                    kind="desktop_user_event",
                    payload={"model_policy": "never"},
                )

                self.assertEqual(snapshot[0].thread_id, "project")
                self.assertNotEqual(followup.event_id, previous_event_id)
                self.assertEqual(ledger.get_run(followup.event_id).thread_id, "project")
                self.assertEqual(ledger.get_run(previous_event_id).finalized_at, previous_finalized_at)
                context = followup.payload["work_continuation"]
                self.assertEqual(context["mode"], "completed_followup")
                self.assertEqual(context["previous_event_id"], previous_event_id)
                self.assertEqual(context["previous_task_excerpt"], "unknown completed project step")
                self.assertEqual(context["previous_outcome_success"], previous_outcome.success)
                self.assertEqual(context["previous_execution_path"], previous_outcome.execution_path.value)
                self.assertLessEqual(len(context["previous_result_excerpt"]), 500)
                self.assertEqual(context["followup"], "再检查当前结果并处理下一步")
                self.assertTrue(context["requires_fresh_resense"])
                self.assertFalse(context["replay_previous_event"])
                cognition = followup.payload["cognition_question"]
                self.assertIn("Historical prior task, context only", cognition)
                self.assertIn("unknown completed project step", cognition)
                self.assertIn("New objective: 再检查当前结果并处理下一步", cognition)
                self.assertIn("Re-sense the current computer", cognition)
                self.assertIn("replay of the previous event is forbidden", cognition)
                self.assertEqual(followup.payload["model_policy"], "never")
                self.assertEqual(ledger.list_messages("shell"), [])
                progress = control.progress("shell", followup.event_id)
                self.assertEqual(progress["thread_id"], "project")
                self.assertFalse(progress["terminal"])
            finally:
                resident.store.close()

    def test_completed_latest_work_is_never_replayed_by_bare_continue_wording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(Path(tmp) / "kernel.db")
            try:
                ledger = RecoveryBoundedWorkLedger(resident)
                control = RestoreAwareWorkControl(ledger)
                ledger.create_thread(thread_id="done", title="Done")
                _, run = ledger.submit("done", "unknown task with no external brain")
                self.assertIsNotNone(run)
                before_events = [item.event_id for item in resident.store.list_events(limit=64)]
                ledger.create_thread(thread_id="shell", title="New work")

                with self.assertRaisesRegex(ValueError, "say what should happen next"):
                    control.start("shell", "刚才那个继续")

                after_events = [item.event_id for item in resident.store.list_events(limit=64)]
                self.assertEqual(after_events, before_events)
                self.assertEqual(ledger.list_messages("shell"), [])
            finally:
                resident.store.close()

    def test_yesterday_reference_fails_closed_when_more_than_one_thread_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(Path(tmp) / "kernel.db")
            try:
                ledger = RecoveryBoundedWorkLedger(resident)
                control = RestoreAwareWorkControl(ledger)
                yesterday = (datetime.now().astimezone() - timedelta(days=1)).isoformat()
                for thread_id in ("yesterday-a", "yesterday-b"):
                    thread = ledger.create_thread(thread_id=thread_id, title=thread_id)
                    ledger._append(
                        thread,
                        WorkMessage(
                            message_id=f"msg-{thread_id}",
                            thread_id=thread_id,
                            role="user",
                            text=f"task {thread_id}",
                            created_at=yesterday,
                        ),
                    )
                ledger.create_thread(thread_id="shell", title="New work")

                with self.assertRaisesRegex(ValueError, "more than one"):
                    control.start("shell", "昨天那个继续")
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
