from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core import CapabilityResult, ExactTaskCapability
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class CapabilityFailureRecoveryTests(unittest.TestCase):
    def test_observed_failure_resumes_without_code_or_duplicate_failure_learning(self):
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
                return CapabilityResult(
                    success=False,
                    error="known compiled capability failure",
                )

            resident.capabilities.register(
                ExactTaskCapability(
                    name="known-failing-local",
                    triggers=("observe one local failure",),
                    handler=handler,
                )
            )
            event = resident.enqueue("observe one local failure")
            claimed = resident.store.claim_event(event.event_id)
            self.assertIsNotNone(claimed)
            assert claimed is not None
            state = WorkingState(
                current_event_id=claimed.event_id,
                stage="native_capability",
                next_action="known-failing-local",
                data={"capability_match": 1.0, "local_capability_checked": True},
            )
            resident.store.save_working_state(state)

            resolved = resident.capabilities.resolve(claimed)
            self.assertIsNotNone(resolved)
            assert resolved is not None
            capability, _confidence = resolved
            local_result = capability.execute(claimed, state)
            self.assertFalse(local_result.success)
            self.assertEqual(calls, 1)

            observed = resident.store.get_working_state()
            self.assertEqual(observed.stage, "native_capability")
            execution = observed.data["capability_execution"]
            self.assertEqual(execution["status"], "observed")
            self.assertFalse(execution["result"]["success"])
            self.assertEqual(
                execution["result"]["error"],
                "known compiled capability failure",
            )
            self.assertEqual(
                resident.kernel.self_model.get("general").evidence_count,
                0,
            )
            self.assertEqual(resident.store.get_runtime_metrics().tasks_total, 0)

            # Simulate a crash after failure accounting commits but before the
            # resident advances WorkingState to native investigation.
            domains = resident.resident_accounting.record_native_capability_failure(
                event_id=event.event_id,
                task=event.task,
                required_capabilities=resident._required_capabilities(claimed),
            )
            self.assertEqual(domains, ("general",))
            accounted_ability = resident.kernel.self_model.get("general")
            accounted_metrics = resident.store.get_runtime_metrics()
            self.assertEqual(accounted_ability.evidence_count, 1)
            self.assertEqual(accounted_ability.score, 0.0)
            self.assertEqual(accounted_metrics.tasks_total, 0)
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

                # The generic stage dispatcher safely returns unknown legacy
                # native_capability state to orient; the durable observed result
                # remains in state.data and must own what happens next.
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
                    side_effect=AssertionError(
                        "observed failure recovery must not consult structured memory"
                    ),
                ), patch.object(
                    restored.capabilities,
                    "resolve",
                    side_effect=AssertionError(
                        "observed failure recovery must not require compiled code"
                    ),
                ):
                    result = restored._orient_step(
                        recovered,
                        restored_state,
                        readiness=restored_readiness,
                    )

                self.assertIsNone(result)
                checkpoint = restored.store.get_working_state()
                self.assertEqual(checkpoint.stage, "native_investigation")
                self.assertEqual(
                    checkpoint.next_action,
                    "select the next native probe",
                )
                self.assertEqual(
                    checkpoint.data["local_failure"],
                    "known compiled capability failure",
                )
                self.assertIsNone(checkpoint.blocked_by)
                self.assertIsNone(restored.store.get_event_outcome(event.event_id))
                self.assertEqual(
                    restored.kernel.self_model.get("general").evidence_count,
                    accounted_ability.evidence_count,
                )
                self.assertEqual(
                    restored.kernel.self_model.get("general").score,
                    accounted_ability.score,
                )
                self.assertEqual(
                    restored.store.get_runtime_metrics().tasks_total,
                    accounted_metrics.tasks_total,
                )
                self.assertTrue(
                    restored.resident_accounting.has_record(
                        event.event_id,
                        "native_capability_failure",
                    )
                )
            finally:
                restored.store.close()

    def test_malformed_observed_result_fails_closed_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            try:
                event = resident.enqueue("do not replay malformed observed result")
                claimed = resident.store.claim_event(event.event_id)
                self.assertIsNotNone(claimed)
                assert claimed is not None
                state = WorkingState(
                    current_event_id=claimed.event_id,
                    stage="orient",
                    next_action="orient to current event",
                    data={
                        "capability_execution": {
                            "attempt_id": "capfx-malformed",
                            "capability_name": "malformed-local",
                            "signature_hash": "deadbeef",
                            "replay_safe": False,
                            "status": "observed",
                            "result": {"error": "missing success truth"},
                        }
                    },
                )
                resident.store.save_working_state(state)
                readiness = resident.kernel.self_model.assess_task(
                    claimed.task,
                    resident._required_capabilities(claimed),
                )

                with patch.object(
                    resident.memory,
                    "recall",
                    side_effect=AssertionError("malformed observed result must fail closed"),
                ), patch.object(
                    resident.capabilities,
                    "resolve",
                    side_effect=AssertionError("malformed observed result must not replay"),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "observed capability result checkpoint is malformed",
                    ):
                        resident._orient_step(
                            claimed,
                            state,
                            readiness=readiness,
                        )

                self.assertIsNone(resident.store.get_event_outcome(event.event_id))
                self.assertEqual(resident.store.get_runtime_metrics().tasks_total, 0)
                self.assertEqual(
                    resident.kernel.self_model.get("general").evidence_count,
                    0,
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
