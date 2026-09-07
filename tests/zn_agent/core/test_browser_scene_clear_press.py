from __future__ import annotations

import hashlib
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
        self.title_value = "Page"

    def title(self):
        return self.title_value


class _Handle:
    def __init__(self, value, on_press=None):
        self.value = value
        self.on_press = on_press

    def fill(self, value):
        self.value = str(value)

    def press(self, key):
        if self.on_press is not None:
            self.on_press(key)


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
    def __init__(self, *, permission, role="searchbox", value="query"):
        identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake",
        )
        self.page = _Page("https://example.com/search")
        self.handle = _Handle(value)
        self.session = SimpleNamespace(
            identity=identity,
            permission=permission,
            pages={"page-1": self.page},
            default_page_id="page-1",
            last_observation={},
        )
        self.role = role
        self.target = BrowserTarget(
            session_id=identity.session_id,
            page_id="page-1",
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id="scene-1",
            observed_at=utc_now(),
            url=self.page.url,
            frame_id="main",
            role=role,
            name="Search",
            selector_hint="browser_scene:scene-1",
        )
        self.binding = SimpleNamespace(
            page_id="page-1",
            target=self.target,
            handle=self.handle,
            scene_target=SimpleNamespace(role=role, frame_id="main"),
        )

    def _session(self, session_id):
        return self.session

    def _validate_authority(self, session, action, authority):
        if authority.action_id != action.action_id:
            raise RuntimeError("wrong authority")
        if not authority.permission.allows_action(action.kind):
            raise RuntimeError(f"browser action is not permitted: {action.kind.value}")

    def _scene_action_binding(self, session, target_id, *, page_id="", expected_target=None):
        if expected_target != self.binding.target:
            raise RuntimeError("target changed")
        return self.binding

    def _scene_revalidate_binding(self, session, binding):
        return None

    def _scene_text_state(self, handle):
        value = handle.value
        return {
            "text_length": len(value),
            "text_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        }

    def _scene_post_target_observation(self, session, binding):
        return BrowserObservation(
            session=session.identity,
            page_id="page-1",
            captured_at=utc_now(),
            url=self.page.url,
            title=self.page.title(),
            load_state="complete",
            target=binding.target,
        )

    def _scene_failed_mutation(self, session, page_id):
        return None

    def _scene_invalidate_page(self, session_id, page_id):
        return None

    def _page(self, session, page_id):
        return session.pages[page_id]

    def _reconcile_pages(self, session):
        return None

    def _capture(self, session, page_id):
        return BrowserObservation(
            session=session.identity,
            page_id=page_id,
            captured_at=utc_now(),
            url=self.page.url,
            title=self.page.title(),
            load_state="complete",
        )

    def _require_url_allowed(self, url, permission):
        if not permission.allows_origin(url):
            raise RuntimeError("url outside authority")

    def _failure(self, action, *, error):
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=False,
            page_id=action.page_id,
            target_id=action.target.target_id,
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


class BrowserSceneClearPressTests(unittest.TestCase):
    def test_clear_requires_text_entry_authority_and_verifies_empty_value(self):
        permission = BrowserPermissionContext(
            allow_page_interaction=True,
            allow_text_entry=True,
            allowed_origins=("https://example.com",),
        )
        harness = _Harness(permission=permission, value="privacy query")
        evidence = _act(harness, BrowserActionKind.CLEAR)
        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(harness.handle.value, "")
        self.assertEqual(evidence.data["text_length_after"], 0)
        self.assertNotIn("privacy query", repr(evidence.data))
        self.assertEqual(evidence.postcondition, "same_scene_target_text_empty")

        denied = _Harness(
            permission=BrowserPermissionContext(allow_page_interaction=True),
            value="query",
        )
        evidence = _act(denied, BrowserActionKind.CLEAR)
        self.assertFalse(evidence.success)
        self.assertIn("not permitted", evidence.error or "")
        self.assertEqual(denied.handle.value, "query")

    def test_enter_requires_navigation_authority_and_explicit_url_postcondition(self):
        permission = BrowserPermissionContext(
            allow_page_interaction=True,
            allow_navigation=True,
            allowed_origins=("https://example.com",),
        )
        harness = _Harness(permission=permission)

        def on_press(key):
            self.assertEqual(key, "Enter")
            harness.page.url = "https://example.com/results"

        harness.handle.on_press = on_press
        evidence = _act(
            harness,
            BrowserActionKind.PRESS,
            args={"key": "Enter"},
            expected={"url_equals": "https://example.com/results"},
        )
        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(
            evidence.postcondition,
            "same_page_url_equals_after_exact_scene_enter",
        )

        denied = _Harness(
            permission=BrowserPermissionContext(allow_page_interaction=True),
        )
        evidence = _act(
            denied,
            BrowserActionKind.PRESS,
            args={"key": "Enter"},
            expected={"url_equals": "https://example.com/results"},
        )
        self.assertFalse(evidence.success)
        self.assertIn("navigation permission", evidence.error or "")

    def test_press_rejects_arbitrary_keys_and_textarea_enter(self):
        permission = BrowserPermissionContext(
            allow_page_interaction=True,
            allow_navigation=True,
        )
        harness = _Harness(permission=permission)
        evidence = _act(
            harness,
            BrowserActionKind.PRESS,
            args={"key": "Control+L"},
            expected={"url_equals": "https://example.com/results"},
        )
        self.assertFalse(evidence.success)
        self.assertIn("only accepts the exact Enter key", evidence.error or "")

        textarea = _Harness(permission=permission, role="textarea")
        evidence = _act(
            textarea,
            BrowserActionKind.PRESS,
            args={"key": "Enter"},
            expected={"url_equals": "https://example.com/results"},
        )
        self.assertFalse(evidence.success)
        self.assertIn("textbox/searchbox only", evidence.error or "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
