from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.kernel.action import NativeActionIntent
from agent.kernel.cognition import CognitiveIncrement
from agent.kernel.embodied_resident import EmbodiedResidentRuntime
from agent.kernel.models import AgentEvent, WorkingState
from agent.kernel.provider_bridge import build_resident_runtime
from agent.kernel.world_closed_loop import WorldAwareTransferResidentRuntime


class FailedActionEvidenceGuardTests(unittest.TestCase):
    @staticmethod
    def _event() -> AgentEvent:
        return AgentEvent(
            event_id="evt-failure-guard",
            task="repair the current workspace",
        )

    @staticmethod
    def _intent(name: str) -> NativeActionIntent:
        return NativeActionIntent(
            intent_id=f"act-{name}",
            event_id="evt-failure-guard",
            kind="command",
            args={"command": f"do-{name}"},
        )

    @staticmethod
    def _resident(tmp: str, filename: str = "kernel.db") -> EmbodiedResidentRuntime:
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=Path(tmp) / filename,
        )
        if not isinstance(resident, EmbodiedResidentRuntime):
            raise AssertionError(type(resident))
        return resident

    def test_product_runtime_keeps_existing_world_aware_resident_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            self.assertIsInstance(resident, WorldAwareTransferResidentRuntime)
            self.assertTrue(hasattr(resident, "_action_blocked_by_current_evidence"))
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_a_b_a_stays_blocked_under_same_reality_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            event = self._event()
            state = WorkingState(current_event_id=event.event_id)
            action_a = self._intent("a")
            action_b = self._intent("b")

            with patch.object(
                EmbodiedResidentRuntime,
                "_evidence_fingerprint",
                return_value="reality-v1",
            ):
                resident._record_failed_action(
                    event, state, action_a, source="body", failure="A failed"
                )
                resident._record_failed_action(
                    event, state, action_b, source="body", failure="B failed"
                )
                self.assertTrue(
                    resident._action_blocked_by_current_evidence(event, state, action_a)
                )
                self.assertTrue(
                    resident._action_blocked_by_current_evidence(event, state, action_b)
                )

            records = state.data[resident._FAILED_ACTION_RECORDS_KEY]
            self.assertEqual(len(records), 2)
            self.assertEqual({item["kind"] for item in records}, {"command"})
            resident.store.close()

    def test_changed_reality_evidence_requalifies_prior_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            event = self._event()
            state = WorkingState(current_event_id=event.event_id)
            action = self._intent("retry")

            with patch.object(
                EmbodiedResidentRuntime,
                "_evidence_fingerprint",
                return_value="reality-v1",
            ):
                resident._record_failed_action(
                    event, state, action, source="verification", failure="check failed"
                )
                self.assertTrue(
                    resident._action_blocked_by_current_evidence(event, state, action)
                )

            # An old interrupted runtime may still have the historical one-slot
            # signature. Once the ledger exists, it cannot turn a changed reality
            # state into a permanent blacklist.
            state.data["native_action_failure_signature"] = resident._intent_signature(action)
            with patch.object(
                EmbodiedResidentRuntime,
                "_evidence_fingerprint",
                return_value="reality-v2",
            ):
                self.assertFalse(
                    resident._action_blocked_by_current_evidence(event, state, action)
                )
                resident._begin_native_action_cycle(event, state, action)
            self.assertNotIn("native_action_failure_signature", state.data)
            self.assertEqual(state.stage, "native_action")
            resident.store.close()

    def test_repeated_failure_is_deduplicated_and_ledger_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            event = self._event()
            state = WorkingState(current_event_id=event.event_id)
            repeated = self._intent("repeat")

            with patch.object(
                EmbodiedResidentRuntime,
                "_evidence_fingerprint",
                return_value="same-reality",
            ):
                resident._record_failed_action(
                    event, state, repeated, source="body", failure="first failure"
                )
                resident._record_failed_action(
                    event, state, repeated, source="body", failure="second failure"
                )
            records = state.data[resident._FAILED_ACTION_RECORDS_KEY]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["failure"], "second failure")

            for index in range(resident._MAX_FAILED_ACTION_RECORDS + 5):
                with patch.object(
                    EmbodiedResidentRuntime,
                    "_evidence_fingerprint",
                    return_value=f"reality-{index}",
                ):
                    resident._record_failed_action(
                        event,
                        state,
                        self._intent(f"bounded-{index}"),
                        source="body",
                        failure=f"failure-{index}",
                    )
            records = state.data[resident._FAILED_ACTION_RECORDS_KEY]
            self.assertEqual(len(records), resident._MAX_FAILED_ACTION_RECORDS)
            self.assertEqual(records[-1]["failure"], "failure-20")
            resident.store.close()

    def test_failure_records_survive_resident_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=store_path)
            self.assertIsInstance(resident, EmbodiedResidentRuntime)
            event = self._event()
            state = WorkingState(
                current_event_id=event.event_id,
                stage="native_investigation",
            )
            action = self._intent("persist")
            with patch.object(
                EmbodiedResidentRuntime,
                "_evidence_fingerprint",
                return_value="persisted-reality",
            ):
                resident._record_failed_action(
                    event, state, action, source="body", failure="persist me"
                )
            resident.store.save_working_state(state)
            resident.store.close()

            restarted = build_resident_runtime(config={"model": {}}, store_path=store_path)
            self.assertIsInstance(restarted, EmbodiedResidentRuntime)
            recovered = restarted.store.get_working_state()
            records = recovered.data[restarted._FAILED_ACTION_RECORDS_KEY]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["failure"], "persist me")
            self.assertEqual(records[0]["evidence_fingerprint"], "persisted-reality")
            restarted.store.close()

    def test_legacy_single_signature_migrates_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            event = self._event()
            state = WorkingState(current_event_id=event.event_id)
            action = self._intent("legacy")
            state.data["native_action_failure_signature"] = resident._intent_signature(action)
            state.data["local_failure"] = "old persisted failure"

            with patch.object(
                EmbodiedResidentRuntime,
                "_evidence_fingerprint",
                return_value="migration-reality",
            ):
                self.assertTrue(
                    resident._action_blocked_by_current_evidence(event, state, action)
                )
            records = state.data[resident._FAILED_ACTION_RECORDS_KEY]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["source"], "legacy")
            self.assertEqual(records[0]["evidence_fingerprint"], "migration-reality")
            resident.store.close()

    def test_external_cognition_cannot_complete_same_blocked_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            event = self._event()
            action = self._intent("blocked")
            increment = CognitiveIncrement.create(
                event_id=event.event_id,
                impasse_id=None,
                source="external:test",
                question="what should change?",
                content="try the same movement again",
                quality=0.8,
                confidence=0.8,
            )
            state = WorkingState(
                current_event_id=event.event_id,
                stage="cognition_integration",
                data={
                    "cognitive_increment": increment.to_dict(),
                    "external_cognition_result": {"model_invocations": 1},
                    "cognition_integration": {"accepted": True},
                },
            )
            with patch.object(
                EmbodiedResidentRuntime,
                "_evidence_fingerprint",
                return_value="same-reality",
            ):
                resident._record_failed_action(
                    event, state, action, source="body", failure="movement failed"
                )
                with patch(
                    "agent.kernel.embodied_resident.derive_native_action_intent",
                    return_value=action,
                ):
                    result = resident._cognition_integration_step(
                        event,
                        state,
                        readiness=None,
                    )

            self.assertIsNotNone(result)
            self.assertFalse(result.success)
            self.assertEqual(state.stage, "failed")
            self.assertIn("did not change current reality", result.reason)
            self.assertIn("did not change current reality", state.data["local_failure"])
            resident.store.close()

    def test_evidence_fingerprint_ignores_observation_clock_noise(self):
        first = EmbodiedResidentRuntime._stable_fact_value(
            {
                "git": {"head": "abc123", "dirty": True},
                "world": {
                    "changed": False,
                    "captured_at": "2026-08-23T10:00:00+00:00",
                },
                "updated_at": "2026-08-23T10:00:01+00:00",
            }
        )
        second = EmbodiedResidentRuntime._stable_fact_value(
            {
                "git": {"head": "abc123", "dirty": True},
                "world": {
                    "changed": False,
                    "captured_at": "2026-08-23T11:00:00+00:00",
                },
                "updated_at": "2026-08-23T11:00:01+00:00",
            }
        )
        changed = EmbodiedResidentRuntime._stable_fact_value(
            {
                "git": {"head": "def456", "dirty": True},
                "world": {
                    "changed": False,
                    "captured_at": "2026-08-23T11:00:00+00:00",
                },
            }
        )
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)


if __name__ == "__main__":
    unittest.main()
