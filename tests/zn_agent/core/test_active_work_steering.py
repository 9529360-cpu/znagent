from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import EventOutcome, EventStatus, ExecutionPath, utc_now
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.steerable_work import SteerableWorkLedger, WorkItem
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


STEERING = "昨天那个产品继续。登录先别做，先把核心记账跑起来，界面简单一点。"


class ActiveWorkSteeringTests(unittest.TestCase):
    @staticmethod
    def _runtime(path: Path):
        return build_resident_runtime(config={"model": {}}, store_path=path)

    @staticmethod
    def _make_yesterday(ledger: SteerableWorkLedger, thread_id: str) -> None:
        thread = ledger.get_thread(thread_id)
        assert thread is not None
        thread.updated_at = (datetime.now().astimezone() - timedelta(days=1)).isoformat()
        ledger._save_thread(thread)

    def test_exact_yesterday_product_phrase_steers_same_root_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(Path(tmp) / "kernel.db")
            try:
                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
                ledger = control.ledger
                self.assertIsInstance(ledger, SteerableWorkLedger)
                ledger.create_thread(thread_id="product", title="Personal ledger product")
                _, old_event = ledger.start(
                    "product",
                    "开发个人记账产品，先做登录和核心记账，界面做完整一点",
                )

                accepted = WorkItem(
                    work_item_id="item-accepted-research",
                    work_thread_id="product",
                    title="Market research",
                    objective="调研个人记账产品",
                    status="completed",
                    plan_version=1,
                    acceptance_criteria=["research evidence retained"],
                    result="verified market notes",
                    completed_at=utc_now(),
                )
                accepted.updated_at = accepted.completed_at or accepted.updated_at
                ledger._save_item(accepted)
                self._make_yesterday(ledger, "product")
                ledger.create_thread(thread_id="fresh-ui", title="New work")

                before_event_ids = {
                    event.event_id for event in resident.store.list_events(limit=64)
                }
                snapshot, new_event = control.start("fresh-ui", STEERING)

                self.assertEqual(snapshot[0].thread_id, "product")
                self.assertNotEqual(new_event.event_id, old_event.event_id)
                self.assertEqual(ledger.plan_version("product"), 2)
                self.assertEqual(new_event.payload["work_plan_version"], 2)
                steering = new_event.payload["work_steering"]
                self.assertEqual(steering["mode"], "active_steer")
                self.assertEqual(steering["reference"], "yesterday")
                self.assertEqual(steering["previous_event_id"], old_event.event_id)
                self.assertEqual(steering["previous_plan_version"], 1)
                self.assertEqual(steering["plan_version"], 2)
                self.assertEqual(
                    steering["objective"],
                    "登录先别做，先把核心记账跑起来，界面简单一点。",
                )
                self.assertTrue(steering["requires_fresh_resense"])
                self.assertFalse(steering["replay_previous_event"])
                cognition = new_event.payload["cognition_question"]
                self.assertIn("Re-sense the current computer", cognition)
                self.assertIn("Do not replay a prior side effect", cognition)

                old_persisted = resident.store.get_event(old_event.event_id)
                self.assertIsNotNone(old_persisted)
                self.assertEqual(old_persisted.status, EventStatus.FAILED)
                old_outcome = resident.store.get_event_outcome(old_event.event_id)
                self.assertIsNotNone(old_outcome)
                self.assertEqual(old_outcome.execution_path, ExecutionPath.CONTROL)
                self.assertIn("superseded by user steering", old_outcome.reason or "")

                old_run = ledger.get_run(old_event.event_id)
                new_run = ledger.get_run(new_event.event_id)
                self.assertEqual(old_run.ledger_state, "stale_finalized")
                self.assertEqual(new_run.ledger_state, "active")
                self.assertEqual(old_run.thread_id, "product")
                self.assertEqual(new_run.thread_id, "product")

                items = {item.work_item_id: item for item in ledger.list_work_items("product")}
                self.assertEqual(items["item-accepted-research"].status, "completed")
                self.assertEqual(items["item-accepted-research"].result, "verified market notes")
                old_item = ledger.work_item_for_event(old_event.event_id)
                new_item = ledger.work_item_for_event(new_event.event_id)
                self.assertEqual(old_item.status, "superseded")
                self.assertEqual(old_item.plan_version, 1)
                self.assertEqual(new_item.status, "running")
                self.assertEqual(new_item.plan_version, 2)

                old_progress = control.progress("product", old_event.event_id)
                self.assertTrue(old_progress["stale"])
                self.assertFalse(old_progress["accepted"])
                self.assertEqual(old_progress["current_plan_version"], 2)
                new_progress = control.progress("fresh-ui", new_event.event_id)
                self.assertEqual(new_progress["thread_id"], "product")
                self.assertEqual(new_progress["plan_version"], 2)
                self.assertEqual(new_progress["current_plan_version"], 2)
                self.assertFalse(new_progress["stale"])

                stale_activity = [
                    message
                    for message in ledger.list_messages("product")
                    if message.role == "activity"
                    and message.detail.get("event_id") == old_event.event_id
                ]
                self.assertEqual(len(stale_activity), 1)
                self.assertTrue(stale_activity[0].detail["stale"])
                self.assertFalse(stale_activity[0].detail["accepted"])
                self.assertEqual(ledger.list_messages("fresh-ui"), [])

                after_event_ids = {
                    event.event_id for event in resident.store.list_events(limit=64)
                }
                self.assertEqual(after_event_ids - before_event_ids, {new_event.event_id})
                self.assertIn(old_event.event_id, after_event_ids)
            finally:
                resident.store.close()

    def test_late_success_from_old_plan_is_retained_but_never_accepted(self) -> None:
        """E2E-27 stale discipline is a commit-time version check, not a worker claim."""
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(Path(tmp) / "kernel.db")
            try:
                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
                ledger = control.ledger
                ledger.create_thread(thread_id="product", title="Product")
                _, old_event = ledger.start("product", "旧计划里的长任务")

                ledger._set_plan_version("product", 2)
                ledger._supersede_items_before("product", 2)
                ledger._mark_run_stale(old_event.event_id)
                _, current_event = ledger.start(
                    "product",
                    "新计划：只推进核心记账",
                    objective="只推进核心记账",
                )

                claimed = resident.store.claim_event(old_event.event_id)
                self.assertIsNotNone(claimed)
                resident.store.complete_event(
                    EventOutcome(
                        event_id=old_event.event_id,
                        success=True,
                        execution_path=ExecutionPath.CAPABILITY,
                        response="old worker says success",
                        reason="late old-plan result",
                    )
                )

                stale_progress = control.progress("product", old_event.event_id)

                self.assertTrue(stale_progress["stale"])
                self.assertFalse(stale_progress["accepted"])
                self.assertEqual(stale_progress["plan_version"], 1)
                self.assertEqual(stale_progress["current_plan_version"], 2)
                self.assertEqual(
                    ledger.get_run(current_event.event_id).ledger_state,
                    "active",
                )
                self.assertEqual(ledger.plan_version("product"), 2)

                messages = ledger.list_messages("product")
                accepted_old_replies = [
                    message
                    for message in messages
                    if message.role == "zn"
                    and message.detail.get("event_id") == old_event.event_id
                ]
                self.assertEqual(accepted_old_replies, [])
                retained = [
                    message
                    for message in messages
                    if message.role == "activity"
                    and message.detail.get("event_id") == old_event.event_id
                    and message.detail.get("stale") is True
                ]
                self.assertEqual(len(retained), 1)
                self.assertFalse(retained[0].detail["accepted"])
                self.assertIn(
                    "old worker says success",
                    retained[0].detail["result_excerpt"],
                )
            finally:
                resident.store.close()

    def test_uncertain_side_effect_blocks_steering_before_plan_changes(self) -> None:
        """Changing direction never erases an unresolved outside-world mutation."""
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(Path(tmp) / "kernel.db")
            try:
                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
                ledger = control.ledger
                ledger.create_thread(thread_id="product", title="Product")
                _, old_event = ledger.start("product", "旧计划：提交一次外部 mutation")
                self._make_yesterday(ledger, "product")
                ledger.create_thread(thread_id="shell", title="New work")

                working = resident.store.get_working_state()
                working.current_event_id = old_event.event_id
                working.stage = "side_effect_recovery"
                working.next_action = "reconcile uncertain outside-world effect"
                resident.store.save_working_state(working)

                with self.assertRaisesRegex(
                    RuntimeError,
                    "unresolved outside-world effect",
                ):
                    control.start("shell", STEERING)

                self.assertEqual(ledger.plan_version("product"), 1)
                self.assertEqual(
                    ledger.get_run(old_event.event_id).ledger_state,
                    "active",
                )
                self.assertEqual(
                    resident.store.get_event(old_event.event_id).status,
                    EventStatus.PENDING,
                )
                self.assertEqual(
                    resident.store.get_working_state().stage,
                    "side_effect_recovery",
                )
                self.assertEqual(ledger.list_messages("shell"), [])
            finally:
                resident.store.close()

    def test_restart_recovers_steering_after_atomic_intent_before_ingress_materialization(self) -> None:
        """A crash after plan commit must not lose the exact next-plan event intent."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = self._runtime(db)
            control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(first))
            ledger = control.ledger
            ledger.create_thread(thread_id="product", title="Product")
            _, old_event = ledger.start("product", "旧计划：登录和记账一起做")
            old_event_id = old_event.event_id
            self._make_yesterday(ledger, "product")
            ledger.create_thread(thread_id="shell", title="New work")
            before_event_ids = {
                event.event_id for event in first.store.list_events(limit=64)
            }

            with patch.object(
                ledger,
                "reconcile_ingress_checkpoints",
                side_effect=RuntimeError("crash after steering intent"),
            ):
                with self.assertRaisesRegex(RuntimeError, "crash after steering intent"):
                    control.start("shell", STEERING)

            self.assertEqual(ledger.plan_version("product"), 2)
            self.assertEqual(ledger.get_run(old_event_id).ledger_state, "stale")
            self.assertEqual(first.store.get_event(old_event_id).status, EventStatus.PENDING)
            self.assertEqual(
                {event.event_id for event in first.store.list_events(limit=64)},
                before_event_ids,
            )
            self.assertTrue(
                any(
                    item.plan_version == 2 and item.status == "running"
                    for item in ledger.list_work_items("product")
                )
            )
            first.store.close()

            restored = self._runtime(db)
            try:
                restored_control = RestoreAwareWorkControl(
                    RecoveryBoundedWorkLedger(restored)
                )
                restored_ledger = restored_control.ledger
                current = restored_ledger._active_run_for_thread("product")
                self.assertIsNotNone(current)
                self.assertNotEqual(current.event_id, old_event_id)
                current_event_id = current.event_id
                self.assertEqual(restored_ledger.plan_version("product"), 2)
                self.assertEqual(
                    restored_ledger.get_run(old_event_id).ledger_state,
                    "stale_finalized",
                )
                old_persisted = restored.store.get_event(old_event_id)
                self.assertEqual(old_persisted.status, EventStatus.FAILED)
                old_outcome = restored.store.get_event_outcome(old_event_id)
                self.assertEqual(old_outcome.execution_path, ExecutionPath.CONTROL)
                current_event = restored.store.get_event(current_event_id)
                self.assertEqual(current_event.status, EventStatus.PENDING)
                self.assertEqual(current_event.payload["work_plan_version"], 2)
                self.assertEqual(
                    current_event.payload["work_steering"]["previous_event_id"],
                    old_event_id,
                )
                self.assertEqual(
                    {event.event_id for event in restored.store.list_events(limit=64)}
                    - before_event_ids,
                    {current_event_id},
                )

                restored_ledger.create_thread(thread_id="restart-ui", title="New work")
                snapshot, resumed = restored_control.start(
                    "restart-ui",
                    "上次那个继续",
                )
                self.assertEqual(snapshot[0].thread_id, "product")
                self.assertEqual(resumed.event_id, current_event_id)
            finally:
                restored.store.close()

    def test_restart_recovers_after_new_event_materialized_before_old_event_superseded(self) -> None:
        """A crash after new ingress exists must preserve that exact event and finish old-plan supersession."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = self._runtime(db)
            control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(first))
            ledger = control.ledger
            ledger.create_thread(thread_id="product", title="Product")
            _, old_event = ledger.start("product", "旧计划：登录和记账一起做")
            old_event_id = old_event.event_id
            self._make_yesterday(ledger, "product")
            ledger.create_thread(thread_id="shell", title="New work")

            with patch.object(
                ledger,
                "_supersede_resident_event",
                side_effect=RuntimeError("crash after new steering event"),
            ):
                with self.assertRaisesRegex(RuntimeError, "crash after new steering event"):
                    control.start("shell", STEERING)

            current = ledger._active_run_for_thread("product")
            self.assertIsNotNone(current)
            current_event_id = current.event_id
            self.assertNotEqual(current_event_id, old_event_id)
            self.assertEqual(ledger.plan_version("product"), 2)
            self.assertEqual(ledger.get_run(old_event_id).ledger_state, "stale")
            self.assertEqual(first.store.get_event(old_event_id).status, EventStatus.PENDING)
            self.assertEqual(first.store.get_event(current_event_id).status, EventStatus.PENDING)
            before_restart_ids = {
                event.event_id for event in first.store.list_events(limit=64)
            }
            self.assertEqual(before_restart_ids, {old_event_id, current_event_id})
            first.store.close()

            restored = self._runtime(db)
            try:
                restored_control = RestoreAwareWorkControl(
                    RecoveryBoundedWorkLedger(restored)
                )
                restored_ledger = restored_control.ledger
                active = restored_ledger._active_run_for_thread("product")
                self.assertIsNotNone(active)
                self.assertEqual(active.event_id, current_event_id)
                self.assertEqual(
                    restored_ledger.get_run(old_event_id).ledger_state,
                    "stale_finalized",
                )
                self.assertEqual(
                    restored.store.get_event(old_event_id).status,
                    EventStatus.FAILED,
                )
                self.assertEqual(
                    restored.store.get_event(current_event_id).status,
                    EventStatus.PENDING,
                )
                self.assertEqual(
                    {event.event_id for event in restored.store.list_events(limit=64)},
                    before_restart_ids,
                )
                self.assertEqual(
                    restored_ledger.work_item_for_event(current_event_id).plan_version,
                    2,
                )
                self.assertEqual(
                    restored.store.get_event(current_event_id).payload["work_steering"]["previous_event_id"],
                    old_event_id,
                )
            finally:
                restored.store.close()

    def test_steered_plan_survives_restart_and_bare_continue_reuses_new_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = self._runtime(db)
            control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(first))
            ledger = control.ledger
            ledger.create_thread(thread_id="product", title="Product")
            _, old_event = ledger.start("product", "旧计划：登录和核心记账一起做")
            self._make_yesterday(ledger, "product")
            ledger.create_thread(thread_id="shell", title="New work")
            _, steered_event = control.start("shell", STEERING)
            steered_event_id = steered_event.event_id
            old_event_id = old_event.event_id
            first.store.close()

            restored = self._runtime(db)
            try:
                restored_control = RestoreAwareWorkControl(
                    RecoveryBoundedWorkLedger(restored)
                )
                restored_ledger = restored_control.ledger
                self.assertEqual(restored_ledger.plan_version("product"), 2)
                self.assertEqual(
                    restored_ledger.get_run(old_event_id).ledger_state,
                    "stale_finalized",
                )
                self.assertEqual(
                    restored_ledger.get_run(steered_event_id).ledger_state,
                    "active",
                )
                self.assertEqual(
                    restored_ledger.work_item_for_event(steered_event_id).plan_version,
                    2,
                )
                restored_ledger.create_thread(thread_id="restart-ui", title="New work")

                snapshot, resumed = restored_control.start(
                    "restart-ui",
                    "上次那个继续",
                )

                self.assertEqual(snapshot[0].thread_id, "product")
                self.assertEqual(resumed.event_id, steered_event_id)
                self.assertEqual(
                    restored_ledger.get_run(steered_event_id).thread_id,
                    "product",
                )
                self.assertEqual(restored_ledger.list_messages("restart-ui"), [])
            finally:
                restored.store.close()

    def test_rpc_keeps_product_thread_identity_when_active_plan_is_steered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(Path(tmp) / "kernel.db")
            server = ResidentRpcServer(resident=resident)
            try:
                server.handle(
                    {
                        "id": "create-product",
                        "method": "work_create",
                        "params": {"thread_id": "product", "title": "Product"},
                    }
                )
                started = server.handle(
                    {
                        "id": "start-product",
                        "method": "work_start",
                        "params": {
                            "thread_id": "product",
                            "task": "旧计划：先做登录，再做核心记账",
                        },
                    }
                )
                self.assertTrue(started["ok"])
                old_event_id = started["result"]["progress"]["event_id"]
                self._make_yesterday(server.work_control.ledger, "product")
                server.handle(
                    {
                        "id": "create-shell",
                        "method": "work_create",
                        "params": {"thread_id": "shell", "title": "New work"},
                    }
                )

                steered = server.handle(
                    {
                        "id": "steer",
                        "method": "work_start",
                        "params": {"thread_id": "shell", "task": STEERING},
                    }
                )

                self.assertTrue(steered["ok"], steered.get("error"))
                result = steered["result"]
                self.assertEqual(result["thread"]["id"], "product")
                self.assertEqual(result["progress"]["thread_id"], "product")
                self.assertEqual(result["progress"]["current_plan_version"], 2)
                self.assertNotEqual(result["progress"]["event_id"], old_event_id)
                self.assertEqual(
                    server.work_control.ledger.get_run(old_event_id).ledger_state,
                    "stale_finalized",
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
