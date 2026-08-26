from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
)
from zn_agent.core.managed_browser import ManagedBrowserError, PlaywrightManagedBrowser


class _FakeRequest:
    def __init__(self, url: str):
        self.url = url


class _FakeRoute:
    def __init__(self, url: str):
        self.request = _FakeRequest(url)
        self.continued = False
        self.aborted = False
        self.error_code = None

    def continue_(self):
        self.continued = True

    def abort(self, *, error_code=None):
        self.aborted = True
        self.error_code = error_code


class _FakeWebSocketRoute:
    def __init__(self, url: str):
        self.url = url
        self.connected = False
        self.closed = False
        self.close_code = None

    def connect_to_server(self):
        self.connected = True

    def close(self, *, code=None, reason=None):
        self.closed = True
        self.close_code = code
        self.close_reason = reason


class _FakePage:
    def __init__(self):
        self.url = "about:blank"
        self._title = ""
        self._ready = "complete"
        self.viewport_size = {"width": 1280, "height": 720}
        self.closed = False
        self.goto_calls = []

    def title(self):
        return self._title

    def evaluate(self, expression):
        if expression != "document.readyState":
            raise AssertionError("unexpected evaluate expression")
        return self._ready

    def goto(self, url, *, wait_until):
        self.goto_calls.append((url, wait_until))
        self.url = url
        self._title = "Fixture"
        self._ready = "interactive"

    def is_closed(self):
        return self.closed


class _FakeContext:
    def __init__(self):
        self.page = _FakePage()
        self.route_handler = None
        self.websocket_handler = None
        self.navigation_timeout = None
        self.action_timeout = None
        self.closed = False

    def set_default_navigation_timeout(self, value):
        self.navigation_timeout = value

    def set_default_timeout(self, value):
        self.action_timeout = value

    def route(self, pattern, handler):
        self.route_pattern = pattern
        self.route_handler = handler

    def route_web_socket(self, pattern, handler):
        self.websocket_pattern = pattern
        self.websocket_handler = handler

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class _FakeBrowser:
    version = "fake-1"

    def __init__(self):
        self.context = _FakeContext()
        self.new_context_kwargs = None
        self.closed = False

    def new_context(self, **kwargs):
        self.new_context_kwargs = kwargs
        return self.context

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, browser):
        self.browser = browser
        self.launch_headless = None

    def launch(self, *, headless):
        self.launch_headless = headless
        return self.browser


class _FakePlaywright:
    def __init__(self):
        self.browser = _FakeBrowser()
        self.chromium = _FakeChromium(self.browser)
        self.stopped = False

    def stop(self):
        self.stopped = True


class _FakeStarter:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


