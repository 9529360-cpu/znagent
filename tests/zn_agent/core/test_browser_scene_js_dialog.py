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


class _Dialog:
    def __init__(self, dialog_type="alert", message="hello", default_value=""):
        self.type = dialog_type
        self.message = message
        self.default_value = default_value
        self.accept_calls = []
        self.dismiss_calls = 0

    def accept(self, **kwargs):
        self.accept_calls.append(dict(kwargs))

    def dismiss(self):
        self.dismiss_calls += 1


class _Page:
    def __init__(self):
        self.url = "https://example.com/start"
        self.listeners = {}

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    def remove_listener(self, event, callback):
        callbacks = self.listeners.get(event, [])
        if callback in callbacks:
            callbacks.remove(callback)

    def emit_dialog(self, dialog):
        for callback in tuple(self.listeners.get("dialog", [])):
            callback(dialog)


class _Handle:
    def __init__(self, page):
        self.page = page
        self.dialogs = []
        self.click_calls = 0
        self.on_click = None

    def click(self):
        self.click_calls += 1
        for dialog in list(self.dialogs):
            self.page.emit_dialog(dialog)
        if self.on_click is not None:
            self.on_click()


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
    def __init__(self, permission):
        identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake",
        )
        self.page = _Page()
        self.handle = _Handle(self.page)
        self.invalidated = []
        self.context_pages = [self.page]
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
            target_id="scene-trigger",
            observed_at=utc_now(),
            url=self.page.url,
            frame_id="main",
            role="button",
            name="Delete",
            selector_hint="browser_scene:button",
        )
        self.binding = SimpleNamespace(
            page_id="page-1",
            target=self.target,
            handle=self.handle,
            scene_target=SimpleNamespace(role="button", frame_id="main"),
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
        for page in self.context_pages:
            if page not in session.pages.values():
                page_id = f"page-{session.next_page_sequence}"
                session.next_page_sequence += 1
                session.pages[page_id] = page

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


class BrowserSceneJsDialogTests(unittest.TestCase):
    def test_accepts_one_expected_alert_and_removes_listener(self):
        harness = _Harness(BrowserPermissionContext(allow_page_interaction=True))
        dialog = _Dialog("alert", "Delete item?")
        harness.handle.dialogs = [dialog]
        evidence = _act(
            harness,
            expected={"js_dialog_type": "alert", "js_dialog_action": "accept"},
        )
        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(len(dialog.accept_calls), 1)
        self.assertEqual(dialog.dismiss_calls, 0)
        self.assertEqual(harness.page.listeners.get("dialog"), [])
        self.assertNotIn("Delete item?", repr(evidence.data))
        self.assertEqual(evidence.data["dialog_message_length"], len("Delete item?"))

    def test_wrong_type_is_dismissed_and_fails(self):
        harness = _Harness(BrowserPermissionContext(allow_page_interaction=True))
        dialog = _Dialog("confirm")
        harness.handle.dialogs = [dialog]
        evidence = _act(
            harness,
            expected={"js_dialog_type": "alert", "js_dialog_action": "accept"},
        )
        self.assertFalse(evidence.success)
        self.assertEqual(dialog.dismiss_calls, 1)
        self.assertIn("type", evidence.error or "")

    def test_prompt_text_requires_text_entry_and_is_not_echoed(self):
        denied = _Harness(BrowserPermissionContext(allow_page_interaction=True))
        denied.handle.dialogs = [_Dialog("prompt")]
        evidence = _act(
            denied,
            expected={"js_dialog_type": "prompt", "js_dialog_action": "accept"},
            args={"prompt_text": "secret-value"},
        )
        self.assertFalse(evidence.success)
        self.assertIn("text-entry", evidence.error or "")

        harness = _Harness(
            BrowserPermissionContext(
                allow_page_interaction=True,
                allow_text_entry=True,
            )
        )
        dialog = _Dialog("prompt")
        harness.handle.dialogs = [dialog]
        evidence = _act(
            harness,
            expected={"js_dialog_type": "prompt", "js_dialog_action": "accept"},
            args={"prompt_text": "secret-value"},
        )
        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(dialog.accept_calls, [{"prompt_text": "secret-value"}])
        self.assertNotIn("secret-value", repr(evidence.data))
        self.assertEqual(evidence.data["prompt_text_length"], len("secret-value"))

    def test_multiple_dialogs_fail_and_extra_dialog_is_dismissed(self):
        harness = _Harness(BrowserPermissionContext(allow_page_interaction=True))
        first = _Dialog("alert")
        second = _Dialog("alert")
        harness.handle.dialogs = [first, second]
        evidence = _act(
            harness,
            expected={"js_dialog_type": "alert", "js_dialog_action": "accept"},
        )
        self.assertFalse(evidence.success)
        self.assertEqual(len(first.accept_calls), 1)
        self.assertEqual(second.dismiss_calls, 1)
        self.assertEqual(evidence.data["dialog_event_count"], 2)

    def test_url_change_requires_navigation_authority_and_exact_postcondition(self):
        harness = _Harness(BrowserPermissionContext(allow_page_interaction=True))
        harness.handle.dialogs = [_Dialog("confirm")]
        evidence = _act(
            harness,
            expected={
                "js_dialog_type": "confirm",
                "js_dialog_action": "accept",
                "url_equals": "https://example.com/done",
            },
        )
        self.assertFalse(evidence.success)
        self.assertIn("navigation permission", evidence.error or "")

        allowed = _Harness(
            BrowserPermissionContext(
                allow_page_interaction=True,
                allow_navigation=True,
                allowed_origins=("https://example.com",),
            )
        )
        allowed.handle.dialogs = [_Dialog("confirm")]
        allowed.handle.on_click = lambda: setattr(
            allowed.page,
            "url",
            "https://example.com/done",
        )
        evidence = _act(
            allowed,
            expected={
                "js_dialog_type": "confirm",
                "js_dialog_action": "accept",
                "url_equals": "https://example.com/done",
            },
        )
        self.assertTrue(evidence.success, evidence.error)

    def test_fresh_page_fails_without_closing_or_claiming_it(self):
        harness = _Harness(BrowserPermissionContext(allow_page_interaction=True))
        harness.handle.dialogs = [_Dialog("alert")]
        fresh = _Page()
        harness.handle.on_click = lambda: harness.context_pages.append(fresh)
        evidence = _act(
            harness,
            expected={"js_dialog_type": "alert", "js_dialog_action": "dismiss"},
        )
        self.assertFalse(evidence.success)
        self.assertEqual(evidence.data["new_page_ids"], ["page-2"])
        self.assertIn(fresh, harness.context_pages)


if __name__ == "__main__":
    unittest.main()
