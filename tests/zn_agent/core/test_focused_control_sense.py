from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.focused_control_sense import (
    FocusedControlObservation,
    NativeFocusedControlSense,
)
from zn_agent.core.models import utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class FocusedControlSenseTests(unittest.TestCase):
    @staticmethod
    def _observation(**overrides):
        values = {
            "process_id": 123,
            "process_name": "notepad.exe",
            "foreground_title": "Untitled - Notepad",
            "foreground_class_name": "Notepad",
            "control_class_name": "Edit",
            "control_id": 15,
            "enabled": True,
            "visible": True,
            "captured_at": utc_now(),
            "source": "test-focused-control",
        }
        values.update(overrides)
        return FocusedControlObservation(**values)

    def test_probe_returns_bounded_structured_identity_from_injected_source(self):
        expected = self._observation()
        sense = NativeFocusedControlSense(probe_fn=lambda: expected)

        observed = sense.probe()

        self.assertEqual(observed, expected)
        self.assertEqual(observed.control_class_name, "Edit")
        self.assertEqual(observed.control_id, 15)
        self.assertTrue(observed.enabled)
        self.assertTrue(observed.visible)

    def test_probe_rejects_missing_native_control_identity(self):
        for observation in (
            self._observation(control_class_name=""),
            self._observation(control_id=0),
            self._observation(process_name=""),
            self._observation(process_id=0),
        ):
            with self.subTest(observation=observation):
                sense = NativeFocusedControlSense(probe_fn=lambda value=observation: value)
                with self.assertRaises(ValueError):
                    sense.probe()

    def test_active_resident_owns_focused_control_sense_without_probing_on_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            self.assertIsInstance(resident.focused_control, NativeFocusedControlSense)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
