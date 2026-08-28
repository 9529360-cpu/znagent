from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
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
            self.assertEqual(
                checkpoint.data["capability_execution"]["status"],
                "observed",
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

    def test_observed_capability_success_resumes_without_code_and_does_not_duplicate_accounting(self):
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
                return CapabilityResult(success=True, response="durable observed result")

            resident.capabilities.register(
                ExactTaskCapability(
                    name="observed-local",
                    triggers=("persist observed capability result",),
                    handler=handler,
                )
            )
            event = resident.enqueue("persist observed capability result")
            claimed = resident.store.claim_event(event.event_id)
            self.assertIsNotNone(claimed)
            assert claimed is not None
            state = WorkingState(
                current_event_id=claimed.event_id,
                stage="native_capability",
                next_action="observed-local",
                data={"capability_match": 1.0, "local_capability_checked": True},
            )
            resident.store.save_working_state(state)
            resolved = resident.capabilities.resolve(claimed)
            self.assertIsNotNone(resolved)
            assert resolved is not None
            capability, confidence = resolved
            local_result = capability.execute(claimed, state)
            self.assertTrue(local_result.success)
            self.assertEqual(calls, 1)
            observed = resident.store.get_working_state()
            self.assertEqual(observed.stage, "native_capability")
            self.assertEqual(observed.data["capability_execution"]["status"], "observed")
            self.assertIsNone(resident.store.get_event_outcome(event.event_id))
            self.assertEqual(resident.store.get_runtime_metrics().tasks_total, 0)
            self.assertEqual(
                resident.kernel.self_model.get("general").evidence_count,
                0,
            )

            domains = resident.resident_accounting.record_native_capability_success(
                event_id=event.event_id,
                task=event.task,
                required_capabilities=resident._required_capabilities(claimed),
                quality=max(0.5, min(1.0, float(confidence))),
            )
            self.assertEqual(domains, ("general",))
            accounted_metrics = resident.store.get_runtime_metrics()
            accounted_ability = resident.kernel.self_model.get("general").evidence_count
            self.assertEqual(accounted_metrics.tasks_total, 1)
            self.assertEqual(accounted_ability, 1)
            self.assertEqual(resident.store.get_working_state().stage, "native_capability")
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            try:
                recovered = restored.store.claim_event(event.event_id)
                self.assertIsNotNone(recovered)
                assert recovered is not None
                restored_state = restored.store.get_working_state()
                restored_readiness = restored.kernel.self_model.assess_task(
                    recovered.task,
                    restored._required_capabilities(recovered),
                )
                self.assertIsNone(
                    restored._advance_event_step(
                        recovered,
                        restored_state,
                        readiness=restored_readiness,
                        learning_evidence=[],
                    )
                )
                self.assertEqual(restored_state.stage, "orient")

                with patch.object(
                    restored.memory,
                    "recall",
                    side_effect=AssertionError("observed capability recovery must not recall"),
                ), patch.object(
                    restored.capabilities,
                    "resolve",
                    side_effect=AssertionError(
                        "observed capability recovery must not require compiled code"
                    ),
                ):
                    result = restored._orient_step(
                        recovered,
                        restored_state,
                        readiness=restored_readiness,
                    )

                self.assertIsNotNone(result)
                assert result is not None
                self.assertTrue(result.success)
                self.assertEqual(result.response, "durable observed result")
                self.assertEqual(result.capability_name, "observed-local")
                checkpoint = restored.store.get_working_state()
                self.assertEqual(checkpoint.stage, "resident_completion")
                self.assertEqual(
                    restored.store.get_runtime_metrics().tasks_total,
                    accounted_metrics.tasks_total,
                )
                self.assertEqual(
                    restored.kernel.self_model.get("general").evidence_count,
                    accounted_ability,
                )
                self.assertTrue(
                    restored.resident_accounting.has_record(
                        event.event_id,
                        "native_capability_success",
                    )
                )
                restored._complete_result(recovered, result)
                outcome = restored.store.get_event_outcome(event.event_id)
                self.assertIsNotNone(outcome)
                assert outcome is not None
                self.assertTrue(outcome.success)
                self.assertEqual(outcome.capability_name, "observed-local")
            finally:
                restored.store.close()

    def test_interrupted_default_capability_enters_recovery_without_replay_or_failure_learning(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            calls = 0

            def interrupted_handler(event, state):
                nonlocal calls
                calls += 1
                raise SystemExit("simulate interruption after durable capability start")

            resident.capabilities.register(
                ExactTaskCapability(
                    name="nonreplayable-local",
                    triggers=("perform uncertain local effect",),
                    handler=interrupted_handler,
                )
            )
            event = resident.enqueue("perform uncertain local effect")
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
            metrics_before = resident.store.get_runtime_metrics()
            ability_before = resident.kernel.self_model.get("general").evidence_count

            with self.assertRaises(SystemExit):
                resident._orient_step(claimed, state, readiness=readiness)

            self.assertEqual(calls, 1)
            interrupted = resident.store.get_working_state()
            self.assertEqual(interrupted.stage, "native_capability")
            execution = interrupted.data["capability_execution"]
            self.assertEqual(execution["status"], "started")
            self.assertFalse(execution["replay_safe"])
            attempt_id = execution["attempt_id"]
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            restored.capabilities.register(
                ExactTaskCapability(
                    name="nonreplayable-local",
                    triggers=("perform uncertain local effect",),
                    handler=lambda event, state: (_ for _ in ()).throw(
                        AssertionError("interrupted default capability must not replay")
                    ),
                )
            )
            try:
                recovered = restored.store.claim_event(event.event_id)
                self.assertIsNotNone(recovered)
                assert recovered is not None
                self.assertEqual(recovered.status, EventStatus.PROCESSING)
                restored_state = restored.store.get_working_state()
                restored_readiness = restored.kernel.self_model.assess_task(
                    recovered.task,
                    restored._required_capabilities(recovered),
                )

                self.assertIsNone(
                    restored._advance_event_step(
                        recovered,
                        restored_state,
                        readiness=restored_readiness,
                        learning_evidence=[],
                    )
                )
                self.assertEqual(restored_state.stage, "orient")
                self.assertIsNone(
                    restored._orient_step(
                        recovered,
                        restored_state,
                        readiness=restored_readiness,
                    )
                )

                recovery = restored.store.get_working_state()
                self.assertEqual(recovery.stage, "side_effect_recovery")
                self.assertEqual(recovery.blocked_by, "outside_world_effect_uncertain")
                self.assertTrue(recovery.data["side_effect_recovery"]["replay_blocked"])
                self.assertEqual(
                    recovery.data["side_effect_recovery"]["attempt_id"],
                    attempt_id,
                )
                self.assertEqual(
                    recovery.data["side_effect_recovery"]["kind"],
                    "capability",
                )
                self.assertIsNone(restored.store.get_event_outcome(event.event_id))
                self.assertEqual(
                    restored.store.get_runtime_metrics().tasks_total,
                    metrics_before.tasks_total,
                )
                self.assertEqual(
                    restored.kernel.self_model.get("general").evidence_count,
                    ability_before,
                )

                cancelled = restored.cancel_uncertain_event(event.event_id)
                self.assertTrue(cancelled.cancelled)
                outcome = restored.store.get_event_outcome(event.event_id)
                self.assertIsNotNone(outcome)
                assert outcome is not None
                self.assertTrue(outcome.cancelled)
                self.assertFalse(outcome.success)
                self.assertEqual(outcome.execution_path.value, "control")
                with closing(sqlite3.connect(restored.store.path)) as conn:
                    row = conn.execute(
                        "SELECT status FROM resident_side_effect_attempts WHERE attempt_id=?",
                        (attempt_id,),
                    ).fetchone()
                self.assertEqual(row, ("work_abandoned",))
                self.assertEqual(restored.store.get_working_state().stage, "idle")
            finally:
                restored.store.close()

    def test_explicit_replay_safe_capability_may_retry_after_interrupted_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )

            def interrupted_handler(event, state):
                raise SystemExit("simulate interruption before replay-safe result")

            resident.capabilities.register(
                ExactTaskCapability(
                    name="replayable-local",
                    triggers=("replay this safe local procedure",),
                    handler=interrupted_handler,
                    replay_safe=True,
                )
            )
            event = resident.enqueue("replay this safe local procedure")
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
            with self.assertRaises(SystemExit):
                resident._orient_step(claimed, state, readiness=readiness)
            interrupted = resident.store.get_working_state()
            self.assertEqual(interrupted.data["capability_execution"]["status"], "started")
            self.assertTrue(interrupted.data["capability_execution"]["replay_safe"])
            attempt_id = interrupted.data["capability_execution"]["attempt_id"]
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            replay_calls = 0

            def replay_handler(event, state):
                nonlocal replay_calls
                replay_calls += 1
                return CapabilityResult(success=True, response="safe replay completed")

            restored.capabilities.register(
                ExactTaskCapability(
                    name="replayable-local",
                    triggers=("replay this safe local procedure",),
                    handler=replay_handler,
                    replay_safe=True,
                )
            )
            try:
                recovered = restored.store.claim_event(event.event_id)
                self.assertIsNotNone(recovered)
                assert recovered is not None
                restored_state = restored.store.get_working_state()
                restored_readiness = restored.kernel.self_model.assess_task(
                    recovered.task,
                    restored._required_capabilities(recovered),
                )
                self.assertIsNone(
                    restored._advance_event_step(
                        recovered,
                        restored_state,
                        readiness=restored_readiness,
                        learning_evidence=[],
                    )
                )
                self.assertEqual(restored_state.stage, "orient")

                result = restored._orient_step(
                    recovered,
                    restored_state,
                    readiness=restored_readiness,
                )
                self.assertIsNotNone(result)
                assert result is not None
                self.assertTrue(result.success)
                self.assertEqual(result.response, "safe replay completed")
                self.assertEqual(replay_calls, 1)
                checkpoint = restored.store.get_working_state()
                self.assertEqual(checkpoint.stage, "resident_completion")
                self.assertEqual(
                    checkpoint.data["capability_execution"]["status"],
                    "observed",
                )
                self.assertEqual(
                    checkpoint.data["capability_execution"]["attempt_id"],
                    attempt_id,
                )
                restored._complete_result(recovered, result)
                outcome = restored.store.get_event_outcome(event.event_id)
                self.assertIsNotNone(outcome)
                assert outcome is not None
                self.assertTrue(outcome.success)
                self.assertEqual(outcome.capability_name, "replayable-local")
                with closing(sqlite3.connect(restored.store.path)) as conn:
                    row = conn.execute(
                        "SELECT status,result_success FROM resident_side_effect_attempts "
                        "WHERE attempt_id=?",
                        (attempt_id,),
                    ).fetchone()
                self.assertEqual(row, ("observed", 1))
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
