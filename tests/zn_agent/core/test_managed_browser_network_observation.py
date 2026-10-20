from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
)
from zn_agent.core.managed_browser import PlaywrightManagedBrowser


class _FakeRequest:
    def __init__(self, *, url, method="GET", failure=None, resource_type="xhr"):
        self._url = url
        self._method = method
        self._failure = failure
        self._resource_type = resource_type

    @property
    def url(self):
        return self._url

    @property
    def method(self):
        return self._method

    @property
    def resource_type(self):
        return self._resource_type

    def failure(self):
        return self._failure


class _FakeResponse:
    def __init__(self, *, status, request):
        self._status = status
        self._request = request

    def status(self):
        return self._status

    @property
    def request(self):
        return self._request


class _FakePage:
    def __init__(self):
        self.url = "about:blank"
        self._title = ""
        self._ready = "complete"
        self.viewport_size = {"width": 1280, "height": 720}
        self.closed = False
        self.event_handlers = {}
        self.goto_error = None

    def title(self):
        return self._title

    def evaluate(self, expression, arg=None):
        if expression == "document.readyState" and arg is None:
            return self._ready
        raise AssertionError("unexpected page evaluate expression")

    def on(self, event, handler):
        if event not in ("console", "pageerror", "requestfailed", "response"):
            raise AssertionError(f"unexpected event subscription: {event!r}")
        self.event_handlers[event] = handler

    def goto(self, url, *, wait_until=None):
        if self.goto_error is not None:
            failed = self.event_handlers.get("requestfailed")
            if failed is not None:
                failed(
                    _FakeRequest(
                        url=url,
                        failure="net::ERR_CONNECTION_REFUSED",
                        resource_type="document",
                    )
                )
            raise self.goto_error
        self.url = url

    def fire_request_failed(self, request):
        handler = self.event_handlers.get("requestfailed")
        if handler is None:
            raise AssertionError("no requestfailed handler installed")
        handler(request)

    def fire_response(self, response):
        handler = self.event_handlers.get("response")
        if handler is None:
            raise AssertionError("no response handler installed")
        handler(response)

    def is_closed(self):
        return self.closed


class _FakeContext:
    def __init__(self):
        self.page = _FakePage()
        self.pages = None

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


