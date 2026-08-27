from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.models import EventStatus, WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.recovery_control import (
    ResidentRecoveryRequired,
    raise_if_synchronous_recovery_blocked,
)


class SynchronousRecoveryControlTests(unittest.TestCase):
    @staticmethod
    def _seed_blocked_recovery(resident, *, suffix: str):
        event = resident.enqueue(
            f"run uncertain command {suffix}",
            payload={"required_capabilities": ["terminal"]},
        )
        claimed = resident.store.claim_event(event.event_id)
        assert claimed is not None
        args = {"command": f"echo uncertain-{suffix}"}
        attempt_id = f"sidefx-sync-{suffix}"
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

    @staticmethod
    def _attempt_status(resident, attempt_id: str) -> str | None:
        with closing(sqlite3.connect(resident.store.path)) as conn:
            row = conn.execute(
                "SELECT status FROM resident_side_effect_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
        return str(row[0]) if row else None

    def test_direct_run_once_yields_without_terminalizing_or_replaying(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                event, attempt_id = self._seed_blocked_recovery(resident, suffix="direct")
                with self.assertRaises(ResidentRecoveryRequired) as raised:
                    resident.run_once(target_event_id=event.event_id)

                self.assertEqual(raised.exception.event_id, event.event_id)
                self.assertEqual(raised.exception.decision, "user_decision_required")
                self.assertIsNone(resident.store.get_event_outcome(event.event_id))
                persisted = resident.store.get_event(event.event_id)
                self.assertIsNotNone(persisted)
                assert persisted is not None
                self.assertEqual(persisted.status, EventStatus.PROCESSING)
                state = resident.store.get_working_state()
                self.assertEqual(state.stage, "side_effect_recovery")
                self.assertEqual(state.blocked_by, "outside_world_effect_uncertain")
                self.assertEqual(self._attempt_status(resident, attempt_id), "started")
                self.assertEqual(
                    [item for item in resident.body.recent_actions(40) if item.event_id == event.event_id],
                    [],
                )
            finally:
                resident.store.close()

    def test_one_step_life_driving_holds_recovery_without_throwing(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                event, attempt_id = self._seed_blocked_recovery(resident, suffix="life")
                self.assertIsNone(
                    resident.run_once(
                        thought=object(),
                        target_event_id=event.event_id,
                    )
                )
                self.assertIsNone(resident.store.get_event_outcome(event.event_id))
                self.assertEqual(resident.store.get_working_state().stage, "side_effect_recovery")
                self.assertEqual(self._attempt_status(resident, attempt_id), "started")
            finally:
                resident.store.close()

    def test_sync_submit_rejects_before_enqueuing_behind_blocked_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                event, _ = self._seed_blocked_recovery(resident, suffix="submit")
                before = {item.event_id for item in resident.store.list_events(limit=100)}
                with self.assertRaises(ResidentRecoveryRequired) as raised:
                    resident.submit("this must not be silently queued")
                after = {item.event_id for item in resident.store.list_events(limit=100)}
                self.assertEqual(raised.exception.event_id, event.event_id)
                self.assertEqual(after, before)
            finally:
                resident.store.close()

    def test_restart_preserves_yield_boundary_then_explicit_cancel_remains_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            event, attempt_id = self._seed_blocked_recovery(resident, suffix="restart")
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
                with self.assertRaises(ResidentRecoveryRequired):
                    restored.run_once(target_event_id=event.event_id)
                self.assertIsNone(restored.store.get_event_outcome(event.event_id))
                self.assertEqual(self._attempt_status(restored, attempt_id), "started")

                cancelled = restored.cancel_uncertain_event(
                    event.event_id,
                    reason="operator abandoned blocked synchronous Work",
                )
                self.assertTrue(cancelled.cancelled)
                outcome = restored.store.get_event_outcome(event.event_id)
                self.assertIsNotNone(outcome)
                assert outcome is not None
                self.assertTrue(outcome.cancelled)
                self.assertEqual(self._attempt_status(restored, attempt_id), "work_abandoned")
                self.assertEqual(restored.store.get_working_state().stage, "idle")
            finally:
                restored.store.close()

    def test_read_only_reverification_is_not_treated_as_explicit_control_block(self):
        state = WorkingState(
            current_event_id="evt-reverify",
            stage="side_effect_recovery",
            blocked_by="outside_world_effect_uncertain",
            data={
                "side_effect_recovery": {
                    "replay_blocked": True,
                    "decision": "reverify_effect",
                }
            },
        )
        raise_if_synchronous_recovery_blocked("evt-reverify", state)


if __name__ == "__main__":
    unittest.main()
