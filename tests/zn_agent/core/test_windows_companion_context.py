from __future__ import annotations

import unittest

from zn_agent.core.device_capability_graph import DeviceCapabilityGraph
from zn_agent.core.windows_companion_context import (
    NativeWindowsCompanionContextSense,
    compare_windows_companion_context,
)


class WindowsCompanionContextTests(unittest.TestCase):
    @staticmethod
    def _sense(*, idle_seconds: float = 12.5, ac_status: str = "online", network: bool = True):
        return NativeWindowsCompanionContextSense(
            session_probe=lambda: {
                "platform_supported": True,
                "process_session_id": 3,
                "active_console_session_id": 3,
                "remote_session": False,
                "input_desktop_openable": True,
                "idle_seconds": idle_seconds,
                "source": ("fixture-session",),
            },
            power_probe=lambda: {
                "platform_supported": True,
                "ac_status": ac_status,
                "battery_present": True,
                "battery_percent": 77,
                "battery_charging": True,
                "battery_saver": False,
                "battery_life_seconds": 5400,
                "source": ("fixture-power",),
            },
            network_probe=lambda: {
                "platform_supported": True,
                "interface_count": 4,
                "up_interface_count": 2 if network else 1,
                "non_loopback_up_interface_count": 1 if network else 0,
                "has_non_loopback_address": network,
                "has_ipv4": network,
                "has_ipv6": False,
                "max_link_speed_mbps": 1000 if network else None,
                "source": ("fixture-network",),
            },
        )

    def test_snapshot_is_bounded_read_only_machine_context(self) -> None:
        snapshot = self._sense().probe()

        self.assertTrue(snapshot.session.platform_supported)
        self.assertEqual(snapshot.session.process_session_id, 3)
        self.assertEqual(snapshot.session.active_console_session_id, 3)
        self.assertTrue(snapshot.session.attached_to_active_console)
        self.assertFalse(snapshot.session.remote_session)
        self.assertTrue(snapshot.session.input_desktop_openable)
        self.assertEqual(snapshot.session.idle_seconds, 12.5)

        self.assertEqual(snapshot.power.ac_status, "online")
        self.assertTrue(snapshot.power.battery_present)
        self.assertEqual(snapshot.power.battery_percent, 77)
        self.assertTrue(snapshot.power.battery_charging)
        self.assertFalse(snapshot.power.battery_saver)
        self.assertEqual(snapshot.power.battery_life_seconds, 5400)

        self.assertEqual(snapshot.network.interface_count, 4)
        self.assertEqual(snapshot.network.up_interface_count, 2)
        self.assertEqual(snapshot.network.non_loopback_up_interface_count, 1)
        self.assertTrue(snapshot.network.has_non_loopback_address)
        self.assertTrue(snapshot.network.has_ipv4)
        self.assertFalse(snapshot.network.has_ipv6)
        self.assertEqual(snapshot.network.max_link_speed_mbps, 1000)

        # The public observation deliberately has no interface-name/address
        # fields, so local network identity is not sprayed into model context.
        self.assertFalse(hasattr(snapshot.network, "interfaces"))
        self.assertFalse(hasattr(snapshot.network, "addresses"))

    def test_probe_failures_degrade_to_unknown_without_inventing_state(self) -> None:
        def boom():
            raise RuntimeError("probe failed")

        snapshot = NativeWindowsCompanionContextSense(
            session_probe=boom,
            power_probe=boom,
            network_probe=boom,
        ).probe()

        self.assertIsNone(snapshot.session.process_session_id)
        self.assertIsNone(snapshot.session.active_console_session_id)
        self.assertIsNone(snapshot.session.attached_to_active_console)
        self.assertIsNone(snapshot.session.remote_session)
        self.assertIsNone(snapshot.session.input_desktop_openable)
        self.assertIsNone(snapshot.session.idle_seconds)
        self.assertEqual(snapshot.power.ac_status, "unknown")
        self.assertIsNone(snapshot.power.battery_present)
        self.assertIsNone(snapshot.power.battery_percent)
        self.assertEqual(snapshot.network.interface_count, 0)
        self.assertEqual(snapshot.network.up_interface_count, 0)
        self.assertEqual(snapshot.network.non_loopback_up_interface_count, 0)
        self.assertIsNone(snapshot.network.has_non_loopback_address)

    def test_invalid_probe_values_are_bounded_instead_of_trusted(self) -> None:
        snapshot = NativeWindowsCompanionContextSense(
            session_probe=lambda: {
                "platform_supported": True,
                "process_session_id": -1,
                "active_console_session_id": "bad",
                "remote_session": "yes",
                "input_desktop_openable": 1,
                "idle_seconds": -10,
            },
            power_probe=lambda: {
                "platform_supported": True,
                "ac_status": "magic",
                "battery_percent": 255,
                "battery_life_seconds": -1,
            },
            network_probe=lambda: {
                "platform_supported": True,
                "interface_count": 1,
                "up_interface_count": 99,
                "non_loopback_up_interface_count": 88,
                "max_link_speed_mbps": -100,
            },
        ).probe()

        self.assertIsNone(snapshot.session.process_session_id)
        self.assertIsNone(snapshot.session.active_console_session_id)
        self.assertIsNone(snapshot.session.remote_session)
        self.assertIsNone(snapshot.session.input_desktop_openable)
        self.assertIsNone(snapshot.session.idle_seconds)
        self.assertEqual(snapshot.power.ac_status, "unknown")
        self.assertIsNone(snapshot.power.battery_percent)
        self.assertIsNone(snapshot.power.battery_life_seconds)
        self.assertEqual(snapshot.network.interface_count, 1)
        self.assertEqual(snapshot.network.up_interface_count, 1)
        self.assertEqual(snapshot.network.non_loopback_up_interface_count, 1)
        self.assertIsNone(snapshot.network.max_link_speed_mbps)

    def test_delta_ignores_idle_drift_but_detects_material_environment_change(self) -> None:
        first = self._sense(idle_seconds=1.0).probe()
        idle_only = self._sense(idle_seconds=80.0).probe()
        idle_delta = compare_windows_companion_context(first, idle_only)
        self.assertFalse(idle_delta.material_change)

        changed = NativeWindowsCompanionContextSense(
            session_probe=lambda: {
                "platform_supported": True,
                "process_session_id": 4,
                "active_console_session_id": 3,
                "remote_session": True,
                "input_desktop_openable": False,
                "idle_seconds": 0.1,
            },
            power_probe=lambda: {
                "platform_supported": True,
                "ac_status": "offline",
                "battery_present": True,
                "battery_percent": 40,
                "battery_charging": False,
                "battery_saver": True,
            },
            network_probe=lambda: {
                "platform_supported": True,
                "interface_count": 4,
                "up_interface_count": 1,
                "non_loopback_up_interface_count": 0,
                "has_non_loopback_address": False,
                "has_ipv4": False,
                "has_ipv6": False,
            },
        ).probe()
        delta = compare_windows_companion_context(first, changed)
        self.assertTrue(delta.material_change)
        self.assertTrue(delta.session_identity_changed)
        self.assertTrue(delta.input_desktop_availability_changed)
        self.assertTrue(delta.remote_session_changed)
        self.assertTrue(delta.power_source_changed)
        self.assertTrue(delta.battery_saver_changed)
        self.assertTrue(delta.network_availability_changed)

    def test_device_graph_composes_machine_and_companion_context_without_new_store(self) -> None:
        sense = self._sense()
        graph = DeviceCapabilityGraph(
            inventory_provider=lambda: [],
            process_provider=lambda: [],
            window_provider=lambda: [],
            cache_path=None,
            inventory_ttl_seconds=0,
            companion_context_sense=sense,
        )

        companion = graph.companion_context()
        combined = graph.resident_context_snapshot(force_inventory_refresh=True)

        self.assertEqual(companion.session.process_session_id, 3)
        self.assertEqual(combined.machine.applications, ())
        self.assertEqual(combined.machine.running_processes, ())
        self.assertEqual(combined.machine.windows, ())
        self.assertIsNone(combined.machine.foreground)
        self.assertEqual(combined.companion.power.battery_percent, 77)
        self.assertTrue(combined.companion.network.has_non_loopback_address)


if __name__ == "__main__":
    unittest.main()
