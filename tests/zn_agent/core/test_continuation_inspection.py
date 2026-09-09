from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work import WorkMessage
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


TASK = "昨天那个产品继续，先看看做到哪了。"


class ContinuationInspectionTests(unittest.TestCase):
    @staticmethod
    def _runtime(path: Path):
        return build_resident_runtime(config={"model": {}}, store_path=path)

    @staticmethod
    def _yesterday() -> str:
        return (datetime.now().astimezone() - timedelta(days=1)).isoformat()

    @classmethod
    def _age_thread(cls, ledger, thread_id: str) -> None:
        thread = ledger.get_thread(thread_id)
        assert thread is not None
        thread.updated_at = cls._yesterday()
        ledger._save_thread(thread)

    def test_status_intent_classifier_is_narrow_and_requires_a_continuation_reference(self) -> None:
        accepted = (
            "昨天那个产品继续，先看看做到哪了。",
            "昨天那个继续，我先看一下进度",
            "上次那个接着做，先告诉我现在做到哪一步了",
            "上次那个继续，现在什么情况",
            "昨天那个继续，先告诉我进展",
        )
        for task in accepted:
            with self.subTest(task=task):
                self.assertIsNotNone(
                    RestoreAwareWorkControl.continuation_inspection_followup(task)
                )

        rejected = (
            "先看看做到哪了",
            "昨天那个产品",
            "昨天那个继续，再做另一件事",
            "昨天那个继续，登录先别做",
            "上次那个继续，先把核心记账跑起来",
        )
        for task in rejected:
            with self.subTest(task=task):
                self.assertIsNone(
                    RestoreAwareWorkControl.continuation_inspection_followup(task)
                )

    def test_active_inspection_reuses_exact_root_plan_and_event_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(Path(tmp) / "kernel.db")
            try:
                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
                ledger = control.ledger
                ledger.create_thread(thread_id="product", title="Product")
                _, event = ledger.start(
                    "product",
                    "开发本地记账产品",
                    objective="开发本地记账产品",
                    acceptance_criteria=["durable result"],
                )
                root = ledger.work_item_for_event(event.event_id)
                self.assertIsNotNone(root)
                self._age_thread(ledger, "product")
                ledger.create_thread(thread_id="shell", title="New work")

                before_events = [item.event_id for item in resident.store.list_events(limit=256)]
                before_workers = ledger.list_worker_runs(thread_id="product", limit=256)
                before_items = [
                    (item.work_item_id, item.status, item.plan_version, item.blocker)
                    for item in ledger.list_work_items("product", limit=256)
                ]
                before_plan = ledger.plan_version("product")
                before_model = resident.store.get_runtime_metrics().model_invocations

                snapshot, inspected = control.start("shell", TASK)
                progress = control.progress("shell", inspected.event_id)

                self.assertEqual(snapshot[0].thread_id, "product")
                self.assertEqual(inspected.event_id, event.event_id)
                self.assertEqual(ledger.work_item_for_event(event.event_id).work_item_id, root.work_item_id)
                self.assertEqual(ledger.plan_version("product"), before_plan)
                self.assertEqual(
                    [item.event_id for item in resident.store.list_events(limit=256)],
                    before_events,
                )
                self.assertEqual(ledger.list_worker_runs(thread_id="product", limit=256), before_workers)
                self.assertEqual(
                    [
                        (item.work_item_id, item.status, item.plan_version, item.blocker)
                        for item in ledger.list_work_items("product", limit=256)
                    ],
                    before_items,
                )
                self.assertEqual(resident.store.get_runtime_metrics().model_invocations, before_model)
                inspection = progress["continuation_inspection"]
                self.assertTrue(inspection["read_only"])
                self.assertTrue(inspection["inspection_complete"])
                self.assertEqual(inspection["root_goal"], "开发本地记账产品")
                self.assertEqual(inspection["plan_version"], before_plan)
                messages = ledger.list_messages("product")
                self.assertTrue(messages[-1].detail["continuation"])
                self.assertTrue(messages[-1].detail["inspection"])
                self.assertFalse(messages[-1].detail["execution_permission"])
            finally:
                resident.store.close()

    def test_inspection_then_bare_continue_reuses_same_active_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(Path(tmp) / "kernel.db")
            try:
                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
                ledger = control.ledger
                ledger.create_thread(thread_id="product", title="Product")
                _, event = ledger.start(
                    "product",
                    "unfinished product task",
                    objective="unfinished product task",
                    acceptance_criteria=["finish it"],
                )
                self._age_thread(ledger, "product")
                ledger.create_thread(thread_id="shell", title="New work")
                control.start("shell", TASK)
                before_events = [item.event_id for item in resident.store.list_events(limit=256)]
                before_plan = ledger.plan_version("product")

                snapshot, resumed = control.start("product", "那继续吧")

                self.assertEqual(snapshot[0].thread_id, "product")
                self.assertEqual(resumed.event_id, event.event_id)
                self.assertEqual(
                    [item.event_id for item in resident.store.list_events(limit=256)],
                    before_events,
                )
                self.assertEqual(ledger.plan_version("product"), before_plan)
                self.assertFalse(ledger.list_messages("product")[-1].detail.get("inspection", False))
            finally:
                resident.store.close()

    def test_yesterday_inspection_ambiguity_and_zero_match_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(Path(tmp) / "kernel.db")
            try:
                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
                ledger = control.ledger
                ledger.create_thread(thread_id="shell", title="New work")
                before_model = resident.store.get_runtime_metrics().model_invocations

                with self.assertRaisesRegex(ValueError, "no durable Work from yesterday"):
                    control.start("shell", TASK)
                self.assertEqual(resident.store.get_runtime_metrics().model_invocations, before_model)

                yesterday = self._yesterday()
                for thread_id in ("a", "b"):
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
                before_events = [item.event_id for item in resident.store.list_events(limit=256)]
                before_messages = {
                    thread_id: len(ledger.list_messages(thread_id))
                    for thread_id in ("a", "b", "shell")
                }
                with self.assertRaisesRegex(ValueError, "more than one"):
                    control.start("shell", TASK)
                self.assertEqual(
                    [item.event_id for item in resident.store.list_events(limit=256)],
                    before_events,
                )
                self.assertEqual(
                    {
                        thread_id: len(ledger.list_messages(thread_id))
                        for thread_id in ("a", "b", "shell")
                    },
                    before_messages,
                )
                self.assertEqual(resident.store.get_runtime_metrics().model_invocations, before_model)
            finally:
                resident.store.close()

    def test_completed_yesterday_work_can_be_inspected_but_bare_replay_stays_forbidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(Path(tmp) / "kernel.db")
            try:
                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
                ledger = control.ledger
                ledger.create_thread(thread_id="done", title="Done")
                _, completed = ledger.submit(
                    "done",
                    "unknown completed product step",
                    objective="completed product step",
                    acceptance_criteria=["terminal evidence"],
                )
                event_id = completed.event.event_id
                self.assertIsNotNone(ledger.get_run(event_id).finalized_at)
                self._age_thread(ledger, "done")
                ledger.create_thread(thread_id="shell", title="New work")
                before_events = [item.event_id for item in resident.store.list_events(limit=256)]

                snapshot, inspected = control.start("shell", TASK)
                progress = control.progress("shell", inspected.event_id)

                self.assertEqual(snapshot[0].thread_id, "done")
                self.assertEqual(inspected.event_id, event_id)
                self.assertIn("continuation_inspection", progress)
                self.assertEqual(
                    [item.event_id for item in resident.store.list_events(limit=256)],
                    before_events,
                )
                with self.assertRaisesRegex(ValueError, "already complete"):
                    control.start("done", "继续")
                self.assertEqual(
                    [item.event_id for item in resident.store.list_events(limit=256)],
                    before_events,
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
