from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.models import EventStatus, WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.work import ResidentWorkLedger


class ResidentWorkUICompletionRecoveryTests(unittest.TestCase):
    def test_verified_ui_completion_survives_restart_without_resensing_or_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = ResidentWorkLedger(resident)
            scope = {
                "kind": "foreground_window_matches",
                "process_name": "notepad.exe",
                "title_equals": "Untitled - Notepad",
            }
            _, event = ledger.start(
                "work-ui-completion-crash",
                "complete only the exact independently verified UI state",
                kind="ui_state_transition",
                payload={
                    "required_capabilities": ["computer_use"],
                    "completion_scope": dict(scope),
                    "model_policy": "never",
                },
            )
            claimed = resident.store.claim_event(event.event_id)
            self.assertIsNotNone(claimed)
            assert claimed is not None
            state = WorkingState(
                current_event_id=event.event_id,
                stage="native_verification",
                next_action="verify the exact typed UI completion scope",
                data={
                    "native_verification_result": {
                        "verified": True,
                        "kind": "foreground_window_matches",
                    },
                },
            )
            resident.store.save_working_state(state)

            response = "foreground window process=notepad.exe title='Untitled - Notepad'"
            reason = (
                "ZN completed this ui_state_transition only from fresh resident-owned "
                "typed UI evidence"
            )
            result = resident._complete_ui_scope(
                claimed,
                state,
                scope,
                response=response,
                reason=reason,
            )
            self.assertTrue(result.success)
            self.assertEqual(result.response, response)
            self.assertEqual(result.reason, reason)
            checkpoint = resident.store.get_working_state()
            self.assertEqual(checkpoint.stage, "native_completion")
            self.assertEqual(checkpoint.next_action, "publish terminal EventOutcome")
            self.assertEqual(checkpoint.data["native_completion_scope"], scope)
            self.assertEqual(checkpoint.data["native_completion"]["response"], response)
            self.assertEqual(checkpoint.data["native_completion"]["reason"], reason)
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
                self.assertEqual(recovered_state.data["native_completion_scope"], scope)

                with patch.object(
                    restored.body,
                    "act",
                    side_effect=AssertionError("body/input must not replay"),
                ), patch.object(
                    restored,
                    "_native_verification_step",
                    side_effect=AssertionError("typed UI verification must not repeat"),
                ):
                    completed = restored.run_once(target_event_id=event.event_id)

                self.assertIsNotNone(completed)
                assert completed is not None
                self.assertTrue(completed.success)
                self.assertEqual(completed.response, response)
                self.assertEqual(completed.reason, reason)
                outcome = restored.store.get_event_outcome(event.event_id)
                self.assertIsNotNone(outcome)
                assert outcome is not None
                self.assertTrue(outcome.success)
                self.assertEqual(outcome.execution_path.value, "body")
                self.assertEqual(outcome.response, response)
                self.assertEqual(restored.store.get_working_state().stage, "idle")
                self.assertEqual(
                    restored.store.get_runtime_metrics().tasks_total,
                    metrics_before.tasks_total,
                )

                progress = restored_ledger.progress(
                    "work-ui-completion-crash",
                    event.event_id,
                )
                self.assertTrue(progress["terminal"])
                self.assertTrue(progress["finalized"])
                self.assertEqual(progress["stage"], "complete")
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main()
