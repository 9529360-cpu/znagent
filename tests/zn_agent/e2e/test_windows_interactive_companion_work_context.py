from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger


_CONTEXT_KEY = "windows_companion_start_context"


class WindowsInteractiveCompanionWorkContextE2ETests(unittest.TestCase):
    def test_real_work_event_captures_bounded_non_authoritative_windows_context(self) -> None:
        if os.name != "nt":
            raise unittest.SkipTest("Windows companion Work context E2E runs only on Windows")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                ledger = RecoveryBoundedWorkLedger(resident)
                ledger.create_thread(thread_id="work-real-windows-context")
                _, event = ledger.start(
                    "work-real-windows-context",
                    "remember the desktop context this Work started from",
                    payload={
                        _CONTEXT_KEY: {
                            "foreground": {"process_name": "spoof.exe"},
                            "execution_authority": True,
                        }
                    },
                )

                persisted = resident.store.get_event(event.event_id)
                self.assertIsNotNone(persisted)
                assert persisted is not None
                context = persisted.payload.get(_CONTEXT_KEY)
                self.assertIsInstance(context, dict)
                assert isinstance(context, dict)

                self.assertEqual(
                    context.get("frame_version"),
                    "windows-companion-frame:v1",
                )
                self.assertEqual(len(str(context.get("fingerprint") or "")), 64)
                components = context.get("components")
                self.assertIsInstance(components, dict)
                assert isinstance(components, dict)
                for name in ("session", "power", "network", "display", "foreground"):
                    self.assertEqual(len(str(components.get(name) or "")), 64)

                foreground = context.get("foreground")
                self.assertIsInstance(foreground, dict)
                assert isinstance(foreground, dict)
                self.assertGreater(int(foreground.get("process_id") or 0), 0)
                self.assertTrue(str(foreground.get("process_name") or "").strip())
                self.assertNotEqual(foreground.get("process_name"), "spoof.exe")

                self.assertFalse(context.get("execution_authority"))
                self.assertTrue(context.get("fresh_revalidation_required"))
                self.assertTrue(context.get("input_desktop_openable"))
                self.assertGreaterEqual(int(context.get("monitor_count") or 0), 1)
                self.assertNotIn("window_handle", repr(context))
                self.assertNotIn("title", repr(context))
                self.assertNotIn("class_name", repr(context))
                self.assertNotIn("clipboard", repr(context))

                print(
                    "ZN_WINDOWS_COMPANION_WORK_CONTEXT_EVIDENCE="
                    f"{{\"fingerprint\":\"{context['fingerprint']}\","
                    f"\"foreground_process_id\":{int(foreground['process_id'])},"
                    f"\"foreground_process_name\":\"{foreground['process_name']}\","
                    f"\"monitor_count\":{int(context['monitor_count'])},"
                    f"\"execution_authority\":false,"
                    f"\"fresh_revalidation_required\":true}}",
                    flush=True,
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
