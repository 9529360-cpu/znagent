from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime


class WindowsInteractiveCompanionForegroundContextE2ETests(unittest.TestCase):
    def test_real_foreground_is_privacy_bounded_and_bound_to_current_monitor(self) -> None:
        if os.name != "nt":
            raise unittest.SkipTest("Windows foreground companion E2E runs only on Windows")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                graph = resident.device_capabilities
                foreground = graph.foreground_companion_context()
                display = graph.display_context()

                self.assertTrue(foreground.platform_supported)
                self.assertTrue(
                    foreground.available,
                    "interactive Windows host did not expose a current foreground window",
                )
                self.assertIsNotNone(foreground.process_id)
                self.assertGreater(int(foreground.process_id or 0), 0)
                self.assertTrue(str(foreground.process_name or "").strip())
                self.assertIsNotNone(foreground.window_handle)
                self.assertGreater(int(foreground.window_handle or 0), 0)
                self.assertGreaterEqual(foreground.title_chars, 0)
                if foreground.title_sha256 is not None:
                    self.assertEqual(len(foreground.title_sha256), 64)
                self.assertGreaterEqual(foreground.class_name_chars, 0)
                if foreground.class_name_sha256 is not None:
                    self.assertEqual(len(foreground.class_name_sha256), 64)
                self.assertFalse(hasattr(foreground, "title"))
                self.assertFalse(hasattr(foreground, "class_name"))

                self.assertIsNotNone(
                    foreground.monitor,
                    "foreground window was not bound to an intersecting real monitor",
                )
                monitor = foreground.monitor
                assert monitor is not None
                self.assertGreater(monitor.width, 0)
                self.assertGreater(monitor.height, 0)
                self.assertGreater(monitor.work_width, 0)
                self.assertGreater(monitor.work_height, 0)
                self.assertFalse(hasattr(monitor, "device_name"))
                self.assertFalse(hasattr(monitor, "serial_number"))

                current_monitor_rect = (
                    monitor.left,
                    monitor.top,
                    monitor.right,
                    monitor.bottom,
                )
                enumerated_rects = {
                    (item.left, item.top, item.right, item.bottom)
                    for item in display.monitors
                }
                self.assertIn(
                    current_monitor_rect,
                    enumerated_rects,
                    "foreground monitor does not belong to the fresh bounded display topology",
                )

                print(
                    "ZN_WINDOWS_FOREGROUND_COMPANION_EVIDENCE="
                    f"{{\"process_id\":{int(foreground.process_id or 0)},"
                    f"\"process_name\":\"{foreground.process_name}\","
                    f"\"window_handle\":{int(foreground.window_handle or 0)},"
                    f"\"title_chars\":{foreground.title_chars},"
                    f"\"title_hash_present\":{str(foreground.title_sha256 is not None).lower()},"
                    f"\"monitor_primary\":{str(bool(monitor.primary)).lower()},"
                    f"\"monitor_left\":{monitor.left},"
                    f"\"monitor_top\":{monitor.top},"
                    f"\"monitor_width\":{monitor.width},"
                    f"\"monitor_height\":{monitor.height}}}",
                    flush=True,
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
