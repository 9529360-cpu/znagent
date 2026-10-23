from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
    BrowserObservation,
    BrowserPermissionContext,
    BrowserPlane,
    BrowserSessionIdentity,
    BrowserTarget,
    BrowserTargetKind,
)
from zn_agent.core.browser_scene_clear_press import PlaywrightBrowserSceneClearPressMixin
from zn_agent.core.models import utc_now


class _Page:
    def __init__(self, url):
        self.url = url

    def title(self):
        return "Page"


class _Handle:
    def __init__(self):
        self.intersects = False
        self.hovered = False
        self.connected = True
        self.on_scroll = None
        self.on_hover = None
        self.scroll_calls = 0
        self.hover_calls = 0

    def scroll_into_view_if_needed(self):
        self.scroll_calls += 1
        self.intersects = True
        if self.on_scroll is not None:
            self.on_scroll()

    def hover(self):
        self.hover_calls += 1
        self.intersects = True
        self.hovered = True
        if self.on_hover is not None:
            self.on_hover()

    def evaluate(self, script, *args):
        if "matches(':hover')" in script:
            return self.hovered and self.connected
        return {
            "connected": self.connected,
            "width": 120,
            "height": 30,
            "left": 0 if self.intersects else 0,
            "top": 10 if self.intersects else 1200,
            "right": 120,
            "bottom": 40 if self.intersects else 1230,
            "viewport_width": 800,
            "viewport_height": 600,
            "intersects": self.intersects,
            "center_in_viewport": self.intersects,
        }


class _Base:
    def act(self, action, authority):
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=False,
            error="delegated",
        )


class _Harness(PlaywrightBrowserSceneClearPressMixin, _Base):
    def __init__(self, *, permission):
        identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake",
        )
        self.page = _Page("https://example.com/start")
        self.handle = _Handle()
        self.context_pages = [self.page]
        self.invalidated = []
        self.session = SimpleNamespace(
            identity=identity,
            permission=permission,
            pages={"page-1": self.page},
            default_page_id="page-1",
            next_page_sequence=2,
            last_observation={},
        )
        self.target = BrowserTarget(
            session_id=identity.session_id,
            page_id="page-1",
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id="scene-1",
            observed_at=utc_now(),
            url=self.page.url,
            frame_id="main",
            role="button",
            name="Menu",
            selector_hint="browser_scene:scene-1",
        )
        self.binding = SimpleNamespace(
            page_id="page-1",
            target=self.target,
            handle=self.handle,
            scene_target=SimpleNamespace(role="button", frame_id="main"),
        )

    def _session(self, session_id):
        if session_id != self.session.identity.session_id:
            raise RuntimeError("wrong session")
        return self.session

    def _validate_authority(self, session, action, authority):
        if authority.action_id != action.action_id:
            raise RuntimeError("wrong authority")
        if not authority.permission.allows_action(action.kind):
            raise RuntimeError(f"browser action is not permitted: {action.kind.value}")

    def _scene_action_binding(self, session, target_id, *, page_id="", expected_target=None):
        if target_id != self.target.target_id:
            raise RuntimeError("wrong target")
        if expected_target is not None and expected_target != self.target:
            raise RuntimeError("target changed")
        return self.binding

    def _scene_revalidate_binding(self, session, binding):
        if not self.handle.connected:
            raise RuntimeError("stale target")

    def _scene_post_target_observation(self, session, binding):
        return BrowserObservation(
            session=session.identity,
            page_id=binding.page_id,
            captured_at=utc_now(),
            url=self.page.url,
            title="Page",
            load_state="complete",
            target=binding.target,
        )

    def _scene_failed_mutation(self, session, page_id):
        self.invalidated.append(("failed", page_id))

    def _scene_invalidate_page(self, session_id, page_id):
        self.invalidated.append(("invalidate", page_id))

    def _page(self, session, page_id):
        return session.pages[page_id]

    def _register_page(self, page):
        page_id = f"page-{self.session.next_page_sequence}"
        self.session.next_page_sequence += 1
        self.session.pages[page_id] = page
        return page_id

    def _reconcile_pages(self, session):
        for page in self.context_pages:
            if page not in session.pages.values():
                self._register_page(page)

    def _require_url_allowed(self, url, permission):
        if not permission.allows_origin(url):
            raise RuntimeError("url outside authority")

    @staticmethod
    def _url_allowed(url, permission):
        return permission.allows_origin(url)

    def _failure(self, action, *, error):
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=False,
            page_id=action.page_id,
            target_id=action.target.target_id if action.target else "",
            error=error,
        )


