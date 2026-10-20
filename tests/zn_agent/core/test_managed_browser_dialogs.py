from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
)
from zn_agent.core.managed_browser import PlaywrightManagedBrowser


class _FakeDialog:
    def __init__(self, *, dialog_type, message="", default_value=""):
        self.type = dialog_type
        self.message = message
        self.default_value = default_value
        self.value = default_value
        self.accepted = False
        self.dismissed = False
        self.prompt_text = None

    def accept(self, prompt_text=None):
        if self.accepted or self.dismissed:
            raise RuntimeError("dialog already handled")
        self.accepted = True
        self.prompt_text = prompt_text
        if self.type == "prompt":
            self.value = prompt_text if prompt_text is not None else self.default_value

    def dismiss(self):
        if self.accepted or self.dismissed:
            raise RuntimeError("dialog already handled")
        self.dismissed = True


class _FakePage:
    def __init__(self):
        self.url = "about:blank"
        self._title = ""
        self._ready = "complete"
        self.viewport_size = {"width": 1280, "height": 720}
        self.closed = False
        self.dialog_handler = None

    def title(self):
        return self._title

    def evaluate(self, expression, arg=None):
        if expression == "document.readyState" and arg is None:
            return self._ready
        raise AssertionError("unexpected page evaluate expression")

    def on(self, event, handler):
        if event != "dialog":
            raise AssertionError(f"unexpected event subscription: {event!r}")
        self.dialog_handler = handler

    def fire_dialog(self, dialog):
        if self.dialog_handler is None:
            raise AssertionError("no dialog handler installed")
        self.dialog_handler(dialog)

    def is_closed(self):
        return self.closed


class _FakeContext:
    def __init__(self):
        self.page = _FakePage()

    def set_default_navigation_timeout(self, value):
        return None

    def set_default_timeout(self, value):
        return None

    def route(self, pattern, handler):
        return None

    def route_web_socket(self, pattern, handler):
        return None

    def new_page(self):
        return self.page

    def close(self):
        return None


class _FakeBrowser:
    version = "fake-1"

    def __init__(self):
        self.context = _FakeContext()

    def new_context(self, **kwargs):
        return self.context

    def close(self):
        return None


class _FakeChromium:
    def __init__(self, browser):
        self.browser = browser

    def launch(self, *, headless):
        return self.browser


class _FakePlaywright:
    def __init__(self):
        self.browser = _FakeBrowser()
        self.chromium = _FakeChromium(self.browser)

    def stop(self):
        return None


class _FakeStarter:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


def _dialog_action(*, session_id, page_id, kind, args=None):
    return BrowserAction.create(
        session_id=session_id,
        page_id=page_id,
        kind=kind,
        args=args,
    )


