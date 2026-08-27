from __future__ import annotations

import http.server
import threading
import unittest

from zn_agent.core.browser import BrowserPermissionContext
from zn_agent.core.managed_browser import ManagedBrowserError, PlaywrightManagedBrowser


class _PageFixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        title = "ZN Page Two" if self.path == "/second" else "ZN Page One"
        body = f"<main>{title}</main>"
        payload = (
            "<!doctype html><html><head>"
            f"<title>{title}</title>"
            "</head><body>"
            f"{body}"
            "</body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class ManagedBrowserPageLifecycleWindowsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _PageFixtureHandler)
        cls.port = int(cls.server.server_address[1])
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_real_chromium_reconciles_new_and_closed_pages_without_reusing_resident_ids(self):
        permission = BrowserPermissionContext(
            allow_private_network=True,
            allowed_origins=(self.origin,),
        )
        browser = PlaywrightManagedBrowser()
        session = browser.open_session(permission=permission, headless=True)
        try:
            initial = browser.observe(session.session_id)
            self.assertEqual(initial.metadata["page_count"], 1)
            self.assertEqual(initial.metadata["page_ids"], [initial.page_id])
            self.assertEqual(initial.metadata["default_page_id"], initial.page_id)

            managed_session = browser._sessions[session.session_id]
            provider_second = managed_session.context.new_page()
            provider_second.goto(self.origin + "/second", wait_until="domcontentloaded")

            reconciled = browser.observe(session.session_id)
            self.assertEqual(reconciled.page_id, initial.page_id)
            self.assertEqual(reconciled.metadata["page_count"], 2)
            self.assertEqual(reconciled.metadata["default_page_id"], initial.page_id)
            second_page_id = next(
                page_id
                for page_id in reconciled.metadata["page_ids"]
                if page_id != initial.page_id
            )

            observed_second = browser.observe(session.session_id, page_id=second_page_id)
            self.assertEqual(observed_second.url, self.origin + "/second")
            self.assertEqual(observed_second.title, "ZN Page Two")
            self.assertEqual(observed_second.page_id, second_page_id)

            managed_session.pages[initial.page_id].close()
            promoted = browser.observe(session.session_id)
            self.assertEqual(promoted.page_id, second_page_id)
            self.assertEqual(promoted.metadata["page_count"], 1)
            self.assertEqual(promoted.metadata["page_ids"], [second_page_id])
            self.assertEqual(promoted.metadata["default_page_id"], second_page_id)
            with self.assertRaisesRegex(ManagedBrowserError, "unknown managed browser page"):
                browser.observe(session.session_id, page_id=initial.page_id)

            provider_third = managed_session.context.new_page()
            provider_third.goto(self.origin + "/", wait_until="domcontentloaded")
            after_third = browser.observe(session.session_id)
            third_page_id = next(
                page_id
                for page_id in after_third.metadata["page_ids"]
                if page_id != second_page_id
            )
            self.assertNotEqual(third_page_id, initial.page_id)
            self.assertNotEqual(third_page_id, second_page_id)
        finally:
            browser.close_session(session.session_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
