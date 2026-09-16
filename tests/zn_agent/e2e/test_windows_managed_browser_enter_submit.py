from __future__ import annotations

import hashlib
import http.server
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.work import ResidentWorkLedger


_TYPED = "zn-enter-submit-42"
_TYPED_DIGEST = hashlib.sha256(_TYPED.encode("utf-8")).hexdigest()


class _EnterFormHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/done":
            values = parse_qs(parsed.query).get("q", [])
            submitted = len(values) == 1 and values[0] == _TYPED
            payload = (
                "<!doctype html><html><head><title>ZN Enter Done</title></head>"
                f"<body><main>{'submitted' if submitted else 'wrong'}</main></body></html>"
            ).encode("utf-8")
        else:
            payload = (
                "<!doctype html><html><head><title>ZN Enter Form</title></head><body>"
                '<form action="/done" method="get">'
                '<label>Search <input id="search" name="q" type="text" aria-label="Search"></label>'
                "</form>"
                "</body></html>"
            ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class ManagedBrowserEnterSubmitWindowsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _EnterFormHandler)
        cls.web_thread = threading.Thread(target=cls.web.serve_forever, daemon=True)
        cls.web_thread.start()
        port = int(cls.web.server_address[1])
        cls.url = f"http://127.0.0.1:{port}/"
        cls.done_url = f"http://127.0.0.1:{port}/done?{urlencode({'q': _TYPED})}"

    @classmethod
    def tearDownClass(cls):
        cls.web.shutdown()
        cls.web.server_close()
        cls.web_thread.join(timeout=5)

    def test_structured_work_fills_exact_textbox_and_submits_real_form_with_enter(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            ledger = ResidentWorkLedger(resident)
            try:
                ledger.create_thread(thread_id="real-enter-submit")
                (_, messages), result = ledger.submit(
                    "real-enter-submit",
                    "fill one exact managed-browser textbox and submit the form with Enter",
                    payload={
                        "required_capabilities": ["browser"],
                        "body_action": {
                            "kind": "browser_fill_named_text_and_press_enter_to_url",
                            "args": {
                                "url": self.url,
                                "textbox_name": "Search",
                                "text": _TYPED,
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
                self.assertTrue(any(message.role == "zn" for message in messages))

                with closing(sqlite3.connect(store_path)) as conn:
                    rows = conn.execute(
                        "SELECT kind,success,action_json,result_json "
                        "FROM native_body_actions ORDER BY rowid DESC LIMIT 8"
                    ).fetchall()
                enter_rows = [
                    row
                    for row in rows
                    if str(row[0]) == "browser_fill_named_text_and_press_enter_to_url"
                ]
                self.assertEqual(len(enter_rows), 1)
                self.assertEqual(int(enter_rows[0][1]), 1)
                encoded = repr(enter_rows)
                self.assertNotIn(_TYPED, encoded)
                self.assertIn(_TYPED_DIGEST, encoded)
                self.assertIn("url_equals_after_fresh_semantic_textbox_enter", encoded)
                self.assertIn('"submit_key":"Enter"', encoded.replace(" ", ""))
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
