from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from zn_agent.core.windows_screen_capture import (
    WindowsScreenCaptureError,
    capture_primary_screen_artifact,
    inspect_screen_capture_artifact,
    screen_capture_artifact_path,
)


@unittest.skipUnless(os.name == "nt", "Windows screen capture is Windows-only")
class WindowsScreenCaptureTests(unittest.TestCase):
    def test_event_identity_owns_deterministic_artifact_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = screen_capture_artifact_path("event-1", home=tmp)
            again = screen_capture_artifact_path("event-1", home=tmp)
            other = screen_capture_artifact_path("event-2", home=tmp)

            self.assertEqual(first, again)
            self.assertNotEqual(first, other)
            self.assertEqual(first.parent, Path(tmp) / "artifacts" / "screenshots")
            self.assertEqual(first.suffix, ".png")

    def test_capture_writes_png_and_independent_hash_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def capture():
                return Image.new("RGB", (24, 12), (10, 20, 30))

            artifact = capture_primary_screen_artifact(
                "event-capture",
                home=tmp,
                capture_fn=capture,
            )
            observed = inspect_screen_capture_artifact(
                artifact.local_path,
                home=tmp,
            )

            self.assertEqual(observed["width"], 24)
            self.assertEqual(observed["height"], 12)
            self.assertEqual(observed["sha256"], artifact.sha256)
            self.assertEqual(observed["size_bytes"], artifact.size_bytes)
            self.assertGreater(observed["size_bytes"], 0)
            self.assertTrue(Path(artifact.local_path).is_file())

    def test_inspection_rejects_png_outside_zn_artifact_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside.png"
            Image.new("RGB", (4, 4), (0, 0, 0)).save(outside)

            with self.assertRaisesRegex(
                WindowsScreenCaptureError,
                "escaped the ZN screenshot root",
            ):
                inspect_screen_capture_artifact(
                    outside,
                    home=Path(tmp) / "home",
                )

    def test_capture_failure_never_leaves_partial_temp_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            class BrokenImage:
                size = (10, 10)

                def save(self, *_args, **_kwargs):
                    raise OSError("disk write failed")

                def close(self):
                    return None

            with self.assertRaisesRegex(
                WindowsScreenCaptureError,
                "disk write failed",
            ):
                capture_primary_screen_artifact(
                    "event-broken",
                    home=tmp,
                    capture_fn=BrokenImage,
                )

            root = Path(tmp) / "artifacts" / "screenshots"
            self.assertEqual(list(root.glob("*")) if root.exists() else [], [])


if __name__ == "__main__":
    unittest.main()
