from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from zn_agent.core.managed_browser import PlaywrightManagedBrowser


class _ValueHandle:
    def __init__(self, value):
        self.value = value

    def json_value(self):
        return self.value

    def dispose(self):
        return None


class _ElementHandle:
    def __init__(self, page, node):
        self.page = page
        self.node = node
        self.disposed = False

    def as_element(self):
        return self

    def evaluate(self, expression, arg=None):
        if self.disposed:
            raise RuntimeError("disposed element")
        if "element === other" in expression:
            return isinstance(arg, _ElementHandle) and self.node is arg.node
        if "element.checked" in expression and "inputType" in expression:
            connected = bool(self.node.get("connected", True))
            supported = bool(self.node.get("supported", True))
            return {
                "connected": connected,
                "supported": supported,
                "disabled": bool(self.node.get("disabled", False)),
                "checked": bool(self.node.get("checked", False)) if connected and supported else None,
            }
        if "document.querySelectorAll" in expression and "element.isConnected" in expression:
            current = self.page.node
            connected = bool(self.node.get("connected", True))
            input_type = "checkbox" if self.node.get("checkbox", True) else "text"
            return {
                "count": 1,
                "current": bool(connected and current is self.node),
                "connected": connected,
                "visible": connected,
                "dom_id": "check-target",
                "tag": "input",
                "role": "checkbox" if input_type == "checkbox" else "textbox",
                "name": "Check target",
                "input_type": input_type,
                "is_password": False,
            }
        raise AssertionError("unexpected evaluate expression")

    def check(self):
        if self.disposed or not self.node.get("connected", True):
            raise RuntimeError("detached element")
        self.page.check_dispatches += 1
        if self.node.get("check_error"):
            raise RuntimeError("provider check error")
        if not self.node.get("check_blocked"):
            self.node["checked"] = True
        if self.node.get("replace_on_check"):
            replacement = dict(self.node)
            replacement.pop("replace_on_check", None)
            self.node["connected"] = False
            replacement["connected"] = True
            self.page.node = replacement

    def dispose(self):
        self.disposed = True


class _BundleHandle:
    def __init__(self, page):
        self.page = page

    def get_property(self, name):
        if name == "count":
            return _ValueHandle(1)
        if name == "node":
            return _ElementHandle(self.page, self.page.node)
        raise AssertionError(name)

    def dispose(self):
        return None


class _Page:
    def __init__(self, node):
        self.node = node
        self.url = "https://example.com/check"
        self.viewport_size = {"width": 800, "height": 600}
        self.check_dispatches = 0

    def title(self):
        return "Check"

    def evaluate(self, expression):
        if expression == "document.readyState":
            return "complete"
        raise AssertionError(expression)

    def evaluate_handle(self, expression, arg=None):
        if "document.querySelectorAll" not in expression or arg != "check-target":
            raise AssertionError("unexpected target query")
        return _BundleHandle(self)

    def is_closed(self):
        return False


class _Context:
    def __init__(self, page):
        self.page = page

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


class _Browser:
    version = "fake"

    def __init__(self, page):
        self.context = _Context(page)

    def new_context(self, **kwargs):
        return self.context

    def close(self):
        return None


class _Chromium:
    def __init__(self, browser):
        self.browser = browser

    def launch(self, *, headless):
        return self.browser


class _Playwright:
    def __init__(self, page):
        self.chromium = _Chromium(_Browser(page))

    def stop(self):
        return None


class _Starter:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


def _build(node, *, permission=None):
    page = _Page(node)
    playwright = _Playwright(page)
    policy = permission or BrowserPermissionContext(allow_page_interaction=True)
    browser = PlaywrightManagedBrowser(
        playwright_factory=lambda: _Starter(playwright),
        url_checker=lambda url, **kwargs: True,
    )
    session = browser.open_session(permission=policy, headless=True)
    query = BrowserTargetQuery(
        kind=BrowserTargetQueryKind.DOM_ID,
        value="check-target",
    )
    observed = browser.observe_target(session.session_id, query)
    return browser, session, policy, page, observed


def _check_action(session, observed, *, kind=BrowserActionKind.CHECK):
    return BrowserAction.create(
        session_id=session.session_id,
        page_id=observed.page_id,
        kind=kind,
        target=observed.target,
    )


class ManagedBrowserCheckTests(unittest.TestCase):
    def test_check_requires_page_interaction_permission_at_authority_boundary(self):
        permission = BrowserPermissionContext()
        browser, session, _permission, page, observed = _build(
            {"connected": True, "checked": False},
            permission=permission,
        )
        try:
            action = _check_action(session, observed)
            with self.assertRaisesRegex(ValueError, "not permitted"):
                BrowserActionAuthority.from_observation(action, observed, permission)
            self.assertEqual(page.check_dispatches, 0)
        finally:
            browser.close()

    def test_check_requires_native_checkbox_target_before_dispatch(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "checked": False, "checkbox": False, "supported": False}
        )
        try:
            action = _check_action(session, observed)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("checkbox", effect.error or "")
            self.assertEqual(page.check_dispatches, 0)
        finally:
            browser.close()

    def test_check_refuses_already_checked_target_before_dispatch(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "checked": True}
        )
        try:
            action = _check_action(session, observed)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("already checked", effect.error or "")
            self.assertEqual(page.check_dispatches, 0)
        finally:
            browser.close()

    def test_check_returns_success_only_from_fresh_same_node_checked_state(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "checked": False}
        )
        try:
            action = _check_action(session, observed)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.postcondition, "same_exact_target_checked")
            self.assertTrue(effect.data["exact_node_continuity"])
            self.assertFalse(effect.data["checked_before"])
            self.assertTrue(effect.data["checked_after"])
            self.assertEqual(page.check_dispatches, 1)
            self.assertNotEqual(effect.observed_at, observed.captured_at)
        finally:
            browser.close()

    def test_check_fails_if_provider_dispatch_does_not_change_checked_state(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "checked": False, "check_blocked": True}
        )
        try:
            action = _check_action(session, observed)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("postcondition was not observed", effect.error or "")
            self.assertTrue(effect.data["exact_node_continuity"])
            self.assertFalse(effect.data["checked_after"])
            self.assertEqual(page.check_dispatches, 1)
        finally:
            browser.close()

    def test_check_fails_if_same_shape_target_is_replaced_during_dispatch(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "checked": False, "replace_on_check": True}
        )
        try:
            action = _check_action(session, observed)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("replaced target node", effect.error or "")
            self.assertFalse(effect.data["exact_node_continuity"])
            self.assertTrue(effect.data["checked_after"])
            self.assertEqual(page.check_dispatches, 1)
        finally:
            browser.close()

    def test_check_refuses_disabled_checkbox_before_dispatch(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "checked": False, "disabled": True}
        )
        try:
            action = _check_action(session, observed)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("disabled", effect.error or "")
            self.assertEqual(page.check_dispatches, 0)
        finally:
            browser.close()

    def test_uncheck_remains_unimplemented_and_does_not_dispatch_check(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "checked": True}
        )
        try:
            action = _check_action(session, observed, kind=BrowserActionKind.UNCHECK)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("not implemented", effect.error or "")
            self.assertEqual(page.check_dispatches, 0)
        finally:
            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
