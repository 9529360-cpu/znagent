from __future__ import annotations

import hashlib
import unittest

from zn_agent.core.device_capability_graph import DeviceCapabilityGraph
from zn_agent.core.foreground_window_sense import (
    ForegroundWindowObservation,
    NativeForegroundWindowSense,
)
from zn_agent.core.windows_foreground_companion import (
    NativeWindowsForegroundCompanionSense,
    foreground_context_changed,
)


class WindowsForegroundCompanionTests(unittest.TestCase):
    @staticmethod
    def _sense(
        *,
        title: str = "Confidential customer record",
        class_name: str = "FixtureWindow",
        process_id: int = 123,
        hwnd: int = 456,
    ) -> NativeWindowsForegroundCompanionSense:
        foreground = NativeForegroundWindowSense(
            probe_fn=lambda: ForegroundWindowObservation(
                process_id=process_id,
                title=title,
                process_name="fixture.exe",
                class_name=class_name,
                captured_at="2026-09-15T00:00:00Z",
                window_handle=hwnd,
            )
        )
        return NativeWindowsForegroundCompanionSense(
            foreground_sense=foreground,
            monitor_probe=lambda current_hwnd: {
                "left": -1280,
                "top": 0,
                "right": 0,
                "bottom": 1024,
                "work_left": -1280,
                "work_top": 0,
                "work_right": 0,
                "work_bottom": 984,
                "primary": False,
            }
            if current_hwnd == hwnd
            else {},
        )

    def test_raw_window_title_and_class_are_redacted_but_identity_change_remains_observable(self) -> None:
        title = "Confidential customer record"
        class_name = "FixtureWindow"
        observation = self._sense(title=title, class_name=class_name).probe()

        self.assertTrue(observation.platform_supported)
        self.assertTrue(observation.available)
        self.assertEqual(observation.process_id, 123)
        self.assertEqual(observation.process_name, "fixture.exe")
        self.assertEqual(observation.window_handle, 456)
        self.assertEqual(observation.title_chars, len(title))
        self.assertEqual(
            observation.title_sha256,
            hashlib.sha256(title.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(observation.class_name_chars, len(class_name))
        self.assertEqual(
            observation.class_name_sha256,
            hashlib.sha256(class_name.encode("utf-8")).hexdigest(),
        )
        self.assertFalse(hasattr(observation, "title"))
        self.assertFalse(hasattr(observation, "class_name"))
        self.assertNotIn(title, repr(observation))
        self.assertNotIn(class_name, repr(observation))

    def test_foreground_monitor_preserves_negative_virtual_coordinates(self) -> None:
        observation = self._sense().probe()
        self.assertIsNotNone(observation.monitor)
        monitor = observation.monitor
        assert monitor is not None
        self.assertEqual(monitor.left, -1280)
        self.assertEqual(monitor.right, 0)
        self.assertEqual(monitor.width, 1280)
        self.assertEqual(monitor.height, 1024)
        self.assertEqual(monitor.work_height, 984)
        self.assertFalse(monitor.primary)
        self.assertFalse(hasattr(monitor, "device_name"))
        self.assertFalse(hasattr(monitor, "serial_number"))

    def test_invalid_monitor_geometry_degrades_without_losing_foreground_identity(self) -> None:
        foreground = NativeForegroundWindowSense(
            probe_fn=lambda: ForegroundWindowObservation(
                process_id=7,
                title="A",
                process_name="fixture.exe",
                class_name="C",
                captured_at="2026-09-15T00:00:00Z",
                window_handle=9,
            )
        )
        observation = NativeWindowsForegroundCompanionSense(
            foreground_sense=foreground,
            monitor_probe=lambda hwnd: {
                "left": 0,
                "top": 0,
                "right": 100,
                "bottom": 100,
                "work_left": -1,
                "work_top": 0,
                "work_right": 100,
                "work_bottom": 100,
                "primary": True,
            },
        ).probe()

        self.assertTrue(observation.available)
        self.assertEqual(observation.process_id, 7)
        self.assertIsNone(observation.monitor)

    def test_zero_window_handle_fails_closed_before_monitor_binding(self) -> None:
        monitor_calls: list[int] = []
        foreground = NativeForegroundWindowSense(
            probe_fn=lambda: ForegroundWindowObservation(
                process_id=7,
                title="A",
                process_name="fixture.exe",
                class_name="C",
                captured_at="2026-09-15T00:00:00Z",
                window_handle=0,
            )
        )
        observation = NativeWindowsForegroundCompanionSense(
            foreground_sense=foreground,
            monitor_probe=lambda hwnd: monitor_calls.append(hwnd) or {},
        ).probe()

        self.assertTrue(observation.platform_supported)
        self.assertFalse(observation.available)
        self.assertIsNone(observation.process_id)
        self.assertIsNone(observation.window_handle)
        self.assertEqual(observation.source, ("foreground-window-invalid-handle",))
        self.assertEqual(monitor_calls, [])

    def test_probe_failure_is_bounded_unavailable_evidence(self) -> None:
        def boom():
            raise RuntimeError("foreground disappeared")

        observation = NativeWindowsForegroundCompanionSense(
            foreground_sense=NativeForegroundWindowSense(probe_fn=boom),
            monitor_probe=lambda hwnd: {},
        ).probe()

        self.assertTrue(observation.platform_supported)
        self.assertFalse(observation.available)
        self.assertIsNone(observation.process_id)
        self.assertIsNone(observation.window_handle)
        self.assertIsNone(observation.title_sha256)
        self.assertIsNone(observation.monitor)

    def test_material_foreground_change_detects_same_process_title_or_window_replacement(self) -> None:
        first = self._sense(title="Record A", hwnd=10).probe()
        same = self._sense(title="Record A", hwnd=10).probe()
        title_changed = self._sense(title="Record B", hwnd=10).probe()
        hwnd_changed = self._sense(title="Record A", hwnd=11).probe()

        self.assertFalse(foreground_context_changed(first, same))
        self.assertTrue(foreground_context_changed(first, title_changed))
        self.assertTrue(foreground_context_changed(first, hwnd_changed))

    def test_resident_context_snapshot_includes_privacy_safe_foreground(self) -> None:
        foreground = self._sense()
        graph = DeviceCapabilityGraph(
            inventory_provider=lambda: [],
            process_provider=lambda: [],
            window_provider=lambda: [],
            cache_path=None,
            inventory_ttl_seconds=0,
            foreground_companion_sense=foreground,
        )
        snapshot = graph.resident_context_snapshot(force_inventory_refresh=True)

        self.assertTrue(snapshot.foreground.available)
        self.assertEqual(snapshot.foreground.process_name, "fixture.exe")
        self.assertEqual(snapshot.foreground.monitor.left, -1280)
        self.assertFalse(hasattr(snapshot.foreground, "title"))


if __name__ == "__main__":
    unittest.main()
