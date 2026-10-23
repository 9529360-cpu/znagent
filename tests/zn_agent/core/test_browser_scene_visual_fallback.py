from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

from zn_agent.core.browser import BrowserPermissionContext, BrowserPlane, BrowserSessionIdentity
from zn_agent.core.browser_scene_clear_press import PlaywrightBrowserSceneClearPressMixin
from zn_agent.core.managed_browser import ManagedBrowserError
from zn_agent.core.models import utc_now
from zn_agent.core.visual_ocr_sense import LocalOcrProviderResult, LocalOcrProviderWord


class _Page:
    def __init__(self):
        self.url = "https://example.com/start"
        self.viewport_size = {"width": 1000, "height": 800}
        self.screenshot_calls = []

    def screenshot(self, **kwargs):
        self.screenshot_calls.append(dict(kwargs))
        return b"png-bytes"


class _Base:
    pass


class _Harness(PlaywrightBrowserSceneClearPressMixin, _Base):
    def __init__(self, *, allow_sensitive=True):
        identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake",
        )
        self.page = _Page()
        self.session = SimpleNamespace(
            identity=identity,
            permission=BrowserPermissionContext(
                allow_sensitive_fields=allow_sensitive,
                allowed_origins=("https://example.com",),
            ),
            pages={"page-1": self.page},
            default_page_id="page-1",
        )
        self.scene_targets = []
        self.scene_frames = [
            SimpleNamespace(
                frame_id="main",
                observable=True,
                blocked_reason="",
            )
        ]
        self.scene_truncated = False
        self.ocr_calls = []
        self.ocr_result = LocalOcrProviderResult(
            language_tag="en-US",
            text="Canvas Login",
            words=(
                LocalOcrProviderWord("Canvas", 10, 20, 50, 20),
                LocalOcrProviderWord("Login", 70, 20, 40, 20),
            ),
        )
        self.after_scene = None

    def _session(self, session_id):
        return self.session

    def _default_page_id(self, session):
        return "page-1"

    def _page(self, session, page_id):
        return self.page

    @staticmethod
    def _require_url_allowed(url, permission):
        if not permission.allows_origin(url):
            raise RuntimeError("url outside authority")

    def observe_scene(self, session_id, *, page_id="", max_targets=64):
        scene = SimpleNamespace(
            scene_id="scene-1",
            session_id=session_id,
            page_id=page_id or "page-1",
            captured_at=utc_now(),
            url=self.page.url,
            targets=tuple(self.scene_targets),
            frames=tuple(self.scene_frames),
            truncated=self.scene_truncated,
        )
        if self.after_scene is not None:
            self.after_scene()
        return scene

    def _browser_local_ocr_provider(self, png_bytes):
        self.ocr_calls.append(png_bytes)
        return self.ocr_result


