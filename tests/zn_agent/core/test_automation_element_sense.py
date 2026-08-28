from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.automation_element_sense import (
    _MAX_AUTOMATION_ID_CHARS,
    AutomationElementObservation,
    NativeAutomationElementSense,
    _WindowsUiAutomationReader,
)
from zn_agent.core.models import utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class AutomationElementSenseTests(unittest.TestCase):
    @staticmethod
    def _observation(*, runtime_id=(42, 7), focused=False, automation_id="editor-1"):
        return AutomationElementObservation(
            runtime_id=tuple(runtime_id),
            process_id=321,
            process_name="notepad.exe",
            framework_id="test-framework",
            control_type=50004,
            class_name="TestEdit",
            is_enabled=True,
            is_keyboard_focusable=True,
            has_keyboard_focus=bool(focused),
            is_offscreen=False,
            native_window_handle=0,
            captured_at=utc_now(),
            automation_id=str(automation_id),
            source="test-uia",
        )

    def test_point_and_focused_probes_return_bounded_observations(self):
        point_calls = []
        focused_calls = []
        sense = NativeAutomationElementSense(
            point_probe_fn=lambda x, y: (
                point_calls.append((x, y)) or self._observation()
            ),
            focused_probe_fn=lambda: (
                focused_calls.append(True) or self._observation(focused=True)
            ),
        )

        point = sense.probe_at_point(50, 20)
        focused = sense.probe_focused()

        self.assertEqual(point_calls, [(50, 20)])
        self.assertEqual(focused_calls, [True])
        self.assertEqual(point.runtime_id, (42, 7))
        self.assertEqual(point.automation_id, "editor-1")
        self.assertTrue(focused.has_keyboard_focus)
        self.assertEqual(point.control_type, 50004)

    def test_observation_exposes_bounded_automation_id_without_dynamic_name(self):
        observation = self._observation(automation_id="editor-1")
        self.assertEqual(observation.automation_id, "editor-1")
        self.assertFalse(hasattr(observation, "name"))

    def test_probe_rejects_missing_runtime_identity(self):
        sense = NativeAutomationElementSense(
            point_probe_fn=lambda _x, _y: self._observation(runtime_id=()),
            focused_probe_fn=lambda: self._observation(),
        )
        with self.assertRaisesRegex(ValueError, "runtime id"):
            sense.probe_at_point(1, 2)

    def test_probe_rejects_injected_oversized_automation_id(self):
        sense = NativeAutomationElementSense(
            point_probe_fn=lambda _x, _y: self._observation(
                automation_id="a" * (_MAX_AUTOMATION_ID_CHARS + 1)
            ),
            focused_probe_fn=lambda: self._observation(),
        )
        with self.assertRaisesRegex(ValueError, "oversized automation id"):
            sense.probe_at_point(1, 2)

    def test_snapshot_reads_bounded_ids_through_standard_cached_property_api(self):
        class CachedElement:
            CachedProcessId = 321
            CachedFrameworkId = "test-framework"
            CachedControlType = 50004
            CachedClassName = "TestEdit"
            CachedIsEnabled = True
            CachedIsKeyboardFocusable = True
            CachedHasKeyboardFocus = False
            CachedIsOffscreen = False
            CachedNativeWindowHandle = 0

            def __init__(self):
                self.calls = []

            def GetCachedPropertyValue(self, property_id):
                self.calls.append(property_id)
                if property_id == 30000:
                    return (42, 7, 9)
                if property_id == 30011:
                    return "editor-1"
                raise AssertionError(f"unexpected cached property id: {property_id}")

        element = CachedElement()
        with patch("psutil.Process") as process:
            process.return_value.name.return_value = "notepad.exe"
            observation = _WindowsUiAutomationReader._snapshot(
                element,
                runtime_id_property_id=30000,
                automation_id_property_id=30011,
            )

        self.assertEqual(element.calls, [30000, 30011])
        self.assertEqual(observation.runtime_id, (42, 7, 9))
        self.assertEqual(observation.automation_id, "editor-1")
        self.assertFalse(hasattr(element, "CachedRuntimeId"))
        self.assertFalse(hasattr(element, "CachedAutomationId"))

    def test_snapshot_truncates_automation_id_before_observation(self):
        class CachedElement:
            CachedProcessId = 321
            CachedFrameworkId = "test-framework"
            CachedControlType = 50004
            CachedClassName = "TestEdit"
            CachedIsEnabled = True
            CachedIsKeyboardFocusable = True
            CachedHasKeyboardFocus = False
            CachedIsOffscreen = False
            CachedNativeWindowHandle = 0

            def GetCachedPropertyValue(self, property_id):
                if property_id == 30000:
                    return (42, 7, 9)
                if property_id == 30011:
                    return "a" * (_MAX_AUTOMATION_ID_CHARS + 50)
                raise AssertionError(f"unexpected cached property id: {property_id}")

        with patch("psutil.Process") as process:
            process.return_value.name.return_value = "notepad.exe"
            observation = _WindowsUiAutomationReader._snapshot(
                CachedElement(),
                runtime_id_property_id=30000,
                automation_id_property_id=30011,
            )

        self.assertEqual(len(observation.automation_id), _MAX_AUTOMATION_ID_CHARS)

    def test_active_resident_owns_automation_sense_without_probing_on_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            self.assertIsInstance(resident.automation_element, NativeAutomationElementSense)
            resident.store.close()

    @unittest.skipUnless(os.name == "nt", "Windows UI Automation runtime")
    def test_windows_native_reader_initializes_mta_cache_only_uia_client(self):
        sense = NativeAutomationElementSense()
        reader = sense._reader()
        self.assertIsNotNone(reader)

    @unittest.skipUnless(os.name == "nt", "Windows UI Automation dependency")
    def test_windows_runtime_installs_com_client_dependency(self):
        self.assertIsNotNone(importlib.util.find_spec("comtypes"))


if __name__ == "__main__":
    unittest.main()
