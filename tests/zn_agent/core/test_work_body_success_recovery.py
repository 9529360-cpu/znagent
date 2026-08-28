from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import EventStatus, WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.work import ResidentWorkLedger


class ResidentWorkBodySuccessRecoveryTests(unittest.TestCase):
    def test_restart_publishes_verified_body_completion_without_body_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "verified.txt"
            expected_text = "already verified body result"
            target.write_text(expected_text, encoding="utf-8")

            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = ResidentWorkLedger(resident)
            _, event = ledger.start(
                "work-body-success-crash",
                "write the exact verified text",
                payload={"required_capabilities": ["filesystem"]},
            )
            claimed = resident.store.claim_event(event.event_id)
            self.assertIsNotNone(claimed)
            assert claimed is not None
            intent = NativeActionIntent(
                intent_id=f"intent-{event.event_id}",
                event_id=event.event_id,
                kind="write_text",
                args={"path": str(target), "content": expected_text},
                expected_outcome={
                    "kind": "text_equals",
                    "path": str(target),
                    "expected_text": expected_text,
                },
                source="resident_choice",
            )
            resident.store.save_working_state(
                WorkingState(
                    current_event_id=event.event_id,
                    stage="native_verification",
                    next_action="verify the requested postcondition from current reality",
                    data={
                        "native_action_intent": intent.to_dict(),
                        "native_action_result": {
                            "success": True,
                            "kind": "write_text",
                        },
                        "native_verification": dict(intent.expected_outcome or {}),
                    },
                )
            )

            result = resident._native_verification_step(
                claimed,
                resident.store.get_working_state(),
                readiness=None,
            )
            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.success)
            checkpoint = resident.store.get_working_state()
            self.assertEqual(checkpoint.stage, "native_completion")
            self.assertEqual(
                checkpoint.data["native_completion"]["execution_path"],
                "body",
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
                    side_effect=AssertionError("body action must not replay"),
                ):
                    completed = restored.run_once(target_event_id=event.event_id)

                self.assertIsNotNone(completed)
                assert completed is not None
                self.assertTrue(completed.success)
                self.assertEqual(completed.response, str(target))
                self.assertEqual(target.read_text(encoding="utf-8"), expected_text)
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
                    "work-body-success-crash",
                    event.event_id,
                )
                self.assertTrue(progress["terminal"])
                self.assertTrue(progress["finalized"])
                self.assertEqual(progress["stage"], "complete")
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main()
