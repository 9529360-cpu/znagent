from __future__ import annotations

import json
import secrets
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


_INITIAL_TITLE = "ZN User Browser Bridge E2E"
_FRESH_TITLE = "ZN Managed Research Fresh A E2E"
_RESULT_TITLE = "ZN Managed Research Result E2E"
_HOST = "zn-extension-e2e.test"
_SESSION_COOKIE = "zn_managed_research_session=already-authenticated-before-zn"
_DRAFT = "keep-this-user-draft"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/login":
            self.server.login_requests += 1  # type: ignore[attr-defined]
            self.send_response(302)
            self.send_header("Set-Cookie", f"{_SESSION_COOKIE}; Path=/; HttpOnly; SameSite=Strict")
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
            port = int(self.server.server_address[1])  # type: ignore[attr-defined]
            body = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>{_INITIAL_TITLE}</title></head>
<body>
  <main>
    <label for="draft">Existing user draft</label>
    <textarea id="draft">{_DRAFT}</textarea>
    <nav aria-label="Release references">
      <a href="http://127.0.0.1:{port}/ref-a">Reference release note</a>
      <a href="http://127.0.0.1:{port}/ref-b">Reference release registry</a>
    </nav>
    <form action="/results" method="get">
      <label for="account-search">Account search</label>
      <input id="account-search" name="q" aria-label="Account search" type="search" value="" autocomplete="off">
      <button type="submit" aria-label="Search">Search</button>
    </form>
  </main>
  <script>
    sessionStorage.setItem('znDraft', document.querySelector('#draft').value);
    const timer = setInterval(async () => {{
      try {{
        const response = await fetch('/state', {{ cache: 'no-store' }});
        const state = await response.text();
        if (state === 'changed') {{
          const oldForm = document.querySelector('form');
          const freshForm = oldForm.cloneNode(true);
          freshForm.dataset.generation = 'fresh';
          oldForm.replaceWith(freshForm);
          document.title = '{_FRESH_TITLE}';
          clearInterval(timer);
        }}
      }} catch {{}}
    }}, 80);
  </script>
</body>
</html>
""".encode("utf-8")
            self._write_html(200, body)
            return

        if parsed.path == "/state":
            self.server.state_requests += 1  # type: ignore[attr-defined]
            self._write_text(200, "changed" if self.server.research_started else "waiting")  # type: ignore[attr-defined]
            return

        if parsed.path == "/ref-a":
            self.server.research_started = True  # type: ignore[attr-defined]
            self.server.managed_requests.append((parsed.path, str(self.headers.get("Cookie") or "")))  # type: ignore[attr-defined]
            code = str(self.server.release_code)  # type: ignore[attr-defined]
            self._write_html(
                200,
                f"<!doctype html><html><head><title>Release note</title></head><body><main><p>Confirmed release code: {code}</p></main></body></html>".encode("utf-8"),
            )
            return

        if parsed.path == "/ref-b":
            self.server.managed_requests.append((parsed.path, str(self.headers.get("Cookie") or "")))  # type: ignore[attr-defined]
            self._write_html(
                200,
                b"<!doctype html><html><head><title>Release registry</title></head><body><main><p>Summary only. Open the details to inspect the release.</p><a href='/ref-b/details'>View release details</a></main></body></html>",
            )
            return

        if parsed.path == "/ref-b/details":
            self.server.managed_requests.append((parsed.path, str(self.headers.get("Cookie") or "")))  # type: ignore[attr-defined]
            code = str(self.server.release_code)  # type: ignore[attr-defined]
            self._write_html(
                200,
                f"<!doctype html><html><head><title>Release registry details</title></head><body><main><p>Registry release code: {code}</p></main></body></html>".encode("utf-8"),
            )
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
            if value != self.server.release_code:  # type: ignore[attr-defined]
                self._write_text(400, "unexpected release code")
                return
            self.server.authenticated_results_requests += 1  # type: ignore[attr-defined]
            body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>checking preserved draft</title></head>
<body><main><h1>Search complete</h1><p>{value}</p></main>
<script>
  document.title = sessionStorage.getItem('znDraft') === '{_DRAFT}' ? '{_RESULT_TITLE}' : 'DRAFT LOST';
</script>
</body></html>
""".encode("utf-8")
            self._write_html(200, body)
            return

        self.send_response(404)
        self.end_headers()

    def _has_existing_session(self) -> bool:
        cookies = [item.strip() for item in str(self.headers.get("Cookie") or "").split(";") if item.strip()]
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