class ManagedBrowserTests(unittest.TestCase):
    def _build(self, *, permission=None, checker=None):
        playwright = _FakePlaywright()
        adapter = PlaywrightManagedBrowser(
            playwright_factory=lambda: _FakeStarter(playwright),
            url_checker=checker or (lambda url, **kwargs: True),
            navigation_timeout_ms=5000,
            action_timeout_ms=3000,
        )
        identity = adapter.open_session(permission=permission, headless=True)
        return adapter, playwright, identity

    def test_open_session_is_ephemeral_and_blocks_service_workers_and_downloads(self):
        adapter, playwright, identity = self._build()
        try:
            self.assertEqual(identity.profile_scope, "ephemeral")
            self.assertTrue(playwright.chromium.launch_headless)
            self.assertEqual(
                playwright.browser.new_context_kwargs,
                {"accept_downloads": False, "service_workers": "block"},
            )
            observation = adapter.observe(identity.session_id)
            self.assertEqual(observation.url, "about:blank")
            self.assertEqual(observation.metadata["service_workers"], "blocked")
            self.assertNotIn("content", observation.metadata)
            self.assertNotIn("html", observation.metadata)
        finally:
            adapter.close()
        self.assertTrue(playwright.browser.context.closed)
        self.assertTrue(playwright.browser.closed)
        self.assertTrue(playwright.stopped)

    def test_download_or_upload_permission_is_rejected_until_file_authority_exists(self):
        adapter = PlaywrightManagedBrowser(
            playwright_factory=lambda: _FakeStarter(_FakePlaywright()),
            url_checker=lambda url, **kwargs: True,
        )
        with self.assertRaises(ManagedBrowserError):
            adapter.open_session(permission=BrowserPermissionContext(allow_downloads=True))
        with self.assertRaises(ManagedBrowserError):
            adapter.open_session(permission=BrowserPermissionContext(allow_uploads=True))

    def test_navigation_requires_fresh_authority_and_returns_observed_effect(self):
        permission = BrowserPermissionContext(allowed_origins=("https://example.com",))
        adapter, playwright, identity = self._build(permission=permission)
        try:
            observation = adapter.observe(identity.session_id)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observation.page_id,
                kind=BrowserActionKind.NAVIGATE,
                args={"url": "https://example.com/next"},
                expected={"url_equals": "https://example.com/next"},
            )
            authority = BrowserActionAuthority.from_observation(action, observation, permission)
            effect = adapter.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.url_before, "about:blank")
            self.assertEqual(effect.url_after, "https://example.com/next")
            self.assertEqual(effect.postcondition, "safe_current_page_observed")
            self.assertEqual(
                playwright.browser.context.page.goto_calls,
                [("https://example.com/next", "domcontentloaded")],
            )
        finally:
            adapter.close()

    def test_stale_authority_fails_before_navigation(self):
        permission = BrowserPermissionContext(allowed_origins=("https://example.com",))
        adapter, playwright, identity = self._build(permission=permission)
        try:
            observation = adapter.observe(identity.session_id)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observation.page_id,
                kind=BrowserActionKind.NAVIGATE,
                args={"url": "https://example.com/"},
            )
            authority = BrowserActionAuthority(
                action_id=action.action_id,
                session_id=identity.session_id,
                issued_at="now",
                observation_captured_at="stale-observation",
                permission=permission,
                page_id=observation.page_id,
            )
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("stale", effect.error or "")
            self.assertEqual(playwright.browser.context.page.goto_calls, [])
        finally:
            adapter.close()

    def test_network_route_and_websocket_route_share_zn_url_boundary(self):
        def checker(url, **kwargs):
            return "blocked.example" not in url

        permission = BrowserPermissionContext()
        adapter, playwright, identity = self._build(permission=permission, checker=checker)
        try:
            context = playwright.browser.context
            allowed = _FakeRoute("https://allowed.example/a")
            blocked = _FakeRoute("https://blocked.example/a")
            context.route_handler(allowed)
            context.route_handler(blocked)
            self.assertTrue(allowed.continued)
            self.assertTrue(blocked.aborted)
            self.assertEqual(blocked.error_code, "blockedbyclient")

            ws_allowed = _FakeWebSocketRoute("wss://allowed.example/socket")
            ws_blocked = _FakeWebSocketRoute("wss://blocked.example/socket")
            context.websocket_handler(ws_allowed)
            context.websocket_handler(ws_blocked)
            self.assertTrue(ws_allowed.connected)
            self.assertTrue(ws_blocked.closed)
            self.assertEqual(ws_blocked.close_code, 1008)
        finally:
            adapter.close()

    def test_origin_policy_blocks_navigation_before_browser_dispatch(self):
        permission = BrowserPermissionContext(allowed_origins=("https://allowed.example",))
        adapter, playwright, identity = self._build(permission=permission)
        try:
            observation = adapter.observe(identity.session_id)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observation.page_id,
                kind=BrowserActionKind.NAVIGATE,
                args={"url": "https://other.example/"},
            )
            authority = BrowserActionAuthority.from_observation(action, observation, permission)
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertEqual(playwright.browser.context.page.goto_calls, [])
        finally:
            adapter.close()

    def test_unimplemented_mutation_returns_failure_evidence_without_dispatch(self):
        adapter, _playwright, identity = self._build()
        try:
            observation = adapter.observe(identity.session_id)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observation.page_id,
                kind=BrowserActionKind.CLICK,
            )
            authority = BrowserActionAuthority.from_observation(
                action,
                observation,
                BrowserPermissionContext(),
            )
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("not implemented", effect.error or "")
        finally:
            adapter.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
