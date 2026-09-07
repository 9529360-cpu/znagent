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
    def __init__(self, url="https://example.com/app"):
        self.url = url

    def title(self):
        return "Page"


class _Handle:
    def __init__(self, *, on_click=None, contains=None):
        self.on_click = on_click
        self.contains = contains or set()
        self.connected = True
        self.clicks = 0

    def click(self):
        self.clicks += 1
        if self.on_click is not None:
            self.on_click()

    def evaluate(self, script, arg=None):
        if "dialog.contains(control)" in script:
            return arg in self.contains
        raise AssertionError(script)


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
    def __init__(self, *, permission, mode="open"):
        identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake",
        )
        self.page = _Page()
        self.session = SimpleNamespace(
            identity=identity,
            permission=permission,
            pages={"page-1": self.page},
            default_page_id="page-1",
            last_observation={},
        )
        self.mode = mode
        self.dialog_visible = mode == "close"
        self.scene_truncated = False
        self.extra_page = None
        self.trigger_handle = _Handle(on_click=self._on_click)
        self.dialog_handle = _Handle(contains={self.trigger_handle})
        self.target = BrowserTarget(
            session_id=identity.session_id,
            page_id="page-1",
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id="trigger-1",
            observed_at=utc_now(),
            url=self.page.url,
            frame_id="main",
            role="button",
            name="Open" if mode == "open" else "Close",
            selector_hint="browser_scene:button",
        )
        self.trigger_binding = SimpleNamespace(
            page_id="page-1",
            target=self.target,
            handle=self.trigger_handle,
            scene_target=SimpleNamespace(role="button", frame_id="main"),
        )
        self.dialog_target = SimpleNamespace(
            target_id="dialog-1",
            role="dialog",
            accessible_name="Settings",
        )
        self.dialog_binding = SimpleNamespace(
            page_id="page-1",
            target=SimpleNamespace(target_id="dialog-1"),
            handle=self.dialog_handle,
            scene_target=self.dialog_target,
        )
        self._rebuild_scene_state()

    def _on_click(self):
        if self.mode == "open":
            self.dialog_visible = True
        else:
            self.dialog_visible = False

    def _rebuild_scene_state(self):
        bindings = {"trigger-1": self.trigger_binding}
        targets = []
        if self.dialog_visible:
            bindings["dialog-1"] = self.dialog_binding
            targets.append(self.dialog_target)
        scene = SimpleNamespace(
            scene_id="scene-current",
            captured_at=utc_now(),
            truncated=self.scene_truncated,
            targets=tuple(targets),
        )
        self.page_state = SimpleNamespace(scene=scene, bindings=bindings)
        self.scene_state = SimpleNamespace(page_scenes={"page-1": self.page_state})

    def _session(self, session_id):
        return self.session

    def _validate_authority(self, session, action, authority):
        if authority.action_id != action.action_id:
            raise RuntimeError("wrong authority")
        if not authority.permission.allows_action(action.kind):
            raise RuntimeError(f"browser action is not permitted: {action.kind.value}")

    def _scene_action_binding(self, session, target_id, *, page_id="", expected_target=None):
        if target_id != "trigger-1":
            raise RuntimeError("wrong target")
        if expected_target is not None and expected_target != self.target:
            raise RuntimeError("target changed")
        return self.trigger_binding

    def _scene_revalidate_binding(self, session, binding):
        if not binding.handle.connected:
            raise RuntimeError("stale target")

    def _scene_state(self, session):
        self._rebuild_scene_state()
        return self.scene_state

    def observe_scene(self, session_id, *, page_id="", max_targets=64):
        self._rebuild_scene_state()
        scene = self.page_state.scene
        return SimpleNamespace(
            scene_id="scene-fresh",
            captured_at=utc_now(),
            truncated=self.scene_truncated,
            targets=scene.targets,
        )

    def _page(self, session, page_id):
        return session.pages[page_id]

    def _reconcile_pages(self, session):
        if self.extra_page is not None and self.extra_page not in session.pages.values():
            session.pages["page-2"] = self.extra_page

    def _require_url_allowed(self, url, permission):
        if not permission.allows_origin(url):
            raise RuntimeError("url outside authority")

    @staticmethod
    def _url_allowed(url, permission):
        return permission.allows_origin(url)

    def _scene_failed_mutation(self, session, page_id):
        return None

    def _scene_invalidate_page(self, session_id, page_id):
        return None

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


