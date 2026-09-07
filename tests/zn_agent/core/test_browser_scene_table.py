from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.browser import BrowserPlane, BrowserSessionIdentity, BrowserTarget, BrowserTargetKind
from zn_agent.core.browser_scene_table import PlaywrightBrowserSceneTableMixin
from zn_agent.core.models import utc_now


class _Handle:
    def __init__(self, raw):
        self.raw = raw
        self.calls = []

    def evaluate(self, script, limits):
        self.calls.append(dict(limits))
        return self.raw


class _Harness(PlaywrightBrowserSceneTableMixin):
    def __init__(self, *, role="table", raw=None):
        identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake",
        )
        self.session = SimpleNamespace(identity=identity)
        self.target = BrowserTarget(
            session_id=identity.session_id,
            page_id="page-1",
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id="scene-table-1",
            observed_at=utc_now(),
            url="https://example.com/table",
            frame_id="main",
            role=role,
            name="Results",
            selector_hint=f"browser_scene:{role}",
        )
        self.handle = _Handle(
            raw
            or {
                "connected": True,
                "supported": True,
                "row_count_observed": 2,
                "rows": [
                    [
                        {"kind": "header", "text": "Name"},
                        {"kind": "header", "text": "Score"},
                    ],
                    [
                        {"kind": "cell", "text": "Ada"},
                        {"kind": "cell", "text": "98"},
                    ],
                ],
                "truncated": False,
            }
        )
        self.binding = SimpleNamespace(
            page_id="page-1",
            target=self.target,
            handle=self.handle,
            scene_target=SimpleNamespace(role=role, frame_id="main"),
        )
        self.revalidated = False

    def _session(self, session_id):
        if session_id != self.session.identity.session_id:
            raise RuntimeError("wrong session")
        return self.session

    def _scene_action_binding(self, session, target_id, *, page_id="", expected_target=None):
        if target_id != self.target.target_id:
            raise RuntimeError("unknown target")
        return self.binding

    def _scene_revalidate_binding(self, session, binding):
        self.revalidated = True


class BrowserSceneTableTests(unittest.TestCase):
    def test_extracts_bounded_rows_and_cells_from_exact_table(self):
        harness = _Harness()
        table = harness.observe_scene_table(
            harness.session.identity.session_id,
            harness.target.target_id,
            max_rows=10,
            max_cells_per_row=8,
            max_cell_text=64,
        )
        self.assertTrue(harness.revalidated)
        self.assertEqual(table.page_id, "page-1")
        self.assertEqual(table.target_id, harness.target.target_id)
        self.assertEqual(table.row_count_observed, 2)
        self.assertFalse(table.truncated)
        self.assertEqual(
            [[cell.text for cell in row.cells] for row in table.rows],
            [["Name", "Score"], ["Ada", "98"]],
        )
        self.assertEqual(table.rows[0].cells[0].kind, "header")
        self.assertEqual(
            harness.handle.calls,
            [{"maxRows": 10, "maxCells": 8, "maxText": 64}],
        )

    def test_caps_requested_limits_at_resident_bounds(self):
        harness = _Harness()
        harness.observe_scene_table(
            harness.session.identity.session_id,
            harness.target.target_id,
            max_rows=9999,
            max_cells_per_row=9999,
            max_cell_text=9999,
        )
        self.assertEqual(
            harness.handle.calls,
            [{"maxRows": 64, "maxCells": 32, "maxText": 512}],
        )

    def test_rejects_non_table_scene_target_before_provider_read(self):
        harness = _Harness(role="button")
        with self.assertRaisesRegex(RuntimeError, "table target"):
            harness.observe_scene_table(
                harness.session.identity.session_id,
                harness.target.target_id,
            )
        self.assertTrue(harness.revalidated)
        self.assertEqual(harness.handle.calls, [])

    def test_rejects_detached_or_unsupported_provider_evidence(self):
        for raw, expected in (
            ({"connected": False}, "detached"),
            ({"connected": True, "supported": False}, "native/ARIA table"),
        ):
            with self.subTest(raw=raw):
                harness = _Harness(raw=raw)
                with self.assertRaisesRegex(RuntimeError, expected):
                    harness.observe_scene_table(
                        harness.session.identity.session_id,
                        harness.target.target_id,
                    )

    def test_preserves_provider_truncation_signal(self):
        harness = _Harness(
            raw={
                "connected": True,
                "supported": True,
                "row_count_observed": 100,
                "rows": [[{"kind": "cell", "text": "bounded"}]],
                "truncated": True,
            }
        )
        table = harness.observe_scene_table(
            harness.session.identity.session_id,
            harness.target.target_id,
        )
        self.assertEqual(table.row_count_observed, 100)
        self.assertTrue(table.truncated)


if __name__ == "__main__":
    unittest.main(verbosity=2)
