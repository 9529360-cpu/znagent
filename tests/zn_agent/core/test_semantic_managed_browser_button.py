from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
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
    def __init__(self, page, generation):
        self.page = page
        self.generation = generation
        self.disposed = False

    def evaluate(self, expression, arg=None):
        if self.disposed:
            raise RuntimeError("disposed element")
        if "native_button" in expression:
            return {
                "connected": True,
                "visible": True,
                "tag": "button",
                "native_button": True,
            }
        if "element === other" in expression:
            return (
                isinstance(arg, _Element)
                and self.page is arg.page
                and self.generation == arg.generation
            )
        raise AssertionError("unexpected element expression")

    def click(self):
        if self.disposed:
            raise RuntimeError("disposed element")
        self.page.click_dispatches += 1
        if not self.page.block_navigation:
            self.page.url = self.page.destination

    def dispose(self):
        self.disposed = True


class _Locator:
    def __init__(self, page, count=1):
        self.page = page
        self._count = count

    def count(self):
        return self._count

    def element_handle(self):
        self.page.handle_calls += 1
        if self.page.replace_before_dispatch and self.page.handle_calls >= 2:
            self.page.node_generation += 1
            self.page.replace_before_dispatch = False
        return _Element(self.page, self.page.node_generation)


class _Page:
    def __init__(self, *, destination: str, count: int = 1):
        self.url = "https://example.com/start"
        self.destination = destination
        self.block_navigation = False
        self.click_dispatches = 0
        self.viewport_size = {"width": 800, "height": 600}
        self.count = count
        self.role_calls = []
        self.handle_calls = 0
        self.node_generation = 1
        self.replace_before_dispatch = False

    def get_by_role(self, role, *, name, exact):
        self.role_calls.append((role, name, exact))
        return _Locator(self, self.count)

    def title(self):
        return "Done" if self.url == self.destination else "Start"

    def evaluate(self, expression):
        if expression == "document.readyState":
            return "complete"
        raise AssertionError(expression)

    def is_closed(self):
        return False


class _Context:
    def __init__(self, page):
        self.page = page
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


def _build(*, destination="https://example.com/done", count=1):
    page = _Page(destination=destination, count=count)
    playwright = _Playwright(page)
    permission = BrowserPermissionContext(
        allow_page_interaction=True,
        allowed_origins=("https://example.com",),
    )
    browser = SemanticPlaywrightManagedBrowser(
        playwright_factory=lambda: _Starter(playwright),
        url_checker=lambda url, **kwargs: True,
    )
    session = browser.open_session(permission=permission, headless=True)
    query = BrowserTargetQuery(
        kind=BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME,
        value="Continue",
    )
    return browser, session, permission, page, query


class SemanticManagedBrowserButtonTests(unittest.TestCase):
    def test_exact_named_native_button_binds_as_accessibility_target(self):
        browser, session, _permission, page, query = _build()
        try:
            observed = browser.observe_target(session.session_id, query)
            self.assertIsNotNone(observed.target)
            assert observed.target is not None
            self.assertIs(observed.target.kind, BrowserTargetKind.ACCESSIBILITY_NODE)
            self.assertEqual(observed.target.role, "button")
            self.assertEqual(observed.target.name, "Continue")
            self.assertEqual(observed.target.selector_hint, "accessible_button_name:exact")
            self.assertEqual(page.role_calls, [("button", "Continue", True)])
        finally:
            browser.close()

    def test_named_button_navigation_requires_unique_exact_match(self):
        browser, session, _permission, _page, query = _build(count=2)
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "ambiguous"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_click_succeeds_only_after_fresh_target_and_exact_url_postcondition(self):
        browser, session, permission, page, query = _build()
        try:
            observed = browser.observe_target(session.session_id, query)
            action = BrowserAction.create(
                session_id=session.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.CLICK,
                target=observed.target,
                expected={"url_equals": "https://example.com/done"},
            )
            authority = BrowserActionAuthority.from_observation(
                action,
                observed,
                permission,
            )
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.url_after, "https://example.com/done")
            self.assertEqual(
                effect.postcondition,
                "url_equals_after_fresh_semantic_button_click",
            )
            self.assertTrue(effect.data["target_revalidated_before_dispatch"])
            self.assertEqual(page.click_dispatches, 1)
            self.assertGreaterEqual(len(page.role_calls), 2)
        finally:
            browser.close()

    def test_replaced_button_before_dispatch_is_safe_for_fresh_reground(self):
        browser, session, permission, page, query = _build()
        try:
            observed = browser.observe_target(session.session_id, query)
            page.replace_before_dispatch = True
            action = BrowserAction.create(
                session_id=session.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.CLICK,
                target=observed.target,
                expected={"url_equals": "https://example.com/done"},
            )
            authority = BrowserActionAuthority.from_observation(
                action,
                observed,
                permission,
            )

            effect = browser.act(action, authority)

            self.assertFalse(effect.success)
            self.assertTrue(effect.allows_fresh_semantic_reground)
            self.assertEqual(effect.data["dispatch_state"], "not_started")
            self.assertTrue(effect.data["requires_fresh_resense"])
            self.assertEqual(page.click_dispatches, 0)
        finally:
            browser.close()

    def test_click_fails_when_button_does_not_reach_expected_url(self):
        browser, session, permission, page, query = _build()
        page.block_navigation = True
        try:
            observed = browser.observe_target(session.session_id, query)
            action = BrowserAction.create(
                session_id=session.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.CLICK,
                target=observed.target,
                expected={"url_equals": "https://example.com/done"},
            )
            authority = BrowserActionAuthority.from_observation(
                action,
                observed,
                permission,
            )
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("postcondition", effect.error or "")
            self.assertEqual(page.click_dispatches, 1)
        finally:
            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
