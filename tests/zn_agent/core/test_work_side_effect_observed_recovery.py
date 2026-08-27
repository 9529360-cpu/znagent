from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class ResidentObservedSideEffectRecoveryTests(unittest.TestCase):
    @staticmethod
    def _attempt_row(resident, event_id: str):
        with closing(sqlite3.connect(resident.store.path)) as conn:
            return conn.execute(
                "SELECT attempt_id,status,result_action_id,result_success "
                "FROM resident_side_effect_attempts WHERE event_id=? "
                "ORDER BY started_at DESC LIMIT 1",
                (event_id,),
            ).fetchone()

    def test_restart_after_observed_append_before_checkpoint_save_recovers_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "observed-before-checkpoint.txt"
            target.write_text("prefix-", encoding="utf-8")

            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            event = resident.enqueue(
                "append suffix once",
                payload={"required_capabilities": ["filesystem"]},
            )
            claimed = resident.store.claim_event(event.event_id)
            self.assertIsNotNone(claimed)
            intent = NativeActionIntent(
                intent_id=f"intent-{event.event_id}",
                event_id=event.event_id,
                kind="write_text",
                args={"path": str(target), "content": "suffix", "append": True},
                expected_outcome={
                    "kind": "text_equals",
                    "path": str(target),
                    "expected_text": "prefix-suffix",
                },
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
            first = resident.body.act(
                "write_text",
                event_id=event.event_id,
                **dict(intent.args),
            )
            self.assertTrue(first.success)
            self.assertEqual(target.read_text(encoding="utf-8"), "prefix-suffix")
            before_restart = self._attempt_row(resident, event.event_id)
            self.assertIsNotNone(before_restart)
            assert before_restart is not None
            self.assertEqual(before_restart[1], "observed")
            self.assertEqual(before_restart[3], 1)
            stale = resident.store.get_working_state()
            self.assertEqual(stale.stage, "native_action")
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            try:
                recovered_event = restored.store.claim_event(event.event_id)
                self.assertIsNotNone(recovered_event)
                assert recovered_event is not None
                recovered_state = restored.store.get_working_state()
                self.assertEqual(recovered_state.stage, "native_action")

                self.assertIsNone(
                    restored._native_action_step(
                        recovered_event,
                        recovered_state,
                        readiness=None,
                    )
                )
                recovery_state = restored.store.get_working_state()
                self.assertEqual(recovery_state.stage, "side_effect_recovery")
                recovery = recovery_state.data["side_effect_recovery"]
                self.assertEqual(recovery["decision"], "reverify_effect")
                self.assertTrue(recovery["replay_blocked"])
                self.assertEqual(target.read_text(encoding="utf-8"), "prefix-suffix")

                result = restored._side_effect_recovery_step(
                    recovered_event,
                    recovery_state,
                    readiness=None,
                )
                self.assertIsNotNone(result)
                assert result is not None
                self.assertTrue(result.success)
                self.assertIn("without replay", result.reason)
                self.assertEqual(target.read_text(encoding="utf-8"), "prefix-suffix")

                after = self._attempt_row(restored, event.event_id)
                self.assertIsNotNone(after)
                assert after is not None
                self.assertEqual(after[0], before_restart[0])
                self.assertEqual(after[1], "verified_effect")
                self.assertEqual(after[2], before_restart[2])
                self.assertEqual(after[3], 1)
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main()
