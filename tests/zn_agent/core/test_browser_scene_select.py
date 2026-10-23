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
    def __init__(self):
        self.url = "https://example.com/form"

    def title(self):
        return "Form"


class _SelectHandle:
    def __init__(self, page, *, selected="before", on_select=None):
        self.page = page
        self.selected = selected
        self.on_select = on_select
        self.dispatches = 0

    def evaluate(self, expression):
        if "selectedOptions" in expression and "element.multiple" in expression:
            return {
                "connected": True,
                "supported": True,
                "disabled": False,
                "multiple": False,
                "selected": [self.selected],
            }
        raise AssertionError("unexpected evaluate expression")

    def select_option(self, *, value):
        self.dispatches += 1
        self.selected = value
        if self.on_select is not None:
            self.on_select(value)
        return [value]


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
    def __init__(self, *, permission, on_select=None):
        identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake",
        )
        self.page = _Page()
        self.handle = _SelectHandle(self.page, on_select=on_select)
        self.session = SimpleNamespace(
            identity=identity,
            permission=permission,
            pages={"page-1": self.page},
            default_page_id="page-1",
            last_observation={},
        )
        self.target = BrowserTarget(
            session_id=identity.session_id,
            page_id="page-1",
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id="scene-select-1",
            observed_at=utc_now(),
            url=self.page.url,
            frame_id="main",
            role="combobox",
            name="Region",
            selector_hint="browser_scene:combobox",
        )
        self.binding = SimpleNamespace(
            page_id="page-1",
            target=self.target,
            handle=self.handle,
            scene_target=SimpleNamespace(role="combobox", frame_id="main"),
        )

    def _session(self, session_id):
        return self.session

    def _validate_authority(self, session, action, authority):
        if authority.action_id != action.action_id:
            raise RuntimeError("wrong authority")
        if not authority.permission.allows_action(action.kind):
            raise RuntimeError(f"browser action is not permitted: {action.kind.value}")

    def _scene_action_binding(self, session, target_id, *, page_id="", expected_target=None):
        if expected_target != self.target:
            raise RuntimeError("target changed")
        return self.binding

    def _scene_revalidate_binding(self, session, binding):
        return None

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

    def _url_allowed(self, url, permission):
        return permission.allows_origin(url)

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


def _act(harness, *, value="after", expected=None):
    action = BrowserAction.create(
        session_id=harness.session.identity.session_id,
        page_id="page-1",
        kind=BrowserActionKind.SELECT_OPTION,
        target=harness.target,
        args={"value": value},
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


class BrowserSceneSelectTests(unittest.TestCase):
    def test_select_verifies_exact_scene_value_without_plaintext_evidence(self):
        permission = BrowserPermissionContext(
            allow_page_interaction=True,
            allowed_origins=("https://example.com",),
        )
        harness = _Harness(permission=permission)
        secret_value = "internal-region-code"
        evidence = _act(harness, value=secret_value)
        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(harness.handle.dispatches, 1)
        digest = hashlib.sha256(secret_value.encode("utf-8")).hexdigest()
        self.assertEqual(evidence.data["expected_value_sha256"], digest)
        self.assertEqual(evidence.data["selected_value_sha256_after"], digest)
        self.assertNotIn(secret_value, repr(evidence.data))
        self.assertEqual(evidence.postcondition, "same_scene_target_selected_value")

    def test_select_refuses_implicit_navigation(self):
        permission = BrowserPermissionContext(
            allow_page_interaction=True,
            allowed_origins=("https://example.com",),
        )
        harness = _Harness(permission=permission)
        harness.handle.on_select = lambda value: setattr(
            harness.page, "url", "https://example.com/changed"
        )
        evidence = _act(harness)
        self.assertFalse(evidence.success)
        self.assertIn("without an explicit url_equals", evidence.error or "")

    def test_select_navigation_requires_navigation_authority_and_exact_url(self):
        expected_url = "https://example.com/changed"
        denied = _Harness(
            permission=BrowserPermissionContext(
                allow_page_interaction=True,
                allowed_origins=("https://example.com",),
            )
        )
        denied.handle.on_select = lambda value: setattr(denied.page, "url", expected_url)
        evidence = _act(denied, expected={"url_equals": expected_url})
        self.assertFalse(evidence.success)
        self.assertIn("navigation permission", evidence.error or "")
        self.assertEqual(denied.handle.dispatches, 0)

        allowed = _Harness(
            permission=BrowserPermissionContext(
                allow_page_interaction=True,
                allow_navigation=True,
                allowed_origins=("https://example.com",),
            )
        )
        allowed.handle.on_select = lambda value: setattr(allowed.page, "url", expected_url)
        evidence = _act(allowed, expected={"url_equals": expected_url})
        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(evidence.url_after, expected_url)
        self.assertEqual(evidence.postcondition, "url_equals_after_exact_scene_select")

    def test_select_refuses_fresh_page_attribution(self):
        permission = BrowserPermissionContext(
            allow_page_interaction=True,
            allowed_origins=("https://example.com",),
        )
        harness = _Harness(permission=permission)

        def create_page(value):
            harness.session.pages["page-2"] = _Page()

        harness.handle.on_select = create_page
        evidence = _act(harness)
        self.assertFalse(evidence.success)
        self.assertIn("fresh page", evidence.error or "")
        self.assertEqual(evidence.data["new_page_ids"], ["page-2"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
