from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from tests.zn_agent.core.test_browser_work_enter_submit import _FakeEnterSubmitBrowser
from tests.zn_agent.core.test_browser_work_form_submit import (
    _DONE_URL,
    _FORM_TEXT,
    _START_URL,
)


class _NoReplayBrowser:
    def __getattr__(self, name):
        raise AssertionError(f"browser must not replay durable Enter submission: {name}")


class BrowserWorkEnterSubmitRecoveryTests(unittest.TestCase):
    def _restart_after_observed_dispatch(self, *, complete_evidence: bool = True):
        tmp = tempfile.TemporaryDirectory()
        store_path = Path(tmp.name) / "kernel.db"
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}}, store_path=store_path
        )
        browser = _FakeEnterSubmitBrowser()
        if not complete_evidence:
            original_act = browser.act

            def act_with_incomplete_enter_evidence(action, authority):
                effect = original_act(action, authority)
                if action.kind.value == "press":
                    effect.data["text_revalidated_before_dispatch"] = False
                return effect

            browser.act = act_with_incomplete_enter_evidence
        resident.managed_browser = browser
        event = resident.enqueue(
            f'open {_START_URL} and type "{_FORM_TEXT}" into textbox "Search", '
            f'then press Enter and expect {_DONE_URL}',
            payload={"required_capabilities": ["browser"]},
        )
        claimed = resident.store.claim_event(event.event_id)
        self.assertIsNotNone(claimed)
        intent = NativeActionIntent(
            intent_id=f"browser-form-enter-submit-{event.event_id}",
            event_id=event.event_id,
            kind="browser_fill_named_text_and_press_enter_to_url",
            args={
                "url": _START_URL,
                "textbox_name": "Search",
                "text": _FORM_TEXT,
                "expected_url": _DONE_URL,
            },
            source="native_deliberation",
        )
        resident.store.save_working_state(
            WorkingState(
                current_event_id=event.event_id,
                stage="native_action",
                next_action="move body: browser Enter submit",
                data={"native_action_intent": intent.to_dict()},
            )
        )
        dispatched = resident.body.act(
            intent.kind,
            event_id=event.event_id,
            **intent.args,
        )
        self.assertTrue(dispatched.success, dispatched.error)
        resident.store.close()

        restored = build_resident_runtime_from_existing_stack(
            config={"model": {}}, store_path=store_path
        )
        restored.managed_browser = _NoReplayBrowser()
        recovered_event = restored.store.claim_event(event.event_id)
        self.assertIsNotNone(recovered_event)
        state = restored.store.get_working_state()
        return tmp, restored, recovered_event, state

    def test_verified_enter_submit_result_resumes_without_replay(self) -> None:
        tmp, restored, event, state = self._restart_after_observed_dispatch()
        try:
            result = restored._native_action_step(event, state, readiness=None)
            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.success)
            self.assertEqual(result.response, _DONE_URL)
            self.assertIn("without replaying", result.reason)
            durable = restored.store.get_working_state()
            self.assertEqual(durable.stage, "native_completion")
            self.assertNotIn("side_effect_recovery", durable.data)
        finally:
            restored.store.close()
            tmp.cleanup()

    def test_incomplete_enter_evidence_remains_fail_closed(self) -> None:
        tmp, restored, event, state = self._restart_after_observed_dispatch(
            complete_evidence=False
        )
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
