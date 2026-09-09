from __future__ import annotations

import copy
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


_HOST = "zn-extension-e2e.test"
_SESSION_COOKIE = "zn_e2e06_session=already-authenticated-before-zn"
_INITIAL_TITLE = "ZN User Browser Bridge E2E"
_FRESH_TITLE = "ZN E2E06 Alice Order Drifted"
_SAVED_TITLE = "ZN E2E06 Note Saved"
_TASK = "查一下 Alice 最近的订单，再去官网核对退货规则，然后回来把备注更新成官网写的退货时限。"
_EVIDENCE_KEY = "resident_user_browser_authenticated_return_note"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/login":
            self.server.login_requests += 1  # type: ignore[attr-defined]
            self.send_response(302)
            self.send_header("Set-Cookie", f"{_SESSION_COOKIE}; Path=/; HttpOnly; SameSite=Strict")
            self.send_header("Location", "/orders/alice")
            self.end_headers()
            return

        if parsed.path == "/orders/alice":
            self.server.order_requests += 1  # type: ignore[attr-defined]
            if not self._has_existing_session():
                self.server.unauthorized_requests += 1  # type: ignore[attr-defined]
                self._write_text(401, "existing browser login required")
                return
            self.server.authenticated_order_requests += 1  # type: ignore[attr-defined]
            saved = str(self.server.saved_note or "")  # type: ignore[attr-defined]
            title = _SAVED_TITLE if parsed.query == "saved=1" else _INITIAL_TITLE
            note_value = saved.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            port = int(self.server.server_address[1])  # type: ignore[attr-defined]
            body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title></head>
<body><main id="order-layout" data-layout="initial">
  <article aria-label="Alice order">
    <h1>Alice</h1><p>Order A-1042</p><p>Status: delivered</p>
    <p>Saved note: {note_value}</p>
  </article>
  <section id="research-panel">
    <a href="http://127.0.0.1:{port}/official-return-policy">Official return policy</a>
  </section>
  <form action="/orders/alice" method="get">
    <label for="order-search">Order search</label>
    <input id="order-search" name="q" aria-label="Order search" type="search" value="" autocomplete="off">
    <button type="submit" aria-label="Search orders">Search orders</button>
  </form>
  <section id="note-slot">
    <form id="note-form" action="/orders/alice?saved=1" method="post" data-generation="initial">
      <label for="order-note">Order note</label>
      <textarea id="order-note" name="note" aria-label="Order note"></textarea>
      <button type="submit" aria-label="Save note">Save note</button>
    </form>
  </section>
</main>
<script>
  const timer = setInterval(async () => {{
    try {{
      const response = await fetch('/research-state', {{cache: 'no-store'}});
      if ((await response.text()) === 'changed') {{
        const layout = document.querySelector('#order-layout');
        const oldSlot = document.querySelector('#note-slot');
        const oldForm = document.querySelector('#note-form');
        const freshWorkspace = document.createElement('aside');
        freshWorkspace.id = 'customer-workspace';
        freshWorkspace.dataset.layout = 'follow-up-sidebar';
        const freshForm = document.createElement('form');
        freshForm.id = 'follow-up-form';
        freshForm.action = '/orders/alice?saved=1';
        freshForm.method = 'post';
        freshForm.dataset.generation = 'fresh';
        freshForm.innerHTML = `
          <h2>Customer follow-up</h2>
          <label for="customer-follow-up">Customer follow-up</label>
          <textarea id="customer-follow-up" name="case_update" aria-label="Customer follow-up"></textarea>
          <button type="submit" aria-label="Commit change">Commit change</button>
        `;
        freshWorkspace.appendChild(freshForm);
        oldForm.remove();
        oldSlot.remove();
        layout.dataset.layout = 'drifted';
        layout.insertBefore(freshWorkspace, layout.firstElementChild);
        document.title = '{_FRESH_TITLE}';
        await fetch('/drift-applied', {{cache: 'no-store'}});
        clearInterval(timer);
      }}
    }} catch {{}}
  }}, 80);