class WindowsInteractiveManagedResearchReturnWorkE2ETests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        WindowsInteractiveUserBrowserBridgeProviderE2ETests._require_input_desktop()

    def test_desktop_work_researches_managed_sources_then_returns_to_fresh_authorized_page(self) -> None:
        self._require_input_desktop()
        browsers = _find_installed_browsers()
        if not browsers:
            self.fail("interactive Windows runner has neither stable Edge nor Chrome")

        release_code = "REL-" + secrets.token_hex(5).upper()
        repo_root = Path(__file__).resolve().parents[3]
        extension = repo_root / "apps" / "desktop" / "browser-extension"
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.release_code = release_code  # type: ignore[attr-defined]
        server.research_started = False  # type: ignore[attr-defined]
        server.login_requests = 0  # type: ignore[attr-defined]
        server.account_requests = 0  # type: ignore[attr-defined]
        server.authenticated_account_requests = 0  # type: ignore[attr-defined]
        server.state_requests = 0  # type: ignore[attr-defined]
        server.results_requests = 0  # type: ignore[attr-defined]
        server.authenticated_results_requests = 0  # type: ignore[attr-defined]
        server.unauthorized_requests = 0  # type: ignore[attr-defined]
        server.result_queries = []  # type: ignore[attr-defined]
        server.managed_requests = []  # type: ignore[attr-defined]
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

            resident = build_resident_runtime(config={"model": {}}, store_path=Path(runtime_tmp.name) / "kernel.db")
            rpc = ResidentRpcServer(resident=resident)
            rpc.service.acquire()

            fixture.activate()
            _press_extension_action_shortcut()
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                if resident.user_browser_authorization().get("provider") == "zn-extension-user-browser":
                    break
                time.sleep(0.05)
            self.assertEqual(resident.user_browser_authorization().get("provider"), "zn-extension-user-browser")

            thread_id = "desktop-managed-research-return-e2e"
            created = rpc.handle({"id": "create", "method": "work_create", "params": {"thread_id": thread_id, "title": "Research references then search"}})
            self.assertTrue(created["ok"])

            task = "检查这里链接的两个参考页，确认它们一致的 release code，然后回来在这个页面搜索那个 code。"
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
            event_id = str(started["result"]["progress"]["event_id"])

            deadline = time.monotonic() + 35.0
            final = None
            while time.monotonic() < deadline:
                resident.live_once()
                polled = rpc.handle(
                    {
                        "id": "progress",
                        "method": "work_progress",
                        "params": {"thread_id": thread_id, "event_id": event_id, "message_limit": 160},
                    }
                )
                self.assertTrue(polled["ok"])
                if polled["result"]["progress"]["terminal"]:
                    final = polled["result"]
                    break
                time.sleep(0.05)

            self.assertIsNotNone(final, "desktop Work did not reach a terminal result")
            assert final is not None
            self.assertTrue(final["progress"]["finalized"])
            messages = final["thread"]["messages"]
            self.assertEqual(messages[0]["role"], "user")
            self.assertEqual(messages[0]["text"], task)
            self.assertNotIn("http://", task.lower())
            self.assertNotIn("tab", task.lower())
            self.assertNotIn("selector", task.lower())
            self.assertNotIn("button", task.lower())
            self.assertNotIn("textbox", task.lower())

            paths = [path for path, _cookie in server.managed_requests]  # type: ignore[attr-defined]
            self.assertIn("/ref-a", paths)
            self.assertIn("/ref-b", paths)
            self.assertIn("/ref-b/details", paths, "source-B landing must force a fresh investigate/replan step")
            self.assertTrue(all(_SESSION_COOKIE not in cookie for _path, cookie in server.managed_requests))  # type: ignore[attr-defined]

            self.assertEqual(int(server.login_requests), login_before)  # type: ignore[attr-defined]
            self.assertEqual(int(server.account_requests), account_before)  # type: ignore[attr-defined]
            self.assertEqual(int(server.results_requests), 1)  # type: ignore[attr-defined]
            self.assertEqual(int(server.authenticated_results_requests), 1)  # type: ignore[attr-defined]
            self.assertEqual(list(server.result_queries), [release_code])  # type: ignore[attr-defined]
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
            self.assertIsNotNone(foreground, "Windows foreground evidence did not prove the final A result and preserved draft")

            print(
                "ZN_MANAGED_RESEARCH_RETURN_WORK_E2E_EVIDENCE="
                + json.dumps(
                    {
                        "provider": provider,
                        "normal_language_task": task,
                        "random_release_code": release_code,
                        "user_supplied_urls_or_targets": False,
                        "existing_authenticated_user_session": True,
                        "managed_sources_used": paths,
                        "source_b_replanned_to_detail": "/ref-b/details" in paths,
                        "managed_received_user_cookie": False,
                        "user_draft_preserved_through_return": True,
                        "final_mutation_exactly_once": True,
                        "same_work_finalized": True,
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