from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime


class WindowsInteractiveUiSecurityContextE2ETests(unittest.TestCase):
    def test_real_resident_and_foreground_integrity_are_observed_without_escalation(self) -> None:
        if os.name != "nt":
            raise unittest.SkipTest("Windows UI security context E2E runs only on Windows")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                context = resident.device_capabilities.ui_security_context()

                self.assertTrue(context.platform_supported)
                self.assertTrue(context.resident.observable)
                self.assertGreater(context.resident.process_id, 0)
                self.assertIsNotNone(context.resident.integrity_rid)
                self.assertGreaterEqual(int(context.resident.integrity_rid or 0), 0)
                self.assertIn(
                    context.resident.integrity_label,
                    {"untrusted", "low", "medium", "medium_plus", "high", "system", "protected"},
                )
                self.assertIsInstance(context.resident.elevated, bool)
                self.assertIsInstance(context.resident.ui_access, bool)

                self.assertIsNotNone(
                    context.foreground,
                    "interactive Windows host did not expose a foreground process for UIPI comparison",
                )
                foreground = context.foreground
                assert foreground is not None
                self.assertTrue(
                    foreground.observable,
                    "foreground process token was not queryable with bounded TOKEN_QUERY authority",
                )
                self.assertGreater(foreground.process_id, 0)
                self.assertIsNotNone(foreground.integrity_rid)
                self.assertIn(
                    foreground.integrity_label,
                    {"untrusted", "low", "medium", "medium_plus", "high", "system", "protected"},
                )
                self.assertIsInstance(foreground.elevated, bool)
                self.assertIsInstance(foreground.ui_access, bool)
                self.assertIsInstance(context.input_integrity_compatible, bool)
                self.assertIn(
                    context.disposition,
                    {"compatible", "foreground_higher_integrity"},
                )

                # Security sensing must never carry foreground title/class text.
                self.assertFalse(hasattr(context, "window_title"))
                self.assertFalse(hasattr(context, "window_class"))

                print(
                    "ZN_WINDOWS_UI_SECURITY_CONTEXT_EVIDENCE="
                    f"{{\"resident_pid\":{context.resident.process_id},"
                    f"\"resident_integrity\":\"{context.resident.integrity_label}\","
                    f"\"resident_elevated\":{str(bool(context.resident.elevated)).lower()},"
                    f"\"resident_ui_access\":{str(bool(context.resident.ui_access)).lower()},"
                    f"\"foreground_pid\":{foreground.process_id},"
                    f"\"foreground_integrity\":\"{foreground.integrity_label}\","
                    f"\"foreground_elevated\":{str(bool(foreground.elevated)).lower()},"
                    f"\"input_integrity_compatible\":{str(bool(context.input_integrity_compatible)).lower()},"
                    f"\"disposition\":\"{context.disposition}\"}}",
                    flush=True,
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
