from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.models import EventStatus, ExecutionPath, WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class ResidentWorkCancellationDurabilityTests(unittest.TestCase):
    @staticmethod
    def _attempt_row(resident, attempt_id: str):
        with closing(sqlite3.connect(resident.store.path)) as conn:
            return conn.execute(
                "SELECT status,completed_at,result_action_id,result_success "
                "FROM resident_side_effect_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()

    def _prepare_uncertain_event(self, resident, *, suffix: str):
        event = resident.enqueue(
            f"run one uncertain command {suffix}",
            kind="desktop_user_event",
            payload={"required_capabilities": ["terminal"]},
        )
        claimed = resident.store.claim_event(event.event_id)
        self.assertIsNotNone(claimed)
        attempt_id = f"sidefx-cancel-{suffix}"
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
                next_action=(
                    "await explicit recovery or cancellation decision; "
                    "do not replay the side effect"
                ),
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

    def test_cancel_uncertain_event_atomically_terminalizes_without_effect_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                event, attempt_id = self._prepare_uncertain_event(
                    resident,
                    suffix="normal",
                )
                self.assertFalse(
                    resident.body.resolve_uncertain_attempt(
                        attempt_id,
                        event_id=event.event_id,
                        status="cancelled",
                    )
                )

                terminal = resident.store.cancel_uncertain_event(event.event_id)

                self.assertEqual(terminal.status, EventStatus.FAILED)
                self.assertIsNone(terminal.last_error)
                outcome = resident.store.get_event_outcome(event.event_id)
                self.assertIsNotNone(outcome)
                assert outcome is not None
                self.assertFalse(outcome.success)
                self.assertTrue(outcome.cancelled)
                self.assertEqual(outcome.execution_path, ExecutionPath.CONTROL)
                self.assertEqual(
                    outcome.reason,
                    "work cancelled by explicit control decision",
                )
                self.assertEqual(outcome.response, "")

                idle = resident.store.get_working_state()
                self.assertEqual(idle.stage, "idle")
                self.assertIsNone(idle.current_event_id)
                attempt = self._attempt_row(resident, attempt_id)
                self.assertIsNotNone(attempt)
                assert attempt is not None
                self.assertEqual(attempt[0], "work_abandoned")
                self.assertIsNotNone(attempt[1])
                self.assertIsNone(attempt[2])
                self.assertIsNone(attempt[3])
                self.assertEqual(resident.body.uncertain_attempts(event.event_id), [])
            finally:
                resident.store.close()

    def test_cancel_uncertain_event_after_restart_does_not_resurrect_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            event, attempt_id = self._prepare_uncertain_event(
                resident,
                suffix="restart",
            )
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            try:
                recovered = restored.store.get_event(event.event_id)
                self.assertIsNotNone(recovered)
                assert recovered is not None
                self.assertEqual(recovered.status, EventStatus.PENDING)
                checkpoint = restored.store.get_working_state()
                self.assertEqual(checkpoint.current_event_id, event.event_id)
                self.assertEqual(checkpoint.stage, "side_effect_recovery")
                self.assertEqual(self._attempt_row(restored, attempt_id)[0], "started")

                restored.store.cancel_uncertain_event(
                    event.event_id,
                    reason="user stopped this Work",
                )
                self.assertEqual(
                    self._attempt_row(restored, attempt_id)[0],
                    "work_abandoned",
                )
            finally:
                restored.store.close()

            restarted_again = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            try:
                terminal = restarted_again.store.get_event(event.event_id)
                outcome = restarted_again.store.get_event_outcome(event.event_id)
                self.assertIsNotNone(terminal)
                self.assertIsNotNone(outcome)
                assert terminal is not None
                assert outcome is not None
                self.assertEqual(terminal.status, EventStatus.FAILED)
                self.assertTrue(outcome.cancelled)
                self.assertEqual(outcome.execution_path, ExecutionPath.CONTROL)
                self.assertEqual(outcome.reason, "user stopped this Work")
                self.assertEqual(restarted_again.store.get_working_state().stage, "idle")
                self.assertEqual(
                    restarted_again.body.uncertain_attempts(event.event_id),
                    [],
                )
                self.assertEqual(
                    self._attempt_row(restarted_again, attempt_id)[0],
                    "work_abandoned",
                )
            finally:
                restarted_again.store.close()

    def test_cancel_uncertain_event_rolls_back_event_outcome_checkpoint_and_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                event, attempt_id = self._prepare_uncertain_event(
                    resident,
                    suffix="rollback",
                )
                before = resident.store.get_working_state()
                with resident.store._lock, resident.store._conn:
                    resident.store._conn.execute(
                        """
                        CREATE TRIGGER fail_cancel_outcome_insert
                        BEFORE INSERT ON event_outcomes
                        BEGIN
                            SELECT RAISE(ABORT, 'forced cancellation outcome failure');
                        END
                        """
                    )

                with self.assertRaises(sqlite3.IntegrityError):
                    resident.store.cancel_uncertain_event(event.event_id)

                persisted = resident.store.get_event(event.event_id)
                self.assertIsNotNone(persisted)
                assert persisted is not None
                self.assertEqual(persisted.status, EventStatus.PROCESSING)
                self.assertIsNone(resident.store.get_event_outcome(event.event_id))
                after = resident.store.get_working_state()
                self.assertEqual(after.current_event_id, before.current_event_id)
                self.assertEqual(after.stage, before.stage)
                self.assertEqual(after.blocked_by, before.blocked_by)
                self.assertEqual(after.data, before.data)
                attempt = self._attempt_row(resident, attempt_id)
                self.assertIsNotNone(attempt)
                assert attempt is not None
                self.assertEqual(attempt[0], "started")
                self.assertIsNone(attempt[1])
                self.assertIsNone(attempt[2])
                self.assertIsNone(attempt[3])
            finally:
                try:
                    with resident.store._lock, resident.store._conn:
                        resident.store._conn.execute(
                            "DROP TRIGGER IF EXISTS fail_cancel_outcome_insert"
                        )
                finally:
                    resident.store.close()

    def test_cancel_uncertain_event_rejects_non_recovery_checkpoint_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                event, attempt_id = self._prepare_uncertain_event(
                    resident,
                    suffix="wrong-state",
                )
                resident.store.save_working_state(
                    WorkingState(
                        current_event_id=event.event_id,
                        stage="native_action",
                        next_action="continue ordinary action",
                        data={"sentinel": "not recovery"},
                    )
                )
                before = resident.store.get_working_state()

                with self.assertRaisesRegex(
                    RuntimeError,
                    "active side-effect recovery checkpoint",
                ):
                    resident.store.cancel_uncertain_event(event.event_id)

                persisted = resident.store.get_event(event.event_id)
                self.assertIsNotNone(persisted)
                assert persisted is not None
                self.assertEqual(persisted.status, EventStatus.PROCESSING)
                self.assertIsNone(resident.store.get_event_outcome(event.event_id))
                after = resident.store.get_working_state()
                self.assertEqual(after.current_event_id, before.current_event_id)
                self.assertEqual(after.stage, before.stage)
                self.assertEqual(after.data, before.data)
                self.assertEqual(self._attempt_row(resident, attempt_id)[0], "started")
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
