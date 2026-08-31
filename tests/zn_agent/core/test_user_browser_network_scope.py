from __future__ import annotations

import unittest

from zn_agent.core.browser import BrowserPermissionContext
from zn_agent.core.user_browser import AuthorizedCDPUserBrowser, UserBrowserBridgeError


class _Page:
    url = "http://127.0.0.1:8080/admin"
    viewport_size = {"width": 800, "height": 600}

    def evaluate(self, expression):
        if expression == "document.visibilityState === 'visible'":
            return True
        if expression == "document.readyState !== undefined":
            return True
        if expression == "document.readyState":
            return "complete"
        raise AssertionError(expression)

    def title(self):
        return "Private admin"

    def is_closed(self):
        return False


class _Context:
    def __init__(self):
        self.pages = [_Page()]


class _Browser:
    version = "fake"

    def __init__(self):
        self.contexts = [_Context()]


class _Chromium:
    def __init__(self):
        self.browser = _Browser()

    def connect_over_cdp(self, endpoint):
        return self.browser


class _Playwright:
    def __init__(self):
        self.chromium = _Chromium()
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1


class _Starter:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


def _adapter():
    playwright = _Playwright()
    adapter = AuthorizedCDPUserBrowser(
        endpoint="http://127.0.0.1:9222",
        playwright_factory=lambda: _Starter(playwright),
        url_checker=lambda url, *, allow_private=False: bool(allow_private),
    )
    return adapter, playwright


class AuthorizedUserBrowserNetworkScopeTests(unittest.TestCase):
    def test_private_current_page_is_rejected_without_private_network_authority(self) -> None:
        adapter, playwright = _adapter()
        permission = BrowserPermissionContext(
            allow_page_interaction=True,
            allowed_origins=("http://127.0.0.1:8080",),
            allow_private_network=False,
        )
        with self.assertRaisesRegex(UserBrowserBridgeError, "network boundary"):
            adapter.open_session(permission=permission)
        self.assertEqual(playwright.stop_calls, 1)
        self.assertFalse(adapter._sessions)

    def test_private_current_page_is_observable_when_explicitly_authorized(self) -> None:
        adapter, playwright = _adapter()
        permission = BrowserPermissionContext(
            allow_page_interaction=True,
            allowed_origins=("http://127.0.0.1:8080",),
            allow_private_network=True,
        )
        session = adapter.open_session(permission=permission)
        try:
            observed = adapter.observe(session.session_id)
            self.assertEqual(observed.url, "http://127.0.0.1:8080/admin")
            self.assertEqual(
                observed.metadata["network_policy"],
                "user_browser_unmodified; ZN observation/action scope enforced",
            )
        finally:
            adapter.close_session(session.session_id)
        self.assertEqual(playwright.stop_calls, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
