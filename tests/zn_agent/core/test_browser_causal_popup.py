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
from zn_agent.core.browser_causal_popup import PlaywrightBrowserCausalPopupMixin
from zn_agent.core.models import utc_now


class _PopupInfo:
    def __init__(self, opener):
        self._opener = opener
        self.value = None

    def __enter__(self):
        self._opener._active_popup_info = self
        return self

    def __exit__(self, exc_type, exc, tb):
        self._opener._active_popup_info = None
        return False


class _Page:
    def __init__(self, url, *, title="Page", opener=None):
        self.url = url
        self._title = title
        self._opener = opener
        self.closed = False
        self._active_popup_info = None

    def title(self):
        return self._title

    def evaluate(self, expression):
        if expression == "document.readyState":
            return "complete"
        if expression == "document.visibilityState":
            return "visible"
        raise AssertionError(expression)

    def expect_popup(self):
        return _PopupInfo(self)

    def opener(self):
        return self._opener

    def wait_for_url(self, expected_url, *, wait_until):
        if self.url != expected_url:
            raise RuntimeError(f"expected {expected_url}, got {self.url}")

    def close(self):
        self.closed = True

    def is_closed(self):
        return self.closed


class _ClickHandle:
    def __init__(self, callback):
        self.callback = callback

    def click(self):
        self.callback()


class _HarnessBase:
    def act(self, action, authority):
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=False,
            page_id=action.page_id,
            postcondition="delegated",
            error="delegated",
        )


class _Harness(PlaywrightBrowserCausalPopupMixin, _HarnessBase):
    def __init__(self, opener, permission):
        identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake",
        )
        self.context_pages = [opener]
        self.ownership = {"page-1": "zn_created"}
        self.session = SimpleNamespace(
            identity=identity,
            permission=permission,
            pages={"page-1": opener},
            default_page_id="page-1",
            next_page_sequence=2,
            last_observation={},
        )
        self.binding = None

    def _session(self, session_id):
        if session_id != self.session.identity.session_id:
            raise RuntimeError("wrong session")
        return self.session

    def _validate_authority(self, session, action, authority):
        if authority.action_id != action.action_id:
            raise RuntimeError("wrong authority")
        if not authority.permission.allow_page_interaction:
            raise RuntimeError("interaction denied")

    def _scene_action_binding(self, session, target_id, *, page_id="", expected_target=None):
        if self.binding is None:
            raise RuntimeError("missing binding")
        if expected_target is not None and self.binding.target != expected_target:
            raise RuntimeError("target changed")
        return self.binding

    def _scene_revalidate_binding(self, session, binding):
        return None

    def _scene_failed_mutation(self, session, page_id):
        return None

    def _scene_invalidate_page(self, session_id, page_id):
        return None

    def _refresh_page_observation_after_failed_mutation(self, session, page_id):
        return None

    def _page(self, session, page_id):
        return session.pages[page_id]

    def _register_page(self, session, page):
        for page_id, existing in session.pages.items():
            if existing is page:
                return page_id
        page_id = f"page-{session.next_page_sequence}"
        session.next_page_sequence += 1
        session.pages[page_id] = page
        return page_id

    def _reconcile_pages(self, session):
        live = [page for page in self.context_pages if not page.closed]
        for page in live:
            self._register_page(session, page)
        for page_id, page in tuple(session.pages.items()):
            if page not in live or page.closed:
                session.pages.pop(page_id, None)
                session.last_observation.pop(page_id, None)
        if session.default_page_id not in session.pages and session.pages:
            session.default_page_id = next(iter(session.pages))

    def _mark_zn_created_page(self, session, page_id):
        self.ownership[page_id] = "zn_created"

    def _forget_page_ownership(self, session, page_id):
        self.ownership.pop(page_id, None)

    def _require_url_allowed(self, url, permission):
        if not self._url_allowed(url, permission):
            raise RuntimeError("url outside authority")

    @staticmethod
    def _url_allowed(url, permission):
        return permission.allows_origin(url)

    def _capture(self, session, page_id):
        page = session.pages[page_id]
        observation = BrowserObservation(
            session=session.identity,
            page_id=page_id,
            captured_at=utc_now(),
            url=page.url,
            title=page.title(),
            load_state="complete",
        )
        session.last_observation[page_id] = observation
        return observation

    def _failure(self, action, *, error):
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=False,
            page_id=action.page_id,
            target_id=action.target.target_id if action.target else "",
            postcondition="",
            error=error,
        )