def _act(harness, kind, *, args=None, expected=None):
    action = BrowserAction.create(
        session_id=harness.session.identity.session_id,
        page_id="page-1",
        kind=kind,
        target=harness.target,
        args=args,
        expected=expected,
    )
    authority = BrowserActionAuthority(
        action_id=action.action_id,
        session_id=action.session_id,
        issued_at=utc_now(),
        observation_captured_at=harness.target.observed_at,
        permission=harness.session.permission,
        target_id=harness.target.target_id,
        page_id="page-1",
    )
    return harness.act(action, authority)


class BrowserScenePointerTests(unittest.TestCase):
    def test_scroll_into_view_is_target_scoped_and_invalidates_scene_after_proof(self):
        harness = _Harness(
            permission=BrowserPermissionContext(
                allow_page_interaction=True,
                allowed_origins=("https://example.com",),
            )
        )
        evidence = _act(harness, BrowserActionKind.SCROLL_INTO_VIEW)

        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(harness.handle.scroll_calls, 1)
        self.assertTrue(evidence.data["viewport_after"]["intersects"])
        self.assertEqual(
            evidence.postcondition,
            "same_scene_target_intersects_viewport_after_scroll",
        )
        self.assertIn(("invalidate", "page-1"), harness.invalidated)

    def test_hover_requires_real_hover_state(self):
        harness = _Harness(
            permission=BrowserPermissionContext(allow_page_interaction=True)
        )
        evidence = _act(harness, BrowserActionKind.HOVER)
        self.assertTrue(evidence.success, evidence.error)
        self.assertTrue(evidence.data["hovered"])
        self.assertEqual(evidence.postcondition, "same_scene_target_hovered")

        failed = _Harness(
            permission=BrowserPermissionContext(allow_page_interaction=True)
        )

        def clear_hover():
            failed.handle.hovered = False

        failed.handle.on_hover = clear_hover
        evidence = _act(failed, BrowserActionKind.HOVER)
        self.assertFalse(evidence.success)
        self.assertIn("hover state", evidence.error or "")

    def test_pointer_actions_require_page_interaction_authority(self):
        harness = _Harness(permission=BrowserPermissionContext())
        evidence = _act(harness, BrowserActionKind.HOVER)
        self.assertFalse(evidence.success)
        self.assertIn("not permitted", evidence.error or "")
        self.assertEqual(harness.handle.hover_calls, 0)

    def test_pointer_action_rejects_url_change(self):
        harness = _Harness(
            permission=BrowserPermissionContext(
                allow_page_interaction=True,
                allowed_origins=("https://example.com",),
            )
        )

        def navigate():
            harness.page.url = "https://example.com/changed"

        harness.handle.on_hover = navigate
        evidence = _act(harness, BrowserActionKind.HOVER)
        self.assertFalse(evidence.success)
        self.assertIn("changed page URL", evidence.error or "")
        self.assertIn(("invalidate", "page-1"), harness.invalidated)

    def test_pointer_action_does_not_claim_or_close_fresh_page(self):
        harness = _Harness(
            permission=BrowserPermissionContext(allow_page_interaction=True)
        )
        extra = _Page("https://example.com/extra")

        def open_extra():
            harness.context_pages.append(extra)

        harness.handle.on_scroll = open_extra
        evidence = _act(harness, BrowserActionKind.SCROLL_INTO_VIEW)
        self.assertFalse(evidence.success)
        self.assertIn("fresh page", evidence.error or "")
        self.assertEqual(evidence.data["new_page_ids"], ["page-2"])
        self.assertIn("page-2", harness.session.pages)
        self.assertFalse(hasattr(extra, "closed"))

    def test_pointer_first_slice_rejects_provider_specific_args_and_expected(self):
        harness = _Harness(
            permission=BrowserPermissionContext(allow_page_interaction=True)
        )
        evidence = _act(
            harness,
            BrowserActionKind.SCROLL_INTO_VIEW,
            args={"pixels": 500},
        )
        self.assertFalse(evidence.success)
        self.assertIn("provider-specific args", evidence.error or "")

        evidence = _act(
            harness,
            BrowserActionKind.HOVER,
            expected={"url_equals": "https://example.com/start"},
        )
        self.assertFalse(evidence.success)
        self.assertIn("navigation postconditions", evidence.error or "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
