from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from tests.zn_agent.core.test_browser_work_named_text import (
    _FakeNamedTextBrowser,
    _TYPED_TEXT,
)


class _NoReplayBrowser:
    def __getattr__(self, name):
        raise AssertionError(f"browser must not replay durable named-text result: {name}")


class BrowserWorkNamedTextRecoveryTests(unittest.TestCase):
    def _restart_after_observed_dispatch(self, *, continuity: bool = True):
        tmp = tempfile.TemporaryDirectory()
        store_path = Path(tmp.name) / "kernel.db"
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=store_path,
        )
        browser = _FakeNamedTextBrowser()
        if not continuity:
            original_act = browser.act

            def act_with_bad_continuity(action, authority):
                effect = original_act(action, authority)
                if action.kind.value == "type_text":
                    effect.data["exact_node_continuity"] = False
                return effect

            browser.act = act_with_bad_continuity
        resident.managed_browser = browser
        event = resident.enqueue(
            'open https://example.com/form and type "ZN hello ✓" into textbox "Search"',
            payload={"required_capabilities": ["browser"]},
        )
        claimed = resident.store.claim_event(event.event_id)
        self.assertIsNotNone(claimed)
        intent = NativeActionIntent(
            intent_id=f"browser-named-text-{event.event_id}",
            event_id=event.event_id,
            kind="browser_type_named_text",
            args={
                "url": "https://example.com/form",
                "target_name": "Search",
                "text": _TYPED_TEXT,
            },
            source="native_deliberation",
        )
        resident.store.save_working_state(
            WorkingState(
                current_event_id=event.event_id,
                stage="native_action",
                next_action="move body: browser_type_named_text",
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
            config={"model": {}},
            store_path=store_path,
        )
        restored.managed_browser = _NoReplayBrowser()
        recovered_event = restored.store.claim_event(event.event_id)
        self.assertIsNotNone(recovered_event)
        state = restored.store.get_working_state()
        return tmp, restored, recovered_event, state

    def test_verified_named_text_result_resumes_without_replay(self) -> None:
        tmp, restored, event, state = self._restart_after_observed_dispatch()
        try:
            result = restored._native_action_step(event, state, readiness=None)
            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.success)
            self.assertNotIn(_TYPED_TEXT, result.response)
            self.assertIn("without replaying", result.reason)
            durable = restored.store.get_working_state()
            self.assertEqual(durable.stage, "native_completion")
            self.assertNotIn("side_effect_recovery", durable.data)
        finally:
            restored.store.close()
            tmp.cleanup()

    def test_incomplete_named_text_evidence_remains_fail_closed(self) -> None:
        tmp, restored, event, state = self._restart_after_observed_dispatch(
            continuity=False
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
