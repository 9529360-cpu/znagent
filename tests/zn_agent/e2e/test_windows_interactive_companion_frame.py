from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.windows_companion_frame import compare_windows_companion_frames


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
                graph = resident.device_capabilities
                first = graph.companion_frame()
                second = graph.companion_frame()

                self.assertEqual(first.frame_version, "windows-companion-frame:v1")
                for value in (
                    first.fingerprint,
                    first.session_fingerprint,
                    first.power_fingerprint,
                    first.network_fingerprint,
                    first.display_fingerprint,
                    first.foreground_fingerprint,
                ):
                    self.assertEqual(len(value), 64)

                self.assertIsNotNone(first.foreground_process_id)
                self.assertGreater(int(first.foreground_process_id or 0), 0)
                self.assertTrue(str(first.foreground_process_name or "").strip())
                self.assertIsNotNone(first.foreground_window_handle)
                self.assertGreater(int(first.foreground_window_handle or 0), 0)
                self.assertGreaterEqual(first.monitor_count, 1)
                self.assertIsNotNone(first.has_non_loopback_network)
                self.assertIn(first.ac_status, {"online", "offline", "unknown"})
                self.assertTrue(first.input_desktop_openable)
                self.assertFalse(hasattr(first, "title"))
                self.assertFalse(hasattr(first, "class_name"))
                self.assertFalse(hasattr(first, "ip_addresses"))

                # No deliberate input/window mutation happens between these
                # observations. If the hosting shell itself changes foreground,
                # only the foreground component may legitimately drift.
                delta = compare_windows_companion_frames(first, second)
                self.assertFalse(delta.session_changed)
                self.assertFalse(delta.power_changed)
                self.assertFalse(delta.network_changed)
                self.assertFalse(delta.display_changed)

                print(
                    "ZN_WINDOWS_COMPANION_FRAME_EVIDENCE="
                    f"{{\"fingerprint\":\"{first.fingerprint}\","
                    f"\"session_fingerprint\":\"{first.session_fingerprint}\","
                    f"\"foreground_fingerprint\":\"{first.foreground_fingerprint}\","
                    f"\"foreground_process_id\":{int(first.foreground_process_id or 0)},"
                    f"\"foreground_process_name\":\"{first.foreground_process_name}\","
                    f"\"monitor_count\":{first.monitor_count},"
                    f"\"network_available\":{str(bool(first.has_non_loopback_network)).lower()},"
                    f"\"input_desktop_openable\":{str(bool(first.input_desktop_openable)).lower()},"
                    f"\"foreground_changed_between_fresh_reads\":{str(bool(delta.foreground_changed)).lower()}}}",
                    flush=True,
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
