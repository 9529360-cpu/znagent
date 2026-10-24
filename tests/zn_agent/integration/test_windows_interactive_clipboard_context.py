from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime


class WindowsInteractiveClipboardContextE2ETests(unittest.TestCase):
    def test_real_clipboard_metadata_is_observable_without_reading_content(self) -> None:
        if os.name != "nt":
            raise unittest.SkipTest("Windows clipboard companion E2E runs only on Windows")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                observation = resident.device_capabilities.clipboard_context()

                self.assertTrue(observation.platform_supported)
                self.assertIsInstance(observation.sequence_available, bool)
                if observation.sequence_available:
                    self.assertIsNotNone(observation.sequence_number)
                    self.assertGreater(int(observation.sequence_number or 0), 0)
                else:
                    self.assertIsNone(observation.sequence_number)
                for flag in (
                    observation.unicode_text_available,
                    observation.file_drop_available,
                    observation.bitmap_available,
                    observation.dib_available,
                ):
                    self.assertIsInstance(flag, bool)
                if observation.owner_process_id is not None:
                    self.assertGreater(observation.owner_process_id, 0)

                for forbidden in (
                    "text",
                    "content",
                    "files",
                    "data",
                    "bitmap_bytes",
                ):
                    self.assertFalse(hasattr(observation, forbidden))

                snapshot = resident.device_capabilities.resident_context_snapshot()
                self.assertEqual(
                    snapshot.clipboard.sequence_available,
                    observation.sequence_available,
                )

                print(
                    "ZN_WINDOWS_CLIPBOARD_CONTEXT_EVIDENCE="
                    f"{{\"sequence_available\":{str(observation.sequence_available).lower()},"
                    f"\"sequence_number\":{int(observation.sequence_number or 0)},"
                    f"\"unicode_text_available\":{str(bool(observation.unicode_text_available)).lower()},"
                    f"\"file_drop_available\":{str(bool(observation.file_drop_available)).lower()},"
                    f"\"bitmap_available\":{str(bool(observation.bitmap_available)).lower()},"
                    f"\"dib_available\":{str(bool(observation.dib_available)).lower()},"
                    f"\"owner_process_id_present\":{str(observation.owner_process_id is not None).lower()}}}",
                    flush=True,
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
