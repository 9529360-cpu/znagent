from __future__ import annotations

import unittest

from zn_agent.core.device_capability_graph import DeviceCapabilityGraph
from zn_agent.core.windows_companion_context import NativeWindowsCompanionContextSense
from zn_agent.core.windows_display_context import NativeWindowsDisplayContextSense


class WindowsDisplayContextTests(unittest.TestCase):
    def test_multi_monitor_topology_preserves_negative_virtual_coordinates(self) -> None:
        sense = NativeWindowsDisplayContextSense(
            probe=lambda: {
                "platform_supported": True,
                "monitor_count": 2,
                "enumerated_monitor_count": 2,
                "primary_width": 1920,
                "primary_height": 1080,
                "virtual_left": -1280,
                "virtual_top": 0,
                "virtual_width": 3200,
                "virtual_height": 1080,
                "monitors": [
                    {
                        "left": -1280,
                        "top": 0,
                        "right": 0,
                        "bottom": 1024,
                        "work_left": -1280,
                        "work_top": 0,
                        "work_right": 0,
                        "work_bottom": 984,
                        "primary": False,
                    },
                    {
                        "left": 0,
                        "top": 0,
                        "right": 1920,
                        "bottom": 1080,
                        "work_left": 0,
                        "work_top": 0,
                        "work_right": 1920,
                        "work_bottom": 1040,
                        "primary": True,
                    },
                ],
                "source": ("fixture-display",),
            }
        )
        observation = sense.probe()

        self.assertTrue(observation.platform_supported)
        self.assertEqual(observation.monitor_count, 2)
        self.assertEqual(observation.enumerated_monitor_count, 2)
        self.assertEqual(observation.primary_monitor_count, 1)
        self.assertEqual(observation.virtual_left, -1280)
        self.assertEqual(observation.virtual_width, 3200)
        self.assertEqual(len(observation.monitors), 2)
        self.assertEqual(observation.monitors[0].left, -1280)
        self.assertEqual(observation.monitors[0].width, 1280)
        self.assertEqual(observation.monitors[1].width, 1920)
        self.assertTrue(observation.monitors[1].primary)
        self.assertFalse(hasattr(observation.monitors[0], "device_name"))
        self.assertFalse(hasattr(observation.monitors[0], "serial_number"))

    def test_invalid_or_out_of_bounds_monitor_geometry_is_rejected(self) -> None:
        sense = NativeWindowsDisplayContextSense(
            probe=lambda: {
                "platform_supported": True,
                "monitor_count": 2,
                "enumerated_monitor_count": 2,
                "primary_width": 1920,
                "primary_height": 1080,
                "virtual_left": 0,
                "virtual_top": 0,
                "virtual_width": 1920,
                "virtual_height": 1080,
                "monitors": [
                    {
                        "left": 0,
                        "top": 0,
                        "right": 0,
                        "bottom": 1080,
                        "work_left": 0,
                        "work_top": 0,
                        "work_right": 0,
                        "work_bottom": 1040,
                        "primary": True,
                    },
                    {
                        "left": 0,
                        "top": 0,
                        "right": 1920,
                        "bottom": 1080,
                        "work_left": -1,
                        "work_top": 0,
                        "work_right": 1920,
                        "work_bottom": 1040,
                        "primary": True,
                    },
                ],
            }
        )
        observation = sense.probe()

        self.assertEqual(observation.monitor_count, 2)
        self.assertEqual(observation.enumerated_monitor_count, 2)
        self.assertEqual(observation.monitors, ())
        self.assertEqual(observation.primary_monitor_count, 0)
        self.assertTrue(observation.truncated)

    def test_monitor_list_is_bounded_and_reports_truncation(self) -> None:
        monitors = [
            {
                "left": index * 100,
                "top": 0,
                "right": index * 100 + 100,
                "bottom": 100,
                "work_left": index * 100,
                "work_top": 0,
                "work_right": index * 100 + 100,
                "work_bottom": 100,
                "primary": index == 0,
            }
            for index in range(20)
        ]
        observation = NativeWindowsDisplayContextSense(
            probe=lambda: {
                "platform_supported": True,
                "monitor_count": 20,
                "enumerated_monitor_count": 20,
                "primary_width": 100,
                "primary_height": 100,
                "virtual_left": 0,
                "virtual_top": 0,
                "virtual_width": 2000,
                "virtual_height": 100,
                "monitors": monitors,
            }
        ).probe()

        self.assertEqual(len(observation.monitors), 16)
        self.assertEqual(observation.enumerated_monitor_count, 20)
        self.assertTrue(observation.truncated)
        self.assertEqual(observation.primary_monitor_count, 1)

    def test_probe_failure_degrades_without_inventing_monitor_geometry(self) -> None:
        def boom():
            raise RuntimeError("display probe failed")

        observation = NativeWindowsDisplayContextSense(probe=boom).probe()
        self.assertEqual(observation.monitor_count, 0)
        self.assertEqual(observation.enumerated_monitor_count, 0)
        self.assertEqual(observation.monitors, ())
        self.assertIsNone(observation.virtual_width)
        self.assertIsNone(observation.primary_width)

    def test_device_graph_composes_display_with_existing_companion_context(self) -> None:
        companion = NativeWindowsCompanionContextSense(
            session_probe=lambda: {"platform_supported": True, "process_session_id": 3},
            power_probe=lambda: {"platform_supported": True, "ac_status": "online"},
            network_probe=lambda: {"platform_supported": True},
        )
        display = NativeWindowsDisplayContextSense(
            probe=lambda: {
                "platform_supported": True,
                "monitor_count": 1,
                "enumerated_monitor_count": 1,
                "primary_width": 1920,
                "primary_height": 1080,
                "virtual_left": 0,
                "virtual_top": 0,
                "virtual_width": 1920,
                "virtual_height": 1080,
                "monitors": [
                    {
                        "left": 0,
                        "top": 0,
                        "right": 1920,
                        "bottom": 1080,
                        "work_left": 0,
                        "work_top": 0,
                        "work_right": 1920,
                        "work_bottom": 1040,
                        "primary": True,
                    }
                ],
            }
        )
        graph = DeviceCapabilityGraph(
            inventory_provider=lambda: [],
            process_provider=lambda: [],
            window_provider=lambda: [],
            cache_path=None,
            inventory_ttl_seconds=0,
            companion_context_sense=companion,
            display_context_sense=display,
        )
        snapshot = graph.resident_context_snapshot(force_inventory_refresh=True)

        self.assertEqual(snapshot.companion.session.process_session_id, 3)
        self.assertEqual(snapshot.display.monitor_count, 1)
        self.assertEqual(snapshot.display.monitors[0].work_height, 1040)


if __name__ == "__main__":
    unittest.main()