class ManagedBrowserNetworkObservationTests(unittest.TestCase):
    def _build(self):
        playwright = _FakePlaywright()
        adapter = PlaywrightManagedBrowser(
            playwright_factory=lambda: _FakeStarter(playwright),
            url_checker=lambda url, **kwargs: True,
        )
        identity = adapter.open_session(
            permission=BrowserPermissionContext(
                allow_navigation=True, allow_page_interaction=True
            ),
            headless=True,
        )
        page = playwright.browser.context.page
        page.url = "https://example.com/app"
        page._title = "App"
        return adapter, playwright, identity

    def _network(self, adapter, identity, *, page_id=""):
        return adapter.observe(identity.session_id, page_id=page_id).network

    def test_no_failures_gives_empty_network_field(self):
        adapter, _playwright, identity = self._build()
        try:
            snapshot = self._network(adapter, identity)
            self.assertEqual(snapshot["total_count"], 0)
            self.assertEqual(snapshot["kept_count"], 0)
            self.assertEqual(snapshot["dropped_count"], 0)
            self.assertEqual(snapshot["failed_requests"], [])
        finally:
            adapter.close()

    def test_requestfailed_is_visible_in_observation(self):
        adapter, playwright, identity = self._build()
        try:
            page = playwright.browser.context.page
            page.fire_request_failed(
                _FakeRequest(
                    url="https://cdn.example.com/app.js",
                    failure="net::ERR_NAME_NOT_RESOLVED",
                )
            )
            snapshot = self._network(adapter, identity)
            self.assertEqual(snapshot["total_count"], 1)
            self.assertEqual(snapshot["kept_count"], 1)
            entry = snapshot["failed_requests"][0]
            self.assertEqual(entry["kind"], "requestfailed")
            self.assertEqual(entry["method"], "GET")
            self.assertEqual(entry["url"], "https://cdn.example.com/app.js")
            self.assertIsNone(entry["status"])
            self.assertEqual(entry["error"], "net::ERR_NAME_NOT_RESOLVED")
            self.assertEqual(entry["resource_type"], "xhr")
            self.assertIn("captured_at", entry)
        finally:
            adapter.close()

    def test_query_params_fragments_and_tokens_are_stripped(self):
        adapter, playwright, identity = self._build()
        try:
            page = playwright.browser.context.page
            raw = (
                "https://user:s3cret@example.com/api/data"
                "?api_key=deadbeefcafe1234&next=%2Fhome"
                "#section"
            )
            page.fire_request_failed(
                _FakeRequest(url=raw, failure="net::ERR_ABORTED")
            )
            snapshot = self._network(adapter, identity)
            entry = snapshot["failed_requests"][0]
            self.assertNotIn("api_key", entry["url"])
            self.assertNotIn("deadbeefcafe1234", entry["url"])
            self.assertNotIn("s3cret", entry["url"])
            self.assertNotIn("#section", entry["url"])
            self.assertNotIn("?", entry["url"])
            # The useful part of the URL survives for debugging.
            self.assertTrue(
                entry["url"].endswith("@example.com/api/data"), entry["url"]
            )
            self.assertTrue(
                entry["url"].startswith("https://"), entry["url"]
            )
        finally:
            adapter.close()

    def test_error_responses_recorded_successes_ignored(self):
        adapter, playwright, identity = self._build()
        try:
            page = playwright.browser.context.page
            page.fire_response(
                _FakeResponse(
                    status=200,
                    request=_FakeRequest(url="https://example.com/ok.png"),
                )
            )
            page.fire_response(
                _FakeResponse(
                    status=301,
                    request=_FakeRequest(url="https://example.com/moved"),
                )
            )
            page.fire_response(
                _FakeResponse(
                    status=404,
                    request=_FakeRequest(
                        url="https://example.com/missing.css?cache=1",
                        resource_type="stylesheet",
                    ),
                )
            )
            page.fire_response(
                _FakeResponse(
                    status=500,
                    request=_FakeRequest(
                        url="https://api.example.com/rpc",
                        method="POST",
                    ),
                )
            )
            snapshot = self._network(adapter, identity)
            self.assertEqual(snapshot["total_count"], 2)
            self.assertEqual(len(snapshot["failed_requests"]), 2)
            first, second = snapshot["failed_requests"]
            self.assertEqual(first["kind"], "response_error")
            self.assertEqual(first["status"], 404)
            self.assertEqual(first["url"], "https://example.com/missing.css")
            self.assertEqual(first["resource_type"], "stylesheet")
            self.assertEqual(second["status"], 500)
            self.assertEqual(second["method"], "POST")
            self.assertEqual(second["error"], "http_status_500")
        finally:
            adapter.close()

    def test_bound_drops_oldest_and_counts_dropped(self):
        adapter, playwright, identity = self._build()
        try:
            page = playwright.browser.context.page
            for index in range(25):
                page.fire_request_failed(
                    _FakeRequest(
                        url=f"https://cdn.example.com/app-{index}.js",
                        failure="net::ERR_ABORTED",
                    )
                )
            snapshot = self._network(adapter, identity)
            self.assertEqual(snapshot["total_count"], 25)
            self.assertEqual(snapshot["kept_count"], 20)
            self.assertEqual(snapshot["dropped_count"], 5)
            self.assertEqual(len(snapshot["failed_requests"]), 5)
            self.assertTrue(
                snapshot["failed_requests"][-1]["url"].endswith("app-24.js")
            )
            self.assertTrue(
                snapshot["failed_requests"][0]["url"].endswith("app-20.js")
            )
        finally:
            adapter.close()

    def test_navigation_failure_carries_network_summary(self):
        adapter, playwright, identity = self._build()
        try:
            page = playwright.browser.context.page
            page.goto_error = RuntimeError("net::ERR_CONNECTION_REFUSED")
            observation = adapter.observe(identity.session_id)
            action = BrowserAction.create(
                session_id=identity.session_id,
                kind=BrowserActionKind.NAVIGATE,
                page_id=observation.page_id,
                args={"url": "https://down.example.com/?token=deadbeef"},
            )
            authority = BrowserActionAuthority.from_observation(
                action,
                observation,
                BrowserPermissionContext(
                    allow_navigation=True, allow_page_interaction=True
                ),
            )
            evidence = adapter.act(action, authority)
            self.assertFalse(evidence.success)
            network = evidence.data.get("network") or {}
            self.assertEqual(network.get("total_count"), 1)
            entry = (network.get("failed_requests") or [None])[0]
            self.assertIsNotNone(entry)
            self.assertEqual(entry["kind"], "requestfailed")
            self.assertEqual(entry["error"], "net::ERR_CONNECTION_REFUSED")
            # Even in the failure evidence the URL is desensitized.
            self.assertEqual(entry["url"], "https://down.example.com/")
            self.assertNotIn("deadbeef", entry["url"])
        finally:
            adapter.close()

    def test_handler_failures_never_break_observation(self):
        adapter, playwright, identity = self._build()
        try:
            page = playwright.browser.context.page

            class _ExplodingRequest:
                @property
                def url(self):
                    raise RuntimeError("provider url blew up")

                @property
                def method(self):
                    raise RuntimeError("provider method blew up")

                @property
                def resource_type(self):
                    raise RuntimeError("provider resource_type blew up")

                def failure(self):
                    raise RuntimeError("provider failure blew up")

            page.fire_request_failed(_ExplodingRequest())
            snapshot = self._network(adapter, identity)
            # The record failed, but observe() still works.
            self.assertEqual(snapshot["total_count"], 0)
        finally:
            adapter.close()

    def test_failures_are_isolated_per_page(self):
        adapter, playwright, identity = self._build()
        try:
            context = playwright.browser.context
            first_page = context.page
            second_page = _FakePage()
            context.pages = [first_page, second_page]
            observed = adapter.observe(identity.session_id)
            second_page_id = [
                pid
                for pid in observed.metadata["page_ids"]
                if pid != observed.page_id
            ][0]
            first_page.fire_request_failed(
                _FakeRequest(
                    url="https://cdn.example.com/app.js",
                    failure="net::ERR_ABORTED",
                )
            )
            first_snapshot = self._network(
                adapter, identity, page_id=observed.page_id
            )
            second_snapshot = self._network(
                adapter, identity, page_id=second_page_id
            )
            self.assertEqual(first_snapshot["total_count"], 1)
            self.assertEqual(second_snapshot["total_count"], 0)
        finally:
            adapter.close()

    def test_closed_page_eviction_drops_network_state(self):
        adapter, playwright, identity = self._build()
        try:
            context = playwright.browser.context
            first_page = context.page
            second_page = _FakePage()
            context.pages = [first_page, second_page]
            adapter.observe(identity.session_id)  # registers the second page
            first_page.fire_request_failed(
                _FakeRequest(
                    url="https://cdn.example.com/app.js",
                    failure="net::ERR_ABORTED",
                )
            )
            first_page.closed = True
            context.pages = [second_page]
            observed = adapter.observe(identity.session_id)
            self.assertEqual(observed.metadata["page_ids"], [observed.page_id])
            self.assertEqual(observed.network["total_count"], 0)
            self.assertEqual(observed.network["failed_requests"], [])
        finally:
            adapter.close()


if __name__ == "__main__":
    unittest.main()
