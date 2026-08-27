from __future__ import annotations

import unittest

from zn_agent.core.browser import BrowserPermissionContext, BrowserTargetQuery, BrowserTargetQueryKind
from zn_agent.core.managed_browser import ManagedBrowserError, PlaywrightManagedBrowser
from test_managed_browser import _FakePage, _FakeStarter, _FakePlaywright, _target_snapshot


class ManagedBrowserPageLifecycleTests(unittest.TestCase):
    def _build(self):
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
        )
        identity = adapter.open_session(
            permission=BrowserPermissionContext(allow_page_interaction=True),
            headless=True,
        )
        return adapter, playwright, identity

    def test_provider_new_page_is_registered_with_stable_resident_page_id(self):
        adapter, playwright, identity = self._build()
        context = playwright.browser.context
        try:
            initial = adapter.observe(identity.session_id)
            self.assertEqual(initial.metadata["page_count"], 1)
            self.assertEqual(initial.metadata["page_ids"], [initial.page_id])
            self.assertEqual(initial.metadata["default_page_id"], initial.page_id)

            second = _FakePage()
            second.url = "https://example.com/second"
            second._title = "Second"
            context.pages.append(second)

            refreshed = adapter.observe(identity.session_id)
            self.assertEqual(refreshed.page_id, initial.page_id)
            self.assertEqual(refreshed.metadata["page_count"], 2)
            second_page_id = refreshed.metadata["page_ids"][1]
            self.assertNotEqual(second_page_id, initial.page_id)

            observed_second = adapter.observe(identity.session_id, page_id=second_page_id)
            self.assertEqual(observed_second.url, second.url)
            self.assertEqual(observed_second.title, "Second")
            self.assertEqual(observed_second.page_id, second_page_id)

            observed_second_again = adapter.observe(identity.session_id, page_id=second_page_id)
            self.assertEqual(observed_second_again.page_id, second_page_id)
        finally:
            adapter.close()

    def test_closed_default_page_is_evicted_and_next_live_page_becomes_default(self):
        adapter, playwright, identity = self._build()
        context = playwright.browser.context
        try:
            initial = adapter.observe(identity.session_id)
            second = _FakePage()
            second.url = "https://example.com/second"
            context.pages.append(second)
            reconciled = adapter.observe(identity.session_id)
            second_page_id = reconciled.metadata["page_ids"][1]

            context.page.closed = True
            context.pages = [second]

            promoted = adapter.observe(identity.session_id)
            self.assertEqual(promoted.page_id, second_page_id)
            self.assertEqual(promoted.url, second.url)
            self.assertEqual(promoted.metadata["page_count"], 1)
            self.assertEqual(promoted.metadata["page_ids"], [second_page_id])
            self.assertEqual(promoted.metadata["default_page_id"], second_page_id)
            with self.assertRaisesRegex(ManagedBrowserError, "unknown managed browser page"):
                adapter.observe(identity.session_id, page_id=initial.page_id)
        finally:
            adapter.close()

    def test_page_eviction_disposes_target_binding_and_removes_stale_observation(self):
        adapter, playwright, identity = self._build()
        context = playwright.browser.context
        page = context.page
        page.target_snapshots["search-input"] = _target_snapshot()
        query = BrowserTargetQuery(
            kind=BrowserTargetQueryKind.DOM_ID,
            value="search-input",
        )
        try:
            observed = adapter.observe_target(identity.session_id, query)
            handle = page.created_element_handles[-1]
            self.assertFalse(handle.disposed)

            second = _FakePage()
            context.pages.append(second)
            adapter.observe(identity.session_id)
            page.closed = True
            context.pages = [second]

            promoted = adapter.observe(identity.session_id)
            self.assertNotEqual(promoted.page_id, observed.page_id)
            self.assertTrue(handle.disposed)
            session = adapter._sessions[identity.session_id]
            self.assertNotIn(observed.page_id, session.last_observation)
            self.assertNotIn(observed.page_id, session.target_bindings)
        finally:
            adapter.close()

    def test_provider_page_registry_failure_fails_closed(self):
        adapter, playwright, identity = self._build()
        context = playwright.browser.context

        class _BrokenPages:
            def __iter__(self):
                raise RuntimeError("page registry unavailable")

        try:
            context.pages = _BrokenPages()
            with self.assertRaisesRegex(ManagedBrowserError, "page registry could not be observed"):
                adapter.observe(identity.session_id)
        finally:
            context.pages = [context.page]
            adapter.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