class BrowserSceneVisualFallbackTests(unittest.TestCase):
    def test_semantic_match_short_circuits_screenshot_and_ocr(self):
        harness = _Harness(allow_sensitive=False)
        harness.scene_targets = [
            SimpleNamespace(
                target_id="scene-button",
                role="button",
                accessible_name="Login",
            )
        ]
        observed = harness.observe_scene_or_local_ocr(
            harness.session.identity.session_id,
            semantic_role="button",
            accessible_name="Login",
            center_x_fraction=0.5,
            center_y_fraction=0.5,
        )
        self.assertEqual(observed.source, "browser_scene")
        self.assertEqual(observed.semantic_target_id, "scene-button")
        self.assertEqual(harness.page.screenshot_calls, [])
        self.assertEqual(harness.ocr_calls, [])

    def test_zero_semantic_match_falls_back_to_in_memory_local_ocr(self):
        harness = _Harness()
        observed = harness.observe_scene_or_local_ocr(
            harness.session.identity.session_id,
            semantic_role="button",
            accessible_name="Login",
            center_x_fraction=0.5,
            center_y_fraction=0.5,
            width_fraction=0.2,
            height_fraction=0.2,
        )
        self.assertEqual(observed.source, "browser_local_ocr")
        self.assertEqual(observed.text, "Canvas Login")
        self.assertFalse(observed.raw_frame_persisted)
        self.assertEqual(harness.ocr_calls, [b"png-bytes"])
        self.assertEqual(len(harness.page.screenshot_calls), 1)
        call = harness.page.screenshot_calls[0]
        self.assertEqual(call["type"], "png")
        self.assertEqual(call["scale"], "css")
        self.assertEqual(
            call["clip"],
            {"x": 400.0, "y": 320.0, "width": 200.0, "height": 160.0},
        )
        self.assertEqual(
            (observed.words[0].left, observed.words[0].top),
            (410.0, 340.0),
        )

    def test_ocr_fallback_requires_explicit_sensitive_read_permission(self):
        harness = _Harness(allow_sensitive=False)
        with self.assertRaisesRegex(ManagedBrowserError, "allow_sensitive_fields"):
            harness.observe_scene_or_local_ocr(
                harness.session.identity.session_id,
                semantic_role="button",
                accessible_name="Login",
                center_x_fraction=0.5,
                center_y_fraction=0.5,
            )
        self.assertEqual(harness.page.screenshot_calls, [])
        self.assertEqual(harness.ocr_calls, [])

    def test_truncated_scene_never_uses_zero_match_as_fallback_authority(self):
        harness = _Harness()
        harness.scene_truncated = True
        with self.assertRaisesRegex(ManagedBrowserError, "truncated"):
            harness.observe_scene_or_local_ocr(
                harness.session.identity.session_id,
                semantic_role="button",
                accessible_name="Login",
                center_x_fraction=0.5,
                center_y_fraction=0.5,
            )
        self.assertEqual(harness.page.screenshot_calls, [])

    def test_unobservable_frame_pixels_keep_cross_origin_boundary_fail_closed(self):
        harness = _Harness()
        harness.scene_frames.append(
            SimpleNamespace(
                frame_id="frame-2",
                observable=False,
                blocked_reason="cross-origin frame is fail-closed for semantic BrowserScene",
            )
        )
        with self.assertRaisesRegex(ManagedBrowserError, "unobservable frame"):
            harness.observe_scene_or_local_ocr(
                harness.session.identity.session_id,
                semantic_role="button",
                accessible_name="Login",
                center_x_fraction=0.5,
                center_y_fraction=0.5,
            )
        self.assertEqual(harness.page.screenshot_calls, [])

    def test_semantic_ambiguity_never_falls_back_to_pixels(self):
        harness = _Harness()
        harness.scene_targets = [
            SimpleNamespace(target_id="a", role="button", accessible_name="Login"),
            SimpleNamespace(target_id="b", role="button", accessible_name="Login"),
        ]
        with self.assertRaisesRegex(ManagedBrowserError, "ambiguous"):
            harness.observe_scene_or_local_ocr(
                harness.session.identity.session_id,
                semantic_role="button",
                accessible_name="Login",
                center_x_fraction=0.5,
                center_y_fraction=0.5,
            )
        self.assertEqual(harness.page.screenshot_calls, [])

    def test_page_drift_between_scene_and_capture_forces_reground(self):
        harness = _Harness()
        harness.after_scene = lambda: setattr(
            harness.page,
            "url",
            "https://example.com/changed",
        )
        with self.assertRaisesRegex(ManagedBrowserError, "changed after semantic scene"):
            harness.observe_scene_or_local_ocr(
                harness.session.identity.session_id,
                semantic_role="button",
                accessible_name="Login",
                center_x_fraction=0.5,
                center_y_fraction=0.5,
            )
        self.assertEqual(harness.page.screenshot_calls, [])

    def test_invalid_ocr_box_is_rejected_not_silently_clamped(self):
        harness = _Harness()
        harness.ocr_result = LocalOcrProviderResult(
            language_tag="en-US",
            text="Bad",
            words=(LocalOcrProviderWord("Bad", math.nan, 0, 10, 10),),
        )
        with self.assertRaisesRegex(ManagedBrowserError, "finite"):
            harness.observe_scene_or_local_ocr(
                harness.session.identity.session_id,
                semantic_role="button",
                accessible_name="Login",
                center_x_fraction=0.5,
                center_y_fraction=0.5,
            )


if __name__ == "__main__":
    unittest.main()
