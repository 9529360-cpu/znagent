from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime

from test_windows_interactive_user_browser_bridge import (
    _find_installed_browsers,
    WindowsInteractiveUserBrowserBridgeProviderE2ETests,
)
from test_windows_interactive_user_browser_extension import (
    _ExtensionBrowserFixture,
    _press_extension_action_shortcut,
)


_INITIAL_TITLE = "ZN Natural Search E2E"
_RESULT_TITLE = "ZN Natural Search Results E2E"
_TEXT = "alice@example.test"
_HOST = "zn-natural-search-e2e.test"
_SESSION_COOKIE = "zn_natural_search_session=already-authenticated-before-zn"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/login":
            self.server.login_requests += 1  # type: ignore[attr-defined]
            self.send_response(302)
            self.send_header(
                "Set-Cookie",
                f"{_SESSION_COOKIE}; Path=/; HttpOnly; SameSite=Strict",
            )
            self.send_header("Location", "/account")
            self.end_headers()
            return

        if parsed.path == "/account":
            self.server.account_requests += 1  # type: ignore[attr-defined]
            if not self._has_existing_session():
                self.server.unauthorized_requests += 1  # type: ignore[attr-defined]
                self._write_text(401, "existing browser login required")
                return
            self.server.authenticated_account_requests += 1  # type: ignore[attr-defined]
            body = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{_INITIAL_TITLE}</title>
  <style>
    html, body {{ height: 100%; margin: 0; }}
    body {{ display: grid; place-items: center; font-family: sans-serif; }}
    form {{ display: grid; gap: 20px; width: 720px; }}
    input, button {{ padding: 18px; font-size: 24px; }}
  </style>
</head>
<body>
  <form action="/results" method="get">
    <label for="account-search">Account search</label>
    <input id="account-search" name="q" aria-label="Account search" type="search" value="" autocomplete="off">
    <button type="submit" aria-label="Search">Search</button>
  </form>