class ManagedBrowserDialogTests(unittest.TestCase):
    def _build(self, *, permission=None):
        playwright = _FakePlaywright()
        adapter = PlaywrightManagedBrowser(
            playwright_factory=lambda: _FakeStarter(playwright),
            url_checker=lambda url, **kwargs: True,
        )
        identity = adapter.open_session(
            permission=permission
            or BrowserPermissionContext(allow_page_interaction=True),
            headless=True,
        )
        page = playwright.browser.context.page
        page.url = "https://example.com/app"
        page._title = "App"
        return adapter, playwright, identity

    def _authorize(self, adapter, identity, action, permission):
        observation = adapter.observe(identity.session_id, page_id=action.page_id)
        return BrowserActionAuthority.from_observation(
            action,
            observation,
            permission,
        )

    def test_open_dialog_is_observed_in_metadata(self):
        adapter, playwright, identity = self._build()
        page = playwright.browser.context.page
        try:
            empty = adapter.observe(identity.session_id)
            self.assertIsNone(empty.metadata["dialog"])
            self.assertEqual(empty.metadata["dialog_auto_dismiss_count"], 0)

            page.fire_dialog(
                _FakeDialog(dialog_type="alert", message="Save failed")
            )
            observed = adapter.observe(identity.session_id)
            dialog = observed.metadata["dialog"]
            self.assertEqual(dialog["type"], "alert")
            self.assertEqual(dialog["message"], "Save failed")
            self.assertIn("opened_at", dialog)
        finally:
            adapter.close()

    def test_dialog_accept_closes_and_verifies_page_state(self):
        permission = BrowserPermissionContext(allow_page_interaction=True)
        adapter, playwright, identity = self._build(permission=permission)
        page = playwright.browser.context.page
        try:
            dialog = _FakeDialog(dialog_type="alert", message="Saved")
            page.fire_dialog(dialog)
            observed = adapter.observe(identity.session_id)
            self.assertEqual(observed.metadata["dialog"]["type"], "alert")

            action = _dialog_action(
                session_id=identity.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.DIALOG_ACCEPT,
            )
            authority = self._authorize(adapter, identity, action, permission)
            evidence = adapter.act(action, authority)

            self.assertTrue(dialog.accepted)
            self.assertTrue(evidence.success)
            self.assertEqual(evidence.postcondition, "dialog_closed")
            self.assertEqual(evidence.data["dialog_type"], "alert")
            self.assertEqual(evidence.data["dialog_handled"], "accept")
            self.assertEqual(evidence.url_before, "https://example.com/app")
            self.assertEqual(evidence.url_after, "https://example.com/app")

            after = adapter.observe(identity.session_id)
            self.assertIsNone(after.metadata["dialog"])
        finally:
            adapter.close()

    def test_dialog_dismiss_confirm(self):
        permission = BrowserPermissionContext(allow_page_interaction=True)
        adapter, playwright, identity = self._build(permission=permission)
        page = playwright.browser.context.page
        try:
            dialog = _FakeDialog(dialog_type="confirm", message="Delete item?")
            page.fire_dialog(dialog)
            observed = adapter.observe(identity.session_id)

            action = _dialog_action(
                session_id=identity.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.DIALOG_DISMISS,
            )
            authority = self._authorize(adapter, identity, action, permission)
            evidence = adapter.act(action, authority)

            self.assertTrue(dialog.dismissed)
            self.assertFalse(dialog.accepted)
            self.assertTrue(evidence.success)
            self.assertEqual(evidence.postcondition, "dialog_dismissed")
            self.assertEqual(evidence.data["dialog_type"], "confirm")

            after = adapter.observe(identity.session_id)
            self.assertIsNone(after.metadata["dialog"])
        finally:
            adapter.close()

    def test_prompt_accept_never_autofills_text(self):
        permission = BrowserPermissionContext(allow_page_interaction=True)
        adapter, playwright, identity = self._build(permission=permission)
        page = playwright.browser.context.page
        try:
            dialog = _FakeDialog(
                dialog_type="prompt",
                message="Your name?",
                default_value="anonymous",
            )
            page.fire_dialog(dialog)
            observed = adapter.observe(identity.session_id)

            rejected = _dialog_action(
                session_id=identity.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.DIALOG_ACCEPT,
                args={"prompt_text": "injected-name"},
            )
            authority = self._authorize(adapter, identity, rejected, permission)
            evidence = adapter.act(rejected, authority)
            self.assertFalse(evidence.success)
            self.assertIn("never auto-fills prompt text", evidence.error)
            self.assertEqual(evidence.data["dispatch_state"], "not_started")
            self.assertFalse(dialog.accepted)
            self.assertIsNotNone(adapter.observe(identity.session_id).metadata["dialog"])

            action = _dialog_action(
                session_id=identity.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.DIALOG_ACCEPT,
            )
            authority = self._authorize(adapter, identity, action, permission)
            evidence = adapter.act(action, authority)

            self.assertTrue(evidence.success)
            self.assertEqual(evidence.data["prompt_value_used"], "default")
            self.assertEqual(dialog.value, "anonymous")
            self.assertIsNone(dialog.prompt_text)
        finally:
            adapter.close()

    def test_dialog_action_without_open_dialog_fails_cleanly(self):
        permission = BrowserPermissionContext(allow_page_interaction=True)
        adapter, playwright, identity = self._build(permission=permission)
        try:
            observed = adapter.observe(identity.session_id)
            self.assertIsNone(observed.metadata["dialog"])

            for kind in (
                BrowserActionKind.DIALOG_ACCEPT,
                BrowserActionKind.DIALOG_DISMISS,
            ):
                action = _dialog_action(
                    session_id=identity.session_id,
                    page_id=observed.page_id,
                    kind=kind,
                )
                authority = self._authorize(adapter, identity, action, permission)
                evidence = adapter.act(action, authority)
                self.assertFalse(evidence.success)
                self.assertIn("no JavaScript dialog", evidence.error)
                self.assertEqual(evidence.data["dispatch_state"], "not_started")
                self.assertTrue(evidence.data["requires_fresh_resense"])
        finally:
            adapter.close()

    def test_beforeunload_is_auto_dismissed_and_never_hangs(self):
        adapter, playwright, identity = self._build()
        page = playwright.browser.context.page
        try:
            dialog = _FakeDialog(dialog_type="beforeunload", message="Leave?")
            page.fire_dialog(dialog)

            self.assertTrue(dialog.dismissed)
            self.assertFalse(dialog.accepted)

            observed = adapter.observe(identity.session_id)
            self.assertIsNone(observed.metadata["dialog"])
            self.assertEqual(observed.metadata["dialog_auto_dismiss_count"], 1)
            last = observed.metadata["last_auto_dismissed_dialog"]
            self.assertEqual(last["type"], "beforeunload")
            self.assertTrue(last["auto_dismissed"])
        finally:
            adapter.close()

    def test_dialog_actions_are_permission_gated(self):
        adapter, playwright, identity = self._build(
            permission=BrowserPermissionContext()
        )
        page = playwright.browser.context.page
        try:
            page.fire_dialog(_FakeDialog(dialog_type="alert", message="hi"))
            observed = adapter.observe(identity.session_id)
            action = _dialog_action(
                session_id=identity.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.DIALOG_ACCEPT,
            )
            with self.assertRaisesRegex(ValueError, "not permitted"):
                BrowserActionAuthority.from_observation(
                    action,
                    observed,
                    BrowserPermissionContext(),
                )
        finally:
            adapter.close()

    def test_dialog_state_is_per_page(self):
        adapter, playwright, identity = self._build()
        page = playwright.browser.context.page
        try:
            page.fire_dialog(_FakeDialog(dialog_type="alert", message="one"))
            observed = adapter.observe(identity.session_id)
            self.assertEqual(observed.metadata["dialog"]["message"], "one")
            self.assertEqual(observed.metadata["dialog_auto_dismiss_count"], 0)
        finally:
            adapter.close()


if __name__ == "__main__":
    unittest.main()
