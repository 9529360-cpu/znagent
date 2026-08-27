from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import EventStatus, WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.work import ResidentWorkLedger


class ResidentWorkPointerCompletionRecoveryTests(unittest.TestCase):
    def test_verified_effect_completion_survives_restart_without_pointer_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = ResidentWorkLedger(resident)
            _, event = ledger.start(
                "work-pointer-effect-completion-crash",
                "complete only the exact independently verified pointer effect",
                kind="effect_probe",
                payload={
                    "required_capabilities": ["computer_use"],
                    "body_action": {
                        "kind": "pointer_click",
                        "args": {
                            "x_fraction": 0.5,
                            "y_fraction": 0.4,
                            "button": "left",
                        },
                    },
                    "expected_outcome": {
                        "kind": "visual_region_changed",
                        "width_fraction": 0.08,
                        "height_fraction": 0.08,
                    },
                    "completion_scope": {
                        "kind": "verified_effect",
                        "effect_kind": "visual_region_changed",
                    },
                    "model_policy": "never",
                },
            )
            claimed = resident.store.claim_event(event.event_id)
            self.assertIsNotNone(claimed)
            assert claimed is not None
            intent = NativeActionIntent(
                intent_id=f"intent-{event.event_id}",
                event_id=event.event_id,
                kind="pointer_click",
                args={
                    "x_fraction": 0.5,
                    "y_fraction": 0.4,
                    "button": "left",
                },
                expected_outcome={
                    "kind": "visual_region_changed",
                    "width_fraction": 0.08,
                    "height_fraction": 0.08,
                },
                source="resident_choice",
            )
            state = WorkingState(
                current_event_id=event.event_id,
                stage="native_verification",
                next_action="verify the bounded pointer effect",
                data={
                    "native_action_intent": intent.to_dict(),
                    "native_action_result": {
                        "success": True,
                        "kind": "pointer_click",
                    },
                    "native_verification_result": {
                        "verified": True,
                        "kind": "visual_region_changed",
                    },
                },
            )
            resident.store.save_working_state(state)

            result = resident._complete_successful_body_action(
                claimed,
                state,
                intent,
                response="verified local pointer effect",
                reason="caller reason must not broaden effect-probe authority",
            )
            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.success)
            self.assertIn("effect_probe", result.reason)
            self.assertIn("no broader user-task semantic", result.reason)
            checkpoint = resident.store.get_working_state()
            self.assertEqual(checkpoint.stage, "native_completion")
            self.assertEqual(checkpoint.next_action, "publish terminal EventOutcome")
            self.assertEqual(
                checkpoint.data["native_completion_scope"],
                {
                    "kind": "verified_effect",
                    "effect_kind": "visual_region_changed",
                },
            )
            self.assertEqual(
                checkpoint.data["native_completion"]["response"],
                "verified local pointer effect",
            )
            self.assertIsNone(resident.store.get_event_outcome(event.event_id))
            metrics_before = resident.store.get_runtime_metrics()
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            restored_ledger = ResidentWorkLedger(restored)
            try:
                recovered_event = restored.store.get_event(event.event_id)
                self.assertIsNotNone(recovered_event)
                assert recovered_event is not None
                self.assertEqual(recovered_event.status, EventStatus.PENDING)
                recovered_state = restored.store.get_working_state()
                self.assertEqual(recovered_state.stage, "native_completion")

                with patch.object(
                    restored.body,
                    "act",
                    side_effect=AssertionError("pointer/body action must not replay"),
                ), patch.object(
                    restored.visual_region,
                    "probe",
                    side_effect=AssertionError("pointer effect must not be re-probed"),
                ):
                    completed = restored.run_once(target_event_id=event.event_id)

                self.assertIsNotNone(completed)
                assert completed is not None
                self.assertTrue(completed.success)
                self.assertEqual(completed.response, "verified local pointer effect")
                self.assertIn("effect_probe", completed.reason)
                outcome = restored.store.get_event_outcome(event.event_id)
                self.assertIsNotNone(outcome)
                assert outcome is not None
                self.assertTrue(outcome.success)
                self.assertEqual(outcome.execution_path.value, "body")
                self.assertEqual(restored.store.get_working_state().stage, "idle")
                self.assertEqual(
                    restored.store.get_runtime_metrics().tasks_total,
                    metrics_before.tasks_total,
                )

                progress = restored_ledger.progress(
                    "work-pointer-effect-completion-crash",
                    event.event_id,
                )
                self.assertTrue(progress["terminal"])
                self.assertTrue(progress["finalized"])
                self.assertEqual(progress["stage"], "complete")
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main()
