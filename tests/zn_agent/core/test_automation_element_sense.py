from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.automation_element_sense import (
    AutomationElementObservation,
    NativeAutomationElementSense,
)
from zn_agent.core.models import utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class AutomationElementSenseTests(unittest.TestCase):
    @staticmethod
    def _observation(*, runtime_id=(42, 7), focused=False):
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
        self.assertTrue(focused.has_keyboard_focus)
        self.assertEqual(point.control_type, 50004)

    def test_observation_excludes_dynamic_name_and_automation_id(self):
        observation = self._observation()
        self.assertFalse(hasattr(observation, "name"))
        self.assertFalse(hasattr(observation, "automation_id"))

    def test_probe_rejects_missing_runtime_identity(self):
        sense = NativeAutomationElementSense(
            point_probe_fn=lambda _x, _y: self._observation(runtime_id=()),
            focused_probe_fn=lambda: self._observation(),
        )
        with self.assertRaisesRegex(ValueError, "runtime id"):
            sense.probe_at_point(1, 2)

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
