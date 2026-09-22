from __future__ import annotations

import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/done":
            body = b"<!doctype html><title>Done</title><h1>Done</h1>"
        else:
            body = b"""<!doctype html>
<title>Managed browser provider contract</title>
<label for="query">Search</label>
<input id="query" aria-label="Search" type="text">
<button aria-label="Submit" onclick="location.href='/done'">Submit</button>
"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


class ManagedBrowserProviderContractTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_chrome_mcp_provider_executes_fresh_semantic_action_chain(self):
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allow_text_entry=True,
            allow_private_network=True,
            allowed_origins=(self.origin,),
        )
        browser = ChromeDevToolsMcpManagedBrowser()
        session = browser.open_session(permission=permission, headless=True)
        try:
            initial = browser.observe(session.session_id)
            navigate = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.NAVIGATE,
                page_id=initial.page_id,
                args={"url": self.origin + "/"},
                expected={"url_equals": self.origin + "/"},
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
                args={"text": "provider contract"},
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
            self.assertTrue(typed.data.get("exact_node_continuity"))
            self.assertEqual(
                typed.data.get("text_length_after"),
                len("provider contract"),
            )

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
                expected={"url_equals": self.origin + "/done"},
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
            self.assertEqual(clicked.url_after, self.origin + "/done")
            self.assertEqual(clicked.data.get("provider"), CHROME_DEVTOOLS_MCP_PROVIDER)
            self.assertEqual(clicked.data.get("provider"), "chrome-devtools-mcp@1.9.0")
            page = browser.read_page(session.session_id, page_id=clicked.page_id)
            self.assertEqual(page["url"], self.origin + "/done")
            self.assertIn("Done", page["text"])
            self.assertEqual(page["provider"], CHROME_DEVTOOLS_MCP_PROVIDER)
        finally:
            browser.close()


if __name__ == "__main__":
    unittest.main()
