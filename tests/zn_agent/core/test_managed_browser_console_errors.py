from __future__ import annotations

import unittest

from zn_agent.core.browser import BrowserPermissionContext
from zn_agent.core.managed_browser import PlaywrightManagedBrowser


class _FakeConsoleMessage:
    def __init__(self, *, message_type, text=""):
        self._type = message_type
        self._text = text

    @property
    def type(self):
        return self._type

    @property
    def text(self):
        return self._text


class _FakePageError(Exception):
    def __init__(self, message, stack=None):
        super().__init__(message)
        self.stack = stack


class _FakePage:
    def __init__(self):
        self.url = "about:blank"
        self._title = ""
        self._ready = "complete"
        self.viewport_size = {"width": 1280, "height": 720}
        self.closed = False
        self.event_handlers = {}

    def title(self):
        return self._title

    def evaluate(self, expression, arg=None):
        if expression == "document.readyState" and arg is None:
            return self._ready
        raise AssertionError("unexpected page evaluate expression")

    def on(self, event, handler):
        if event not in ("console", "pageerror"):
            raise AssertionError(f"unexpected event subscription: {event!r}")
        self.event_handlers[event] = handler

    def fire_console(self, message):
        handler = self.event_handlers.get("console")
        if handler is None:
            raise AssertionError("no console handler installed")
        handler(message)

    def fire_pageerror(self, error):
        handler = self.event_handlers.get("pageerror")
        if handler is None:
            raise AssertionError("no pageerror handler installed")
        handler(error)

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


