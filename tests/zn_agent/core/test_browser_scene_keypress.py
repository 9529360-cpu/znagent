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
        self.focused = True
        self.press_calls = []

    def press(self, key):
        self.press_calls.append(key)
        if key == "Tab":
            self.focused = False
        if self.harness.on_press is not None:
            self.harness.on_press(key)

    def evaluate(self, script):
        return self.focused


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
    def __init__(self, *, trigger_role="textbox"):
        identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake",
        )
        self.page = _Page()
        self.on_press = None
        self.current_truncated = False
        self.fresh_truncated = False
        self.expected_targets = []
        self.session = SimpleNamespace(
            identity=identity,
            permission=BrowserPermissionContext(allow_page_interaction=True),
            pages={"page-1": self.page},
            default_page_id="page-1",
            last_observation={},
        )
        self.target = BrowserTarget(
            session_id=identity.session_id,
            page_id="page-1",
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id="trigger",
            observed_at=utc_now(),
            url=self.page.url,
            frame_id="main",
            role=trigger_role,
            name="Trigger",
            selector_hint=f"browser_scene:{trigger_role}",
        )
        self.handle = _Handle(self)
        self.binding = SimpleNamespace(
            page_id="page-1",
            target=self.target,
            handle=self.handle,
            scene_target=SimpleNamespace(role=trigger_role, frame_id="main"),
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

    def _scene_state(self, session):
        scene = SimpleNamespace(
            truncated=self.current_truncated,
            targets=tuple(self.expected_targets),
        )
        return SimpleNamespace(page_scenes={"page-1": SimpleNamespace(scene=scene)})

    def observe_scene(self, session_id, *, page_id="", max_targets=64):
        return SimpleNamespace(
            scene_id="fresh",
            captured_at=utc_now(),
            truncated=self.fresh_truncated,
            targets=tuple(self.expected_targets),
        )

    def _page(self, session, page_id):
        return self.page

    def _reconcile_pages(self, session):
        return None

    def _scene_failed_mutation(self, session, page_id):
        return None

    def _scene_invalidate_page(self, session_id, page_id):
        return None

    @staticmethod
    def _require_url_allowed(url, permission):
        if not permission.allows_origin(url):
            raise RuntimeError("outside authority")

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


def _act(harness, key, *, expected):
    action = BrowserAction.create(
        session_id=harness.session.identity.session_id,
        page_id="page-1",
        kind=BrowserActionKind.PRESS,
        target=harness.target,
        args={"key": key},
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


class BrowserSceneKeypressTests(unittest.TestCase):
    def test_tab_proves_exact_target_blurred(self):
        harness = _Harness(trigger_role="textbox")
        evidence = _act(
            harness,
            "Tab",
            expected={"target_blurred_equals": True},
        )
        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(harness.handle.press_calls, ["Tab"])
        self.assertFalse(evidence.data["focused_after"])

    def test_arbitrary_chord_remains_refused(self):
        harness = _Harness(trigger_role="textbox")
        evidence = _act(
            harness,
            "Control+L",
            expected={"target_blurred_equals": True},
        )
        self.assertFalse(evidence.success)
        self.assertIn("accepts only", evidence.error or "")
        self.assertEqual(harness.handle.press_calls, [])

    def test_escape_succeeds_only_when_unique_named_target_disappears(self):
        harness = _Harness(trigger_role="textbox")
        dialog = SimpleNamespace(
            role="dialog",
            accessible_name="Search help",
            selected=None,
            checked=None,
        )
        harness.expected_targets = [dialog]
        harness.on_press = lambda key: harness.expected_targets.clear()
        evidence = _act(
            harness,
            "Escape",
            expected={
                "target_absent_equals": {
                    "role": "dialog",
                    "accessible_name": "Search help",
                }
            },
        )
        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(evidence.data["matching_target_count_after"], 0)
        self.assertNotIn("Search help", repr(evidence.data))

    def test_escape_refuses_truncated_current_scene_before_dispatch(self):
        harness = _Harness(trigger_role="textbox")
        harness.expected_targets = [
            SimpleNamespace(
                role="dialog",
                accessible_name="Search help",
                selected=None,
                checked=None,
            )
        ]
        harness.current_truncated = True
        evidence = _act(
            harness,
            "Escape",
            expected={
                "target_absent_equals": {
                    "role": "dialog",
                    "accessible_name": "Search help",
                }
            },
        )
        self.assertFalse(evidence.success)
        self.assertIn("non-truncated", evidence.error or "")
        self.assertEqual(harness.handle.press_calls, [])

    def test_arrow_tab_proves_named_tab_became_selected(self):
        harness = _Harness(trigger_role="tab")
        first = SimpleNamespace(
            role="tab",
            accessible_name="General",
            selected=False,
            checked=None,
        )
        target = SimpleNamespace(
            role="tab",
            accessible_name="Advanced",
            selected=False,
            checked=None,
        )
        harness.expected_targets = [first, target]

        def select_advanced(key):
            target.selected = True

        harness.on_press = select_advanced
        evidence = _act(
            harness,
            "ArrowRight",
            expected={
                "state_target_equals": {
                    "role": "tab",
                    "accessible_name": "Advanced",
                    "state": "selected",
                    "value": True,
                }
            },
        )
        self.assertTrue(evidence.success, evidence.error)
        self.assertTrue(evidence.data["state_after"])
        self.assertNotIn("Advanced", repr(evidence.data))

    def test_arrow_rejects_already_satisfied_state_without_dispatch(self):
        harness = _Harness(trigger_role="tab")
        harness.expected_targets = [
            SimpleNamespace(
                role="tab",
                accessible_name="Advanced",
                selected=True,
                checked=None,
            )
        ]
        evidence = _act(
            harness,
            "ArrowRight",
            expected={
                "state_target_equals": {
                    "role": "tab",
                    "accessible_name": "Advanced",
                    "state": "selected",
                    "value": True,
                }
            },
        )
        self.assertFalse(evidence.success)
        self.assertIn("already observed", evidence.error or "")
        self.assertEqual(harness.handle.press_calls, [])

    def test_safe_keypress_fails_if_url_changes(self):
        harness = _Harness(trigger_role="textbox")
        harness.on_press = lambda key: setattr(
            harness.page,
            "url",
            "https://example.com/changed",
        )
        evidence = _act(
            harness,
            "Tab",
            expected={"target_blurred_equals": True},
        )
        self.assertFalse(evidence.success)
        self.assertIn("changed URL", evidence.error or "")


if __name__ == "__main__":
    unittest.main()
