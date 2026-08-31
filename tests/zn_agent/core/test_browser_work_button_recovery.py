from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class BrowserWorkButtonRecoveryTests(unittest.TestCase):
    def test_interrupted_named_button_work_enters_recovery_without_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                args = {
                    "url": "https://example.com/start",
                    "target_name": "Continue",
                    "expected_url": "https://example.com/done",
                }
                event = resident.enqueue(
                    "click the requested button once",
                    payload={"required_capabilities": ["browser"]},
                )
                claimed = resident.store.claim_event(event.event_id)
                self.assertIsNotNone(claimed)

                intent = NativeActionIntent(
                    intent_id=f"intent-{event.event_id}",
                    event_id=event.event_id,
                    kind="browser_click_named_button_to_url",
                    args=args,
                    source="resident_choice",
                )
                state = WorkingState(
                    current_event_id=event.event_id,
                    stage="native_action",
                    next_action="move body: browser_click_named_button_to_url",
                    data={"native_action_intent": intent.to_dict()},
                )
                resident.store.save_working_state(state)

                signature = resident.body._signature_hash(intent.kind, args)
                resident.body._start_attempt(
                    attempt_id=f"sidefx-seeded-{event.event_id}",
                    event_id=event.event_id,
                    kind=intent.kind,
                    signature_hash=signature,
                )

                self.assertIsNone(
                    resident._native_action_step(event, state, readiness=None)
                )
                recovered = resident.store.get_working_state()
                self.assertEqual(recovered.stage, "side_effect_recovery")
                recovery = recovered.data["side_effect_recovery"]
                self.assertEqual(
                    recovery["kind"],
                    "browser_click_named_button_to_url",
                )
                self.assertEqual(recovery["decision"], "user_decision_required")
                self.assertTrue(recovery["replay_blocked"])
                self.assertNotIn("local_failure", recovered.data)
                self.assertEqual(len(resident.body.uncertain_attempts(event.event_id)), 1)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
