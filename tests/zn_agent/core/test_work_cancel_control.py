from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import ExecutionPath, WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.work import ResidentWorkLedger
from zn_agent.core.work_control import ResidentWorkControl


class ResidentWorkCancelControlTests(unittest.TestCase):
    @staticmethod
    def _attempt_status(resident, attempt_id: str) -> str | None:
        with closing(sqlite3.connect(resident.store.path)) as conn:
            row = conn.execute(
                "SELECT status FROM resident_side_effect_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
        return str(row[0]) if row else None

    def _prepare_uncertain_work(
        self,
        resident,
        ledger: ResidentWorkLedger,
        *,
        thread_id: str,
        suffix: str,
        payload: dict | None = None,
    ):
        ledger.create_thread(thread_id=thread_id)
        _, event = ledger.start(
            thread_id,
            f"run uncertain command {suffix}",
            payload=payload,
        )
        claimed = resident.store.claim_event(event.event_id)
        self.assertIsNotNone(claimed)
        attempt_id = f"sidefx-control-{suffix}"
        args = {"command": f"echo uncertain-{suffix}"}
        resident.body._start_attempt(
            attempt_id=attempt_id,
            event_id=event.event_id,
            kind="command",
            signature_hash=resident.body._signature_hash("command", args),
        )
        resident.store.save_working_state(
            WorkingState(
                current_event_id=event.event_id,
                stage="side_effect_recovery",
                next_action="await explicit recovery or cancellation decision; do not replay the side effect",
                blocked_by="outside_world_effect_uncertain",
                data={
                    "side_effect_recovery": {
                        "status": "decision_required",
                        "kind": "command",
                        "attempt_id": attempt_id,
                        "replay_blocked": True,
                        "decision": "user_decision_required",
                    }
                },
            )
        )
        return event, attempt_id

    def test_general_work_stop_is_durable_and_consumed_before_next_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            ledger = ResidentWorkLedger(resident)
            control = ResidentWorkControl(ledger)
            try:
                ledger.create_thread(thread_id="cancel-general")
                _, event = ledger.start(
                    "cancel-general",
                    "answer a question that should be stopped before execution",
                )

                requested = control.cancel("cancel-general", event.event_id)
                self.assertEqual(requested["stage"], "cancelling")
                self.assertEqual(requested["blocked_by"], "cancellation_requested")
                self.assertFalse(requested["terminal"])
                self.assertIsNotNone(
                    resident.store.get_event_cancellation_request(event.event_id)
                )

                run = resident.run_once(target_event_id=event.event_id)
                self.assertIsNotNone(run)
                assert run is not None
                self.assertTrue(run.cancelled)
                self.assertFalse(run.success)
                self.assertEqual(run.execution_path, ExecutionPath.CONTROL)
                self.assertEqual(run.response, "Work stopped.")
                self.assertEqual(run.model_invocations, 0)
                self.assertIsNone(
                    resident.store.get_event_cancellation_request(event.event_id)
                )

                progress = control.progress("cancel-general", event.event_id)
                self.assertEqual(progress["status"], "cancelled")
                self.assertEqual(progress["stage"], "cancelled")
                self.assertTrue(progress["terminal"])
                self.assertTrue(progress["finalized"])
                self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)

                _, messages = control.get_snapshot("cancel-general")
                cancelled = [
                    message
                    for message in messages
                    if message.role == "zn" and message.detail.get("cancelled") is True
                ]
                self.assertEqual(len(cancelled), 1)
                self.assertNotIn("failed", cancelled[0].detail)
                self.assertNotIn("outside_world_effect", cancelled[0].detail)
            finally:
                resident.store.close()

    def test_general_work_stop_survives_restart_without_resuming_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = ResidentWorkLedger(resident)
            control = ResidentWorkControl(ledger)
            ledger.create_thread(thread_id="cancel-general-restart")
            _, event = ledger.start(
                "cancel-general-restart",
                "do not resume this work after restart",
            )
            progress = control.cancel("cancel-general-restart", event.event_id)
            self.assertEqual(progress["stage"], "cancelling")
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            restored_control = ResidentWorkControl(ResidentWorkLedger(restored))
            try:
                request = restored.store.get_event_cancellation_request(event.event_id)
                self.assertIsNotNone(request)

                run = restored.run_once(target_event_id=event.event_id)
                self.assertIsNotNone(run)
                assert run is not None
                self.assertTrue(run.cancelled)
                self.assertEqual(run.model_invocations, 0)

                progress = restored_control.progress(
                    "cancel-general-restart",
                    event.event_id,
                )
                self.assertEqual(progress["status"], "cancelled")
                self.assertTrue(progress["finalized"])
                self.assertEqual(restored.store.get_runtime_metrics().model_invocations, 0)
            finally:
                restored.store.close()

    def test_stop_request_switches_to_uncertain_cancellation_if_inflight_effect_becomes_uncertain(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            ledger = ResidentWorkLedger(resident)
            control = ResidentWorkControl(ledger)
            try:
                ledger.create_thread(thread_id="cancel-race")
                _, event = ledger.start(
                    "cancel-race",
                    "run one action and then stop safely",
                )
                requested = control.cancel("cancel-race", event.event_id)
                self.assertEqual(requested["stage"], "cancelling")

                claimed = resident.store.claim_event(event.event_id)
                self.assertIsNotNone(claimed)
                attempt_id = "sidefx-control-race"
                args = {"command": "echo uncertain-race"}
                resident.body._start_attempt(
                    attempt_id=attempt_id,
                    event_id=event.event_id,
                    kind="command",
                    signature_hash=resident.body._signature_hash("command", args),
                )
                resident.store.save_working_state(
                    WorkingState(
                        current_event_id=event.event_id,
                        stage="side_effect_recovery",
                        next_action="await explicit recovery or cancellation decision; do not replay the side effect",
                        blocked_by="outside_world_effect_uncertain",
                        data={
                            "native_action_intent": {
                                "intent_id": "intent-race",
                                "kind": "command",
                                "args": args,
                            },
                            "side_effect_recovery": {
                                "status": "decision_required",
                                "kind": "command",
                                "intent_id": "intent-race",
                                "attempt_id": attempt_id,
                                "replay_blocked": True,
                                "decision": "user_decision_required",
                            },
                        },
                    )
                )

                run = resident.run_once(target_event_id=event.event_id)
                self.assertIsNotNone(run)
                assert run is not None
                self.assertTrue(run.cancelled)
                self.assertEqual(run.execution_path, ExecutionPath.CONTROL)
                self.assertEqual(self._attempt_status(resident, attempt_id), "work_abandoned")
                self.assertIsNone(
                    resident.store.get_event_cancellation_request(event.event_id)
                )

                progress = control.progress("cancel-race", event.event_id)
                self.assertEqual(progress["status"], "cancelled")
                self.assertTrue(progress["finalized"])
                _, messages = control.get_snapshot("cancel-race")
                cancelled = [
                    message
                    for message in messages
                    if message.role == "zn" and message.detail.get("cancelled") is True
                ]
                self.assertEqual(len(cancelled), 1)
                self.assertEqual(
                    cancelled[0].detail.get("outside_world_effect"),
                    "uncertain",
                )
            finally:
                resident.store.close()

    def test_resident_cancel_bypasses_life_failure_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            ledger = ResidentWorkLedger(resident)
            try:
                event, attempt_id = self._prepare_uncertain_work(
                    resident,
                    ledger,
                    thread_id="cancel-no-life-failure",
                    suffix="life",
                )
                with patch.object(
                    type(resident.life),
                    "observe_action",
                    side_effect=AssertionError("cancellation must not be observed as an action result"),
                ):
                    run = resident.cancel_uncertain_event(event.event_id)

                self.assertTrue(run.cancelled)
                self.assertFalse(run.success)
                self.assertEqual(run.execution_path, ExecutionPath.CONTROL)
                self.assertEqual(self._attempt_status(resident, attempt_id), "work_abandoned")
                restored = resident.result_for(event.event_id)
                self.assertIsNotNone(restored)
                assert restored is not None
                self.assertTrue(restored.cancelled)
                self.assertEqual(restored.execution_path, ExecutionPath.CONTROL)
            finally:
                resident.store.close()

    def test_will_restart_reconciles_cancelled_step_without_failed_or_completed_learning(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = ResidentWorkLedger(resident)
            intention = resident.will.intend(
                "keep investigating until the operator decides what to do",
                next_task="run uncertain command",
                complete_on_step_success=True,
            )
            event, _ = self._prepare_uncertain_work(
                resident,
                ledger,
                thread_id="cancel-will-restart",
                suffix="will",
                payload={"intention_id": intention.intention_id},
            )
            resident.will.engage(intention.intention_id, event.event_id)
            resident.store.cancel_uncertain_event(
                event.event_id,
                reason="operator stopped this Work",
            )
            before = resident.will.get(intention.intention_id)
            self.assertIsNotNone(before)
            assert before is not None
            self.assertEqual(before.status, "engaged")
            self.assertEqual(before.related_event_id, event.event_id)
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            try:
                restored.will.reconcile_outcomes()
                after = restored.will.get(intention.intention_id)
                self.assertIsNotNone(after)
                assert after is not None
                self.assertEqual(after.status, "active")
                self.assertIsNone(after.related_event_id)
                self.assertEqual(after.current_step, "run uncertain command")
                self.assertEqual(after.last_outcome, "operator stopped this Work")
                matching = [line for line in after.progress if event.event_id in line]
                self.assertTrue(any(" cancelled:" in line for line in matching))
                self.assertFalse(any(" failed:" in line for line in matching))
                self.assertNotEqual(after.status, "completed")
            finally:
                restored.store.close()

    def test_work_control_finalizes_cancelled_run_without_failure_or_uncertain_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            ledger = ResidentWorkLedger(resident)
            control = ResidentWorkControl(ledger)
            try:
                event, attempt_id = self._prepare_uncertain_work(
                    resident,
                    ledger,
                    thread_id="cancel-work-control",
                    suffix="ledger",
                )
                progress = control.cancel("cancel-work-control", event.event_id)

                self.assertEqual(progress["status"], "cancelled")
                self.assertEqual(progress["stage"], "cancelled")
                self.assertTrue(progress["terminal"])
                self.assertTrue(progress["finalized"])
                self.assertIsNone(progress["recovery"])
                self.assertIsNone(progress.get("error"))
                self.assertEqual(self._attempt_status(resident, attempt_id), "work_abandoned")

                _, messages = control.get_snapshot("cancel-work-control")
                zn_messages = [message for message in messages if message.role == "zn"]
                activities = [message for message in messages if message.role == "activity"]
                self.assertEqual(len(zn_messages), 1)
                self.assertTrue(zn_messages[0].detail.get("cancelled"))
                self.assertEqual(
                    zn_messages[0].detail.get("outside_world_effect"),
                    "uncertain",
                )
                self.assertNotIn("failed", zn_messages[0].detail)
                self.assertEqual(len(activities), 1)
                self.assertTrue(activities[0].detail.get("cancelled"))
                self.assertEqual(activities[0].detail.get("execution_path"), "control")
                self.assertEqual(ledger.list_artifacts("cancel-work-control"), [])
            finally:
                resident.store.close()

    def test_rpc_cancel_repairs_crash_window_and_returns_cancelled_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            server = ResidentRpcServer(resident=resident)
            event, _ = self._prepare_uncertain_work(
                resident,
                server.work,
                thread_id="cancel-rpc",
                suffix="rpc",
            )
            resident.store.cancel_uncertain_event(
                event.event_id,
                reason="operator stopped this Work",
            )
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            restored_server = ResidentRpcServer(resident=restored)
            try:
                response = restored_server.handle(
                    {
                        "id": "cancel-1",
                        "method": "work_cancel",
                        "params": {
                            "thread_id": "cancel-rpc",
                            "event_id": event.event_id,
                        },
                    }
                )
                self.assertTrue(response["ok"])
                result = response["result"]
                self.assertEqual(result["progress"]["status"], "cancelled")
                self.assertTrue(result["progress"]["finalized"])
                self.assertTrue(
                    any(
                        message.get("detail", {}).get("cancelled") is True
                        for message in result["thread"]["messages"]
                    )
                )
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main()
