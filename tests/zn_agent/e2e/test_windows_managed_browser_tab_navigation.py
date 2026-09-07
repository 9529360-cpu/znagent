from __future__ import annotations

import http.server
import threading
import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
)
from zn_agent.core.semantic_managed_browser import SemanticPlaywrightManagedBrowser


class _TabHistoryFixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        titles = {
            "/one": "ZN Tab One",
            "/two": "ZN Tab Two",
            "/three": "ZN Tab Three",
        }
        title = titles.get(self.path, "ZN Tab Unknown")
        payload = (
            "<!doctype html><html><head>"
            f"<title>{title}</title>"
            "</head><body>"
            f"<main><h1>{title}</h1></main>"
            "</body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class ManagedBrowserTabHistoryWindowsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            _TabHistoryFixtureHandler,
        )
        cls.port = int(cls.server.server_address[1])
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    @staticmethod
    def _authority(browser, session_id, action, *, page_id=""):
        observation = browser.observe(session_id, page_id=page_id)
        permission = browser._sessions[session_id].permission
        return BrowserActionAuthority.from_observation(
            action,
            observation,
            permission,
        )

    def test_real_chromium_verified_tab_lifecycle_and_history(self):
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allow_private_network=True,
            allowed_origins=(self.origin,),
        )
        browser = SemanticPlaywrightManagedBrowser()
        session = browser.open_session(permission=permission, headless=True)
        try:
            initial = browser.observe(session.session_id)
            first_page_id = initial.page_id

            navigate_one = BrowserAction.create(
                session_id=session.session_id,
                page_id=first_page_id,
                kind=BrowserActionKind.NAVIGATE,
                args={"url": self.origin + "/one"},
                expected={"url_equals": self.origin + "/one"},
            )
            navigated = browser.act(
                navigate_one,
                self._authority(
                    browser,
                    session.session_id,
                    navigate_one,
                    page_id=first_page_id,
                ),
            )
            self.assertTrue(navigated.success, navigated.error)

            open_two = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.OPEN_TAB,
                args={"url": self.origin + "/two"},
                expected={"url_equals": self.origin + "/two"},
            )
            current = browser.observe(session.session_id)
            opened = browser.act(
                open_two,
                BrowserActionAuthority.from_observation(open_two, current, permission),
            )
            self.assertTrue(opened.success, opened.error)
            second_page_id = opened.page_id
            self.assertNotEqual(second_page_id, first_page_id)
            self.assertEqual(opened.data["fresh_page_id"], second_page_id)
            self.assertEqual(browser.observe(session.session_id).page_id, second_page_id)

            workspace = browser.observe_browser_workspace(session.session_id)
            self.assertEqual(len(workspace.tabs), 2)
            self.assertEqual(len({tab.page_id for tab in workspace.tabs}), 2)
            self.assertTrue(all(tab.in_authority_scope for tab in workspace.tabs))
            second_tab = next(tab for tab in workspace.tabs if tab.page_id == second_page_id)
            self.assertEqual(second_tab.ownership, "zn_created")

            switch_first = BrowserAction.create(
                session_id=session.session_id,
                page_id=first_page_id,
                kind=BrowserActionKind.SWITCH_TAB,
            )
            switched_first = browser.act(
                switch_first,
                self._authority(
                    browser,
                    session.session_id,
                    switch_first,
                    page_id=first_page_id,
                ),
            )
            self.assertTrue(switched_first.success, switched_first.error)
            self.assertEqual(browser.observe(session.session_id).page_id, first_page_id)
            self.assertFalse(switched_first.data["os_foreground_verified"])

            switch_second = BrowserAction.create(
                session_id=session.session_id,
                page_id=second_page_id,
                kind=BrowserActionKind.SWITCH_TAB,
            )
            switched_second = browser.act(
                switch_second,
                self._authority(
                    browser,
                    session.session_id,
                    switch_second,
                    page_id=second_page_id,
                ),
            )
            self.assertTrue(switched_second.success, switched_second.error)
            self.assertEqual(browser.observe(session.session_id).page_id, second_page_id)

            navigate_three = BrowserAction.create(
                session_id=session.session_id,
                page_id=second_page_id,
                kind=BrowserActionKind.NAVIGATE,
                args={"url": self.origin + "/three"},
                expected={"url_equals": self.origin + "/three"},
            )
            navigated_three = browser.act(
                navigate_three,
                self._authority(
                    browser,
                    session.session_id,
                    navigate_three,
                    page_id=second_page_id,
                ),
            )
            self.assertTrue(navigated_three.success, navigated_three.error)
            scene_three = browser.observe_scene(session.session_id, page_id=second_page_id)
            self.assertEqual(scene_three.url, self.origin + "/three")
            scene_state = browser._scene_state(browser._sessions[session.session_id])
            self.assertIn(second_page_id, scene_state.page_scenes)

            back = BrowserAction.create(
                session_id=session.session_id,
                page_id=second_page_id,
                kind=BrowserActionKind.BACK,
                expected={"url_equals": self.origin + "/two"},
            )
            backed = browser.act(
                back,
                self._authority(
                    browser,
                    session.session_id,
                    back,
                    page_id=second_page_id,
                ),
            )
            self.assertTrue(backed.success, backed.error)
            self.assertTrue(backed.data["provider_transition_reported"])
            self.assertEqual(backed.url_after, self.origin + "/two")
            self.assertNotIn(second_page_id, scene_state.page_scenes)

            forward = BrowserAction.create(
                session_id=session.session_id,
                page_id=second_page_id,
                kind=BrowserActionKind.FORWARD,
                expected={"url_equals": self.origin + "/three"},
            )
            forwarded = browser.act(
                forward,
                self._authority(
                    browser,
                    session.session_id,
                    forward,
                    page_id=second_page_id,
                ),
            )
            self.assertTrue(forwarded.success, forwarded.error)
            self.assertEqual(forwarded.url_after, self.origin + "/three")

            browser.observe_scene(session.session_id, page_id=second_page_id)
            reload_action = BrowserAction.create(
                session_id=session.session_id,
                page_id=second_page_id,
                kind=BrowserActionKind.RELOAD,
                expected={"url_equals": self.origin + "/three"},
            )
            reloaded = browser.act(
                reload_action,
                self._authority(
                    browser,
                    session.session_id,
                    reload_action,
                    page_id=second_page_id,
                ),
            )
            self.assertTrue(reloaded.success, reloaded.error)
            self.assertTrue(reloaded.data["reload_dispatched"])
            self.assertFalse(reloaded.data["business_state_verified"])
            self.assertNotIn(second_page_id, scene_state.page_scenes)

            before_failed_open = browser.observe_browser_workspace(session.session_id)
            failed_open = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.OPEN_TAB,
                args={"url": self.origin + "/two"},
                expected={"url_equals": self.origin + "/three"},
            )
            current = browser.observe(session.session_id)
            failed = browser.act(
                failed_open,
                BrowserActionAuthority.from_observation(
                    failed_open,
                    current,
                    permission,
                ),
            )
            self.assertFalse(failed.success)
            self.assertTrue(failed.data["rollback_complete"])
            after_failed_open = browser.observe_browser_workspace(session.session_id)
            self.assertEqual(
                {tab.page_id for tab in after_failed_open.tabs},
                {tab.page_id for tab in before_failed_open.tabs},
            )
            self.assertEqual(len(after_failed_open.tabs), 2)

            close_second = BrowserAction.create(
                session_id=session.session_id,
                page_id=second_page_id,
                kind=BrowserActionKind.CLOSE_TAB,
            )
            closed = browser.act(
                close_second,
                self._authority(
                    browser,
                    session.session_id,
                    close_second,
                    page_id=second_page_id,
                ),
            )
            self.assertTrue(closed.success, closed.error)
            self.assertEqual(closed.data["fresh_default_page_id"], first_page_id)

            final = browser.observe(session.session_id)
            self.assertEqual(final.page_id, first_page_id)
            self.assertEqual(final.url, self.origin + "/one")
            self.assertEqual(final.metadata["page_count"], 1)
            self.assertEqual(final.metadata["page_ids"], [first_page_id])
            self.assertEqual(final.metadata["default_page_id"], first_page_id)
            final_workspace = browser.observe_browser_workspace(session.session_id)
            self.assertEqual([tab.page_id for tab in final_workspace.tabs], [first_page_id])
            self.assertTrue(final_workspace.tabs[0].in_authority_scope)
        finally:
            browser.close_session(session.session_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