def _authorized_popup_action(harness, handle, *, expected_url):
    target = BrowserTarget(
        session_id=harness.session.identity.session_id,
        page_id="page-1",
        kind=BrowserTargetKind.ACCESSIBILITY_NODE,
        target_id="scene-target-1",
        observed_at=utc_now(),
        url=harness.session.pages["page-1"].url,
        frame_id="main",
        role="link",
        name="Open",
        selector_hint="browser_scene:scene-target-1",
    )
    harness.binding = SimpleNamespace(
        page_id="page-1",
        target=target,
        handle=handle,
        scene_target=SimpleNamespace(role="link", frame_id="main"),
    )
    action = BrowserAction.create(
        session_id=harness.session.identity.session_id,
        page_id="page-1",
        kind=BrowserActionKind.CLICK,
        target=target,
        expected={"popup_url_equals": expected_url},
    )
    authority = BrowserActionAuthority(
        action_id=action.action_id,
        session_id=action.session_id,
        issued_at=utc_now(),
        observation_captured_at=target.observed_at,
        permission=harness.session.permission,
        target_id=target.target_id,
        page_id="page-1",
    )
    return action, authority


class BrowserCausalPopupTests(unittest.TestCase):
    def test_exact_click_binds_one_fresh_popup_and_preserves_default_page(self):
        opener = _Page("https://example.com/start", title="Start")
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allowed_origins=("https://example.com",),
        )
        harness = _Harness(opener, permission)
        popup = _Page("https://example.com/popup", title="Popup", opener=opener)

        def click():
            harness.context_pages.append(popup)
            opener._active_popup_info.value = popup

        action, authority = _authorized_popup_action(
            harness,
            _ClickHandle(click),
            expected_url=popup.url,
        )
        evidence = harness.act(action, authority)

        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(evidence.postcondition, "causal_popup_opener_and_url_verified")
        self.assertEqual(evidence.data["opener_page_id"], "page-1")
        self.assertEqual(evidence.data["popup_page_id"], "page-2")
        self.assertEqual(evidence.data["new_page_ids"], ["page-2"])
        self.assertEqual(harness.session.default_page_id, "page-1")
        self.assertEqual(harness.ownership["page-2"], "zn_created")

    def test_popup_with_wrong_opener_is_closed_and_fails(self):
        opener = _Page("https://example.com/start")
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allowed_origins=("https://example.com",),
        )
        harness = _Harness(opener, permission)
        other = _Page("https://example.com/other")
        popup = _Page("https://example.com/popup", opener=other)

        def click():
            harness.context_pages.append(popup)
            opener._active_popup_info.value = popup

        action, authority = _authorized_popup_action(
            harness,
            _ClickHandle(click),
            expected_url=popup.url,
        )
        evidence = harness.act(action, authority)

        self.assertFalse(evidence.success)
        self.assertIn("opener identity", evidence.error or "")
        self.assertTrue(popup.closed)
        self.assertNotIn("page-2", harness.session.pages)
        self.assertEqual(harness.session.default_page_id, "page-1")

    def test_popup_outside_authorized_origin_is_closed(self):
        opener = _Page("https://example.com/start")
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allowed_origins=("https://example.com",),
        )
        harness = _Harness(opener, permission)
        popup = _Page("https://evil.example/popup", opener=opener)

        def click():
            harness.context_pages.append(popup)
            opener._active_popup_info.value = popup

        action, authority = _authorized_popup_action(
            harness,
            _ClickHandle(click),
            expected_url="https://example.com/expected",
        )
        popup.url = "https://evil.example/popup"
        evidence = harness.act(action, authority)

        self.assertFalse(evidence.success)
        self.assertIn("permitted browser boundary", evidence.error or "")
        self.assertTrue(popup.closed)
        self.assertEqual(harness.session.default_page_id, "page-1")

    def test_multiple_new_pages_are_ambiguous_not_guessed(self):
        opener = _Page("https://example.com/start")
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allowed_origins=("https://example.com",),
        )
        harness = _Harness(opener, permission)
        popup = _Page("https://example.com/popup", opener=opener)
        extra = _Page("https://example.com/extra", opener=opener)

        def click():
            harness.context_pages.extend([popup, extra])
            opener._active_popup_info.value = popup

        action, authority = _authorized_popup_action(
            harness,
            _ClickHandle(click),
            expected_url=popup.url,
        )
        evidence = harness.act(action, authority)

        self.assertFalse(evidence.success)
        self.assertIn("ambiguous new-page set", evidence.error or "")
        self.assertEqual(set(evidence.data["new_page_ids"]), {"page-2", "page-3"})
        self.assertEqual(harness.session.default_page_id, "page-1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
