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
        if 'getAttribute("aria-pressed")' in expression:
            value = self.node.get("aria_pressed")
            return value if type(value) is bool else None
        if "document.querySelectorAll" in expression and "element.isConnected" in expression:
            current = self.page.node
            connected = bool(self.node.get("connected", True))
            return {
                "count": 1,
                "current": bool(connected and current is self.node),
                "connected": connected,
                "visible": connected,
                "dom_id": "toggle",
                "tag": "button",
                "role": "button",
                "name": "Toggle",
                "input_type": "",
                "is_password": False,
            }
        raise AssertionError("unexpected evaluate expression")

    def click(self):
        if self.disposed or not self.node.get("connected", True):
            raise RuntimeError("detached element")
        self.page.click_dispatches += 1
        if self.node.get("click_error"):
            raise RuntimeError("provider click error")
        if self.node.get("click_blocked"):
            return
        before = self.node.get("aria_pressed")
        if type(before) is bool:
            self.node["aria_pressed"] = not before
        if self.node.get("replace_on_click"):
            replacement = dict(self.node)
            replacement.pop("replace_on_click", None)
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
        self.url = "https://example.com/toggle"
        self.viewport_size = {"width": 800, "height": 600}
        self.click_dispatches = 0

    def title(self):
        return "Toggle"

    def evaluate(self, expression):
        if expression == "document.readyState":
            return "complete"
        raise AssertionError(expression)

    def evaluate_handle(self, expression, arg=None):
        if "document.querySelectorAll" not in expression or arg != "toggle":
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


def _build(node):
    page = _Page(node)
    playwright = _Playwright(page)
    permission = BrowserPermissionContext(allow_page_interaction=True)
    browser = PlaywrightManagedBrowser(
        playwright_factory=lambda: _Starter(playwright),
        url_checker=lambda url, **kwargs: True,
    )
    session = browser.open_session(permission=permission, headless=True)
    query = BrowserTargetQuery(
        kind=BrowserTargetQueryKind.DOM_ID,
        value="toggle",
    )
    observed = browser.observe_target(session.session_id, query)
    return browser, session, permission, page, observed


def _click_action(session, observed, *, expected):
    action = BrowserAction.create(
        session_id=session.session_id,
        page_id=observed.page_id,
        kind=BrowserActionKind.CLICK,
        target=observed.target,
        expected=expected,
    )
    return action


class ManagedBrowserClickTests(unittest.TestCase):
    def test_click_requires_boolean_aria_pressed_postcondition_before_dispatch(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "aria_pressed": False}
        )
        try:
            action = _click_action(session, observed, expected={})
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("aria_pressed", effect.error or "")
            self.assertEqual(page.click_dispatches, 0)
        finally:
            browser.close()

    def test_click_requires_observed_state_transition_not_preexisting_success(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "aria_pressed": True}
        )
        try:
            action = _click_action(session, observed, expected={"aria_pressed": True})
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("already observed", effect.error or "")
            self.assertEqual(page.click_dispatches, 0)
        finally:
            browser.close()

    def test_click_returns_success_only_from_fresh_same_node_aria_pressed_transition(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "aria_pressed": False}
        )
        try:
            action = _click_action(session, observed, expected={"aria_pressed": True})
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.postcondition, "same_exact_target_aria_pressed")
            self.assertTrue(effect.data["exact_node_continuity"])
            self.assertFalse(effect.data["aria_pressed_before"])
            self.assertTrue(effect.data["aria_pressed_after"])
            self.assertEqual(page.click_dispatches, 1)
            self.assertNotEqual(effect.observed_at, observed.captured_at)
        finally:
            browser.close()

    def test_click_fails_if_provider_dispatch_does_not_produce_expected_state(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "aria_pressed": False, "click_blocked": True}
        )
        try:
            action = _click_action(session, observed, expected={"aria_pressed": True})
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("postcondition was not observed", effect.error or "")
            self.assertTrue(effect.data["exact_node_continuity"])
            self.assertFalse(effect.data["aria_pressed_after"])
            self.assertEqual(page.click_dispatches, 1)
        finally:
            browser.close()

    def test_click_fails_if_same_shape_target_is_replaced_during_dispatch(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "aria_pressed": False, "replace_on_click": True}
        )
        try:
            action = _click_action(session, observed, expected={"aria_pressed": True})
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("replaced target node", effect.error or "")
            self.assertFalse(effect.data["exact_node_continuity"])
            self.assertTrue(effect.data["aria_pressed_after"])
            self.assertEqual(page.click_dispatches, 1)
        finally:
            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
