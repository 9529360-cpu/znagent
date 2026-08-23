from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.outbound_media import (
    OutboundMediaAuthorizationError,
    OutboundMediaPathPolicy,
    default_outbound_media_roots,
)


class OutboundMediaPathPolicyTests(unittest.TestCase):
    def test_default_roots_are_zns_artifact_and_outbound_channel_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(
                default_outbound_media_roots(home),
                (home / "artifacts", home / "channels" / "outbound"),
            )

    def test_authorizes_regular_file_inside_zn_artifact_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            artifact = home / "artifacts" / "report.txt"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("resident artifact", encoding="utf-8")
            policy = OutboundMediaPathPolicy.for_zn_home(home)

            authorized = policy.authorize(artifact)

            self.assertEqual(authorized.path, artifact.resolve())
            self.assertEqual(authorized.allowed_root, (home / "artifacts").resolve())
            self.assertEqual(authorized.size_bytes, len("resident artifact"))

    def test_rejects_file_outside_allowed_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "zn-home"
            outside = Path(tmp) / "private.txt"
            outside.write_text("do not send", encoding="utf-8")
            policy = OutboundMediaPathPolicy.for_zn_home(home)

            with self.assertRaisesRegex(
                OutboundMediaAuthorizationError,
                "outside ZN-authorized roots",
            ):
                policy.authorize(outside)

    def test_rejects_relative_missing_directory_empty_and_oversized_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "outbound"
            root.mkdir()
            policy = OutboundMediaPathPolicy([root], max_bytes=4)

            with self.assertRaisesRegex(OutboundMediaAuthorizationError, "must be absolute"):
                policy.authorize("relative.txt")
            with self.assertRaisesRegex(OutboundMediaAuthorizationError, "does not resolve"):
                policy.authorize(root / "missing.txt")
            with self.assertRaisesRegex(OutboundMediaAuthorizationError, "not a regular file"):
                policy.authorize(root)

            empty = root / "empty.bin"
            empty.write_bytes(b"")
            with self.assertRaisesRegex(OutboundMediaAuthorizationError, "is empty"):
                policy.authorize(empty)

            large = root / "large.bin"
            large.write_bytes(b"12345")
            with self.assertRaisesRegex(OutboundMediaAuthorizationError, "exceeds limit"):
                policy.authorize(large)

    def test_explicit_extra_root_can_be_authorized(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            export_root = Path(tmp) / "explicit-export"
            export_root.mkdir()
            media = export_root / "voice.ogg"
            media.write_bytes(b"voice")
            policy = OutboundMediaPathPolicy.for_zn_home(
                home,
                extra_roots=(export_root,),
            )

            authorized = policy.authorize(media)

            self.assertEqual(authorized.allowed_root, export_root.resolve())

    @unittest.skipIf(os.name == "nt", "symlink creation may require Windows privileges")
    def test_symlink_escape_is_rejected_after_real_path_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "outbound"
            outside = Path(tmp) / "outside.txt"
            root.mkdir()
            outside.write_text("secret", encoding="utf-8")
            link = root / "looks-authorized.txt"
            link.symlink_to(outside)
            policy = OutboundMediaPathPolicy([root])

            with self.assertRaisesRegex(
                OutboundMediaAuthorizationError,
                "outside ZN-authorized roots",
            ):
                policy.authorize(link)


if __name__ == "__main__":
    unittest.main()
