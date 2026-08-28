from __future__ import annotations

import inspect
import unittest
from dataclasses import replace
from unittest.mock import patch

from zn_agent.core.automation_text_state_sense import (
    FocusedAutomationTextObservation,
    NativeFocusedAutomationTextSense,
    _WindowsAutomationTextStateReader,
)
from zn_agent.core.models import utc_now


class AutomationTextStateSenseTests(unittest.TestCase):
    @staticmethod
    def _observation(**overrides):
        values = {
            "runtime_id": (42, 7, 9),
            "process_id": 321,
            "process_name": "powershell.exe",
            "framework_id": "WPF",
            "control_type": 50004,
            "class_name": "TextBox",
            "automation_id": "zn-editor",
            "native_window_handle": 0,
            "is_enabled": True,
            "is_keyboard_focusable": True,
            "has_keyboard_focus": True,
            "is_offscreen": False,
            "is_password": False,
            "is_value_pattern_available": True,
            "value_is_read_only": False,
            "text_length": 6,
            "text_sha256": NativeFocusedAutomationTextSense.digest_text("secret"),
            "captured_at": utc_now(),
            "source": "test-uia-text",
        }
        values.update(overrides)
        return FocusedAutomationTextObservation(**values)

    @staticmethod
    def _element(*, runtime=(42, 7, 9), password=False, read_only=False, text="safe text"):
        class Element:
            CachedProcessId = 321
            CachedFrameworkId = "WPF"
            CachedControlType = 50004
            CachedClassName = "TextBox"
            CachedIsEnabled = True
            CachedIsKeyboardFocusable = True
            CachedHasKeyboardFocus = True
            CachedIsOffscreen = False
            CachedNativeWindowHandle = 0

            def __init__(self):
                self.current_calls = []

            def GetCachedPropertyValue(self, property_id):
                values = {
                    30000: runtime,
                    30011: "zn-editor",
                    30019: password,
                    30043: True,
                    30046: read_only,
                }
                return values[property_id]

            def GetCurrentPropertyValue(self, property_id):
                self.current_calls.append(property_id)
                if property_id != 30045:
                    raise AssertionError(f"unexpected current property: {property_id}")
                return text

        return Element()

    def test_snapshot_exports_only_length_and_digest_after_safe_gate(self):
        element = self._element(text="ZN modern text")
        with patch("psutil.Process") as process:
            process.return_value.name.return_value = "powershell.exe"
            observed = _WindowsAutomationTextStateReader._snapshot(
                element,
                recheck_fn=lambda: self._element(text="ignored after read"),
                runtime_id_property_id=30000,
                automation_id_property_id=30011,
                is_password_property_id=30019,
                is_value_pattern_available_property_id=30043,
                value_is_read_only_property_id=30046,
                value_value_property_id=30045,
            )
        self.assertEqual(element.current_calls, [30045])
        self.assertEqual(observed.text_length, len("ZN modern text"))
        self.assertEqual(
            observed.text_sha256,
            NativeFocusedAutomationTextSense.digest_text("ZN modern text"),
        )
        self.assertFalse(hasattr(observed, "text"))
        self.assertFalse(hasattr(observed, "value"))

    def test_password_gate_happens_before_dynamic_value_read(self):
        element = self._element(password=True, text="must-not-be-read")
        with self.assertRaisesRegex(RuntimeError, "password"):
            _WindowsAutomationTextStateReader._snapshot(
                element,
                recheck_fn=lambda: element,
                runtime_id_property_id=30000,
                automation_id_property_id=30011,
                is_password_property_id=30019,
                is_value_pattern_available_property_id=30043,
                value_is_read_only_property_id=30046,
                value_value_property_id=30045,
            )
        self.assertEqual(element.current_calls, [])

    def test_readonly_gate_happens_before_dynamic_value_read(self):
        element = self._element(read_only=True, text="must-not-be-read")
        with self.assertRaisesRegex(RuntimeError, "read-only"):
            _WindowsAutomationTextStateReader._snapshot(
                element,
                recheck_fn=lambda: element,
                runtime_id_property_id=30000,
                automation_id_property_id=30011,
                is_password_property_id=30019,
                is_value_pattern_available_property_id=30043,
                value_is_read_only_property_id=30046,
                value_value_property_id=30045,
            )
        self.assertEqual(element.current_calls, [])

    def test_runtime_id_drift_after_read_is_rejected(self):
        element = self._element(text="short-lived")
        with patch("psutil.Process") as process:
            process.return_value.name.return_value = "powershell.exe"
            with self.assertRaisesRegex(RuntimeError, "RuntimeId changed"):
                _WindowsAutomationTextStateReader._snapshot(
                    element,
                    recheck_fn=lambda: self._element(runtime=(42, 7, 10)),
                    runtime_id_property_id=30000,
                    automation_id_property_id=30011,
                    is_password_property_id=30019,
                    is_value_pattern_available_property_id=30043,
                    value_is_read_only_property_id=30046,
                    value_value_property_id=30045,
                )

    def test_oversized_text_is_rejected_without_echoing_content(self):
        marker = "SENSITIVE-" + ("x" * 4096)
        element = self._element(text=marker)
        with self.assertRaises(RuntimeError) as raised:
            _WindowsAutomationTextStateReader._snapshot(
                element,
                recheck_fn=lambda: element,
                runtime_id_property_id=30000,
                automation_id_property_id=30011,
                is_password_property_id=30019,
                is_value_pattern_available_property_id=30043,
                value_is_read_only_property_id=30046,
                value_value_property_id=30045,
            )
        self.assertNotIn(marker, str(raised.exception))

    def test_validation_refuses_password_and_invalid_digest(self):
        with self.assertRaisesRegex(ValueError, "password"):
            NativeFocusedAutomationTextSense._validate(
                replace(self._observation(), is_password=True)
            )
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            NativeFocusedAutomationTextSense._validate(
                replace(self._observation(), text_sha256="not-a-digest")
            )

    def test_reader_has_no_mutation_or_name_tree_surface(self):
        source = inspect.getsource(_WindowsAutomationTextStateReader)
        self.assertIn("UIA_ValueValuePropertyId", source)
        self.assertNotIn("UIA_NamePropertyId", source)
        self.assertNotIn("AddPattern", source)
        self.assertNotIn("SetValue", source)
        self.assertNotIn("FindFirst", source)
        self.assertNotIn("FindAll", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
