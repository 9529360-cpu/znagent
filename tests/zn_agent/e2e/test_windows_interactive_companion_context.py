from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime


class WindowsInteractiveCompanionContextE2ETests(unittest.TestCase):
    def test_real_resident_observes_session_power_and_network_context(self) -> None:
        if os.name != "nt":
            raise unittest.SkipTest("Windows companion context E2E runs only on Windows")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                context = resident.device_capabilities.companion_context()

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

                print(
                    "ZN_WINDOWS_COMPANION_CONTEXT_EVIDENCE="
                    f"{{\"session_id\":{int(context.session.process_session_id or 0)},"
                    f"\"active_console_session_id\":{int(context.session.active_console_session_id or 0)},"
                    f"\"input_desktop_openable\":{str(bool(context.session.input_desktop_openable)).lower()},"
                    f"\"remote_session\":{str(bool(context.session.remote_session)).lower()},"
                    f"\"ac_status\":\"{context.power.ac_status}\","
                    f"\"up_interfaces\":{context.network.up_interface_count},"
                    f"\"non_loopback_up_interfaces\":{context.network.non_loopback_up_interface_count}}}",
                    flush=True,
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
