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
    def __init__(self, page):
        self.page = page
        self.disposed = False

    def evaluate(self, expression, arg=None):
        if self.disposed:
            raise RuntimeError("disposed element")
        if "native_textbox" in expression:
            return {
                "connected": True,
                "visible": True,
                "tag": "input",
                "input_type": self.page.input_type,
                "native_textbox": self.page.input_type == "text",
                "is_password": self.page.input_type == "password",
                "disabled": self.page.disabled,
                "read_only": self.page.read_only,
            }
        if "element === other" in expression:
            return isinstance(arg, _Element) and self.page is arg.page
        raise AssertionError("unexpected element expression")

    def dispose(self):
        self.disposed = True


class _Locator:
    def __init__(self, page):
        self.page = page

    def count(self):
        return self.page.count

    def element_handle(self):
        return _Element(self.page)


class _Page:
    def __init__(self, *, count=1, input_type="text", disabled=False, read_only=False):
        self.url = "https://example.com/form"
        self.viewport_size = {"width": 800, "height": 600}
        self.count = count
        self.input_type = input_type
        self.disabled = disabled
        self.read_only = read_only
        self.role_calls = []

    def get_by_role(self, role, *, name, exact):
        self.role_calls.append((role, name, exact))
        return _Locator(self)

    def title(self):
        return "Form"

    def evaluate(self, expression):
        if expression == "document.readyState":
            return "complete"
        raise AssertionError(expression)

    def is_closed(self):
        return False


class _Context:
    def __init__(self, page):
        self.pages = [page]
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


def _build(**page_kwargs):
    page = _Page(**page_kwargs)
    playwright = _Playwright(page)
    browser = SemanticPlaywrightManagedBrowser(
        playwright_factory=lambda: _Starter(playwright),
        url_checker=lambda url, **kwargs: True,
    )
    session = browser.open_session(
        permission=BrowserPermissionContext(
            allow_page_interaction=True,
            allow_text_entry=True,
        ),
        headless=True,
    )
    query = BrowserTargetQuery(
        kind=BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
        value="Search",
    )
    return browser, session, page, query


class SemanticManagedBrowserTextboxTests(unittest.TestCase):
    def test_exact_named_textbox_binds_without_value_disclosure(self) -> None:
        browser, session, page, query = _build()
        try:
            observed = browser.observe_target(session.session_id, query)
            self.assertIsNotNone(observed.target)
            assert observed.target is not None
            self.assertIs(observed.target.kind, BrowserTargetKind.ACCESSIBILITY_NODE)
            self.assertEqual(observed.target.role, "textbox")
            self.assertEqual(observed.target.name, "Search")
            self.assertEqual(
                observed.target.selector_hint,
                "accessible_textbox_name:exact",
            )
            self.assertEqual(page.role_calls, [("textbox", "Search", True)])
        finally:
            browser.close()

    def test_named_textbox_requires_unique_exact_match(self) -> None:
        browser, session, _page, query = _build(count=2)
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "ambiguous"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_named_textbox_refuses_password_disabled_and_read_only_targets(self) -> None:
        cases = (
            ({"input_type": "password"}, "password"),
            ({"disabled": True}, "disabled"),
            ({"read_only": True}, "read-only"),
        )
        for page_kwargs, expected in cases:
            with self.subTest(expected=expected):
                browser, session, _page, query = _build(**page_kwargs)
                try:
                    with self.assertRaisesRegex(ManagedBrowserError, expected):
                        browser.observe_target(session.session_id, query)
                finally:
                    browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
