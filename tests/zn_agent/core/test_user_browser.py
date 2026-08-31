from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserPermissionContext,
    BrowserPlane,
    BrowserTargetKind,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from zn_agent.core.user_browser import (
    AuthorizedCDPUserBrowser,
    UserBrowserBridgeError,
)


class _Element:
    def __init__(self, page):
        self.page = page
        self.disposed = False

    def evaluate(self, expression, arg=None):
        if self.disposed:
            raise RuntimeError("disposed")
        if "native_textbox" in expression:
            return {
                "connected": True,
                "visible": True,
                "tag": "input",
                "input_type": "text",
                "native_textbox": True,
                "is_password": False,
                "disabled": False,
                "read_only": False,
            }
        if "element === other" in expression:
            return isinstance(arg, _Element) and self.page is arg.page
        raise AssertionError(expression)

    def dispose(self):
        self.disposed = True


class _Locator:
    def __init__(self, page):
        self.page = page

    def count(self):
        return self.page.target_count

    def element_handle(self):
        return _Element(self.page)


class _Page:
    def __init__(self, *, url: str, title: str, visible: bool, target_count: int = 1):
        self.url = url
        self._title = title
        self.visible = visible
        self.target_count = target_count
        self.viewport_size = {"width": 1280, "height": 720}
        self.role_calls = []

    def evaluate(self, expression):
        if expression == "document.visibilityState === 'visible'":
            return self.visible
        if expression == "document.readyState !== undefined":
            return True
        if expression == "document.readyState":
            return "complete"
        raise AssertionError(expression)

    def get_by_role(self, role, *, name, exact):
        self.role_calls.append((role, name, exact))
        return _Locator(self)

    def title(self):
        return self._title

    def is_closed(self):
        return False


class _Context:
    def __init__(self, pages):
        self.pages = list(pages)
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


class _Browser:
    version = "123.0"

    def __init__(self, contexts):
        self.contexts = list(contexts)
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


class _Chromium:
    def __init__(self, browser):
        self.browser = browser
        self.endpoints = []

    def connect_over_cdp(self, endpoint):
        self.endpoints.append(endpoint)
        return self.browser


class _Playwright:
    def __init__(self, browser):
        self.chromium = _Chromium(browser)
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1


class _Starter:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


def _build(pages):
    context = _Context(pages)
    provider_browser = _Browser([context])
    playwright = _Playwright(provider_browser)
    adapter = AuthorizedCDPUserBrowser(
        endpoint="http://127.0.0.1:9222",
        playwright_factory=lambda: _Starter(playwright),
        url_checker=lambda url, **kwargs: True,
    )
    return adapter, playwright, provider_browser, context


class AuthorizedCDPUserBrowserTests(unittest.TestCase):
    def test_endpoint_must_be_explicit_loopback_without_credentials(self) -> None:
        invalid = (
            "",
            "http://example.com:9222",
            "http://user:secret@127.0.0.1:9222",
            "http://127.0.0.1",
            "file:///tmp/devtools",
        )
        for endpoint in invalid:
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    AuthorizedCDPUserBrowser(endpoint=endpoint)

        for endpoint in (
            "http://127.0.0.1:9222",
            "http://localhost:9222",
            "ws://[::1]:9222/devtools/browser/test",
        ):
            with self.subTest(endpoint=endpoint):
                adapter = AuthorizedCDPUserBrowser(endpoint=endpoint)
                self.assertEqual(adapter.endpoint, endpoint)

    def test_attach_adopts_unique_visible_existing_tab_and_semantic_target(self) -> None:
        hidden = _Page(
            url="https://example.test/background",
            title="Background",
            visible=False,
        )
        current = _Page(
            url="https://example.test/account",
            title="Account",
            visible=True,
        )
        adapter, playwright, provider_browser, context = _build([hidden, current])
        permission = BrowserPermissionContext(
            allow_page_interaction=True,
            allow_text_entry=True,
            allowed_origins=("https://example.test",),
        )

        session = adapter.open_session(permission=permission)
        try:
            self.assertIs(session.plane, BrowserPlane.USER)
            self.assertEqual(session.profile_scope, "user_existing")
            self.assertEqual(session.provider, "playwright-user-cdp")
            self.assertEqual(
                playwright.chromium.endpoints,
                ["http://127.0.0.1:9222"],
            )

            observed = adapter.observe(session.session_id)
            self.assertEqual(observed.url, "https://example.test/account")
            self.assertEqual(observed.title, "Account")
            self.assertEqual(observed.metadata["profile_scope"], "user_existing")
            self.assertEqual(
                observed.metadata["service_workers"],
                "user_owned_unmodified",
            )
            self.assertEqual(
                observed.metadata["attachment"],
                "authorized_existing_session",
            )

            target = adapter.observe_target(
                session.session_id,
                BrowserTargetQuery(
                    kind=BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
                    value="Account search",
                ),
            )
            self.assertIsNotNone(target.target)
            assert target.target is not None
            self.assertIs(target.target.kind, BrowserTargetKind.ACCESSIBILITY_NODE)
            self.assertEqual(target.target.role, "textbox")
            self.assertEqual(target.target.name, "Account search")
            self.assertEqual(
                current.role_calls,
                [("textbox", "Account search", True)],
            )
        finally:
            adapter.close_session(session.session_id)

        self.assertEqual(playwright.stop_calls, 1)
        self.assertEqual(provider_browser.close_calls, 0)
        self.assertEqual(context.close_calls, 0)

    def test_attach_refuses_ambiguous_visible_tabs_without_closing_user_browser(self) -> None:
        pages = [
            _Page(url="https://one.test", title="One", visible=True),
            _Page(url="https://two.test", title="Two", visible=True),
        ]
        adapter, playwright, provider_browser, context = _build(pages)
        with self.assertRaisesRegex(UserBrowserBridgeError, "multiple visible pages"):
            adapter.open_session()
        self.assertEqual(playwright.stop_calls, 1)
        self.assertEqual(provider_browser.close_calls, 0)
        self.assertEqual(context.close_calls, 0)

    def test_attach_requires_exactly_one_existing_context(self) -> None:
        page = _Page(url="https://example.test", title="Example", visible=True)
        contexts = [_Context([page]), _Context([page])]
        provider_browser = _Browser(contexts)
        playwright = _Playwright(provider_browser)
        adapter = AuthorizedCDPUserBrowser(
            endpoint="http://127.0.0.1:9222",
            playwright_factory=lambda: _Starter(playwright),
        )
        with self.assertRaisesRegex(UserBrowserBridgeError, "exactly one"):
            adapter.open_session()
        self.assertEqual(playwright.stop_calls, 1)
        self.assertEqual(provider_browser.close_calls, 0)
        self.assertEqual(sum(context.close_calls for context in contexts), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
