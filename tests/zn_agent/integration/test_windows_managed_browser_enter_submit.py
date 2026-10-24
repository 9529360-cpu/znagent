from __future__ import annotations

import hashlib
import http.server
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.semantic_managed_browser import SemanticPlaywrightManagedBrowser


_TYPED = "zn-enter-submit-42"
_TYPED_DIGEST = hashlib.sha256(_TYPED.encode("utf-8")).hexdigest()

# Reuse the already-downloaded full Chromium build (playwright 1.64's headless
# shell is not installed on this machine); the existing binary is injected via
# executable_path instead of re-downloading anything.
_CHROME_BINARY = (
    Path.home()
    / ".cache"
    / "ms-playwright"
    / "chromium-1248"
    / "chrome-linux64"
    / "chrome"
)


class _ExecutablePathChromium:
    """Wrap playwright's chromium launcher to pin the existing binary."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def launch(self, **kwargs):
        kwargs.setdefault("executable_path", str(_CHROME_BINARY))
        return self._inner.launch(**kwargs)


class _StartedExecutablePathPlaywright:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.chromium = _ExecutablePathChromium(inner.chromium)

    def stop(self):
        return self._inner.stop()

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _ExecutablePathPlaywrightFactory:
    def start(self):
        from playwright.sync_api import sync_playwright

        return _StartedExecutablePathPlaywright(sync_playwright().start())


def _chromium_factory():
    return _ExecutablePathPlaywrightFactory()


class _EnterFormHandler(http.server.BaseHTTPRequestHandler):
    @staticmethod
    def _page_payload(*, submitted: bool) -> bytes:
        return (
            "<!doctype html><html><head><title>ZN Enter Result</title></head>"
            f"<body><main>{'submitted' if submitted else 'wrong'}</main></body></html>"
        ).encode("utf-8")

    def _send_html(self, payload: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/done":
            self._send_html(self._page_payload(submitted=True))
            return
        if parsed.path == "/wrong":
            self._send_html(self._page_payload(submitted=False))
            return
        payload = (
            "<!doctype html><html><head><title>ZN Enter Form</title></head><body>"
            '<form action="/submit" method="post">'
            '<label>Search <input id="search" name="q" type="text" aria-label="Search"></label>'
            "</form>"
            "</body></html>"
        ).encode("utf-8")
        self._send_html(payload)

    def do_POST(self):
        parsed = urlsplit(self.path)
        content_length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(content_length).decode("utf-8", errors="strict")
        values = parse_qs(body).get("q", [])
        submitted = (
            parsed.path == "/submit"
            and len(values) == 1
            and values[0] == _TYPED
        )
        destination = "/done" if submitted else "/wrong"
        self.send_response(303)
        self.send_header("Location", destination)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt, *args):
        return


class ManagedBrowserEnterSubmitWindowsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The loopback target is a private literal IP; opt in for this test
        # process only via ZN's own documented env switch (no product change).
        cls._previous_allow_private = os.environ.get("ZN_ALLOW_PRIVATE_URLS")
        os.environ["ZN_ALLOW_PRIVATE_URLS"] = "1"
        cls.web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _EnterFormHandler)
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
        if cls._previous_allow_private is None:
            os.environ.pop("ZN_ALLOW_PRIVATE_URLS", None)
        else:
            os.environ["ZN_ALLOW_PRIVATE_URLS"] = cls._previous_allow_private

    def test_structured_work_fills_exact_textbox_and_submits_real_form_with_enter(self):
        if not _CHROME_BINARY.is_file():
            self.skipTest(f"chromium binary missing: {_CHROME_BINARY}")
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            # Real semantic adapter (with the C6 Press mixin wired) against the
            # existing headless Chromium binary; executable_path is injected so
            # no browser download is required. The loopback target needs the
            # explicit private-network grant, which the structured body action
            # accepts as an argument.
            resident.managed_browser = SemanticPlaywrightManagedBrowser(
                playwright_factory=_chromium_factory
            )
            try:
                result = resident.body.act(
                    "browser_fill_named_text_and_press_enter_to_url",
                    event_id="evt-real-enter-submit",
                    url=self.url,
                    textbox_name="Search",
                    text=_TYPED,
                    expected_url=self.done_url,
                    allow_private_network=True,
                )
                self.assertTrue(result.success, result.error)
                self.assertEqual(result.output, self.done_url)

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
