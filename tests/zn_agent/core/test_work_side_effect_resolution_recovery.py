from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import EventStatus, WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.work import ResidentWorkLedger


class ResidentWorkSideEffectResolutionRecoveryTests(unittest.TestCase):
    @staticmethod
    def _attempt_row(resident, attempt_id: str):
        with closing(sqlite3.connect(resident.store.path)) as conn:
            return conn.execute(
                "SELECT status,result_action_id FROM resident_side_effect_attempts "
                "WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()

    def test_restart_after_verified_effect_before_checkpoint_save_completes_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "effect-present.txt"
            target.write_text("prefix-suffix", encoding="utf-8")

            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = ResidentWorkLedger(resident)
            _, event = ledger.start(
                "work-sidefx-resolution-crash",
                "append suffix to the current file",
                payload={"required_capabilities": ["filesystem"]},
            )
            claimed = resident.store.claim_event(event.event_id)
            self.assertIsNotNone(claimed)
            assert claimed is not None

            args = {"path": str(target), "content": "suffix", "append": True}
            expected = {
                "kind": "text_equals",
                "path": str(target),
                "expected_text": "prefix-suffix",
            }
            intent = NativeActionIntent(
                intent_id=f"intent-{event.event_id}",
                event_id=event.event_id,
                kind="write_text",
                args=args,
                expected_outcome=expected,
                source="resident_choice",
            )
            resident.store.save_working_state(
                WorkingState(
                    current_event_id=event.event_id,
                    stage="native_action",
                    next_action="move body: write_text",
                    data={"native_action_intent": intent.to_dict()},
                )
            )
            attempt_id = f"sidefx-seeded-{event.event_id}"
            resident.body._start_attempt(
                attempt_id=attempt_id,
                event_id=event.event_id,
                kind="write_text",
                signature_hash=resident.body._signature_hash("write_text", args),
            )

            self.assertIsNone(
                resident._native_action_step(claimed, resident.store.get_working_state(), readiness=None)
            )
            recovery = resident.store.get_working_state()
            self.assertEqual(recovery.stage, "side_effect_recovery")
            self.assertEqual(
                recovery.data["side_effect_recovery"]["decision"],
                "reverify_effect",
            )

            evidence = resident.body.act(
                "read_text",
                event_id=event.event_id,
                path=str(target),
                max_chars=len("prefix-suffix") + 1,
            )
            self.assertTrue(evidence.success)
            self.assertEqual(evidence.output, "prefix-suffix")
            self.assertTrue(
                resident.body.resolve_uncertain_attempt(
                    attempt_id,
                    event_id=event.event_id,
                    status="verified_effect",
                    evidence_action_id=evidence.action_id,
                )
            )
            self.assertFalse(
                resident.body.resolve_uncertain_attempt(
                    attempt_id,
                    event_id=event.event_id,
                    status="verified_absent",
                    evidence_action_id="conflicting-evidence",
                )
            )
            self.assertEqual(
                self._attempt_row(resident, attempt_id),
                ("verified_effect", evidence.action_id),
            )
            still_recovery = resident.store.get_working_state()
            self.assertEqual(still_recovery.stage, "side_effect_recovery")
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
                self.assertEqual(recovered_state.stage, "side_effect_recovery")
                self.assertEqual(
                    recovered_state.data["side_effect_recovery"]["decision"],
                    "reverify_effect",
                )

                claimed_after_restart = restored.store.claim_event(event.event_id)
                self.assertIsNotNone(claimed_after_restart)
                assert claimed_after_restart is not None
                result = restored._side_effect_recovery_step(
                    claimed_after_restart,
                    recovered_state,
                    readiness=None,
                )
                self.assertIsNotNone(result)
                assert result is not None
                self.assertTrue(result.success)
                self.assertIn("without replay", result.reason or "")
                self.assertEqual(target.read_text(encoding="utf-8"), "prefix-suffix")
                self.assertEqual(
                    self._attempt_row(restored, attempt_id),
                    ("verified_effect", evidence.action_id),
                )
                writes = [
                    item
                    for item in restored.body.recent_actions(80)
                    if item.event_id == event.event_id and item.kind == "write_text"
                ]
                self.assertEqual(writes, [])

                # Simulate a second crash after recovery has returned success but
                # before the outer resident publishes terminal EventOutcome truth.
                # The durable checkpoint must remain replay-safe recovery rather
                # than a dead-end `complete` marker that reconstructs as `orient`.
                before_terminal = restored.store.get_working_state()
                self.assertEqual(before_terminal.stage, "side_effect_recovery")
                self.assertEqual(
                    before_terminal.data["side_effect_recovery"]["decision"],
                    "reverify_effect",
                )
                self.assertIsNone(restored.store.get_event_outcome(event.event_id))
                restored.store.close()

                restored_again = build_resident_runtime_from_existing_stack(
                    config={"model": {}},
                    store_path=store_path,
                )
                restored_again_ledger = ResidentWorkLedger(restored_again)
                try:
                    event_again = restored_again.store.get_event(event.event_id)
                    self.assertIsNotNone(event_again)
                    assert event_again is not None
                    self.assertEqual(event_again.status, EventStatus.PENDING)
                    state_again = restored_again.store.get_working_state()
                    self.assertEqual(state_again.stage, "side_effect_recovery")
                    self.assertEqual(
                        state_again.data["side_effect_recovery"]["decision"],
                        "reverify_effect",
                    )
                    claimed_again = restored_again.store.claim_event(event.event_id)
                    self.assertIsNotNone(claimed_again)
                    assert claimed_again is not None
                    result_again = restored_again._side_effect_recovery_step(
                        claimed_again,
                        state_again,
                        readiness=None,
                    )
                    self.assertIsNotNone(result_again)
                    assert result_again is not None
                    self.assertTrue(result_again.success)
                    self.assertEqual(target.read_text(encoding="utf-8"), "prefix-suffix")
                    writes_again = [
                        item
                        for item in restored_again.body.recent_actions(80)
                        if item.event_id == event.event_id and item.kind == "write_text"
                    ]
                    self.assertEqual(writes_again, [])

                    restored_again._complete_result(claimed_again, result_again)
                    progress = restored_again_ledger.progress(
                        "work-sidefx-resolution-crash",
                        event.event_id,
                    )
                    self.assertTrue(progress["terminal"])
                    self.assertTrue(progress["finalized"])
                    self.assertEqual(progress["stage"], "complete")
                finally:
                    restored_again.store.close()
            finally:
                try:
                    restored.store.close()
                except sqlite3.ProgrammingError:
                    pass


if __name__ == "__main__":
    unittest.main()
