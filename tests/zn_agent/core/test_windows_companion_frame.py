from __future__ import annotations

import unittest

from zn_agent.core.device_capability_graph import DeviceCapabilityGraph
from zn_agent.core.foreground_window_sense import (
    ForegroundWindowObservation,
    NativeForegroundWindowSense,
)
from zn_agent.core.windows_companion_context import NativeWindowsCompanionContextSense
from zn_agent.core.windows_companion_frame import compare_windows_companion_frames
from zn_agent.core.windows_display_context import NativeWindowsDisplayContextSense
from zn_agent.core.windows_foreground_companion import NativeWindowsForegroundCompanionSense


class WindowsCompanionFrameTests(unittest.TestCase):
    @staticmethod
    def _graph(
        *,
        title: str = "Customer A",
        battery_percent: int = 80,
        idle_seconds: float = 1.0,
        interface_count: int = 2,
        network_available: bool = True,
        monitor_count: int = 1,
        process_session_id: int = 3,
    ) -> DeviceCapabilityGraph:
        companion = NativeWindowsCompanionContextSense(
            session_probe=lambda: {
                "platform_supported": True,
                "process_session_id": process_session_id,
                "active_console_session_id": 3,
                "attached_to_active_console": process_session_id == 3,
                "remote_session": False,
                "input_desktop_openable": True,
                "idle_seconds": idle_seconds,
            },
            power_probe=lambda: {
                "platform_supported": True,
                "ac_status": "online",
                "battery_present": True,
                "battery_percent": battery_percent,
                "battery_charging": True,
                "battery_saver": False,
                "battery_life_seconds": 7200,
            },
            network_probe=lambda: {
                "platform_supported": True,
                "interface_count": interface_count,
                "up_interface_count": interface_count,
                "non_loopback_up_interface_count": 1 if network_available else 0,
                "has_non_loopback_address": network_available,
                "has_ipv4": network_available,
                "has_ipv6": False,
                "max_link_speed_mbps": 1000,
            },
        )
        monitors = [
            {
                "left": index * 1920,
                "top": 0,
                "right": index * 1920 + 1920,
                "bottom": 1080,
                "work_left": index * 1920,
                "work_top": 0,
                "work_right": index * 1920 + 1920,
                "work_bottom": 1040,
                "primary": index == 0,
            }
            for index in range(monitor_count)
        ]
        display = NativeWindowsDisplayContextSense(
            probe=lambda: {
                "platform_supported": True,
                "monitor_count": monitor_count,
                "enumerated_monitor_count": monitor_count,
                "primary_width": 1920,
                "primary_height": 1080,
                "virtual_left": 0,
                "virtual_top": 0,
                "virtual_width": 1920 * monitor_count,
                "virtual_height": 1080,
                "monitors": monitors,
            }
        )
        native_foreground = NativeForegroundWindowSense(
            probe_fn=lambda: ForegroundWindowObservation(
                process_id=100,
                title=title,
                process_name="fixture.exe",
                class_name="FixtureWindow",
                captured_at="2026-09-15T00:00:00Z",
                window_handle=200,
            )
        )
        foreground = NativeWindowsForegroundCompanionSense(
            foreground_sense=native_foreground,
            monitor_probe=lambda hwnd: monitors[0] if hwnd == 200 else {},
        )
        return DeviceCapabilityGraph(
            inventory_provider=lambda: [],
            process_provider=lambda: [],
            window_provider=lambda: [],
            cache_path=None,
            inventory_ttl_seconds=0,
            companion_context_sense=companion,
            display_context_sense=display,
            foreground_companion_sense=foreground,
        )

    def test_frame_is_stable_across_non_material_idle_battery_and_adapter_churn(self) -> None:
        first = self._graph(
            idle_seconds=1.0,
            battery_percent=80,
            interface_count=2,
        ).companion_frame()
        later = self._graph(
            idle_seconds=900.0,
            battery_percent=65,
            interface_count=8,
        ).companion_frame()

        self.assertEqual(first.fingerprint, later.fingerprint)
        self.assertEqual(first.session_fingerprint, later.session_fingerprint)
        self.assertEqual(first.power_fingerprint, later.power_fingerprint)
        self.assertEqual(first.network_fingerprint, later.network_fingerprint)
        self.assertFalse(compare_windows_companion_frames(first, later).material_change)

    def test_foreground_change_invalidates_only_foreground_and_full_frame(self) -> None:
        first = self._graph(title="Customer A").companion_frame()
        second = self._graph(title="Customer B").companion_frame()
        delta = compare_windows_companion_frames(first, second)

        self.assertNotEqual(first.fingerprint, second.fingerprint)
        self.assertTrue(delta.foreground_changed)
        self.assertFalse(delta.session_changed)
        self.assertFalse(delta.power_changed)
        self.assertFalse(delta.network_changed)
        self.assertFalse(delta.display_changed)

    def test_network_availability_display_and_session_changes_are_independent(self) -> None:
        first = self._graph().companion_frame()
        no_network = self._graph(network_available=False).companion_frame()
        display_changed = self._graph(monitor_count=2).companion_frame()
        session_changed = self._graph(process_session_id=4).companion_frame()

        self.assertTrue(compare_windows_companion_frames(first, no_network).network_changed)
        self.assertTrue(compare_windows_companion_frames(first, display_changed).display_changed)
        self.assertTrue(compare_windows_companion_frames(first, session_changed).session_changed)

    def test_frame_exposes_only_bounded_foreground_identity(self) -> None:
        title = "Confidential Customer A"
        frame = self._graph(title=title).companion_frame()

        self.assertEqual(frame.frame_version, "windows-companion-frame:v1")
        self.assertEqual(len(frame.fingerprint), 64)
        self.assertEqual(len(frame.foreground_fingerprint), 64)
        self.assertEqual(frame.foreground_process_id, 100)
        self.assertEqual(frame.foreground_process_name, "fixture.exe")
        self.assertEqual(frame.foreground_window_handle, 200)
        self.assertNotIn(title, repr(frame))
        self.assertFalse(hasattr(frame, "title"))
        self.assertFalse(hasattr(frame, "class_name"))

    def test_repeated_fresh_reads_with_same_material_context_keep_same_fingerprint(self) -> None:
        graph = self._graph()
        first = graph.companion_frame()
        second = graph.companion_frame()

        self.assertNotEqual(first.observed_at, "")
        self.assertNotEqual(second.observed_at, "")
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.foreground_fingerprint, second.foreground_fingerprint)


if __name__ == "__main__":
    unittest.main()
