from __future__ import annotations

import http.server
import threading
import unittest
from urllib.parse import urlsplit

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from zn_agent.core.chrome_devtools_mcp_browser import (
    CHROME_DEVTOOLS_MCP_PROVIDER,
    ChromeDevToolsMcpManagedBrowser,
)


_TYPED = "mature browser substrate"


class _ProviderHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/done":
            payload = (
                "<!doctype html><html><head><title>Provider Done</title></head>"
                "<body><main>submitted by mature browser provider</main></body></html>"
            ).encode("utf-8")
        else:
            expected = _TYPED.replace("\\", "\\\\").replace("'", "\\'")
            payload = (
                "<!doctype html><html><head><title>Provider Fixture</title></head>"
                "<body>"
                '<label>Search <input type="text" aria-label="Search"></label>'
                '<button type="button" aria-label="Submit" onclick="location.href = '
                "document.querySelector('input').value === '"
                + expected
                + "' ? '/done' : '/wrong'"
                + '">Submit</button>'
                "</body></html>"
            ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class ChromeDevToolsMcpProviderWindowsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
        cls.thread = threading.Thread(target=cls.web.serve_forever, daemon=True)
        cls.thread.start()
        port = int(cls.web.server_address[1])
        cls.url = f"http://127.0.0.1:{port}/"
        cls.done_url = f"http://127.0.0.1:{port}/done"
        parsed = urlsplit(cls.url)
        cls.origin = f"{parsed.scheme}://{parsed.netloc}"

    @classmethod
    def tearDownClass(cls):
        cls.web.shutdown()
        cls.web.server_close()
        cls.thread.join(timeout=5)

    def test_real_official_provider_runs_semantic_form_with_fresh_zn_authority(self):
        browser = ChromeDevToolsMcpManagedBrowser()
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allow_text_entry=True,
            allow_private_network=True,
            allowed_origins=(self.origin,),
        )
        session = browser.open_session(permission=permission, headless=True)
        try:
            initial = browser.observe(session.session_id)
            navigate = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.NAVIGATE,
                page_id=initial.page_id,
                args={"url": self.url},
                expected={"url_equals": self.url},
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
            self.assertEqual(navigated.data["provider"], CHROME_DEVTOOLS_MCP_PROVIDER)

            textbox = browser.observe_target(
                session.session_id,
                BrowserTargetQuery(
                    kind=BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
                    value="Search",
                ),
                page_id=navigated.page_id,
            )
            type_action = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.TYPE_TEXT,
                page_id=textbox.page_id,
                target=textbox.target,
                args={"text": _TYPED},
            )
            typed = browser.act(
                type_action,
                BrowserActionAuthority.from_observation(
                    type_action,
                    textbox,
                    permission,
                ),
            )
            self.assertTrue(typed.success, typed.error)
            self.assertTrue(typed.data["exact_node_continuity"])

            button = browser.observe_target(
                session.session_id,
                BrowserTargetQuery(
                    kind=BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME,
                    value="Submit",
                ),
                page_id=typed.page_id,
            )
            click = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.CLICK,
                page_id=button.page_id,
                target=button.target,
                expected={"url_equals": self.done_url},
            )
            clicked = browser.act(
                click,
                BrowserActionAuthority.from_observation(
                    click,
                    button,
                    permission,
                ),
            )
            self.assertTrue(clicked.success, clicked.error)
            self.assertEqual(clicked.url_after, self.done_url)

            page = browser.read_page(session.session_id, page_id=clicked.page_id)
            self.assertEqual(page["url"], self.done_url)
            self.assertIn("submitted by mature browser provider", page["text"])
            self.assertEqual(page["provider"], CHROME_DEVTOOLS_MCP_PROVIDER)
            self.assertEqual(page["profile_scope"], "ephemeral")
        finally:
            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