class ManagedBrowserConsoleErrorTests(unittest.TestCase):
    def _build(self):
        playwright = _FakePlaywright()
        adapter = PlaywrightManagedBrowser(
            playwright_factory=lambda: _FakeStarter(playwright),
            url_checker=lambda url, **kwargs: True,
        )
        identity = adapter.open_session(
            permission=BrowserPermissionContext(allow_page_interaction=True),
            headless=True,
        )
        page = playwright.browser.context.page
        page.url = "https://example.com/app"
        page._title = "App"
        return adapter, playwright, identity

    def _console_errors(self, adapter, identity, *, page_id=""):
        return adapter.observe(identity.session_id, page_id=page_id).metadata[
            "console_errors"
        ]

    def test_no_errors_gives_empty_snapshot(self):
        adapter, _playwright, identity = self._build()
        try:
            snapshot = self._console_errors(adapter, identity)
            self.assertEqual(snapshot["total_count"], 0)
            self.assertEqual(snapshot["kept_count"], 0)
            self.assertEqual(snapshot["dropped_count"], 0)
            self.assertEqual(snapshot["recent"], [])
        finally:
            adapter.close()

    def test_console_error_is_visible_in_observation(self):
        adapter, playwright, identity = self._build()
        try:
            page = playwright.browser.context.page
            page.fire_console(
                _FakeConsoleMessage(message_type="error", text="TypeError: boom")
            )
            snapshot = self._console_errors(adapter, identity)
            self.assertEqual(snapshot["total_count"], 1)
            self.assertEqual(snapshot["kept_count"], 1)
            self.assertEqual(snapshot["dropped_count"], 0)
            self.assertEqual(len(snapshot["recent"]), 1)
            entry = snapshot["recent"][0]
            self.assertEqual(entry["kind"], "console")
            self.assertEqual(entry["type"], "error")
            self.assertEqual(entry["text"], "TypeError: boom")
            self.assertIn("captured_at", entry)
        finally:
            adapter.close()

    def test_console_warning_and_info_are_not_recorded(self):
        adapter, playwright, identity = self._build()
        try:
            page = playwright.browser.context.page
            page.fire_console(
                _FakeConsoleMessage(message_type="warning", text="slow page")
            )
            page.fire_console(
                _FakeConsoleMessage(message_type="info", text="hello")
            )
            snapshot = self._console_errors(adapter, identity)
            self.assertEqual(snapshot["total_count"], 0)
            self.assertEqual(snapshot["recent"], [])
        finally:
            adapter.close()

    def test_pageerror_is_visible_in_observation(self):
        adapter, playwright, identity = self._build()
        try:
            page = playwright.browser.context.page
            page.fire_pageerror(
                _FakePageError("TypeError: boom", stack="TypeError: boom\n    at app.js:1:2")
            )
            snapshot = self._console_errors(adapter, identity)
            self.assertEqual(snapshot["total_count"], 1)
            entry = snapshot["recent"][0]
            self.assertEqual(entry["kind"], "pageerror")
            self.assertEqual(entry["type"], "pageerror")
            self.assertEqual(entry["text"], "TypeError: boom\n    at app.js:1:2")
        finally:
            adapter.close()

    def test_secret_in_error_text_is_redacted(self):
        adapter, playwright, identity = self._build()
        try:
            page = playwright.browser.context.page
            raw = "Uncaught TypeError: login failed for api_key=deadbeefcafe1234"
            page.fire_console(_FakeConsoleMessage(message_type="error", text=raw))
            snapshot = self._console_errors(adapter, identity)
            entry = snapshot["recent"][0]
            self.assertNotIn("deadbeefcafe1234", entry["text"])
            self.assertIn("<redacted>", entry["text"])
            # The surrounding (non-secret) context is still useful.
            self.assertIn("Uncaught TypeError", entry["text"])
        finally:
            adapter.close()

    def test_long_error_text_is_truncated(self):
        adapter, playwright, identity = self._build()
        try:
            page = playwright.browser.context.page
            page.fire_console(
                _FakeConsoleMessage(message_type="error", text="x" * 3000)
            )
            snapshot = self._console_errors(adapter, identity)
            entry = snapshot["recent"][0]
            self.assertLessEqual(len(entry["text"]), 1024)
        finally:
            adapter.close()

    def test_bound_drops_oldest_and_counts_dropped(self):
        adapter, playwright, identity = self._build()
        try:
            page = playwright.browser.context.page
            for index in range(25):
                page.fire_console(
                    _FakeConsoleMessage(message_type="error", text=f"error-{index}")
                )
            snapshot = self._console_errors(adapter, identity)
            self.assertEqual(snapshot["total_count"], 25)
            self.assertEqual(snapshot["kept_count"], 20)
            self.assertEqual(snapshot["dropped_count"], 5)
            # Recent window shows only the last five errors.
            self.assertEqual(len(snapshot["recent"]), 5)
            self.assertEqual(snapshot["recent"][-1]["text"], "error-24")
            self.assertEqual(snapshot["recent"][0]["text"], "error-20")
        finally:
            adapter.close()

    def test_errors_are_isolated_per_page(self):
        adapter, playwright, identity = self._build()
        try:
            context = playwright.browser.context
            first_page = context.page
            second_page = _FakePage()
            context.pages = [first_page, second_page]
            # Reconcile registers the new page (with its own observer).
            observed = adapter.observe(identity.session_id)
            second_page_id = [
                pid for pid in observed.metadata["page_ids"]
                if pid != observed.page_id
            ][0]
            first_page.fire_console(
                _FakeConsoleMessage(message_type="error", text="first page error")
            )
            first_snapshot = self._console_errors(
                adapter, identity, page_id=observed.page_id
            )
            second_snapshot = self._console_errors(
                adapter, identity, page_id=second_page_id
            )
            self.assertEqual(first_snapshot["total_count"], 1)
            self.assertEqual(second_snapshot["total_count"], 0)
        finally:
            adapter.close()

    def test_closed_page_eviction_drops_error_state(self):
        adapter, playwright, identity = self._build()
        try:
            context = playwright.browser.context
            first_page = context.page
            second_page = _FakePage()
            context.pages = [first_page, second_page]
            adapter.observe(identity.session_id)  # registers the second page
            first_page.fire_console(
                _FakeConsoleMessage(message_type="error", text="gone page error")
            )
            # Closing the page and removing it from the provider evicts it;
            # the error state must go with it instead of lingering.
            first_page.closed = True
            context.pages = [second_page]
            observed = adapter.observe(identity.session_id)
            self.assertEqual(observed.metadata["page_ids"], [observed.page_id])
            snapshot = observed.metadata["console_errors"]
            self.assertEqual(snapshot["total_count"], 0)
            self.assertEqual(snapshot["recent"], [])
        finally:
            adapter.close()

    def test_handler_failures_never_break_observation(self):
        adapter, playwright, identity = self._build()
        try:
            page = playwright.browser.context.page

            class _RaisingText:
                type = "error"

                @property
                def text(self):
                    raise RuntimeError("provider text blew up")

            # A broken provider callback must not break observe().
            page.fire_console(_RaisingText())
            snapshot = self._console_errors(adapter, identity)
            self.assertEqual(snapshot["total_count"], 0)
        finally:
            adapter.close()


if __name__ == "__main__":
    unittest.main()
