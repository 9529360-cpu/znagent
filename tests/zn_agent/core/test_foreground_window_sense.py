from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.foreground_window_sense import (
    ForegroundWindowObservation,
    NativeForegroundWindowSense,
)
from zn_agent.core.models import utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class ForegroundWindowSenseTests(unittest.TestCase):
    def test_probe_returns_bounded_structured_identity_from_injected_source(self):
        calls = 0

        def probe():
            nonlocal calls
            calls += 1
            return ForegroundWindowObservation(
                process_id=123,
                title="Settings",
                process_name="SystemSettings.exe",
                class_name="ApplicationFrameWindow",
                captured_at=utc_now(),
                source="test",
            )

        sense = NativeForegroundWindowSense(probe_fn=probe)
        first = sense.probe()
        second = sense.probe()

        self.assertEqual(calls, 2)
        self.assertEqual(first.process_id, 123)
        self.assertEqual(first.title, "Settings")
        self.assertEqual(first.process_name, "SystemSettings.exe")
        self.assertEqual(second.source, "test")

    def test_probe_rejects_unusable_identity(self):
        sense = NativeForegroundWindowSense(
            probe_fn=lambda: ForegroundWindowObservation(
                process_id=0,
                title="",
                process_name="",
                class_name="",
                captured_at=utc_now(),
                source="test",
            )
        )
        with self.assertRaisesRegex(ValueError, "invalid process id"):
            sense.probe()

    def test_probe_rejects_missing_process_name(self):
        sense = NativeForegroundWindowSense(
            probe_fn=lambda: ForegroundWindowObservation(
                process_id=123,
                title="Settings",
                process_name="",
                class_name="ApplicationFrameWindow",
                captured_at=utc_now(),
                source="test",
            )
        )
        with self.assertRaisesRegex(ValueError, "no process name"):
            sense.probe()

    def test_active_resident_owns_foreground_window_sense_without_probing_on_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            self.assertIsInstance(resident.foreground_window, NativeForegroundWindowSense)
            resident.store.close()
