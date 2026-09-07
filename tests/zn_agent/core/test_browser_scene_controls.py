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
    def __init__(self, url="https://example.com/app"):
        self.url = url

    def title(self):
        return "App"


class _Handle:
    def __init__(self, *, pressed=None, expanded=None, selected=None, disabled=False):
        self.pressed = pressed
        self.expanded = expanded
        self.selected = selected
        self.disabled = disabled
        self.connected = True
        self.click_calls = 0
        self.on_click = None

    def click(self):
        self.click_calls += 1
        if self.on_click is not None:
            self.on_click()

    def evaluate(self, script, *args):
        if "aria-pressed" in script and "aria-expanded" in script and "aria-selected" in script:
            return {
                "connected": self.connected,
                "disabled": self.disabled,
                "pressed": self.pressed,
                "expanded": self.expanded,
                "selected": self.selected,
            }
        raise AssertionError("unexpected script")


class _Base:
    def act(self, action, authority):
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=False,
            page_id=action.page_id,
            target_id=action.target.target_id if action.target else "",
            error="delegated",
        )


class _Harness(PlaywrightBrowserSceneClearPressMixin, _Base):
    def __init__(self, *, role, handle, permission=None):
        identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake",
        )
        self.page = _Page()
        self.handle = handle
        self.context_pages = [self.page]
        self.invalidated = []
        self.session = SimpleNamespace(
            identity=identity,
            permission=permission
            or BrowserPermissionContext(
                allow_page_interaction=True,
                allowed_origins=("https://example.com",),
            ),
            pages={"page-1": self.page},
            default_page_id="page-1",
            next_page_sequence=2,
            last_observation={},
        )
        self.target = BrowserTarget(
            session_id=identity.session_id,
            page_id="page-1",
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id="scene-control-1",
            observed_at=utc_now(),
            url=self.page.url,
            frame_id="main",
            role=role,
            name="Control",
            selector_hint=f"browser_scene:{role}",
        )
        self.binding = SimpleNamespace(
            page_id="page-1",
            target=self.target,
            handle=handle,
            scene_target=SimpleNamespace(role=role, frame_id="main"),
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
            title=self.page.title(),
            load_state="complete",
            target=binding.target,
        )

    def _scene_failed_mutation(self, session, page_id):
        self.invalidated.append(("failed", page_id))

    def _scene_invalidate_page(self, session_id, page_id):
        self.invalidated.append(("invalidate", page_id))

    def _page(self, session, page_id):
        return session.pages[page_id]

    def _register_page(self, session, page):
        page_id = f"page-{session.next_page_sequence}"
        session.next_page_sequence += 1
        session.pages[page_id] = page
        return page_id

    def _reconcile_pages(self, session):
        for page in self.context_pages:
            if page not in session.pages.values():
                self._register_page(session, page)

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


def _act(harness, *, expected, args=None):
    action = BrowserAction.create(
        session_id=harness.session.identity.session_id,
        page_id="page-1",
        kind=BrowserActionKind.CLICK,
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


class BrowserSceneStatefulControlTests(unittest.TestCase):
    def test_toggle_button_proves_aria_pressed_transition(self):
        handle = _Handle(pressed=False)
        handle.on_click = lambda: setattr(handle, "pressed", True)
        harness = _Harness(role="button", handle=handle)

        evidence = _act(harness, expected={"pressed_equals": True})

        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(handle.click_calls, 1)
        self.assertEqual(evidence.data["state_before"], False)
        self.assertEqual(evidence.data["state_after"], True)
        self.assertEqual(evidence.postcondition, "same_scene_target_aria_pressed_equals")
        self.assertIn(("invalidate", "page-1"), harness.invalidated)

    def test_menu_button_and_submenu_item_prove_aria_expanded(self):
        for role in ("button", "menuitem"):
            with self.subTest(role=role):
                handle = _Handle(expanded=False)
                handle.on_click = lambda h=handle: setattr(h, "expanded", True)
                harness = _Harness(role=role, handle=handle)
                evidence = _act(harness, expected={"expanded_equals": True})
                self.assertTrue(evidence.success, evidence.error)
                self.assertTrue(evidence.data["state_after"])

    def test_tab_click_requires_selected_state_transition(self):
        handle = _Handle(selected=False)
        handle.on_click = lambda: setattr(handle, "selected", True)
        harness = _Harness(role="tab", handle=handle)

        evidence = _act(harness, expected={"selected_equals": True})

        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(evidence.data["state"], "selected")
        self.assertTrue(evidence.data["state_after"])

    def test_refuses_stateless_or_already_satisfied_control_click(self):
        stateless = _Harness(role="button", handle=_Handle())
        evidence = _act(stateless, expected={"pressed_equals": True})
        self.assertFalse(evidence.success)
        self.assertIn("does not expose aria-pressed", evidence.error or "")
        self.assertEqual(stateless.handle.click_calls, 0)

        already = _Harness(role="tab", handle=_Handle(selected=True))
        evidence = _act(already, expected={"selected_equals": True})
        self.assertFalse(evidence.success)
        self.assertIn("already observed before dispatch", evidence.error or "")
        self.assertEqual(already.handle.click_calls, 0)

    def test_requires_page_interaction_authority_and_one_boolean_postcondition(self):
        denied = _Harness(
            role="button",
            handle=_Handle(pressed=False),
            permission=BrowserPermissionContext(),
        )
        evidence = _act(denied, expected={"pressed_equals": True})
        self.assertFalse(evidence.success)
        self.assertIn("not permitted", evidence.error or "")

        wrong_shape = _Harness(role="button", handle=_Handle(pressed=False))
        evidence = _act(
            wrong_shape,
            expected={"pressed_equals": True, "expanded_equals": True},
        )
        self.assertFalse(evidence.success)
        self.assertIn("exactly one explicit state postcondition", evidence.error or "")

        wrong_type = _Harness(role="tab", handle=_Handle(selected=False))
        evidence = _act(wrong_type, expected={"selected_equals": "true"})
        self.assertFalse(evidence.success)
        self.assertIn("must be a boolean", evidence.error or "")

    def test_url_change_or_fresh_page_fails_without_ownership_guessing(self):
        nav_handle = _Handle(pressed=False)
        nav_harness = _Harness(role="button", handle=nav_handle)

        def navigate():
            nav_handle.pressed = True
            nav_harness.page.url = "https://example.com/other"

        nav_handle.on_click = navigate
        evidence = _act(nav_harness, expected={"pressed_equals": True})
        self.assertFalse(evidence.success)
        self.assertIn("changed page URL", evidence.error or "")

        popup_handle = _Handle(expanded=False)
        popup_harness = _Harness(role="menuitem", handle=popup_handle)
        extra = _Page("https://example.com/extra")

        def open_extra():
            popup_handle.expanded = True
            popup_harness.context_pages.append(extra)

        popup_handle.on_click = open_extra
        evidence = _act(popup_harness, expected={"expanded_equals": True})
        self.assertFalse(evidence.success)
        self.assertIn("fresh page", evidence.error or "")
        self.assertEqual(evidence.data["new_page_ids"], ["page-2"])
        self.assertIn("page-2", popup_harness.session.pages)

    def test_navigation_click_remains_delegated_to_existing_navigation_layer(self):
        harness = _Harness(role="button", handle=_Handle(pressed=False))
        evidence = _act(
            harness,
            expected={"url_equals": "https://example.com/next"},
        )
        self.assertFalse(evidence.success)
        self.assertNotIn("stateful click", evidence.error or "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
