from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlsplit

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.service import ResidentService

from test_windows_interactive_user_browser_bridge import (
    _find_installed_browsers,
    WindowsInteractiveUserBrowserBridgeProviderE2ETests,
)
from test_windows_interactive_user_browser_extension import (
    _ExtensionBrowserFixture,
    _press_extension_action_shortcut,
)


_INITIAL_TITLE = "ZN User Browser Bridge E2E"
_RESULT_TITLE = "ZN Search Results E2E"
_TARGET_NAME = "Account search"
_BUTTON_NAME = "Search"
_TEXT = "alice@example.test"
_HOST = "zn-extension-e2e.test"
_SESSION_COOKIE = "zn_existing_session=already-authenticated-before-zn"


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
    <label for="account-search">{_TARGET_NAME}</label>
    <input id="account-search" name="q" aria-label="{_TARGET_NAME}" type="text" value="" autocomplete="off">
    <button type="submit" aria-label="{_BUTTON_NAME}">{_BUTTON_NAME}</button>
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
<body><main><h1>Search complete</h1><p id="result">{_TEXT}</p></main></body>
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


class WindowsInteractiveUserBrowserExtensionFormSubmitE2ETests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        WindowsInteractiveUserBrowserBridgeProviderE2ETests._require_input_desktop()

    def test_existing_session_fills_clicks_resenses_and_proves_results(self) -> None:
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
        account_url = f"http://{_HOST}:{port}/account"
        results_url = f"http://{_HOST}:{port}/results?q={quote_plus(_TEXT)}"

        provider, executable = browsers[0]
        fixture = _ExtensionBrowserFixture(provider, executable, login_url, extension)
        runtime_tmp = tempfile.TemporaryDirectory()
        resident = None
        service = None
        try:
            # Browser owns the authenticated session before Resident exists.
            fixture.start()
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if int(server.authenticated_account_requests) >= 1:  # type: ignore[attr-defined]
                    break
                time.sleep(0.05)
            self.assertGreaterEqual(int(server.login_requests), 1)  # type: ignore[attr-defined]
            self.assertGreaterEqual(int(server.authenticated_account_requests), 1)  # type: ignore[attr-defined]
            self.assertEqual(int(server.unauthorized_requests), 0)  # type: ignore[attr-defined]
            login_before = int(server.login_requests)  # type: ignore[attr-defined]
            account_before = int(server.account_requests)  # type: ignore[attr-defined]

            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(runtime_tmp.name) / "kernel.db",
            )
            service = ResidentService(resident)
            service.acquire()

            fixture.activate()
            _press_extension_action_shortcut()
            deadline = time.monotonic() + 8.0
            authorization = None
            while time.monotonic() < deadline:
                candidate = resident.user_browser_authorization()
                if (
                    candidate.get("authorized")
                    and candidate.get("provider") == "zn-extension-user-browser"
                ):
                    authorization = candidate
                    break
                time.sleep(0.05)
            self.assertIsNotNone(
                authorization,
                "real loaded extension did not explicitly authorize the existing-session tab",
            )

            task = (
                f'open {account_url} and type "{_TEXT}" into textbox "{_TARGET_NAME}", '
                f'then click button "{_BUTTON_NAME}" and expect {results_url}'
            )
            result = resident.submit(
                task,
                payload={"model_policy": "never"},
            )
            self.assertTrue(result.success, result.reason)
            self.assertEqual(result.model_invocations, 0)
            self.assertEqual(result.response, results_url)

            # Independent server evidence proves the existing browser session and
            # exact user query crossed the real page transition. No provider return
            # can manufacture these HTTP observations.
            self.assertEqual(int(server.login_requests), login_before)  # type: ignore[attr-defined]
            self.assertEqual(int(server.account_requests), account_before)  # type: ignore[attr-defined]
            self.assertEqual(int(server.results_requests), 1)  # type: ignore[attr-defined]
            self.assertEqual(int(server.authenticated_results_requests), 1)  # type: ignore[attr-defined]
            self.assertEqual(list(server.result_queries), [_TEXT])  # type: ignore[attr-defined]
            self.assertEqual(int(server.unauthorized_requests), 0)  # type: ignore[attr-defined]

            # Independent Windows foreground evidence must agree with the result
            # page, while the Body itself already performed a fresh extension tab
            # observation and exact final-URL comparison after the click.
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
                "Windows foreground evidence did not prove the browser reached the results page",
            )

            fixture.activate()
            _press_extension_action_shortcut()
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if not resident.user_browser_extension_status().get("authorized"):
                    break
                time.sleep(0.05)
            self.assertFalse(resident.user_browser_extension_status()["authorized"])
            self.assertIsNotNone(fixture.process)
            assert fixture.process is not None
            self.assertIsNone(fixture.process.poll())

            print(
                "ZN_USER_BROWSER_EXTENSION_FORM_E2E_EVIDENCE="
                + json.dumps(
                    {
                        "provider": provider,
                        "browser_plane": "user",
                        "existing_authenticated_session": True,
                        "session_established_before_resident": True,
                        "credential_transfer_to_zn": False,
                        "start_navigation_performed_by_zn": False,
                        "semantic_steps": ["type_exact_textbox", "click_exact_button"],
                        "page_transition": True,
                        "fresh_final_url_verified": True,
                        "server_authenticated_result_requests": int(
                            server.authenticated_results_requests  # type: ignore[attr-defined]
                        ),
                        "independent_verifiers": ["http-server", "windows-foreground"],
                        "browser_process_alive_after_revoke": fixture.process.poll() is None,
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
            if service is not None:
                service.release()
            if resident is not None:
                resident.store.close()
            runtime_tmp.cleanup()
            fixture.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
