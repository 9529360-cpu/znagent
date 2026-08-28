from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from zn_agent.core.automation_element_sense import (
    AutomationElementObservation,
    NativeAutomationElementSense,
    _WindowsUiAutomationReader,
)
from zn_agent.core.models import utc_now


class AutomationTextCapabilitySenseTests(unittest.TestCase):
    @staticmethod
    def _base_observation(**overrides):
        values = {
            "runtime_id": (42, 7, 9),
            "process_id": 321,
            "process_name": "powershell.exe",
            "framework_id": "WPF",
            "control_type": 50004,
            "class_name": "TextBox",
            "is_enabled": True,
            "is_keyboard_focusable": True,
            "has_keyboard_focus": True,
            "is_offscreen": False,
            "native_window_handle": 0,
            "captured_at": utc_now(),
            "automation_id": "zn-editor",
            "is_password": False,
            "is_value_pattern_available": False,
            "is_text_pattern_available": False,
            "value_is_read_only": None,
            "source": "test-uia",
        }
        values.update(overrides)
        return AutomationElementObservation(**values)

    def test_snapshot_exposes_text_capabilities_without_dynamic_value(self):
        class CachedElement:
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
                self.calls = []

            def GetCachedPropertyValue(self, property_id):
                self.calls.append(property_id)
                values = {
                    30000: (42, 7, 9),
                    30011: "zn-editor",
                    30019: False,
                    30043: True,
                    30040: True,
                    30046: False,
                }
                if property_id not in values:
                    raise AssertionError(f"unexpected cached property id: {property_id}")
                return values[property_id]

        element = CachedElement()
        with patch("psutil.Process") as process:
            process.return_value.name.return_value = "powershell.exe"
            observation = _WindowsUiAutomationReader._snapshot(
                element,
                runtime_id_property_id=30000,
                automation_id_property_id=30011,
                is_password_property_id=30019,
                is_value_pattern_available_property_id=30043,
                is_text_pattern_available_property_id=30040,
                value_is_read_only_property_id=30046,
            )

        self.assertEqual(element.calls, [30000, 30011, 30019, 30043, 30040, 30046])
        self.assertFalse(observation.is_password)
        self.assertTrue(observation.is_value_pattern_available)
        self.assertTrue(observation.is_text_pattern_available)
        self.assertFalse(observation.value_is_read_only)
        self.assertFalse(hasattr(observation, "value"))
        self.assertFalse(hasattr(observation, "text"))
        self.assertFalse(hasattr(observation, "name"))

    def test_snapshot_skips_value_readonly_when_value_pattern_is_absent(self):
        class CachedElement:
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
                self.calls = []

            def GetCachedPropertyValue(self, property_id):
                self.calls.append(property_id)
                values = {
                    30000: (42, 7, 9),
                    30011: "zn-editor",
                    30019: False,
                    30043: False,
                    30040: True,
                }
                if property_id not in values:
                    raise AssertionError(f"unexpected cached property id: {property_id}")
                return values[property_id]

        element = CachedElement()
        with patch("psutil.Process") as process:
            process.return_value.name.return_value = "powershell.exe"
            observation = _WindowsUiAutomationReader._snapshot(
                element,
                runtime_id_property_id=30000,
                automation_id_property_id=30011,
                is_password_property_id=30019,
                is_value_pattern_available_property_id=30043,
                is_text_pattern_available_property_id=30040,
                value_is_read_only_property_id=30046,
            )

        self.assertFalse(observation.is_value_pattern_available)
        self.assertTrue(observation.is_text_pattern_available)
        self.assertIsNone(observation.value_is_read_only)
        self.assertNotIn(30046, element.calls)

    def test_validation_rejects_value_readonly_without_value_capability(self):
        observation = self._base_observation(
            is_value_pattern_available=False,
            value_is_read_only=False,
        )
        with self.assertRaisesRegex(ValueError, "without Value capability"):
            NativeAutomationElementSense._validate(observation)

    def test_reader_never_requests_dynamic_value_name_or_control_pattern(self):
        source = inspect.getsource(_WindowsUiAutomationReader._run)
        self.assertNotIn("UIA_ValueValuePropertyId", source)
        self.assertNotIn("UIA_NamePropertyId", source)
        self.assertNotIn("AddPattern", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
