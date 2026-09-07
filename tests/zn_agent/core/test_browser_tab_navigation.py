from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserPlane,
)
from zn_agent.core.semantic_managed_browser import SemanticPlaywrightManagedBrowser


class _Page:
    def __init__(self, url: str, title: str):
        self.url = url
        self._title = title
        self.viewport_size = {"width": 1200, "height": 800}
        self.closed = False
        self.visible = True
        self.context = None
        self.history = [url]
        self.history_index = 0

    def title(self):
        return self._title

    def evaluate(self, expression):
        if expression == "document.readyState":
            return "complete"
        if expression == "document.visibilityState === 'visible'":
            return self.visible
        if expression == "document.visibilityState":
            return "visible" if self.visible else "hidden"
        raise AssertionError(expression)

    def is_closed(self):
        return self.closed

    def goto(self, url, *, wait_until):
        del wait_until
        self.history = self.history[: self.history_index + 1]
        self.history.append(url)
        self.history_index += 1
        self.url = url
        self._title = url.rsplit("/", 1)[-1] or "page"

    def bring_to_front(self):
        if self.context is not None:
            for page in self.context.pages:
                page.visible = page is self

    def close(self):
        self.closed = True
        self.visible = False

    def go_back(self, *, wait_until):
        del wait_until
        if self.history_index > 0:
            self.history_index -= 1
            self.url = self.history[self.history_index]

    def go_forward(self, *, wait_until):
        del wait_until
        if self.history_index + 1 < len(self.history):
            self.history_index += 1
            self.url = self.history[self.history_index]

    def reload(self, *, wait_until):
        del wait_until
        return None


class _Context:
    def __init__(self, initial: _Page):
        self.pages = [initial]
        initial.context = self
        self._initial_claimed = False

    def set_default_navigation_timeout(self, value):
        return None

    def set_default_timeout(self, value):
        return None

    def route(self, pattern, handler):
        return None

    def route_web_socket(self, pattern, handler):
        return None

    def new_page(self):
        if not self._initial_claimed:
            self._initial_claimed = True
            return self.pages[0]
        page = _Page("about:blank", "")
        page.context = self
        for existing in self.pages:
            existing.visible = False
        self.pages.append(page)
        return page

    def close(self):
        return None


class _Browser:
    version = "fake"

    def __init__(self, context):
        self.context = context

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
    def __init__(self, context):
        self.chromium = _Chromium(_Browser(context))

    def stop(self):
        return None


class _Starter:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


class _UserLikeBrowser(SemanticPlaywrightManagedBrowser):
    name = "fake-user-cdp"
    plane = BrowserPlane.USER


def _build(*, user=False):
    initial = _Page("https://example.com/one", "One")
    context = _Context(initial)
    playwright = _Playwright(context)
    cls = _UserLikeBrowser if user else SemanticPlaywrightManagedBrowser
    browser = cls(
        playwright_factory=lambda: _Starter(playwright),
        url_checker=lambda url, **kwargs: True,
    )
    permission = BrowserPermissionContext(
        allow_navigation=True,
        allow_page_interaction=True,
        allowed_origins=("https://example.com",),
    )
    session = browser.open_session(permission=permission, headless=True)
    return browser, session, permission, context


def _authority(action, observation, permission):
    return BrowserActionAuthority.from_observation(
        action,
        observation,
        permission,
    )


class BrowserTabNavigationTests(unittest.TestCase):
    def test_open_switch_and_close_zn_created_tab(self):
        browser, session, permission, _context = _build()
        try:
            initial = browser.observe(session.session_id)
            open_action = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.OPEN_TAB,
                page_id=initial.page_id,
                args={"url": "https://example.com/two"},
                expected={"url_equals": "https://example.com/two"},
            )
            opened = browser.act(
                open_action,
                _authority(open_action, initial, permission),
            )
            self.assertTrue(opened.success, opened.error)
            self.assertEqual(opened.page_id, "page-2")
            self.assertEqual(opened.data["ownership"], "zn_created")

            old_tab = browser.observe(session.session_id, page_id="page-1")
            switch = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.SWITCH_TAB,
                page_id="page-1",
            )
            switched = browser.act(
                switch,
                _authority(switch, old_tab, permission),
            )
            self.assertTrue(switched.success, switched.error)
            self.assertEqual(switched.page_id, "page-1")

            new_tab = browser.observe(session.session_id, page_id="page-2")
            close = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.CLOSE_TAB,
                page_id="page-2",
            )
            closed = browser.act(
                close,
                _authority(close, new_tab, permission),
            )
            self.assertTrue(closed.success, closed.error)
            workspace = browser.observe_browser_workspace(session.session_id)
            self.assertEqual([tab.page_id for tab in workspace.tabs], ["page-1"])
        finally:
            browser.close()

    def test_user_existing_tab_cannot_be_closed(self):
        browser, session, permission, _context = _build(user=True)
        try:
            observed = browser.observe(session.session_id)
            close = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.CLOSE_TAB,
                page_id=observed.page_id,
            )
            evidence = browser.act(
                close,
                _authority(close, observed, permission),
            )
            self.assertFalse(evidence.success)
            self.assertIn("did not create", evidence.error or "")
            self.assertEqual(
                [tab.ownership for tab in browser.observe_browser_workspace(session.session_id).tabs],
                ["user_existing"],
            )
        finally:
            browser.close()

    def test_back_forward_and_reload_require_fresh_verified_urls(self):
        browser, session, permission, _context = _build()
        try:
            first = browser.observe(session.session_id)
            navigate = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.NAVIGATE,
                page_id=first.page_id,
                args={"url": "https://example.com/two"},
                expected={"url_equals": "https://example.com/two"},
            )
            nav_evidence = browser.act(
                navigate,
                _authority(navigate, first, permission),
            )
            self.assertTrue(nav_evidence.success, nav_evidence.error)

            at_two = browser.observe(session.session_id)
            back = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.BACK,
                page_id=at_two.page_id,
                expected={"url_equals": "https://example.com/one"},
            )
            back_evidence = browser.act(
                back,
                _authority(back, at_two, permission),
            )
            self.assertTrue(back_evidence.success, back_evidence.error)

            at_one = browser.observe(session.session_id)
            forward = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.FORWARD,
                page_id=at_one.page_id,
                expected={"url_equals": "https://example.com/two"},
            )
            forward_evidence = browser.act(
                forward,
                _authority(forward, at_one, permission),
            )
            self.assertTrue(forward_evidence.success, forward_evidence.error)

            at_two_again = browser.observe(session.session_id)
            reload = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.RELOAD,
                page_id=at_two_again.page_id,
            )
            reload_evidence = browser.act(
                reload,
                _authority(reload, at_two_again, permission),
            )
            self.assertTrue(reload_evidence.success, reload_evidence.error)
            self.assertEqual(reload_evidence.url_after, "https://example.com/two")
        finally:
            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