</script>
</body></html>""".encode("utf-8")
            self._write_html(200, body)
            return

        if parsed.path == "/official-return-policy":
            self.server.research_started = True  # type: ignore[attr-defined]
            self.server.managed_requests.append(  # type: ignore[attr-defined]
                (parsed.path, str(self.headers.get("Cookie") or ""))
            )
            # The managed research response cannot finish until the USER page has
            # actually replaced and moved the form. This makes the required order
            # deterministic: research starts -> drift applies -> fresh Sense runs.
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and not bool(self.server.drift_applied):  # type: ignore[attr-defined]
                time.sleep(0.02)
            if not bool(self.server.drift_applied):  # type: ignore[attr-defined]
                self._write_text(503, "authorized page drift did not apply")
                return
            policy = str(self.server.policy_text)  # type: ignore[attr-defined]
            self._write_html(
                200,
                f"<!doctype html><html><head><title>Official returns</title></head><body><main><h1>Returns</h1><p>Official return policy: {policy}</p></main></body></html>".encode("utf-8"),
            )
            return

        if parsed.path == "/research-state":
            self._write_text(200, "changed" if self.server.research_started else "waiting")  # type: ignore[attr-defined]
            return

        if parsed.path == "/drift-applied":
            self.server.drift_applied = True  # type: ignore[attr-defined]
            self.server.drift_reports += 1  # type: ignore[attr-defined]
            self._write_text(200, "ok")
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path != "/orders/alice" or parsed.query != "saved=1":
            self.send_response(404)
            self.end_headers()
            return
        self.server.note_mutations += 1  # type: ignore[attr-defined]
        if not self._has_existing_session():
            self.server.unauthorized_requests += 1  # type: ignore[attr-defined]
            self._write_text(401, "existing browser login required")
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        parsed_values = parse_qs(raw, keep_blank_values=True)
        self.server.submitted_field_names = sorted(parsed_values)  # type: ignore[attr-defined]
        values = parsed_values.get("case_update", [])
        if len(values) != 1 or "note" in parsed_values:
            self.server.rejected_stale_submissions += 1  # type: ignore[attr-defined]
            self._write_text(400, "drifted form field required")
            return
        note = values[0]
        self.server.saved_note = note  # type: ignore[attr-defined]
        body = f"""<!doctype html><html><head><title>{_SAVED_TITLE}</title></head>
