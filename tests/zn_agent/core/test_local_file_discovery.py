from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.local_file_discovery import (
    LocalFileDiscovery,
    build_local_file_discovery_capability,
    parse_local_file_search_request,
)


class LocalFileDiscoveryTests(unittest.TestCase):
    def test_parses_bounded_downloads_yesterday_goal_without_model(self):
        request = parse_local_file_search_request("找到我昨天下载的合同")
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.scope, "downloads")
        self.assertEqual(request.query, "合同")
        self.assertEqual(
            request.modified_date,
            (
                datetime.now().astimezone().date()
                - timedelta(days=1)
            ).isoformat(),
        )
        self.assertEqual(request.extensions, ())

    def test_parses_explicit_pdf_query_but_rejects_unscoped_search(self):
        request = parse_local_file_search_request(
            "找一下下载目录里关于人工智能的 PDF 文件"
        )
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.scope, "downloads")
        self.assertEqual(request.query, "人工智能")
        self.assertEqual(request.extensions, (".pdf",))
        self.assertIsNone(parse_local_file_search_request("帮我找一下合同"))

    def test_search_uses_filename_metadata_and_never_reads_file_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "archive"
            nested.mkdir()
            yesterday = datetime.now().astimezone() - timedelta(days=1)

            expected = root / "合同_最终版.pdf"
            expected.write_bytes(b"TOP SECRET BODY MUST NOT BE READ")
            os.utime(
                expected,
                (yesterday.timestamp(), yesterday.timestamp()),
            )

            stale = nested / "合同_旧版.pdf"
            stale.write_bytes(b"OLD SECRET")
            old = yesterday - timedelta(days=5)
            os.utime(stale, (old.timestamp(), old.timestamp()))

            request = parse_local_file_search_request(
                "找到我昨天下载的合同"
            )
            assert request is not None
            discovery = LocalFileDiscovery(
                roots={"downloads": root},
                max_scan_entries=100,
            )
            with patch.object(
                Path,
                "open",
                side_effect=AssertionError("file content must not be read"),
            ):
                result = discovery.search(request)

            self.assertTrue(result.complete)
            self.assertEqual(result.matched_count, 1)
            self.assertEqual(
                [Path(item.path) for item in result.candidates],
                [expected.resolve()],
            )

    def test_capability_is_zero_token_read_only_and_lists_multiple_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("合同_A.pdf", "合同_B.docx"):
                (root / name).write_bytes(b"x")
            event = SimpleNamespace(
                task="找下载目录里的合同文件",
                kind="desktop_user_event",
                payload={},
            )
            capability = build_local_file_discovery_capability(
                roots={"downloads": root}
            )
            self.assertTrue(capability.replay_safe)
            self.assertEqual(capability.match(event), 0.98)

            result = capability.execute(event, SimpleNamespace())

            self.assertTrue(result.success)
            self.assertTrue(result.verification_passed)
            self.assertEqual(result.data["matched_count"], 2)
            self.assertIn("合同_A.pdf", result.response)
            self.assertIn("合同_B.docx", result.response)

    def test_scan_limit_is_reported_as_incomplete_not_silently_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(5):
                (root / f"合同_{index}.txt").write_text(
                    "x",
                    encoding="utf-8",
                )
            request = parse_local_file_search_request(
                "找下载目录里的合同文件"
            )
            assert request is not None
            result = LocalFileDiscovery(
                roots={"downloads": root},
                max_scan_entries=2,
            ).search(request)
            self.assertFalse(result.complete)


if __name__ == "__main__":
    unittest.main()
