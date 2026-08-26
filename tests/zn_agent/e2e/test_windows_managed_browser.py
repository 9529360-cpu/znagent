from __future__ import annotations

import http.server
import socket
import threading
import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
)
from zn_agent.core.managed_browser import PlaywrightManagedBrowser


class _FixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/next":
            title = "ZN Browser Next"
            body = "ZN managed browser next marker"
        else:
            title = "ZN Browser Fixture"
            body = "ZN managed browser marker"
        payload = (
            "<!doctype html><html><head>"
            f"<title>{title}</title>"
            "</head><body>"
            f"<main>{body}</main>"
            "</body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class ManagedBrowserWindowsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
        cls.port = int(cls.server.server_address[1])
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_local_headless_chromium_observes_and_verifies_navigation(self):
        permission = BrowserPermissionContext(
            allow_private_network=True,
            allowed_origins=(self.origin,),
        )
        browser = PlaywrightManagedBrowser()
        session = browser.open_session(permission=permission, headless=True)
        try:
            initial = browser.observe(session.session_id)
            self.assertEqual(initial.url, "about:blank")
            self.assertEqual(session.profile_scope, "ephemeral")
            self.assertEqual(session.provider, "playwright-chromium")

            first = BrowserAction.create(
                session_id=session.session_id,
                page_id=initial.page_id,
                kind=BrowserActionKind.NAVIGATE,
                args={"url": self.origin + "/"},
                expected={"url_equals": self.origin + "/"},
            )
            first_authority = BrowserActionAuthority.from_observation(
                first,
                initial,
                permission,
            )
            first_effect = browser.act(first, first_authority)
            self.assertTrue(first_effect.success, first_effect.error)
            self.assertEqual(first_effect.url_after, self.origin + "/")

            observed = browser.observe(session.session_id, page_id=initial.page_id)
            self.assertEqual(observed.title, "ZN Browser Fixture")
            self.assertIn(observed.load_state, {"interactive", "complete"})
            self.assertNotIn("text", observed.metadata)
            self.assertNotIn("content", observed.metadata)
            self.assertNotIn("html", observed.metadata)

            second = BrowserAction.create(
                session_id=session.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.NAVIGATE,
                args={"url": self.origin + "/next"},
                expected={"url_equals": self.origin + "/next"},
            )
            second_authority = BrowserActionAuthority.from_observation(
                second,
                observed,
                permission,
            )
            second_effect = browser.act(second, second_authority)
            self.assertTrue(second_effect.success, second_effect.error)
            self.assertEqual(second_effect.url_after, self.origin + "/next")
            self.assertEqual(
                browser.observe(session.session_id, page_id=observed.page_id).title,
                "ZN Browser Next",
            )

            current = browser.observe(session.session_id, page_id=observed.page_id)
            metadata_probe = BrowserAction.create(
                session_id=session.session_id,
                page_id=current.page_id,
                kind=BrowserActionKind.NAVIGATE,
                args={"url": "http://169.254.169.254/latest/meta-data/"},
            )
            metadata_authority = BrowserActionAuthority.from_observation(
                metadata_probe,
                current,
                permission,
            )
            metadata_effect = browser.act(metadata_probe, metadata_authority)
            self.assertFalse(metadata_effect.success)
            self.assertIn("network boundary", metadata_effect.error or "")
        finally:
            browser.close_session(session.session_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