<body><main><article><h1>Alice</h1><p>Order A-1042</p><p>Status: delivered</p><p>Saved note: {note}</p></article></main></body></html>""".encode("utf-8")
        self._write_html(200, body)

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


class E2E06BrowserDriftRecoveryTests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        WindowsInteractiveUserBrowserBridgeProviderE2ETests._require_input_desktop()

    def test_authenticated_order_note_regrounds_after_semantic_and_layout_drift(self) -> None:
        self._require_input_desktop()
        browsers = _find_installed_browsers()
        if not browsers:
            self.fail("interactive Windows runner has neither stable Edge nor Chrome")

        policy = "Returns accepted within 30 days of delivery."
        repo_root = Path(__file__).resolve().parents[3]
        extension = repo_root / "apps" / "desktop" / "browser-extension"
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.policy_text = policy  # type: ignore[attr-defined]
        server.saved_note = ""  # type: ignore[attr-defined]
        server.research_started = False  # type: ignore[attr-defined]
        server.drift_applied = False  # type: ignore[attr-defined]
        server.drift_reports = 0  # type: ignore[attr-defined]
        server.login_requests = 0  # type: ignore[attr-defined]
        server.order_requests = 0  # type: ignore[attr-defined]
        server.authenticated_order_requests = 0  # type: ignore[attr-defined]
        server.unauthorized_requests = 0  # type: ignore[attr-defined]
        server.note_mutations = 0  # type: ignore[attr-defined]
        server.rejected_stale_submissions = 0  # type: ignore[attr-defined]
        server.submitted_field_names = []  # type: ignore[attr-defined]
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
                if int(server.authenticated_order_requests) >= 1:  # type: ignore[attr-defined]
                    break
                time.sleep(0.05)
            self.assertGreaterEqual(int(server.authenticated_order_requests), 1)  # type: ignore[attr-defined]
            self.assertEqual(int(server.unauthorized_requests), 0)  # type: ignore[attr-defined]
            login_before = int(server.login_requests)  # type: ignore[attr-defined]

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
            authorization = resident.user_browser_authorization()
            self.assertEqual(authorization.get("provider"), "zn-extension-user-browser")
            attached_at = str(authorization.get("attached_at") or "")
            authorized_tab_id = int(authorization.get("tab_id") or 0)
            self.assertGreater(authorized_tab_id, 0)

            thread_id = "e2e06-browser-drift-recovery"
            created = rpc.handle({"id": "create", "method": "work_create", "params": {"thread_id": thread_id, "title": "Alice return note drift recovery"}})
            self.assertTrue(created["ok"])
            started = rpc.handle(
                {
                    "id": "start",
                    "method": "work_start",
                    "params": {
                        "thread_id": thread_id,
                        "task": _TASK,
                        "kind": "desktop_user_event",
                        "priority": 0,
                        "payload": {"model_policy": "never"},
                    },
                }
            )
            self.assertTrue(started["ok"])
            event_id = str(started["result"]["progress"]["event_id"])

            deadline = time.monotonic() + 45.0
            final = None
            evidence_snapshot = None
            while time.monotonic() < deadline:
                resident.live_once()
                current = resident.store.get_working_state().data.get(_EVIDENCE_KEY)
                if isinstance(current, dict):
                    evidence_snapshot = copy.deepcopy(current)
                polled = rpc.handle(
                    {
                        "id": "progress",
                        "method": "work_progress",
                        "params": {"thread_id": thread_id, "event_id": event_id, "message_limit": 180},
                    }
                )
                self.assertTrue(polled["ok"])
                if polled["result"]["progress"]["terminal"]:
                    final = polled["result"]
                    break
                time.sleep(0.05)

            self.assertIsNotNone(final, "E2E-06 Work did not reach a terminal result")
            assert final is not None
            progress = final["progress"]
            self.assertTrue(progress["finalized"])
            self.assertEqual(progress["thread_id"], thread_id)
            self.assertEqual(progress["event_id"], event_id)

            run_result = resident.result_for(event_id)
            self.assertIsNotNone(run_result)
            assert run_result is not None
            self.assertTrue(run_result.success)
            self.assertEqual(run_result.model_invocations, 0)
            self.assertIn("fresh anchored read proving the saved policy text", str(run_result.reason or ""))

            self.assertIsInstance(evidence_snapshot, dict)
            assert isinstance(evidence_snapshot, dict)
            initial = evidence_snapshot.get("initial_authorized_page")
            fresh = evidence_snapshot.get("fresh_authorized_page")
            note_form = evidence_snapshot.get("note_form")
            self.assertIsInstance(initial, dict)
            self.assertIsInstance(fresh, dict)
            self.assertIsInstance(note_form, dict)
            assert isinstance(initial, dict) and isinstance(fresh, dict) and isinstance(note_form, dict)

            self.assertTrue(bool(server.drift_applied))  # type: ignore[attr-defined]
            self.assertGreaterEqual(int(server.drift_reports), 1)  # type: ignore[attr-defined]
            self.assertTrue(evidence_snapshot.get("authorized_page_changed_during_research"))
            self.assertEqual(initial.get("textbox_name"), "Order note")
            self.assertEqual(fresh.get("textbox_name"), "Customer follow-up")
            self.assertEqual(initial.get("textbox_query_parameter"), "note")
            self.assertEqual(fresh.get("textbox_query_parameter"), "case_update")
            self.assertEqual(initial.get("button_name"), "Save note")
            self.assertEqual(fresh.get("button_name"), "Commit change")
            self.assertNotEqual(initial.get("textbox_target_id"), fresh.get("textbox_target_id"))
            self.assertNotEqual(initial.get("button_target_id"), fresh.get("button_target_id"))
            self.assertNotEqual(initial.get("form_signature"), fresh.get("form_signature"))
            self.assertEqual(note_form.get("textbox_name"), fresh.get("textbox_name"))
            self.assertEqual(note_form.get("textbox_query_parameter"), fresh.get("textbox_query_parameter"))
            self.assertEqual(note_form.get("button_name"), fresh.get("button_name"))
            self.assertEqual(note_form.get("textbox_target_id"), fresh.get("textbox_target_id"))
            self.assertEqual(note_form.get("button_target_id"), fresh.get("button_target_id"))
            self.assertEqual(note_form.get("form_signature"), fresh.get("form_signature"))

            self.assertEqual(int(server.note_mutations), 1)  # type: ignore[attr-defined]
            self.assertEqual(int(server.rejected_stale_submissions), 0)  # type: ignore[attr-defined]
            self.assertEqual(list(server.submitted_field_names), ["case_update"])  # type: ignore[attr-defined]
            self.assertEqual(str(server.saved_note), policy)  # type: ignore[attr-defined]
            self.assertEqual(int(server.login_requests), login_before)  # type: ignore[attr-defined]
            self.assertEqual(int(server.unauthorized_requests), 0)  # type: ignore[attr-defined]
            self.assertEqual([path for path, _ in server.managed_requests], ["/official-return-policy"])  # type: ignore[attr-defined]
            self.assertTrue(all(_SESSION_COOKIE not in cookie for _path, cookie in server.managed_requests))  # type: ignore[attr-defined]

            current_auth = resident.user_browser_authorization()
            self.assertEqual(int(current_auth.get("tab_id") or 0), authorized_tab_id)
            self.assertEqual(str(current_auth.get("attached_at") or ""), attached_at)
            self.assertEqual(str(evidence_snapshot.get("authorization_attached_at") or ""), attached_at)

            fixture.activate()
            deadline = time.monotonic() + 5.0
            foreground = None
            while time.monotonic() < deadline:
                candidate = resident.foreground_window.probe()
                if _SAVED_TITLE.lower() in candidate.title.lower():
                    foreground = candidate
                    break
                time.sleep(0.05)
            self.assertIsNotNone(foreground, "fresh Windows evidence did not prove the persisted E2E-06 saved-note page")

            resident.revoke_user_browser_extension_tab()
            self.assertFalse(resident.user_browser_extension_status().get("authorized"))
            self.assertEqual(int(server.login_requests), login_before)  # type: ignore[attr-defined]
            self.assertEqual(str(server.saved_note), policy)  # type: ignore[attr-defined]

            print(
                "ZN_E2E06_BROWSER_DRIFT_RECOVERY="
                + json.dumps(
                    {
                        "provider": provider,
                        "normal_language_task": _TASK,
                        "same_root_work": progress["thread_id"] == thread_id,
                        "model_invocations": run_result.model_invocations,
                        "existing_authenticated_user_session": True,
                        "authorized_tab_id_stable": int(current_auth.get("tab_id") or 0) == authorized_tab_id,
                        "same_authorization_generation_through_mutation": str(current_auth.get("attached_at") or "") == attached_at,
                        "managed_received_user_cookie": False,
                        "layout_and_dom_drift_applied": bool(server.drift_applied),  # type: ignore[attr-defined]
                        "initial_textbox_name": initial.get("textbox_name"),
                        "fresh_textbox_name": fresh.get("textbox_name"),
                        "initial_control_name": initial.get("textbox_query_parameter"),
                        "fresh_control_name": fresh.get("textbox_query_parameter"),
                        "initial_button_name": initial.get("button_name"),
                        "fresh_button_name": fresh.get("button_name"),
                        "textbox_target_changed": initial.get("textbox_target_id") != fresh.get("textbox_target_id"),
                        "button_target_changed": initial.get("button_target_id") != fresh.get("button_target_id"),
                        "form_signature_changed": initial.get("form_signature") != fresh.get("form_signature"),
                        "mutation_field_names": list(server.submitted_field_names),  # type: ignore[attr-defined]
                        "saved_note": policy,
                        "saved_business_state_verified": True,
                        "note_mutations": int(server.note_mutations),  # type: ignore[attr-defined]
                        "stale_submission_rejections": int(server.rejected_stale_submissions),  # type: ignore[attr-defined]
                        "authorization_revoked_after_completion": True,
                        "session_login_replayed": False,
                        "independent_verifiers": ["http-server-persisted-state", "resident-fresh-anchor", "windows-foreground"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                flush=True,
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
