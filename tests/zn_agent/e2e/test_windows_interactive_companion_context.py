from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.windows_companion_body import WindowsCompanionAwareBody


class WindowsInteractiveCompanionContextE2ETests(unittest.TestCase):
    def test_real_resident_observes_session_power_network_and_display_context(self) -> None:
        if os.name != "nt":
            raise unittest.SkipTest("Windows companion context E2E runs only on Windows")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertIsInstance(resident.body, WindowsCompanionAwareBody)
                self.assertIs(resident.body.device_capabilities, resident.device_capabilities)

                context = resident.device_capabilities.companion_context()
                display = resident.device_capabilities.display_context()

                self.assertTrue(context.session.platform_supported)
                self.assertIsNotNone(context.session.process_session_id)
                self.assertGreaterEqual(int(context.session.process_session_id or -1), 0)
                self.assertIsNotNone(context.session.active_console_session_id)
                self.assertGreaterEqual(int(context.session.active_console_session_id or -1), 0)
                self.assertIsNotNone(context.session.remote_session)
                self.assertTrue(
                    context.session.input_desktop_openable,
                    "hosted interactive Windows acceptance must expose the real input desktop",
                )
                self.assertIsNotNone(context.session.idle_seconds)
                self.assertGreaterEqual(float(context.session.idle_seconds or 0.0), 0.0)

                connection_state = resident.body._current_session_connection_state(
                    int(context.session.process_session_id or 0)
                )
                self.assertEqual(
                    connection_state,
                    "active",
                    "real OS-wide input must only be admitted from a WTSActive user session",
                )

                self.assertTrue(context.power.platform_supported)
                self.assertIn(context.power.ac_status, {"online", "offline", "unknown"})
                if context.power.battery_percent is not None:
                    self.assertGreaterEqual(context.power.battery_percent, 0)
                    self.assertLessEqual(context.power.battery_percent, 100)

                self.assertTrue(context.network.platform_supported)
                self.assertGreaterEqual(context.network.interface_count, 1)
                self.assertGreaterEqual(context.network.up_interface_count, 0)
                self.assertLessEqual(
                    context.network.up_interface_count,
                    context.network.interface_count,
                )
                self.assertGreaterEqual(context.network.non_loopback_up_interface_count, 0)
                self.assertLessEqual(
                    context.network.non_loopback_up_interface_count,
                    context.network.up_interface_count,
                )
                self.assertIsNotNone(context.network.has_non_loopback_address)
                self.assertFalse(hasattr(context.network, "interfaces"))
                self.assertFalse(hasattr(context.network, "addresses"))

                self.assertTrue(display.platform_supported)
                self.assertGreaterEqual(display.monitor_count, 1)
                self.assertGreaterEqual(display.enumerated_monitor_count, 1)
                self.assertEqual(display.primary_monitor_count, 1)
                self.assertIsNotNone(display.primary_width)
                self.assertIsNotNone(display.primary_height)
                self.assertIsNotNone(display.virtual_width)
                self.assertIsNotNone(display.virtual_height)
                self.assertGreater(int(display.virtual_width or 0), 0)
                self.assertGreater(int(display.virtual_height or 0), 0)
                self.assertGreaterEqual(len(display.monitors), 1)
                self.assertLessEqual(len(display.monitors), 16)
                for monitor in display.monitors:
                    self.assertGreater(monitor.width, 0)
                    self.assertGreater(monitor.height, 0)
                    self.assertGreater(monitor.work_width, 0)
                    self.assertGreater(monitor.work_height, 0)
                    self.assertFalse(hasattr(monitor, "device_name"))
                    self.assertFalse(hasattr(monitor, "serial_number"))

                body_context = resident.body.act("windows_companion_context")
                self.assertTrue(body_context.success)
                self.assertTrue(body_context.data.get("read_only"))
                self.assertFalse(body_context.data.get("dispatch_sent"))
                self.assertEqual(
                    body_context.data["session"]["process_session_id"],
                    context.session.process_session_id,
                )
                self.assertEqual(
                    body_context.data["display"]["monitor_count"],
                    display.monitor_count,
                )
                self.assertTrue(body_context.data["interactive_input"]["ready"])
                self.assertEqual(
                    body_context.data["interactive_input"]["session_connection_state"],
                    "active",
                )
                self.assertEqual(
                    body_context.data["interactive_input"]["disposition"],
                    "ready",
                )

                print(
                    "ZN_WINDOWS_COMPANION_CONTEXT_EVIDENCE="
                    f"{{\"session_id\":{int(context.session.process_session_id or 0)},"
                    f"\"active_console_session_id\":{int(context.session.active_console_session_id or 0)},"
                    f"\"wts_state\":\"{connection_state}\","
                    f"\"input_ready\":{str(bool(body_context.data['interactive_input']['ready'])).lower()},"
                    f"\"input_desktop_openable\":{str(bool(context.session.input_desktop_openable)).lower()},"
                    f"\"remote_session\":{str(bool(context.session.remote_session)).lower()},"
                    f"\"ac_status\":\"{context.power.ac_status}\","
                    f"\"up_interfaces\":{context.network.up_interface_count},"
                    f"\"non_loopback_up_interfaces\":{context.network.non_loopback_up_interface_count},"
                    f"\"monitor_count\":{display.monitor_count},"
                    f"\"virtual_width\":{int(display.virtual_width or 0)},"
                    f"\"virtual_height\":{int(display.virtual_height or 0)}}}",
                    flush=True,
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