def _act(harness, expected):
    action = BrowserAction.create(
        session_id=harness.session.identity.session_id,
        page_id="page-1",
        kind=BrowserActionKind.CLICK,
        target=harness.target,
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


class BrowserSceneDialogTests(unittest.TestCase):
    def test_open_named_dialog_requires_absent_before_and_unique_after(self):
        harness = _Harness(
            permission=BrowserPermissionContext(allow_page_interaction=True),
            mode="open",
        )
        evidence = _act(harness, {"dialog_open_equals": "Settings"})
        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(
            evidence.postcondition,
            "named_dialog_visible_after_exact_scene_click",
        )
        self.assertEqual(evidence.data["matching_dialog_count_before"], 0)
        self.assertEqual(evidence.data["matching_dialog_count_after"], 1)
        self.assertEqual(harness.trigger_handle.clicks, 1)
        self.assertNotIn("Settings", repr(evidence.data))

    def test_close_requires_trigger_contained_in_current_named_dialog(self):
        harness = _Harness(
            permission=BrowserPermissionContext(allow_page_interaction=True),
            mode="close",
        )
        evidence = _act(harness, {"dialog_closed_equals": "Settings"})
        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(
            evidence.postcondition,
            "named_dialog_absent_after_exact_scene_click",
        )
        self.assertEqual(evidence.data["matching_dialog_count_before"], 1)
        self.assertEqual(evidence.data["matching_dialog_count_after"], 0)

        refused = _Harness(
            permission=BrowserPermissionContext(allow_page_interaction=True),
            mode="close",
        )
        refused.dialog_handle.contains.clear()
        evidence = _act(refused, {"dialog_closed_equals": "Settings"})
        self.assertFalse(evidence.success)
        self.assertIn("not contained", evidence.error or "")
        self.assertEqual(refused.trigger_handle.clicks, 0)

    def test_open_rejects_already_visible_and_truncated_scene(self):
        harness = _Harness(
            permission=BrowserPermissionContext(allow_page_interaction=True),
            mode="open",
        )
        harness.dialog_visible = True
        evidence = _act(harness, {"dialog_open_equals": "Settings"})
        self.assertFalse(evidence.success)
        self.assertIn("already observed", evidence.error or "")

        truncated = _Harness(
            permission=BrowserPermissionContext(allow_page_interaction=True),
            mode="open",
        )
        truncated.scene_truncated = True
        evidence = _act(truncated, {"dialog_open_equals": "Settings"})
        self.assertFalse(evidence.success)
        self.assertIn("non-truncated", evidence.error or "")

    def test_dialog_transition_requires_page_interaction_authority(self):
        harness = _Harness(permission=BrowserPermissionContext(), mode="open")
        evidence = _act(harness, {"dialog_open_equals": "Settings"})
        self.assertFalse(evidence.success)
        self.assertIn("not permitted", evidence.error or "")
        self.assertEqual(harness.trigger_handle.clicks, 0)

    def test_url_change_and_fresh_page_fail_closed(self):
        changed = _Harness(
            permission=BrowserPermissionContext(
                allow_page_interaction=True,
                allowed_origins=("https://example.com",),
            ),
            mode="open",
        )

        def change_url():
            changed.dialog_visible = True
            changed.page.url = "https://example.com/other"

        changed.trigger_handle.on_click = change_url
        evidence = _act(changed, {"dialog_open_equals": "Settings"})
        self.assertFalse(evidence.success)
        self.assertIn("changed page URL", evidence.error or "")

        fresh = _Harness(
            permission=BrowserPermissionContext(allow_page_interaction=True),
            mode="open",
        )
        fresh.extra_page = _Page("https://example.com/extra")
        evidence = _act(fresh, {"dialog_open_equals": "Settings"})
        self.assertFalse(evidence.success)
        self.assertIn("fresh page", evidence.error or "")
        self.assertIn("page-2", fresh.session.pages)

    def test_malformed_dialog_postconditions_are_rejected(self):
        harness = _Harness(
            permission=BrowserPermissionContext(allow_page_interaction=True),
            mode="open",
        )
        evidence = _act(
            harness,
            {
                "dialog_open_equals": "Settings",
                "dialog_closed_equals": "Settings",
            },
        )
        self.assertFalse(evidence.success)
        self.assertIn("exactly one", evidence.error or "")

        evidence = _act(harness, {"dialog_open_equals": ""})
        self.assertFalse(evidence.success)
        self.assertIn("non-empty", evidence.error or "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
