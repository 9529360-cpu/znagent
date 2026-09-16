from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime


class WindowsInteractiveCompanionFrameE2ETests(unittest.TestCase):
    def test_real_current_windows_context_has_stable_privacy_bounded_frame(self) -> None:
        if os.name != "nt":
            raise unittest.SkipTest("Windows companion frame E2E runs only on Windows")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                frame = resident.device_capabilities.companion_frame()

                self.assertEqual(frame.frame_version, "windows-companion-frame:v1")
                for value in (
                    frame.fingerprint,
                    frame.session_fingerprint,
                    frame.power_fingerprint,
                    frame.network_fingerprint,
                    frame.display_fingerprint,
                    frame.foreground_fingerprint,
                ):
                    self.assertEqual(len(value), 64)

                self.assertIsNotNone(frame.foreground_process_id)
                self.assertGreater(int(frame.foreground_process_id or 0), 0)
                self.assertTrue(str(frame.foreground_process_name or "").strip())
                self.assertIsNotNone(frame.foreground_window_handle)
                self.assertGreater(int(frame.foreground_window_handle or 0), 0)
                self.assertGreaterEqual(frame.monitor_count, 1)
                self.assertIsNotNone(frame.has_non_loopback_network)
                self.assertIn(frame.ac_status, {"online", "offline", "unknown"})
                self.assertTrue(frame.input_desktop_openable)
                self.assertEqual(frame.session_connection_state, "active")
                self.assertFalse(hasattr(frame, "title"))
                self.assertFalse(hasattr(frame, "class_name"))
                self.assertFalse(hasattr(frame, "ip_addresses"))

                print(
                    "ZN_WINDOWS_COMPANION_FRAME_EVIDENCE="
                    f"{{\"fingerprint\":\"{frame.fingerprint}\","
                    f"\"session_fingerprint\":\"{frame.session_fingerprint}\","
                    f"\"foreground_fingerprint\":\"{frame.foreground_fingerprint}\","
                    f"\"foreground_process_id\":{int(frame.foreground_process_id or 0)},"
                    f"\"foreground_process_name\":\"{frame.foreground_process_name}\","
                    f"\"monitor_count\":{frame.monitor_count},"
                    f"\"network_available\":{str(bool(frame.has_non_loopback_network)).lower()},"
                    f"\"input_desktop_openable\":{str(bool(frame.input_desktop_openable)).lower()},"
                    f"\"session_connection_state\":\"{frame.session_connection_state}\"}}",
                    flush=True,
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