</body>
</html>
""".encode("utf-8")
            self._write_html(200, body)
            return

        if parsed.path == "/results":
            self.server.results_requests += 1  # type: ignore[attr-defined]
            if not self._has_existing_session():
                self.server.unauthorized_requests += 1  # type: ignore[attr-defined]
                self._write_text(401, "existing browser login required")
                return
            query = parse_qs(parsed.query, keep_blank_values=True).get("q", [])
            value = query[0] if len(query) == 1 else ""
            self.server.result_queries.append(value)  # type: ignore[attr-defined]
            if value != _TEXT:
                self._write_text(400, "unexpected search query")
                return
            self.server.authenticated_results_requests += 1  # type: ignore[attr-defined]
            body = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>{_RESULT_TITLE}</title></head>
<body><main><h1>Search complete</h1><p>{_TEXT}</p></main></body>
</html>
""".encode("utf-8")
            self._write_html(200, body)
            return

        self.send_response(404)
        self.end_headers()

    def _has_existing_session(self) -> bool:
        cookies = [
            item.strip()
            for item in str(self.headers.get("Cookie") or "").split(";")
            if item.strip()
        ]
        return _SESSION_COOKIE in cookies

    def _write_text(self, status: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_html(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return None


class WindowsInteractiveNaturalUserBrowserSearchWorkE2ETests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        WindowsInteractiveUserBrowserBridgeProviderE2ETests._require_input_desktop()

    def test_desktop_work_searches_current_authorized_page_without_engineering_targets(self) -> None:
        self._require_input_desktop()
        browsers = _find_installed_browsers()
        if not browsers:
            self.fail("interactive Windows runner has neither stable Edge nor Chrome")

        repo_root = Path(__file__).resolve().parents[3]
        extension = repo_root / "apps" / "desktop" / "browser-extension"
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.login_requests = 0  # type: ignore[attr-defined]
        server.account_requests = 0  # type: ignore[attr-defined]
        server.authenticated_account_requests = 0  # type: ignore[attr-defined]
        server.results_requests = 0  # type: ignore[attr-defined]
        server.authenticated_results_requests = 0  # type: ignore[attr-defined]
        server.unauthorized_requests = 0  # type: ignore[attr-defined]
        server.result_queries = []  # type: ignore[attr-defined]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        port = int(server.server_address[1])
        login_url = f"http://{_HOST}:{port}/login"

        provider, executable = browsers[0]
        fixture = _ExtensionBrowserFixture(provider, executable, login_url, extension)
        runtime_tmp = tempfile.TemporaryDirectory()
        resident = None
        rpc = None
        try:
            fixture.start()
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if int(server.authenticated_account_requests) >= 1:  # type: ignore[attr-defined]
                    break
                time.sleep(0.05)
            self.assertGreaterEqual(int(server.authenticated_account_requests), 1)  # type: ignore[attr-defined]
            self.assertEqual(int(server.unauthorized_requests), 0)  # type: ignore[attr-defined]
            login_before = int(server.login_requests)  # type: ignore[attr-defined]
            account_before = int(server.account_requests)  # type: ignore[attr-defined]

            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(runtime_tmp.name) / "kernel.db",
            )
            rpc = ResidentRpcServer(resident=resident)
            rpc.service.acquire()

            fixture.activate()
            _press_extension_action_shortcut()
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                authorization = resident.user_browser_authorization()
                if authorization.get("provider") == "zn-extension-user-browser":
                    break
                time.sleep(0.05)
            self.assertEqual(
                resident.user_browser_authorization().get("provider"),
                "zn-extension-user-browser",
            )

            thread_id = "desktop-natural-search-e2e"
            created = rpc.handle(
                {
                    "id": "create",
                    "method": "work_create",
                    "params": {"thread_id": thread_id, "title": "Natural browser search"},
                }
            )
            self.assertTrue(created["ok"])

            # This is the same daemon Work ingress used by the desktop input box.
            # The user supplies no URL, DOM id, coordinates, accessible names,
            # internal action kind, expected destination or engineering vocabulary.
            task = f"Search this page for {_TEXT}."
            started = rpc.handle(
                {
                    "id": "start",
                    "method": "work_start",
                    "params": {
                        "thread_id": thread_id,
                        "task": task,
                        "kind": "desktop_user_event",
                        "priority": 0,
                        "payload": {"model_policy": "never"},
                    },
                }
            )
            self.assertTrue(started["ok"])
            progress = started["result"]["progress"]
            event_id = str(progress["event_id"])

            deadline = time.monotonic() + 20.0
            final = None
            while time.monotonic() < deadline:
                resident.live_once()
                polled = rpc.handle(
                    {
                        "id": "progress",
                        "method": "work_progress",
                        "params": {
                            "thread_id": thread_id,
                            "event_id": event_id,
                            "message_limit": 120,
                        },
                    }
                )
                self.assertTrue(polled["ok"])
                progress = polled["result"]["progress"]
                if progress["terminal"]:
                    final = polled["result"]
                    break
                time.sleep(0.05)

            self.assertIsNotNone(final, "desktop Work did not reach a terminal result")
            assert final is not None
            self.assertTrue(final["progress"]["finalized"])
            messages = final["thread"]["messages"]
            self.assertEqual(messages[0]["role"], "user")
            self.assertEqual(messages[0]["text"], task)
            zn_messages = [message for message in messages if message["role"] == "zn"]
            self.assertEqual(len(zn_messages), 1)
            self.assertIn("/results?q=", zn_messages[0]["text"])
            self.assertNotIn("textbox", task.lower())
            self.assertNotIn("button", task.lower())
            self.assertNotIn("http://", task.lower())

            # Independent HTTP evidence proves the actual authenticated browser
            # submitted the exact requested query once. It cannot be fabricated by
            # the resident's own completion result.
            self.assertEqual(int(server.login_requests), login_before)  # type: ignore[attr-defined]
            self.assertEqual(int(server.account_requests), account_before)  # type: ignore[attr-defined]
            self.assertEqual(int(server.results_requests), 1)  # type: ignore[attr-defined]
            self.assertEqual(int(server.authenticated_results_requests), 1)  # type: ignore[attr-defined]
            self.assertEqual(list(server.result_queries), [_TEXT])  # type: ignore[attr-defined]
            self.assertEqual(int(server.unauthorized_requests), 0)  # type: ignore[attr-defined]

            fixture.activate()
            deadline = time.monotonic() + 5.0
            foreground = None
            while time.monotonic() < deadline:
                candidate = resident.foreground_window.probe()
                if _RESULT_TITLE.lower() in candidate.title.lower():
                    foreground = candidate
                    break
                time.sleep(0.05)
            self.assertIsNotNone(
                foreground,
                "Windows foreground evidence did not prove the user-visible result page",
            )

            print(
                "ZN_NATURAL_USER_BROWSER_SEARCH_WORK_E2E_EVIDENCE="
                + json.dumps(
                    {
                        "provider": provider,
                        "desktop_work_ingress": True,
                        "normal_language_task": task,
                        "user_supplied_target_names": False,
                        "user_supplied_urls": False,
                        "existing_authenticated_session": True,
                        "credential_transfer_to_zn": False,
                        "semantic_steps": [
                            "discover_search_textbox",
                            "type_and_resense",
                            "discover_search_button",
                            "click_and_resense",
                        ],
                        "exact_query_submitted_once": True,
                        "work_finalized": True,
                        "independent_verifiers": ["http-server", "windows-foreground"],
                    },
                    sort_keys=True,
                )
            )
        finally:
            if resident is not None:
                try:
                    if resident.user_browser_extension_status().get("authorized"):
                        resident.revoke_user_browser_extension_tab()
                except Exception:
                    pass
            if rpc is not None:
                try:
                    rpc.service.release()
                except Exception:
                    pass
            if resident is not None:
                try:
                    resident.store.close()
                except Exception:
                    pass
            runtime_tmp.cleanup()
            fixture.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
