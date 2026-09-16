from __future__ import annotations

import unittest

from zn_agent.core.device_capability_graph import DeviceCapabilityGraph
from zn_agent.core.foreground_window_sense import (
    ForegroundWindowObservation,
    NativeForegroundWindowSense,
)
from zn_agent.core.windows_companion_context import NativeWindowsCompanionContextSense
from zn_agent.core.windows_companion_frame import (
    WindowsCompanionFrameSense,
    WindowsCompanionFrameUnstableError,
    compare_windows_companion_frames,
)
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

    def test_wts_connection_state_change_invalidates_only_session_and_full_frame(self) -> None:
        graph = self._graph()
        active = WindowsCompanionFrameSense(
            graph,
            session_connection_state_probe=lambda _session_id: "active",
        ).probe()
        disconnected = WindowsCompanionFrameSense(
            graph,
            session_connection_state_probe=lambda _session_id: "disconnected",
        ).probe()
        delta = compare_windows_companion_frames(active, disconnected)

        self.assertEqual(active.session_connection_state, "active")
        self.assertEqual(disconnected.session_connection_state, "disconnected")
        self.assertNotEqual(active.fingerprint, disconnected.fingerprint)
        self.assertTrue(delta.session_changed)
        self.assertFalse(delta.power_changed)
        self.assertFalse(delta.network_changed)
        self.assertFalse(delta.display_changed)
        self.assertFalse(delta.foreground_changed)

    def test_invalid_wts_connection_state_degrades_to_unknown_without_inventing_identity(self) -> None:
        frame = WindowsCompanionFrameSense(
            self._graph(),
            session_connection_state_probe=lambda _session_id: "not-a-real-state",
        ).probe()
        self.assertIsNone(frame.session_connection_state)

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

    def test_cross_sense_transition_retries_until_consecutive_material_samples_match(self) -> None:
        state = {"phase": "a", "session_reads": 0}

        def session_probe() -> dict[str, object]:
            state["session_reads"] += 1
            if state["session_reads"] == 1:
                state["phase"] = "b"
                session_id = 3
            else:
                session_id = 4
            return {
                "platform_supported": True,
                "process_session_id": session_id,
                "active_console_session_id": 4,
                "attached_to_active_console": session_id == 4,
                "remote_session": False,
                "input_desktop_openable": True,
                "idle_seconds": 0.0,
            }

        companion = NativeWindowsCompanionContextSense(
            session_probe=session_probe,
            power_probe=lambda: {
                "platform_supported": True,
                "ac_status": "online",
                "battery_present": False,
                "battery_charging": False,
                "battery_saver": False,
            },
            network_probe=lambda: {
                "platform_supported": True,
                "interface_count": 1,
                "up_interface_count": 1,
                "non_loopback_up_interface_count": 1,
                "has_non_loopback_address": True,
                "has_ipv4": True,
                "has_ipv6": False,
            },
        )

        def monitor() -> dict[str, object]:
            left = 0 if state["phase"] == "a" else 1920
            return {
                "left": left,
                "top": 0,
                "right": left + 1920,
                "bottom": 1080,
                "work_left": left,
                "work_top": 0,
                "work_right": left + 1920,
                "work_bottom": 1040,
                "primary": state["phase"] == "a",
            }

        display = NativeWindowsDisplayContextSense(
            probe=lambda: {
                "platform_supported": True,
                "monitor_count": 1,
                "enumerated_monitor_count": 1,
                "primary_width": 1920,
                "primary_height": 1080,
                "virtual_left": monitor()["left"],
                "virtual_top": 0,
                "virtual_width": 1920,
                "virtual_height": 1080,
                "monitors": [monitor()],
            }
        )
        native_foreground = NativeForegroundWindowSense(
            probe_fn=lambda: ForegroundWindowObservation(
                process_id=100 if state["phase"] == "a" else 101,
                title="A" if state["phase"] == "a" else "B",
                process_name="a.exe" if state["phase"] == "a" else "b.exe",
                class_name="FixtureWindow",
                captured_at="2026-09-15T00:00:00Z",
                window_handle=200 if state["phase"] == "a" else 201,
            )
        )
        foreground = NativeWindowsForegroundCompanionSense(
            foreground_sense=native_foreground,
            monitor_probe=lambda _hwnd: monitor(),
        )
        graph = DeviceCapabilityGraph(
            inventory_provider=lambda: [],
            process_provider=lambda: [],
            window_provider=lambda: [],
            cache_path=None,
            inventory_ttl_seconds=0,
            companion_context_sense=companion,
            display_context_sense=display,
            foreground_companion_sense=foreground,
        )

        frame = WindowsCompanionFrameSense(
            graph,
            session_connection_state_probe=lambda _session_id: "active",
            stability_reads=3,
        ).probe()

        self.assertEqual(state["session_reads"], 3)
        self.assertEqual(frame.foreground_process_id, 101)
        self.assertEqual(frame.foreground_process_name, "b.exe")
        self.assertEqual(frame.foreground_window_handle, 201)

    def test_persistent_material_drift_fails_closed_after_bounded_reads(self) -> None:
        state = {"reads": 0}

        def session_probe() -> dict[str, object]:
            state["reads"] += 1
            session_id = 3 if state["reads"] % 2 else 4
            return {
                "platform_supported": True,
                "process_session_id": session_id,
                "active_console_session_id": 3,
                "attached_to_active_console": session_id == 3,
                "remote_session": False,
                "input_desktop_openable": True,
                "idle_seconds": 0.0,
            }

        graph = self._graph()
        graph._companion_context_sense = NativeWindowsCompanionContextSense(
            session_probe=session_probe,
            power_probe=lambda: {
                "platform_supported": True,
                "ac_status": "online",
                "battery_present": False,
                "battery_charging": False,
                "battery_saver": False,
            },
            network_probe=lambda: {
                "platform_supported": True,
                "interface_count": 1,
                "up_interface_count": 1,
                "non_loopback_up_interface_count": 1,
                "has_non_loopback_address": True,
                "has_ipv4": True,
                "has_ipv6": False,
            },
        )

        with self.assertRaises(WindowsCompanionFrameUnstableError):
            WindowsCompanionFrameSense(
                graph,
                session_connection_state_probe=lambda _session_id: "active",
                stability_reads=3,
            ).probe()
        self.assertEqual(state["reads"], 3)

    def test_stability_read_bound_is_validated(self) -> None:
        graph = self._graph()
        with self.assertRaises(ValueError):
            WindowsCompanionFrameSense(graph, stability_reads=1)
        with self.assertRaises(ValueError):
            WindowsCompanionFrameSense(graph, stability_reads=9)


if __name__ == "__main__":
    unittest.main()
