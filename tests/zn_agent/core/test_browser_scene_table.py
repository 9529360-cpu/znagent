from __future__ import annotations

import json
import unittest
from dataclasses import asdict
from types import SimpleNamespace

from zn_agent.core.browser_scene_table import PlaywrightBrowserSceneTableMixin
from zn_agent.core.managed_browser import ManagedBrowserError


class _Handle:
    def __init__(self, raw):
        self.raw = raw
        self.calls = []

    def evaluate(self, script, limits):
        self.calls.append({"script": script, "limits": dict(limits)})
        if isinstance(self.raw, Exception):
            raise self.raw
        return self.raw


class _Harness(PlaywrightBrowserSceneTableMixin):
    def __init__(self, *, role="table", raw=None, stale=False, main_frame=True):
        self.session = SimpleNamespace(identity=SimpleNamespace(session_id="session-1"))
        self.page = SimpleNamespace(main_frame=object())
        frame = self.page.main_frame if main_frame else object()
        self.target = SimpleNamespace(target_id="scene-table-1")
        self.handle = _Handle(
            raw
            if raw is not None
            else {
                "connected": True,
                "supported": True,
                "row_count_observed": 2,
                "rows": [
                    [
                        {"kind": "header", "text": "订单号", "truncated": False},
                        {"kind": "header", "text": "金额", "truncated": False},
                    ],
                    [
                        {"kind": "cell", "text": "1002", "truncated": False},
                        {"kind": "cell", "text": "99.50", "truncated": False},
                    ],
                ],
                "truncated": False,
            }
        )
        self.binding = SimpleNamespace(
            page_id="page-1",
            target=self.target,
            handle=self.handle,
            frame=frame,
            scene_target=SimpleNamespace(role=role),
        )
        self.stale = stale
        self.revalidated = 0

    def _session(self, session_id):
        if session_id != "session-1":
            raise ManagedBrowserError("unknown session")
        return self.session

    def _scene_action_binding(self, session, target_id, *, page_id="", expected_target=None):
        if target_id != self.target.target_id:
            raise ManagedBrowserError("browser scene target is stale or unknown")
        return self.binding

    def _scene_revalidate_binding(self, session, binding):
        self.revalidated += 1
        if self.stale:
            raise ManagedBrowserError("browser scene target became stale after page change")

    def _page(self, session, page_id):
        return self.page


class BrowserSceneTableTests(unittest.TestCase):
    def test_exact_table_extracts_header_and_data_in_order(self):
        harness = _Harness()
        table = harness.observe_scene_table("session-1", "scene-table-1", page_id="page-1")
        self.assertEqual(harness.revalidated, 1)
        self.assertEqual(table.page_id, "page-1")
        self.assertEqual(table.target_id, "scene-table-1")
        self.assertEqual(table.row_count_observed, 2)
        self.assertFalse(table.truncated)
        self.assertEqual(
            [[(cell.kind, cell.text) for cell in row.cells] for row in table.rows],
            [
                [("header", "订单号"), ("header", "金额")],
                [("cell", "1002"), ("cell", "99.50")],
            ],
        )

    def test_hard_caps_are_clamped_to_64_32_512(self):
        harness = _Harness()
        harness.observe_scene_table(
            "session-1",
            "scene-table-1",
            max_rows=9999,
            max_cells_per_row=9999,
            max_cell_text=9999,
        )
        self.assertEqual(
            harness.handle.calls[0]["limits"],
            {"maxRows": 64, "maxCells": 32, "maxText": 512},
        )

    def test_non_table_rejected_before_table_payload_read(self):
        harness = _Harness(role="button")
        with self.assertRaisesRegex(ManagedBrowserError, "table target"):
            harness.observe_scene_table("session-1", "scene-table-1")
        self.assertEqual(harness.revalidated, 1)
        self.assertEqual(harness.handle.calls, [])

    def test_non_main_frame_rejected_before_table_payload_read(self):
        harness = _Harness(main_frame=False)
        with self.assertRaisesRegex(ManagedBrowserError, "main-frame"):
            harness.observe_scene_table("session-1", "scene-table-1")
        self.assertEqual(harness.handle.calls, [])

    def test_detached_malformed_and_provider_failure_are_rejected(self):
        cases = (
            ({"connected": False}, "detached"),
            ({"connected": True, "supported": True, "rows": "bad"}, "invalid rows"),
            (RuntimeError("execution context was destroyed"), "provider failed"),
        )
        for raw, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ManagedBrowserError, expected):
                    _Harness(raw=raw).observe_scene_table("session-1", "scene-table-1")

    def test_truncation_signal_is_preserved(self):
        harness = _Harness(
            raw={
                "connected": True,
                "supported": True,
                "row_count_observed": 100,
                "rows": [[{"kind": "cell", "text": "bounded", "truncated": False}]],
                "truncated": True,
            }
        )
        table = harness.observe_scene_table("session-1", "scene-table-1")
        self.assertEqual(table.row_count_observed, 100)
        self.assertTrue(table.truncated)

    def test_colspan_rowspan_and_partial_materialization_are_fail_closed(self):
        for reason in ("cell_span", "aria_rowcount_mismatch", "aria_colcount_mismatch"):
            with self.subTest(reason=reason):
                raw = {"connected": True, "supported": True, "complex_reason": reason}
                with self.assertRaisesRegex(ManagedBrowserError, reason):
                    _Harness(raw=raw).observe_scene_table("session-1", "scene-table-1")

    def test_stale_target_rejected_before_table_payload_read(self):
        harness = _Harness(stale=True)
        with self.assertRaisesRegex(ManagedBrowserError, "stale"):
            harness.observe_scene_table("session-1", "scene-table-1")
        self.assertEqual(harness.handle.calls, [])

    def test_structured_result_does_not_expose_html_or_page_wide_text(self):
        table = _Harness().observe_scene_table("session-1", "scene-table-1")
        serialized = json.dumps(asdict(table), ensure_ascii=False).lower()
        self.assertNotIn("html", serialized)
        self.assertNotIn("page_text", serialized)
        self.assertNotIn("innerhtml", serialized)
        self.assertEqual(set(asdict(table)), {
            "session_id", "page_id", "target_id", "captured_at", "rows", "row_count_observed", "truncated"
        })


if __name__ == "__main__":
    unittest.main(verbosity=2)
