from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserPermissionContext,
    BrowserTargetKind,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from zn_agent.core.semantic_managed_browser import (
    ManagedBrowserError,
    SemanticPlaywrightManagedBrowser,
)


class _Element:
    def __init__(self, evidence):
        self.evidence = dict(evidence)
        self.disposed = False

    def evaluate(self, expression, arg=None):
        if self.disposed:
            raise RuntimeError("disposed element")
        if "native_checkbox" in expression:
            return dict(self.evidence)
        if "element === other" in expression:
            return self is arg
        raise AssertionError("unexpected element expression")

    def dispose(self):
        self.disposed = True


class _Locator:
    def __init__(self, *, count, element=None):
        self._count = count
        self._element = element
        self.element_handle_calls = 0

    def count(self):
        return self._count

    def element_handle(self):
        self.element_handle_calls += 1
        return self._element


class _Page:
    def __init__(self, locator):
        self.locator = locator
        self.url = "https://example.com/settings"
        self.viewport_size = {"width": 800, "height": 600}
        self.role_calls = []

    def get_by_role(self, role, *, name, exact):
        self.role_calls.append((role, name, exact))
        return self.locator

    def title(self):
        return "Settings"

    def evaluate(self, expression):
        if expression == "document.readyState":
            return "complete"
        raise AssertionError(expression)

    def is_closed(self):
        return False


class _Context:
    def __init__(self, page):
        self._page = page
        self.pages = [page]

    def set_default_navigation_timeout(self, value):
        return None

    def set_default_timeout(self, value):
        return None

    def route(self, pattern, handler):
        return None

    def route_web_socket(self, pattern, handler):
        return None

    def new_page(self):
        return self._page

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


def _build(locator):
    page = _Page(locator)
    playwright = _Playwright(page)
    browser = SemanticPlaywrightManagedBrowser(
        playwright_factory=lambda: _Starter(playwright),
        url_checker=lambda url, **kwargs: True,
    )
    session = browser.open_session(
        permission=BrowserPermissionContext(allow_page_interaction=True),
        headless=True,
    )
    query = BrowserTargetQuery(
        kind=BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME,
        value="Email updates",
    )
    return browser, session, page, query


class SemanticManagedBrowserTests(unittest.TestCase):
    def test_exact_accessible_name_binds_one_idless_native_checkbox(self):
        element = _Element(
            {
                "connected": True,
                "visible": True,
                "tag": "input",
                "input_type": "checkbox",
                "native_checkbox": True,
            }
        )
        locator = _Locator(count=1, element=element)
        browser, session, page, query = _build(locator)
        try:
            observed = browser.observe_target(session.session_id, query)
            self.assertIsNotNone(observed.target)
            assert observed.target is not None
            self.assertIs(observed.target.kind, BrowserTargetKind.ACCESSIBILITY_NODE)
            self.assertEqual(observed.target.role, "checkbox")
            self.assertEqual(observed.target.name, "Email updates")
            self.assertEqual(
                observed.target.selector_hint,
                "accessible_checkbox_name:exact",
            )
            self.assertEqual(page.role_calls, [("checkbox", "Email updates", True)])
        finally:
            browser.close()

    def test_semantic_checkbox_zero_matches_fails_closed(self):
        locator = _Locator(count=0)
        browser, session, _page, query = _build(locator)
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "not found"):
                browser.observe_target(session.session_id, query)
            self.assertEqual(locator.element_handle_calls, 0)
        finally:
            browser.close()

    def test_semantic_checkbox_multiple_exact_matches_are_ambiguous(self):
        locator = _Locator(count=2)
        browser, session, _page, query = _build(locator)
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "ambiguous"):
                browser.observe_target(session.session_id, query)
            self.assertEqual(locator.element_handle_calls, 0)
        finally:
            browser.close()

    def test_semantic_checkbox_refuses_non_native_checkbox_role(self):
        element = _Element(
            {
                "connected": True,
                "visible": True,
                "tag": "div",
                "input_type": "",
                "native_checkbox": False,
            }
        )
        locator = _Locator(count=1, element=element)
        browser, session, _page, query = _build(locator)
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "native input"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_semantic_checkbox_refuses_hidden_target(self):
        element = _Element(
            {
                "connected": True,
                "visible": False,
                "tag": "input",
                "input_type": "checkbox",
                "native_checkbox": True,
            }
        )
        locator = _Locator(count=1, element=element)
        browser, session, _page, query = _build(locator)
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "not visible"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
