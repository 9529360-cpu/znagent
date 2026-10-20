from __future__ import annotations

import time
import unittest

from zn_agent.core.browser import BrowserPermissionContext, BrowserSessionOwner

_OWNER = BrowserSessionOwner(work_id="test", root_id="test", purpose="test")
from zn_agent.core.managed_browser import (
    ManagedBrowserError,
    PlaywrightManagedBrowser,
    _MAX_SESSION_EVENTS,
)
from test_managed_browser import _FakeStarter, _FakePlaywright


class ManagedBrowserSessionTtlTests(unittest.TestCase):
    def _build(self, **kwargs):
        playwright = _FakePlaywright()
        context = playwright.browser.context
        context.pages = [context.page]
        original_new_page = context.new_page

        def new_page():
            if not context.pages:
                page = original_new_page()
                context.pages.append(page)
                return page
            return context.pages[0]

        context.new_page = new_page
        adapter = PlaywrightManagedBrowser(
            playwright_factory=lambda: _FakeStarter(playwright),
            url_checker=lambda url, **kwargs: True,
            **kwargs,
        )
        identity = adapter.open_session(
            owner=_OWNER,
            permission=BrowserPermissionContext(allow_page_interaction=True),
            headless=True,
        )
        return adapter, playwright, identity

    def _backdate_activity(self, adapter, session_id, *, idle_seconds):
        session = adapter._sessions[session_id]
        session.last_activity_monotonic = time.monotonic() - idle_seconds

    def test_default_ttl_is_30_minutes(self):
        adapter, _, _ = self._build()
        try:
            self.assertEqual(adapter.session_idle_ttl_seconds, 30 * 60)
        finally:
            adapter.close()

    def test_idle_session_beyond_ttl_is_closed_and_journaled(self):
        adapter, playwright, identity = self._build(session_idle_ttl_seconds=60)
        session_id = identity.session_id
        try:
            self._backdate_activity(adapter, session_id, idle_seconds=61)

            closed = adapter.close_idle_sessions()

            self.assertEqual(closed, [session_id])
            self.assertNotIn(session_id, adapter._sessions)
            self.assertTrue(playwright.browser.closed)
            self.assertTrue(playwright.stopped)

            events = adapter.session_events()
            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(event["event"], "browser_session_closed")
            self.assertEqual(event["reason"], "idle_ttl")
            self.assertEqual(event["session_id"], session_id)
            self.assertEqual(event["provider"], "playwright-chromium")
            self.assertEqual(event["plane"], "managed")
            self.assertGreaterEqual(event["idle_seconds"], 61)
            self.assertEqual(event["ttl_seconds"], 60)
            self.assertTrue(event["closed_at"])
        finally:
            adapter.close()

    def test_active_session_is_not_closed(self):
        adapter, _, identity = self._build(session_idle_ttl_seconds=60)
        session_id = identity.session_id
        try:
            # A fresh observe refreshes activity; nothing should be swept.
            adapter.observe(session_id)
            closed = adapter.close_idle_sessions()
            self.assertEqual(closed, [])
            self.assertIn(session_id, adapter._sessions)
            self.assertEqual(adapter.session_events(), ())
            # Session still fully usable afterwards.
            adapter.observe(session_id)
        finally:
            adapter.close()

    def test_session_at_or_below_ttl_boundary_stays_open(self):
        adapter, _, identity = self._build(session_idle_ttl_seconds=60)
        session_id = identity.session_id
        try:
            self._backdate_activity(adapter, session_id, idle_seconds=59)
            closed = adapter.close_idle_sessions()
            self.assertEqual(closed, [])
            self.assertIn(session_id, adapter._sessions)
        finally:
            adapter.close()

    def test_explicit_close_session_still_works(self):
        adapter, _, identity = self._build(session_idle_ttl_seconds=60)
        session_id = identity.session_id
        try:
            adapter.close_session(session_id)
            self.assertNotIn(session_id, adapter._sessions)

            # Unknown sessions stay a silent no-op; explicit behavior unchanged.
            adapter.close_session(session_id)
            adapter.close_session("does-not-exist")

            events = adapter.session_events()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["reason"], "explicit")
            self.assertEqual(events[0]["session_id"], session_id)
            self.assertIsNone(events[0]["ttl_seconds"])
        finally:
            adapter.close()

    def test_auto_sweep_runs_on_entry_point(self):
        adapter, _, identity = self._build(session_idle_ttl_seconds=60)
        session_id = identity.session_id
        try:
            self._backdate_activity(adapter, session_id, idle_seconds=3600)
            # Force the throttled sweep to run on the next entry point.
            adapter._last_auto_sweep_monotonic = 0.0

            with self.assertRaisesRegex(
                ManagedBrowserError, "unknown managed browser session"
            ):
                adapter.observe(session_id)

            self.assertNotIn(session_id, adapter._sessions)
            events = adapter.session_events()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["reason"], "idle_ttl")
        finally:
            adapter.close()

    def test_auto_sweep_is_throttled(self):
        adapter, _, identity = self._build(session_idle_ttl_seconds=60)
        session_id = identity.session_id
        try:
            self._backdate_activity(adapter, session_id, idle_seconds=3600)
            # A sweep just ran: the next entry point must not sweep again,
            # so the idle session survives this call.
            adapter._last_auto_sweep_monotonic = time.monotonic()

            adapter.observe(session_id)
            self.assertIn(session_id, adapter._sessions)
            self.assertEqual(adapter.session_events(), ())
        finally:
            adapter.close()

    def test_ttl_disabled_closes_nothing(self):
        adapter, _, identity = self._build(session_idle_ttl_seconds=0)
        session_id = identity.session_id
        try:
            self._backdate_activity(adapter, session_id, idle_seconds=10**9)

            self.assertEqual(adapter.close_idle_sessions(), [])
            adapter._last_auto_sweep_monotonic = 0.0
            adapter.observe(session_id)

            self.assertIn(session_id, adapter._sessions)
            self.assertEqual(adapter.session_events(), ())
        finally:
            adapter.close()

    def test_ttl_override_on_close_idle_sessions(self):
        adapter, _, identity = self._build(session_idle_ttl_seconds=3600)
        session_id = identity.session_id
        try:
            self._backdate_activity(adapter, session_id, idle_seconds=61)

            # Adapter default TTL would keep it open; the override closes it.
            self.assertEqual(adapter.close_idle_sessions(), [])
            closed = adapter.close_idle_sessions(ttl_seconds=60)
            self.assertEqual(closed, [session_id])
            self.assertEqual(adapter.session_events()[0]["ttl_seconds"], 60)
        finally:
            adapter.close()

    def test_session_event_callback_receives_ttl_close(self):
        received = []
        adapter, _, identity = self._build(
            session_idle_ttl_seconds=60,
            session_event_callback=received.append,
        )
        session_id = identity.session_id
        try:
            self._backdate_activity(adapter, session_id, idle_seconds=61)
            adapter.close_idle_sessions()

            self.assertEqual(len(received), 1)
            self.assertEqual(received[0]["reason"], "idle_ttl")
            self.assertEqual(received[0]["session_id"], session_id)
        finally:
            adapter.close()

    def test_failing_callback_does_not_break_close(self):
        def _boom(event):
            raise RuntimeError("callback exploded")

        adapter, _, identity = self._build(
            session_idle_ttl_seconds=60,
            session_event_callback=_boom,
        )
        session_id = identity.session_id
        try:
            self._backdate_activity(adapter, session_id, idle_seconds=61)
            closed = adapter.close_idle_sessions()

            self.assertEqual(closed, [session_id])
            self.assertNotIn(session_id, adapter._sessions)
            # The journal record itself is still written.
            self.assertEqual(len(adapter.session_events()), 1)
        finally:
            adapter.close()

    def test_journal_is_bounded(self):
        adapter, _, _ = self._build(session_idle_ttl_seconds=0)
        try:
            for _ in range(_MAX_SESSION_EVENTS + 10):
                identity = adapter.open_session(
                    owner=_OWNER,
                    permission=BrowserPermissionContext(
                        allow_page_interaction=True
                    ),
                    headless=True,
                )
                adapter.close_session(identity.session_id)
            events = adapter.session_events()
            self.assertEqual(len(events), _MAX_SESSION_EVENTS)
        finally:
            adapter.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
