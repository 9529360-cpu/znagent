from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core import ExecutionPath
from zn_agent.core.automation_element_sense import AutomationElementObservation
from zn_agent.core.automation_text_state_sense import (
    FocusedAutomationTextObservation,
    NativeFocusedAutomationTextSense,
)
from zn_agent.core.foreground_window_sense import ForegroundWindowObservation
from zn_agent.core.keyboard_text_body import KeyboardTextBody
from zn_agent.core.models import utc_now
from zn_agent.core.provider_bridge import build_resident_runtime


class _BrowserTextBody(KeyboardTextBody):
    def __init__(self, *, resident, current_text: str = ""):
        super().__init__(resident=resident)
        self.current_text = current_text
        self.keyboard_calls: list[str] = []

    def _send_keyboard_text(self, text: str) -> tuple[int, int]:
        self.keyboard_calls.append(text)
        _, units = self.validate_text(text)
        self.current_text += text
        expected = len(units) * 2
        return expected, expected


class _BrowserForegroundSense:
    def probe(self):
        return ForegroundWindowObservation(
            process_id=220,
            process_name="msedge.exe",
            title="Example form - Microsoft Edge",
            class_name="Chrome_WidgetWin_1",
            captured_at=utc_now(),
            source="test-browser-foreground",
        )


class _BrowserAutomationSense:
    RUNTIME_ID = (42, 220, 7)

    def __init__(self, *, runtime_id: tuple[int, ...] | None = None):
        self.runtime_id = runtime_id or self.RUNTIME_ID
        self.calls = 0

    def probe_focused(self):
        self.calls += 1
        return AutomationElementObservation(
            runtime_id=self.runtime_id,
            process_id=220,
            process_name="msedge.exe",
            framework_id="Chrome",
            control_type=50004,
            class_name="input",
            is_enabled=True,
            is_keyboard_focusable=True,
            has_keyboard_focus=True,
            is_offscreen=False,
            native_window_handle=0,
            captured_at=utc_now(),
            automation_id="message",
            is_password=False,
            is_value_pattern_available=True,
            is_text_pattern_available=False,
            value_is_read_only=False,
            source="test-browser-uia",
        )


class _BrowserTextStateSense:
    def __init__(self, body: _BrowserTextBody, *, runtime_id=None, password=False):
        self.body = body
        self.runtime_id = runtime_id or _BrowserAutomationSense.RUNTIME_ID
        self.password = bool(password)
        self.calls = 0

    def probe(self):
        self.calls += 1
        return FocusedAutomationTextObservation(
            runtime_id=self.runtime_id,
            process_id=220,
            process_name="msedge.exe",
            framework_id="Chrome",
            control_type=50004,
            class_name="input",
            automation_id="message",
            native_window_handle=0,
            is_enabled=True,
            is_keyboard_focusable=True,
            has_keyboard_focus=True,
            is_offscreen=False,
            is_password=self.password,
            is_value_pattern_available=True,
            value_is_read_only=False,
            text_length=len(self.body.current_text),
            text_sha256=NativeFocusedAutomationTextSense.digest_text(
                self.body.current_text
            ),
            captured_at=utc_now(),
            source="test-browser-uia-text",
        )


class UserBrowserFocusedTextEntryTests(unittest.TestCase):
    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 16) -> None:
        for _ in range(limit):
            if resident.store.get_working_state().stage == stage:
                return
            result = resident.live_once()
            if result is not None:
                raise AssertionError(f"event reached terminal result before {stage}: {result}")
        raise AssertionError(f"resident did not reach {stage}")

    @staticmethod
    def _resident(tmp: str, *, current_text="", text_runtime_id=None, password=False):
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )
        body = _BrowserTextBody(resident=resident, current_text=current_text)
        resident.body = body
        resident.foreground_window = _BrowserForegroundSense()
        resident.automation_element = _BrowserAutomationSense()
        resident.automation_text_state = _BrowserTextStateSense(
            body,
            runtime_id=text_runtime_id,
            password=password,
        )
        return resident, body

    @staticmethod
    def _event(resident, *, text="ZN browser text"):
        return resident.enqueue(
            "type explicit text into the currently focused browser textbox",
            kind="ui_state_transition",
            payload={
                "body_action": {"kind": "keyboard_text", "args": {"text": text}},
                "expected_outcome": {"kind": "focused_text_equals_action_text"},
                "completion_scope": {
                    "kind": "focused_automation_edit_text",
                    "process_name": "msedge.exe",
                    "title_equals": "Example form - Microsoft Edge",
                    "control_type": 50004,
                    "class_name_equals": "input",
                    "automation_id_equals": "message",
                },
                "action_precondition": {
                    "kind": "foreground_window_matches",
                    "process_name": "msedge.exe",
                    "title_equals": "Example form - Microsoft Edge",
                },
                "model_policy": "never",
            },
        )

    def test_empty_exact_browser_edit_types_once_then_verifies_fresh_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            try:
                self._event(resident)
                self._advance_until_stage(resident, "native_action")
                self.assertIsNone(resident.live_once())
                self.assertEqual(body.keyboard_calls, [])

                self.assertIsNone(resident.live_once())
                self.assertEqual(body.keyboard_calls, ["ZN browser text"])

                result = resident.live_once()
                self.assertIsNotNone(result)
                self.assertTrue(result.success, result)
                self.assertEqual(result.execution_path, ExecutionPath.BODY)
                self.assertEqual(result.model_invocations, 0)
            finally:
                resident.managed_browser.close()
                resident.store.close()

    def test_nonempty_different_browser_edit_refuses_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp, current_text="existing")
            try:
                self._event(resident)
                self._advance_until_stage(resident, "native_action")
                self.assertIsNone(resident.live_once())
                self.assertEqual(body.keyboard_calls, [])
                self.assertIn(
                    "non-empty",
                    resident.store.get_working_state().data.get("local_failure", ""),
                )
            finally:
                resident.managed_browser.close()
                resident.store.close()

    def test_structural_and_text_runtime_id_mismatch_refuses_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp, text_runtime_id=(42, 220, 8))
            try:
                self._event(resident)
                self._advance_until_stage(resident, "native_action")
                self.assertIsNone(resident.live_once())
                self.assertEqual(body.keyboard_calls, [])
                self.assertIn(
                    "different RuntimeIds",
                    resident.store.get_working_state().data.get("local_failure", ""),
                )
            finally:
                resident.managed_browser.close()
                resident.store.close()

    def test_password_browser_edit_refuses_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp, password=True)
            try:
                self._event(resident)
                self._advance_until_stage(resident, "native_action")
                self.assertIsNone(resident.live_once())
                self.assertEqual(body.keyboard_calls, [])
                self.assertIn(
                    "does not match",
                    resident.store.get_working_state().data.get("local_failure", ""),
                )
            finally:
                resident.managed_browser.close()
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
