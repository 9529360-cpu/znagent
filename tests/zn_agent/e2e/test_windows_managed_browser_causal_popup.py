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


class _CausalPopupFixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/popup"):
            payload = b"""<!doctype html><html><head><title>ZN Causal Popup</title></head>
            <body><main><h1>Popup destination</h1></main></body></html>"""
        else:
            payload = b"""<!doctype html><html><head><title>ZN Popup Opener</title></head>
            <body><main>
              <h1>Popup opener</h1>
              <button aria-label='Open popup'
                onclick="window.open('/popup', 'zn-causal-popup')">Open popup</button>
            </main></body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class ManagedBrowserCausalPopupWindowsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            _CausalPopupFixtureHandler,
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
    def _authority(browser, session_id, action, *, page_id):
        observed = browser.observe(session_id, page_id=page_id)
        permission = browser._sessions[session_id].permission
        return BrowserActionAuthority.from_observation(
            action,
            observed,
            permission,
        )

    def test_real_chromium_opener_popup_and_exact_return_loop(self):
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allow_private_network=True,
            allowed_origins=(self.origin,),
        )
        browser = SemanticPlaywrightManagedBrowser()
        identity = browser.open_session(permission=permission, headless=True)
        try:
            initial = browser.observe(identity.session_id)
            opener_page_id = initial.page_id
            opener_url = self.origin + "/opener"
            popup_url = self.origin + "/popup"

            navigate = BrowserAction.create(
                session_id=identity.session_id,
                page_id=opener_page_id,
                kind=BrowserActionKind.NAVIGATE,
                args={"url": opener_url},
                expected={"url_equals": opener_url},
            )
            navigated = browser.act(
                navigate,
                BrowserActionAuthority.from_observation(
                    navigate,
                    initial,
                    permission,
                ),
            )
            self.assertTrue(navigated.success, navigated.error)

            scene = browser.observe_scene(identity.session_id, page_id=opener_page_id)
            target = next(
                item
                for item in scene.targets
                if item.role == "button" and item.accessible_name == "Open popup"
            )
            observed_target = browser.observe_scene_target(
                identity.session_id,
                target.target_id,
                page_id=opener_page_id,
            )
            click = BrowserAction.create(
                session_id=identity.session_id,
                page_id=opener_page_id,
                kind=BrowserActionKind.CLICK,
                target=observed_target.target,
                expected={"popup_url_equals": popup_url},
            )
            click_authority = BrowserActionAuthority.from_observation(
                click,
                observed_target,
                permission,
            )
            effect = browser.act(click, click_authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(
                effect.postcondition,
                "causal_popup_opener_and_url_verified",
            )
            popup_page_id = effect.data["popup_page_id"]
            self.assertNotEqual(popup_page_id, opener_page_id)
            self.assertEqual(effect.data["opener_page_id"], opener_page_id)
            self.assertEqual(effect.data["popup_url"], popup_url)
            self.assertEqual(effect.data["expected_popup_url"], popup_url)
            self.assertEqual(effect.data["ownership"], "zn_created")
            self.assertTrue(effect.data["opener_matches"])
            self.assertEqual(effect.data["new_page_ids"], [popup_page_id])
            self.assertEqual(effect.data["default_page_id_before"], opener_page_id)
            self.assertEqual(effect.data["default_page_id_after"], opener_page_id)
            self.assertTrue(effect.data["target_revalidated_before_dispatch"])
            self.assertEqual(browser.observe(identity.session_id).page_id, opener_page_id)
            self.assertEqual(
                browser.observe(identity.session_id, page_id=opener_page_id).url,
                opener_url,
            )

            popup_observation = browser.observe(
                identity.session_id,
                page_id=popup_page_id,
            )
            self.assertEqual(popup_observation.page_id, popup_page_id)
            self.assertEqual(popup_observation.url, popup_url)

            switch_popup = BrowserAction.create(
                session_id=identity.session_id,
                page_id=popup_page_id,
                kind=BrowserActionKind.SWITCH_TAB,
            )
            switched_popup = browser.act(
                switch_popup,
                self._authority(
                    browser,
                    identity.session_id,
                    switch_popup,
                    page_id=popup_page_id,
                ),
            )
            self.assertTrue(switched_popup.success, switched_popup.error)
            fresh_popup = browser.observe(identity.session_id)
            self.assertEqual(fresh_popup.page_id, popup_page_id)
            self.assertEqual(fresh_popup.url, popup_url)

            switch_opener = BrowserAction.create(
                session_id=identity.session_id,
                page_id=opener_page_id,
                kind=BrowserActionKind.SWITCH_TAB,
            )
            switched_opener = browser.act(
                switch_opener,
                self._authority(
                    browser,
                    identity.session_id,
                    switch_opener,
                    page_id=opener_page_id,
                ),
            )
            self.assertTrue(switched_opener.success, switched_opener.error)
            final = browser.observe(identity.session_id)
            self.assertEqual(final.page_id, opener_page_id)
            self.assertEqual(final.url, opener_url)

            workspace = browser.observe_browser_workspace(identity.session_id)
            self.assertEqual(
                {tab.page_id for tab in workspace.tabs},
                {opener_page_id, popup_page_id},
            )
            popup_tab = next(
                tab for tab in workspace.tabs if tab.page_id == popup_page_id
            )
            self.assertEqual(popup_tab.ownership, "zn_created")
        finally:
            browser.close_session(identity.session_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
