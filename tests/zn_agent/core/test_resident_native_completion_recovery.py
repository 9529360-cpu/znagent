from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core import CapabilityResult, ExactTaskCapability
from zn_agent.core.models import EventStatus, WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class ResidentNativeCompletionRecoveryTests(unittest.TestCase):
    def test_compiled_capability_completion_survives_restart_without_reexecution(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            calls = 0

            def handler(event, state):
                nonlocal calls
                calls += 1
                return CapabilityResult(success=True, response="resident capability result")

            resident.capabilities.register(
                ExactTaskCapability(
                    name="restart-safe-local",
                    triggers=("complete locally once",),
                    handler=handler,
                )
            )
            event = resident.enqueue("complete locally once")
            claimed = resident.store.claim_event(event.event_id)
            self.assertIsNotNone(claimed)
            assert claimed is not None
            readiness = resident.kernel.self_model.assess_task(
                claimed.task,
                resident._required_capabilities(claimed),
            )
            state = WorkingState(
                current_event_id=claimed.event_id,
                stage="orient",
                next_action="orient to current event",
                data={},
            )
            resident.store.save_working_state(state)

            result = resident._orient_step(
                claimed,
                state,
                readiness=readiness,
            )

            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.success)
            self.assertEqual(result.response, "resident capability result")
            self.assertEqual(result.capability_name, "restart-safe-local")
            self.assertEqual(calls, 1)
            checkpoint = resident.store.get_working_state()
            self.assertEqual(checkpoint.stage, "resident_completion")
            self.assertEqual(checkpoint.next_action, "publish terminal EventOutcome")
            self.assertEqual(
                checkpoint.data["resident_completion"]["capability_name"],
                "restart-safe-local",
            )
            self.assertIsNone(resident.store.get_event_outcome(event.event_id))
            metrics_before = resident.store.get_runtime_metrics()
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            try:
                recovered_event = restored.store.get_event(event.event_id)
                self.assertIsNotNone(recovered_event)
                assert recovered_event is not None
                self.assertEqual(recovered_event.status, EventStatus.PENDING)
                self.assertEqual(
                    restored.store.get_working_state().stage,
                    "resident_completion",
                )

                with patch.object(
                    restored.capabilities,
                    "resolve",
                    side_effect=AssertionError(
                        "compiled capability resolution/execution must not replay"
                    ),
                ):
                    completed = restored.run_once(target_event_id=event.event_id)

                self.assertIsNotNone(completed)
                assert completed is not None
                self.assertTrue(completed.success)
                self.assertEqual(completed.response, "resident capability result")
                self.assertEqual(completed.capability_name, "restart-safe-local")
                outcome = restored.store.get_event_outcome(event.event_id)
                self.assertIsNotNone(outcome)
                assert outcome is not None
                self.assertTrue(outcome.success)
                self.assertEqual(outcome.execution_path.value, "capability")
                self.assertEqual(outcome.capability_name, "restart-safe-local")
                self.assertEqual(
                    restored.store.get_runtime_metrics().tasks_total,
                    metrics_before.tasks_total,
                )
                self.assertEqual(restored.store.get_working_state().stage, "idle")
            finally:
                restored.store.close()

    def test_memory_completion_survives_restart_without_recall(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            resident.memory.remember(
                "restart-safe-fact",
                {"answer": 42},
                aliases=("what is the restart-safe answer",),
            )
            event = resident.enqueue("what is the restart-safe answer")
            claimed = resident.store.claim_event(event.event_id)
            self.assertIsNotNone(claimed)
            assert claimed is not None
            readiness = resident.kernel.self_model.assess_task(
                claimed.task,
                resident._required_capabilities(claimed),
            )
            state = WorkingState(
                current_event_id=claimed.event_id,
                stage="orient",
                next_action="orient to current event",
                data={},
            )
            resident.store.save_working_state(state)

            result = resident._orient_step(
                claimed,
                state,
                readiness=readiness,
            )

            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.success)
            self.assertEqual(result.response, '{"answer": 42}')
            checkpoint = resident.store.get_working_state()
            self.assertEqual(checkpoint.stage, "resident_completion")
            self.assertEqual(checkpoint.next_action, "publish terminal EventOutcome")
            self.assertEqual(
                checkpoint.data["resident_completion"]["execution_path"],
                "memory",
            )
            self.assertIsNone(resident.store.get_event_outcome(event.event_id))
            metrics_before = resident.store.get_runtime_metrics()
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            try:
                recovered_event = restored.store.get_event(event.event_id)
                self.assertIsNotNone(recovered_event)
                assert recovered_event is not None
                self.assertEqual(recovered_event.status, EventStatus.PENDING)
                self.assertEqual(
                    restored.store.get_working_state().stage,
                    "resident_completion",
                )

                with patch.object(
                    restored.memory,
                    "recall",
                    side_effect=AssertionError("structured memory recall must not replay"),
                ):
                    completed = restored.run_once(target_event_id=event.event_id)

                self.assertIsNotNone(completed)
                assert completed is not None
                self.assertTrue(completed.success)
                self.assertEqual(completed.response, '{"answer": 42}')
                outcome = restored.store.get_event_outcome(event.event_id)
                self.assertIsNotNone(outcome)
                assert outcome is not None
                self.assertTrue(outcome.success)
                self.assertEqual(outcome.execution_path.value, "memory")
                self.assertEqual(
                    restored.store.get_runtime_metrics().tasks_total,
                    metrics_before.tasks_total,
                )
                self.assertEqual(restored.store.get_working_state().stage, "idle")
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main()
