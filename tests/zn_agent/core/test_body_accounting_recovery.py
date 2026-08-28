from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.body import BodyActionResult
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class BodyAccountingRecoveryTests(unittest.TestCase):
    def _resident(self, db: Path):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=db,
        )

    @staticmethod
    def _intent(event_id: str) -> NativeActionIntent:
        return NativeActionIntent(
            intent_id=f"intent-{event_id}",
            event_id=event_id,
            kind="pointer_move",
            args={"x": 10, "y": 20},
            source="resident_choice",
        )

    def test_body_success_checkpoint_precedes_accounting_and_restart_finishes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = self._resident(db)
            event = first.enqueue("complete durable body success")
            claimed = first.store.claim_event(event.event_id)
            self.assertIsNotNone(claimed)
            assert claimed is not None
            intent = self._intent(event.event_id)
            state = WorkingState(
                current_event_id=event.event_id,
                stage="native_action",
                next_action="move body: pointer_move",
                data={"native_action_intent": intent.to_dict()},
            )
            first.store.save_working_state(state)

            with patch.object(
                first.resident_accounting,
                "record_native_body_success",
                side_effect=RuntimeError("crash before Body success accounting"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "crash before Body success accounting",
                ):
                    first._complete_successful_body_action(
                        claimed,
                        state,
                        intent,
                        response="body done",
                        reason="verified body completion",
                    )

            checkpoint = first.store.get_working_state()
            self.assertEqual(checkpoint.stage, "native_completion")
            self.assertEqual(
                checkpoint.data["native_completion"]["execution_path"],
                "body",
            )
            self.assertIn("native_body_completion_accounting", checkpoint.data)
            self.assertIsNone(first.store.get_event_outcome(event.event_id))
            self.assertEqual(first.store.get_runtime_metrics().tasks_total, 0)
            self.assertEqual(first.kernel.self_model.get("general").evidence_count, 0)
            self.assertEqual(first.kernel.self_model.knowledge("general").evidence_count, 0)
            first.store.close()

            restored = self._resident(db)
            try:
                with patch.object(
                    restored.body,
                    "act",
                    side_effect=AssertionError("Body must not replay after native_completion"),
                ):
                    result = restored.run_once(target_event_id=event.event_id)

                self.assertIsNotNone(result)
                assert result is not None
                self.assertTrue(result.success)
                self.assertEqual(result.response, "body done")
                self.assertEqual(restored.store.get_runtime_metrics().tasks_total, 1)
                self.assertEqual(restored.kernel.self_model.get("general").evidence_count, 1)
                self.assertEqual(
                    restored.kernel.self_model.knowledge("general").evidence_count,
                    1,
                )
                self.assertTrue(
                    restored.resident_accounting.has_record(
                        event.event_id,
                        "native_body_success",
                    )
                )
            finally:
                restored.store.close()

    def test_body_failure_checkpoint_precedes_learning_and_restart_applies_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = self._resident(db)
            event = first.enqueue("observe one durable Body failure")
            claimed = first.store.claim_event(event.event_id)
            self.assertIsNotNone(claimed)
            assert claimed is not None
            intent = self._intent(event.event_id)
            state = WorkingState(
                current_event_id=event.event_id,
                stage="native_action",
                next_action="move body: pointer_move",
                data={"native_action_intent": intent.to_dict()},
            )
            first.store.save_working_state(state)
            failed = BodyActionResult(
                action_id="action-failed-once",
                kind="pointer_move",
                success=False,
                error="simulated Body failure",
                event_id=event.event_id,
            )

            with patch.object(first.body, "act", return_value=failed), patch.object(
                first.resident_accounting,
                "record_native_body_failure",
                side_effect=RuntimeError("crash before Body failure learning"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "crash before Body failure learning",
                ):
                    first._native_action_step(
                        claimed,
                        state,
                        readiness=None,
                    )

            checkpoint = first.store.get_working_state()
            self.assertEqual(checkpoint.stage, "native_investigation")
            records = checkpoint.data.get("native_action_failure_records")
            self.assertIsInstance(records, list)
            assert isinstance(records, list) and records
            accounting = records[-1].get("resident_accounting")
            self.assertIsInstance(accounting, dict)
            assert isinstance(accounting, dict)
            self.assertFalse(accounting["applied"])
            failure_identity = accounting["failure_identity"]
            self.assertEqual(first.kernel.self_model.get("general").evidence_count, 0)
            self.assertEqual(first.store.get_runtime_metrics().tasks_total, 0)
            first.store.close()

            restored = self._resident(db)
            try:
                recovered = restored.store.claim_event(event.event_id)
                self.assertIsNotNone(recovered)
                assert recovered is not None
                recovered_state = restored.store.get_working_state()
                self.assertEqual(recovered_state.stage, "native_investigation")

                with patch.object(
                    restored.body,
                    "act",
                    side_effect=AssertionError("failed Body action must not replay for accounting"),
                ):
                    restored._apply_pending_body_failure_accounting(
                        recovered,
                        recovered_state,
                    )
                    restored._apply_pending_body_failure_accounting(
                        recovered,
                        recovered_state,
                    )

                self.assertEqual(restored.kernel.self_model.get("general").evidence_count, 1)
                self.assertEqual(restored.store.get_runtime_metrics().tasks_total, 0)
                failure_kind = restored.resident_accounting.native_body_failure_kind(
                    failure_identity
                )
                self.assertTrue(
                    restored.resident_accounting.has_record(event.event_id, failure_kind)
                )
                final_state = restored.store.get_working_state()
                final_records = final_state.data["native_action_failure_records"]
                self.assertTrue(
                    final_records[-1]["resident_accounting"]["applied"]
                )
            finally:
                restored.store.close()

    def test_postcondition_failure_is_checkpointed_before_failure_learning(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            try:
                event = resident.enqueue("observe contradicted Body postcondition")
                claimed = resident.store.claim_event(event.event_id)
                self.assertIsNotNone(claimed)
                assert claimed is not None
                intent = self._intent(event.event_id)
                state = WorkingState(
                    current_event_id=event.event_id,
                    stage="native_verification",
                    next_action="verify body result",
                    data={"native_action_intent": intent.to_dict()},
                )
                resident.store.save_working_state(state)

                with patch.object(
                    resident.resident_accounting,
                    "record_native_body_failure",
                    side_effect=RuntimeError("crash before verification failure learning"),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "crash before verification failure learning",
                    ):
                        resident._fail_postcondition_verification(
                            claimed,
                            state,
                            intent,
                            failure="current reality contradicted the postcondition",
                        )

                checkpoint = resident.store.get_working_state()
                self.assertEqual(checkpoint.stage, "native_investigation")
                records = checkpoint.data["native_action_failure_records"]
                self.assertEqual(records[-1]["source"], "verification")
                self.assertFalse(records[-1]["resident_accounting"]["applied"])
                self.assertEqual(
                    resident.kernel.self_model.get("general").evidence_count,
                    0,
                )

                resident._apply_pending_body_failure_accounting(claimed, checkpoint)
                self.assertEqual(
                    resident.kernel.self_model.get("general").evidence_count,
                    1,
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
