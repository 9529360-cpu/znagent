from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.browser_named_goal import (
    browser_named_text_intent,
    browser_named_text_request,
    browser_named_text_state,
)
from zn_agent.core.browser_named_target_sense import (
    BrowserNamedTargetObservation,
    NativeBrowserNamedTargetSense,
)
from zn_agent.core.focused_text_sense import NativeFocusedTextSense
from zn_agent.core.models import AgentEvent, utc_now


class BrowserNamedGoalTests(unittest.TestCase):
    @staticmethod
    def _event(text: str = "alice") -> AgentEvent:
        return AgentEvent(
            event_id="evt-browser-goal",
            task="Fill the Account search box in my current browser with alice",
            payload={
                "resident_goal": {
                    "kind": "user_browser_named_text",
                    "target_name": "Account search",
                    "text": text,
                },
                "model_policy": "never",
            },
        )

    @staticmethod
    def _target(*, focused: bool) -> BrowserNamedTargetObservation:
        return BrowserNamedTargetObservation(
            runtime_id=(42, 9),
            process_id=123,
            process_name="chrome.exe",
            foreground_title="Accounts",
            framework_id="Chrome",
            control_type=50004,
            class_name="Chrome_RenderWidgetHostHWND",
            automation_id="account-search",
            is_enabled=True,
            is_keyboard_focusable=True,
            has_keyboard_focus=focused,
            is_offscreen=False,
            is_password=False,
            is_value_pattern_available=True,
            value_is_read_only=False,
            native_window_handle=0,
            center_x_fraction=0.4,
            center_y_fraction=0.3,
            captured_at=utc_now(),
            source="test-browser-target",
        )

    @staticmethod
    def _text(value: str):
        return SimpleNamespace(
            runtime_id=(42, 9),
            process_name="chrome.exe",
            text_length=len(value),
            text_sha256=NativeFocusedTextSense.digest_text(value),
        )

    def test_request_is_typed_world_state_not_action_sequence(self):
        request = browser_named_text_request(self._event())
        self.assertEqual(request["target_name"], "Account search")
        self.assertEqual(request["text"], "alice")
        self.assertNotIn("actions", request)
        self.assertNotIn("coordinates", request)

    def test_unfocused_target_forms_only_current_focus_movement(self):
        event = self._event()
        state = browser_named_text_state(event, self._target(focused=False), None)
        self.assertEqual(state["phase"], "needs_focus")
        intent = browser_named_text_intent(event, state)
        self.assertEqual(intent.kind, "pointer_click")
        self.assertEqual(intent.source, "native_deliberation")
        self.assertEqual(intent.expected_outcome["kind"], "browser_named_target_focused")

    def test_fresh_empty_focused_target_forms_text_movement_after_resense(self):
        event = self._event()
        state = browser_named_text_state(
            event,
            self._target(focused=True),
            self._text(""),
        )
        self.assertEqual(state["phase"], "needs_text")
        intent = browser_named_text_intent(event, state)
        self.assertEqual(intent.kind, "keyboard_text")
        self.assertEqual(intent.args["text"], "alice")

    def test_final_digest_is_required_for_goal_completion(self):
        event = self._event()
        state = browser_named_text_state(
            event,
            self._target(focused=True),
            self._text("alice"),
        )
        self.assertTrue(state["satisfied"])
        self.assertTrue(state["text_verified"])
        self.assertIsNone(browser_named_text_intent(event, state))

    def test_nonempty_different_text_fails_closed_instead_of_replacing(self):
        event = self._event()
        state = browser_named_text_state(
            event,
            self._target(focused=True),
            self._text("existing private value"),
        )
        self.assertEqual(state["phase"], "blocked")
        self.assertIn("non-empty", state["blocked"])
        self.assertIsNone(browser_named_text_intent(event, state))

    def test_exact_target_sense_rejects_non_browser_and_password_controls(self):
        def observation(process_name="chrome.exe", is_password=False):
            return BrowserNamedTargetObservation(
                runtime_id=(1, 2),
                process_id=11,
                process_name=process_name,
                foreground_title="Accounts",
                framework_id="Chrome",
                control_type=50004,
                class_name="Edit",
                automation_id="account-search",
                is_enabled=True,
                is_keyboard_focusable=True,
                has_keyboard_focus=False,
                is_offscreen=False,
                is_password=is_password,
                is_value_pattern_available=True,
                value_is_read_only=False,
                native_window_handle=0,
                center_x_fraction=0.5,
                center_y_fraction=0.5,
                captured_at=utc_now(),
                source="test",
            )

        with self.assertRaisesRegex(ValueError, "Chrome or Edge"):
            NativeBrowserNamedTargetSense(
                probe_fn=lambda _name, _type: observation(process_name="notepad.exe")
            ).probe_exact_edit("Account search")
        with self.assertRaisesRegex(ValueError, "password"):
            NativeBrowserNamedTargetSense(
                probe_fn=lambda _name, _type: observation(is_password=True)
            ).probe_exact_edit("Account search")


if __name__ == "__main__":
    unittest.main()
