from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.models import EventStatus, ExecutionPath, WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class TerminalFailureRecoveryTests(unittest.TestCase):
    @staticmethod
    def _build(db: Path):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=db,
        )

    def _advance_to_native_deliberation(self, resident, event) -> None:
        for _ in range(12):
            state = resident.store.get_working_state()
            if (
                state.current_event_id == event.event_id
                and state.stage == "native_deliberation"
            ):
                return
            result = resident.live_once()
            self.assertIsNone(result)
        self.fail("resident did not reach native_deliberation")

    def test_budget_failure_accounting_survives_crash_before_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._build(db)
            event = resident.enqueue(
                "diagnose an unfamiliar failure that has no local evidence yet",
                payload={"model_policy": "never"},
            )
            self._advance_to_native_deliberation(resident, event)

            with patch.object(
                resident,
                "_complete_result",
                side_effect=SystemExit("crash before EventOutcome publication"),
            ):
                with self.assertRaises(SystemExit):
                    resident.live_once()

            checkpoint = resident.store.get_working_state()
            self.assertEqual(checkpoint.stage, "terminal_failure")
            self.assertEqual(checkpoint.current_event_id, event.event_id)
            self.assertFalse(checkpoint.data["terminal_failure"]["success"])
            self.assertEqual(
                checkpoint.data["terminal_failure"]["execution_path"],
                ExecutionPath.BUDGET_BLOCKED.value,
            )
            self.assertIsNone(resident.store.get_event_outcome(event.event_id))
            self.assertEqual(resident.store.get_runtime_metrics().tasks_total, 1)
            self.assertTrue(
                resident.resident_accounting.has_record(
                    event.event_id,
                    "terminal_failure",
                )
            )
            impasse_attempts = resident.life.snapshot().current_impasse.attempts
            resident.store.close()

            restored = self._build(db)
            try:
                result = restored.run_once(target_event_id=event.event_id)

                self.assertIsNotNone(result)
                assert result is not None
                self.assertFalse(result.success)
                self.assertEqual(result.execution_path, ExecutionPath.BUDGET_BLOCKED)
                self.assertEqual(restored.store.get_runtime_metrics().tasks_total, 1)
                self.assertEqual(
                    restored.life.snapshot().current_impasse.attempts,
                    impasse_attempts,
                )
                outcome = restored.store.get_event_outcome(event.event_id)
                self.assertIsNotNone(outcome)
                assert outcome is not None
                self.assertFalse(outcome.success)
                self.assertEqual(outcome.execution_path, ExecutionPath.BUDGET_BLOCKED)
                self.assertEqual(
                    restored.store.get_event(event.event_id).status,
                    EventStatus.FAILED,
                )
                self.assertEqual(restored.store.get_working_state().stage, "idle")
            finally:
                restored.store.close()

    def test_budget_failure_checkpoint_survives_crash_before_accounting(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._build(db)
            event = resident.enqueue(
                "diagnose an unfamiliar failure that has no local evidence yet",
                payload={"model_policy": "never"},
            )
            self._advance_to_native_deliberation(resident, event)

            with patch.object(
                resident.resident_accounting,
                "record_terminal_failure",
                side_effect=SystemExit("crash after checkpoint before accounting"),
            ):
                with self.assertRaises(SystemExit):
                    resident.live_once()

            checkpoint = resident.store.get_working_state()
            self.assertEqual(checkpoint.stage, "terminal_failure")
            self.assertIsNone(resident.store.get_event_outcome(event.event_id))
            self.assertEqual(resident.store.get_runtime_metrics().tasks_total, 0)
            self.assertFalse(
                resident.resident_accounting.has_record(
                    event.event_id,
                    "terminal_failure",
                )
            )
            impasse_attempts = resident.life.snapshot().current_impasse.attempts
            resident.store.close()

            restored = self._build(db)
            try:
                result = restored.run_once(target_event_id=event.event_id)

                self.assertIsNotNone(result)
                assert result is not None
                self.assertFalse(result.success)
                self.assertEqual(restored.store.get_runtime_metrics().tasks_total, 1)
                self.assertTrue(
                    restored.resident_accounting.has_record(
                        event.event_id,
                        "terminal_failure",
                    )
                )
                self.assertEqual(
                    restored.life.snapshot().current_impasse.attempts,
                    impasse_attempts,
                )
            finally:
                restored.store.close()

    def test_outer_exception_failure_survives_restart_without_duplicate_accounting(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._build(db)
            event = resident.enqueue("exercise deterministic resident exception recovery")

            with patch.object(
                resident,
                "_advance_event_step",
                side_effect=RuntimeError("injected deterministic failure"),
            ), patch.object(
                resident,
                "_complete_result",
                side_effect=SystemExit("crash before exception outcome publication"),
            ):
                with self.assertRaises(SystemExit):
                    resident.run_once(target_event_id=event.event_id)

            checkpoint = resident.store.get_working_state()
            self.assertEqual(checkpoint.stage, "terminal_failure")
            self.assertIn(
                "RuntimeError: injected deterministic failure",
                checkpoint.data["terminal_failure"]["reason"],
            )
            self.assertEqual(resident.store.get_runtime_metrics().tasks_total, 1)
            self.assertIsNone(resident.store.get_event_outcome(event.event_id))
            resident.store.close()

            restored = self._build(db)
            try:
                with patch.object(
                    restored,
                    "_orient_step",
                    side_effect=AssertionError(
                        "terminal exception checkpoint must not re-enter orientation"
                    ),
                ):
                    result = restored.run_once(target_event_id=event.event_id)

                self.assertIsNotNone(result)
                assert result is not None
                self.assertFalse(result.success)
                self.assertIn("injected deterministic failure", result.reason)
                self.assertEqual(restored.store.get_runtime_metrics().tasks_total, 1)
                self.assertTrue(
                    restored.resident_accounting.has_record(
                        event.event_id,
                        "terminal_failure",
                    )
                )
                self.assertIsNotNone(restored.store.get_event_outcome(event.event_id))
            finally:
                restored.store.close()

    def test_publish_exception_preserves_durable_success_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._build(db)
            resident.memory.remember(
                "terminal-publication-test",
                "durable answer",
                aliases=("return the durable publication test answer",),
            )
            event = resident.enqueue("return the durable publication test answer")

            with patch.object(
                resident.store,
                "complete_event",
                side_effect=RuntimeError("terminal publication unavailable"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "terminal publication unavailable",
                ):
                    resident.run_once(target_event_id=event.event_id)

            checkpoint = resident.store.get_working_state()
            self.assertEqual(checkpoint.stage, "resident_completion")
            self.assertTrue(checkpoint.data["resident_completion"]["success"])
            self.assertNotIn("terminal_failure", checkpoint.data)
            self.assertIsNone(resident.store.get_event_outcome(event.event_id))
            metrics_before = resident.store.get_runtime_metrics().tasks_total
            self.assertEqual(metrics_before, 1)

            result = resident.run_once(target_event_id=event.event_id)
            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.success)
            self.assertEqual(result.response, "durable answer")
            self.assertEqual(resident.store.get_runtime_metrics().tasks_total, metrics_before)
            self.assertIsNotNone(resident.store.get_event_outcome(event.event_id))
            resident.store.close()

    def test_outer_exception_does_not_reclassify_outside_world_uncertainty(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._build(db)
            event = resident.enqueue("preserve uncertain outside-world effect")
            resident.store.save_working_state(
                WorkingState(
                    current_event_id=event.event_id,
                    stage="side_effect_recovery",
                    blocked_by="outside_world_effect_uncertain",
                    next_action="await explicit recovery decision",
                    data={
                        "side_effect_recovery": {
                            "status": "uncertain",
                            "replay_blocked": True,
                        }
                    },
                )
            )

            with patch.object(
                resident,
                "_advance_event_step",
                side_effect=RuntimeError("recovery observer unavailable"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "recovery observer unavailable",
                ):
                    resident.run_once(target_event_id=event.event_id)

            checkpoint = resident.store.get_working_state()
            self.assertEqual(checkpoint.stage, "side_effect_recovery")
            self.assertEqual(checkpoint.blocked_by, "outside_world_effect_uncertain")
            self.assertTrue(checkpoint.data["side_effect_recovery"]["replay_blocked"])
            self.assertNotIn("terminal_failure", checkpoint.data)
            self.assertEqual(resident.store.get_runtime_metrics().tasks_total, 0)
            self.assertIsNone(resident.store.get_event_outcome(event.event_id))
            self.assertEqual(
                resident.store.get_event(event.event_id).status,
                EventStatus.PROCESSING,
            )
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
