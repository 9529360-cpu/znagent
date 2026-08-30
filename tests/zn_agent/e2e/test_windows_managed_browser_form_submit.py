from __future__ import annotations

import hashlib
import http.server
import tempfile
import threading
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.work import ResidentWorkLedger


_TYPED = "ZN same-session form ✓"
_TYPED_DIGEST = hashlib.sha256(_TYPED.encode("utf-8")).hexdigest()


class _FormHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/done":
            payload = (
                "<!doctype html><html><head><title>ZN Form Done</title></head>"
                "<body><main>submitted</main></body></html>"
            ).encode("utf-8")
        else:
            payload = (
                "<!doctype html><html><head><title>ZN Form</title></head><body>"
                '<label>Search <input type="text" aria-label="Search"></label>'
                '<button type="button" onclick="location.href=\'/done\'">Continue</button>'
                "</body></html>"
            ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class ManagedBrowserFormSubmitWindowsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FormHandler)
        cls.web_thread = threading.Thread(target=cls.web.serve_forever, daemon=True)
        cls.web_thread.start()
        port = int(cls.web.server_address[1])
        cls.url = f"http://127.0.0.1:{port}/"
        cls.done_url = f"http://127.0.0.1:{port}/done"

    @classmethod
    def tearDownClass(cls):
        cls.web.shutdown()
        cls.web.server_close()
        cls.web_thread.join(timeout=5)

    def test_structured_work_fills_and_submits_in_one_real_chromium_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=Path(tmp) / "kernel.db"
            )
            ledger = ResidentWorkLedger(resident)
            try:
                ledger.create_thread(thread_id="real-form-submit")
                (_, messages), result = ledger.submit(
                    "real-form-submit",
                    "fill one exact textbox and submit one exact button in one managed session",
                    payload={
                        "required_capabilities": ["browser"],
                        "body_action": {
                            "kind": "browser_fill_named_text_and_click_named_button_to_url",
                            "args": {
                                "url": self.url,
                                "textbox_name": "Search",
                                "text": _TYPED,
                                "button_name": "Continue",
                                "expected_url": self.done_url,
                                "allow_private_network": True,
                            },
                        },
                        "model_policy": "never",
                    },
                )
                self.assertTrue(result.success, result.reason)
                self.assertEqual(result.model_invocations, 0)
                self.assertEqual(result.response, self.done_url)
                actions = [
                    action
                    for action in result.body_actions
                    if action.kind
                    == "browser_fill_named_text_and_click_named_button_to_url"
                ]
                self.assertEqual(len(actions), 1)
                self.assertTrue(actions[0].success)
                self.assertNotIn(_TYPED, repr(result))
                self.assertNotIn(_TYPED, repr(actions[0]))
                self.assertTrue(any(message.role == "zn" for message in messages))

                persisted = resident.store.recent_body_actions(limit=8)
                encoded = repr(persisted)
                self.assertNotIn(_TYPED, encoded)
                self.assertIn(_TYPED_DIGEST, encoded)
            finally:
                resident.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
