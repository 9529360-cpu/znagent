from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.body import BodyAction, BodyActionResult
from zn_agent.core.models import WorkingState, utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class _NoReplayBrowser:
    def __getattr__(self, name):
        raise AssertionError(f"browser provider must not be used during observed-result recovery: {name}")


class BrowserWorkObservedResultRecoveryTests(unittest.TestCase):
    @staticmethod
    def _intent(event_id: str) -> NativeActionIntent:
        return NativeActionIntent(
            intent_id=f"intent-{event_id}",
            event_id=event_id,
            kind="browser_click_named_button_to_url",
            args={
                "url": "https://example.com/start",
                "target_name": "Continue",
                "expected_url": "https://example.com/done",
            },
            source="resident_choice",
        )

    @staticmethod
    def _verified_result(event_id: str, *, revalidated: bool = True) -> BodyActionResult:
        now = utc_now()
        return BodyActionResult(
            action_id=f"body-observed-{event_id}",
            kind="browser_click_named_button_to_url",
            success=True,
            output="https://example.com/done",
            data={
                "url": "https://example.com/start",
                "expected_url": "https://example.com/done",
                "observed_url": "https://example.com/done",
                "page_id": "page-1",
                "target_id": "a11y-continue",
                "target_role": "button",
                "target_name": "Continue",
                "selector_hint": "accessible_button_name:exact",
                "provider": "test-browser",
                "postcondition": "url_equals_after_fresh_semantic_button_click",
                "target_revalidated_before_dispatch": revalidated,
                "browser_evidence": {
                    "action_id": "browser-click-1",
                    "session_id": "browser-session-1",
                    "observed_at": now,
                    "success": True,
                    "page_id": "page-1",
                    "url_before": "https://example.com/start",
                    "url_after": "https://example.com/done",
                    "target_id": "a11y-continue",
                    "postcondition": "url_equals_after_fresh_semantic_button_click",
                    "data": {
                        "provider": "test-browser",
                        "target_revalidated_before_dispatch": revalidated,
                        "expected_url": "https://example.com/done",
                    },
                    "error": None,
                },
                "closed": True,
            },
            event_id=event_id,
            started_at=now,
            completed_at=now,
        )

    @staticmethod
    def _seed_observed_result(resident, event, intent, result) -> None:
        resident.store.save_working_state(
            WorkingState(
                current_event_id=event.event_id,
                stage="native_action",
                next_action="move body: browser_click_named_button_to_url",
                data={"native_action_intent": intent.to_dict()},
            )
        )
        signature = resident.body._signature_hash(intent.kind, dict(intent.args))
        attempt_id = f"sidefx-observed-{event.event_id}"
        resident.body._start_attempt(
            attempt_id=attempt_id,
            event_id=event.event_id,
            kind=intent.kind,
            signature_hash=signature,
        )
        resident.body._record(
            BodyAction(
                action_id=result.action_id,
                kind=result.kind,
                args=dict(intent.args),
                event_id=event.event_id,
            ),
            result,
        )
        resident.body._finish_attempt(attempt_id, result)

    def _restart_with_observed_result(self, *, revalidated: bool):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        store_path = root / "kernel.db"
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=store_path,
        )
        event = resident.enqueue(
            "click the requested button once",
            payload={"required_capabilities": ["browser"]},
        )
        claimed = resident.store.claim_event(event.event_id)
        self.assertIsNotNone(claimed)
        intent = self._intent(event.event_id)
        result = self._verified_result(event.event_id, revalidated=revalidated)
        self._seed_observed_result(resident, event, intent, result)
        resident.store.close()

        restored = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=store_path,
        )
        restored.managed_browser = _NoReplayBrowser()
        recovered_event = restored.store.claim_event(event.event_id)
        self.assertIsNotNone(recovered_event)
        assert recovered_event is not None
        recovered_state = restored.store.get_working_state()
        return tmp, restored, recovered_event, recovered_state

    def test_verified_observed_button_result_completes_without_replay(self) -> None:
        tmp, restored, event, state = self._restart_with_observed_result(revalidated=True)
        try:
            result = restored._native_action_step(event, state, readiness=None)
            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.success)
            self.assertEqual(result.response, "https://example.com/done")
            self.assertIn("without replaying", result.reason)

            durable = restored.store.get_working_state()
            self.assertEqual(durable.stage, "native_completion")
            self.assertNotIn("side_effect_recovery", durable.data)
            self.assertEqual(
                durable.data["native_action_result"]["action_id"],
                f"body-observed-{event.event_id}",
            )
        finally:
            restored.store.close()
            tmp.cleanup()

    def test_incomplete_observed_button_evidence_stays_fail_closed(self) -> None:
        tmp, restored, event, state = self._restart_with_observed_result(revalidated=False)
        try:
            result = restored._native_action_step(event, state, readiness=None)
            self.assertIsNone(result)
            durable = restored.store.get_working_state()
            self.assertEqual(durable.stage, "side_effect_recovery")
            recovery = durable.data["side_effect_recovery"]
            self.assertEqual(recovery["decision"], "user_decision_required")
            self.assertTrue(recovery["replay_blocked"])
        finally:
            restored.store.close()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
