from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
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
        self.url = "https://example.com/start"


class _Handle:
    def __init__(self, harness):
        self.harness = harness
        self.click_calls = 0

    def click(self):
        self.click_calls += 1
        if self.harness.on_click is not None:
            self.harness.on_click()


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
    def __init__(self, *, permission=None):
        identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake",
        )
        self.page = _Page()
        self.on_click = None
        self.invalidated = []
        self.truncated_before = False
        self.truncated_after = False
        self.row_present = True
        self.session = SimpleNamespace(
            identity=identity,
            permission=permission or BrowserPermissionContext(allow_page_interaction=True),
            pages={"page-1": self.page},
            default_page_id="page-1",
            last_observation={},
        )
        self.target = BrowserTarget(
            session_id=identity.session_id,
            page_id="page-1",
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id="delete-button",
            observed_at=utc_now(),
            url=self.page.url,
            frame_id="main",
            role="button",
            name="Delete",
            selector_hint="browser_scene:button",
        )
        self.handle = _Handle(self)
        self.binding = SimpleNamespace(
            page_id="page-1",
            target=self.target,
            handle=self.handle,
            scene_target=SimpleNamespace(role="button", frame_id="main"),
        )

    def _row_target(self):
        return SimpleNamespace(
            target_id="row-1",
            role="row",
            accessible_name="Invoice 42",
        )

    def _scene_state(self, session):
        targets = (self._row_target(),) if self.row_present else ()
        scene = SimpleNamespace(
            truncated=self.truncated_before,
            targets=targets,
        )
        return SimpleNamespace(
            page_scenes={
                "page-1": SimpleNamespace(scene=scene),
            }
        )

    def observe_scene(self, session_id, *, page_id=""):
        targets = (self._row_target(),) if self.row_present else ()
        return SimpleNamespace(
            scene_id="fresh-scene",
            captured_at=utc_now(),
            truncated=self.truncated_after,
            targets=targets,
        )

    def _session(self, session_id):
        return self.session

    def _validate_authority(self, session, action, authority):
        if not authority.permission.allows_action(action.kind):
            raise RuntimeError("not permitted")

    def _scene_action_binding(self, session, target_id, *, page_id="", expected_target=None):
        return self.binding

    def _scene_revalidate_binding(self, session, binding):
        return None

    def _page(self, session, page_id):
        return self.page

    def _scene_failed_mutation(self, session, page_id):
        self.invalidated.append(("failed", page_id))

    def _scene_invalidate_page(self, session_id, page_id):
        self.invalidated.append(("invalidate", page_id))

    def _reconcile_pages(self, session):
        return None

    @staticmethod
    def _url_allowed(url, permission):
        return permission.allows_origin(url)

    @staticmethod
    def _require_url_allowed(url, permission):
        if not permission.allows_origin(url):
            raise RuntimeError("url outside authority")

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


def _act(harness, *, expected, args=None):
    action = BrowserAction.create(
        session_id=harness.session.identity.session_id,
        page_id="page-1",
        kind=BrowserActionKind.CLICK,
        target=harness.target,
        expected=expected,
        args=args,
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


class BrowserSceneCommandTests(unittest.TestCase):
    def test_command_succeeds_only_when_unique_target_disappears(self):
        harness = _Harness()
        harness.on_click = lambda: setattr(harness, "row_present", False)
        evidence = _act(
            harness,
            expected={
                "target_absent_equals": {
                    "role": "row",
                    "accessible_name": "Invoice 42",
                }
            },
        )
        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(harness.handle.click_calls, 1)
        self.assertEqual(evidence.data["matching_target_count_before"], 1)
        self.assertEqual(evidence.data["matching_target_count_after"], 0)
        self.assertNotIn("Invoice 42", repr(evidence.data))

    def test_command_fails_when_target_remains(self):
        harness = _Harness()
        evidence = _act(
            harness,
            expected={
                "target_absent_equals": {
                    "role": "row",
                    "accessible_name": "Invoice 42",
                }
            },
        )
        self.assertFalse(evidence.success)
        self.assertIn("remained", evidence.error or "")

    def test_command_refuses_truncated_current_or_fresh_scene(self):
        current = _Harness()
        current.truncated_before = True
        evidence = _act(
            current,
            expected={
                "target_absent_equals": {
                    "role": "row",
                    "accessible_name": "Invoice 42",
                }
            },
        )
        self.assertFalse(evidence.success)
        self.assertIn("non-truncated", evidence.error or "")
        self.assertEqual(current.handle.click_calls, 0)

        fresh = _Harness()
        fresh.truncated_after = True
        fresh.on_click = lambda: setattr(fresh, "row_present", False)
        evidence = _act(
            fresh,
            expected={
                "target_absent_equals": {
                    "role": "row",
                    "accessible_name": "Invoice 42",
                }
            },
        )
        self.assertFalse(evidence.success)
        self.assertIn("truncated fresh scene", evidence.error or "")

    def test_command_requires_page_interaction_authority(self):
        harness = _Harness(permission=BrowserPermissionContext())
        evidence = _act(
            harness,
            expected={
                "target_absent_equals": {
                    "role": "row",
                    "accessible_name": "Invoice 42",
                }
            },
        )
        self.assertFalse(evidence.success)
        self.assertIn("not permitted", evidence.error or "")

    def test_command_rejects_extra_expectations_and_provider_args(self):
        harness = _Harness()
        evidence = _act(
            harness,
            expected={
                "target_absent_equals": {
                    "role": "row",
                    "accessible_name": "Invoice 42",
                },
                "url_equals": "https://example.com/done",
            },
        )
        self.assertFalse(evidence.success)
        self.assertIn("exactly target_absent_equals", evidence.error or "")

        evidence = _act(
            harness,
            expected={
                "target_absent_equals": {
                    "role": "row",
                    "accessible_name": "Invoice 42",
                }
            },
            args={"position": {"x": 1, "y": 1}},
        )
        self.assertFalse(evidence.success)
        self.assertIn("coordinates", evidence.error or "")


if __name__ == "__main__":
    unittest.main()
