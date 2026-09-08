from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import ModelRoute
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
_ROOT_TITLE = "ZN E2E07 Orders"
_ORDER = "A-1042"
_STATUS = "Status: delivered"
_CHILD_TITLE = f"Order {_ORDER} — {_STATUS}"
_TASK = f"在这个已经登录的网站里，打开订单 {_ORDER} 的详情看看，确认状态，然后回来继续处理。"
_SESSION_COOKIE = "zn_e2e07_session=already-authenticated-before-zn"


class _E2E07Cognition:
    def __init__(self) -> None:
        self.calls = 0

    @staticmethod
    def _observed_name(question: str, name: str) -> bool:
        return f'"name": "{name}"' in question

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        del context
        self.calls += 1
        if "Interpret only the user's desired outcome in the current browser" in question:
            value = {
                "kind": "user_browser_semantic_lookup",
                "subject_value": _ORDER,
                "subject_semantics": "订单编号",
                "operation": "打开这个订单的详情",
                "desired_result": "确认订单状态",
            }
        elif "Select the one safe textbox" in question:
            value = (
                {"status": "selected", "name": "订单编号"}
                if self._observed_name(question, "订单编号")
                else {"status": "ambiguous"}
            )
        elif "Select the button" in question:
            value = (
                {"status": "selected", "name": "打开订单详情"}
                if self._observed_name(question, "打开订单详情")
                else {"status": "ambiguous"}
            )
        elif "extract the business fact" in question:
            value = (
                {"status": "verified", "result": _STATUS}
                if _CHILD_TITLE in question
                else {"status": "not_verified"}
            )
        else:
            value = {"status": "not_verified"}
        return CognitiveIncrement(
            text=json.dumps(value, ensure_ascii=False),
            provider="e2e-cognition",
            model="bounded-language-fixture",
        )


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

        if parsed.path == "/root-dom-replaced":
            self.server.root_dom_replaced += 1  # type: ignore[attr-defined]
            self._write(200, "text/plain; charset=utf-8", b"ok")
            return

        if parsed.path == "/account":
            if not self._has_existing_session():
                self.server.unauthorized_requests += 1  # type: ignore[attr-defined]
                self._write(401, "text/plain; charset=utf-8", b"existing browser login required")
                return
            self.server.account_requests += 1  # type: ignore[attr-defined]
            body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{_ROOT_TITLE}</title>
<style>body{{font-family:sans-serif}} form{{display:grid;gap:12px;width:640px}} input,button{{padding:14px;font-size:20px}}</style>
</head><body>
<h1>Orders</h1>
<form id="orders" action="/orders/detail" method="get" target="_blank">
<label>订单编号<input aria-label="订单编号" name="order" type="text" autocomplete="off"></label>
<button id="open-detail" type="submit" aria-label="打开订单详情">打开订单详情</button>
</form>
<script>
let wasHidden = false;
document.addEventListener('visibilitychange', () => {{
  if (document.hidden) {{ wasHidden = true; return; }}
  if (!wasHidden) return;
  wasHidden = false;
  const oldButton = document.getElementById('open-detail');
  if (!oldButton) return;
  const replacement = oldButton.cloneNode(true);
  replacement.id = 'open-detail';
  oldButton.replaceWith(replacement);
  fetch('/root-dom-replaced', {{cache: 'no-store'}}).catch(() => {{}});
}});
</script>
</body></html>""".encode("utf-8")
            self._write(200, "text/html; charset=utf-8", body)
            return

        if parsed.path == "/orders/detail":
            if not self._has_existing_session():
                self.server.unauthorized_requests += 1  # type: ignore[attr-defined]
                self._write(401, "text/plain; charset=utf-8", b"existing browser login required")
                return
            values = parse_qs(parsed.query, keep_blank_values=True).get("order", [])
            order = values[0] if len(values) == 1 else ""
            self.server.child_requests += 1  # type: ignore[attr-defined]
            self.server.child_orders.append(order)  # type: ignore[attr-defined]
            if order != _ORDER:
                self._write(400, "text/plain; charset=utf-8", b"unexpected order")
                return
            body = f"""<!doctype html><html><head><meta charset="utf-8"><title>{_CHILD_TITLE}</title></head>
<body><main><h1>Order {_ORDER}</h1><p>{_STATUS}</p></main></body></html>""".encode("utf-8")
            self._write(200, "text/html; charset=utf-8", body)
            return

        if parsed.path == "/unrelated":
            if not self._has_existing_session():
                self.server.unauthorized_requests += 1  # type: ignore[attr-defined]
                self._write(401, "text/plain; charset=utf-8", b"existing browser login required")
                return
            self.server.unrelated_requests += 1  # type: ignore[attr-defined]
            self._write(
                200,
                "text/html; charset=utf-8",
                b"<!doctype html><title>Unrelated user tab</title><p>not task authority</p>",
            )
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

    def _write(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return None


class E2E07UserBrowserCausalPopupTests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        WindowsInteractiveUserBrowserBridgeProviderE2ETests._require_input_desktop()

    @staticmethod
    def _enable_cognition(resident, cognition: _E2E07Cognition) -> None:
        resident.kernel.reconfigure_resources(
            routes=[ModelRoute(
                route_id="e2e07-user-browser-causal-popup",
                provider="fixture",
                model="bounded-language-fixture",
                capabilities={"language_understanding": 1.0, "general": 0.8},
            )],
            worker_factory=CognitiveResourceWorkerFactory(resource_builder=lambda _route: cognition),
            max_attempts=1,
            resource_status={"available": True, "error": None},
        )

    def _start_server(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.login_requests = 0  # type: ignore[attr-defined]
        server.account_requests = 0  # type: ignore[attr-defined]
        server.child_requests = 0  # type: ignore[attr-defined]
        server.child_orders = []  # type: ignore[attr-defined]
        server.unrelated_requests = 0  # type: ignore[attr-defined]
        server.root_dom_replaced = 0  # type: ignore[attr-defined]
        server.unauthorized_requests = 0  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def _make_runtime(self):
        browsers = _find_installed_browsers()
        if not browsers:
            self.fail("interactive Windows runner has neither stable Edge nor Chrome")
        server, server_thread = self._start_server()
        port = int(server.server_address[1])
        login_url = f"http://{_HOST}:{port}/login"
        repo_root = Path(__file__).resolve().parents[3]
        extension = repo_root / "apps" / "desktop" / "browser-extension"
        provider, executable = browsers[0]
        fixture = _ExtensionBrowserFixture(provider, executable, login_url, extension)
        runtime_tmp = tempfile.TemporaryDirectory()
        cognition = _E2E07Cognition()
        env = {
            "server": server,
            "server_thread": server_thread,
            "fixture": fixture,
            "runtime_tmp": runtime_tmp,
            "resident": None,
            "rpc": None,
            "cognition": cognition,
            "provider": provider,
            "executable": executable,
            "port": port,
        }
        try:
            fixture.start()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and server.account_requests < 1:  # type: ignore[attr-defined]
                time.sleep(0.05)
            self.assertGreaterEqual(server.account_requests, 1)  # type: ignore[attr-defined]
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(runtime_tmp.name) / "kernel.db",
            )
            env["resident"] = resident
            rpc = ResidentRpcServer(resident=resident)
            env["rpc"] = rpc
            rpc.service.acquire()
            self._enable_cognition(resident, cognition)
            fixture.activate()
            _press_extension_action_shortcut()
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if resident.user_browser_authorization().get("provider") == "zn-extension-user-browser":
                    break
                time.sleep(0.05)
            self.assertEqual(
                resident.user_browser_authorization().get("provider"),
                "zn-extension-user-browser",
            )
            return env
        except BaseException:
            self._close_runtime(env)
            raise

    def _close_runtime(self, env) -> None:
        resident = env.get("resident")
        rpc = env.get("rpc")
        try:
            if resident is not None and resident.user_browser_extension_status().get("authorized"):
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
        fixture = env.get("fixture")
        if fixture is not None:
            try:
                fixture.close()
            except Exception:
                pass
        server = env.get("server")
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
        thread = env.get("server_thread")
        if thread is not None:
            thread.join(timeout=2)
        runtime_tmp = env.get("runtime_tmp")
        if runtime_tmp is not None:
            runtime_tmp.cleanup()

    def _start_work(self, env) -> str:
        rpc = env["rpc"]
        thread_id = "e2e07-user-browser-causal-popup"
        self.assertTrue(rpc.handle({
            "id": "create",
            "method": "work_create",
            "params": {"thread_id": thread_id, "title": "E2E07 causal popup"},
        })["ok"])
        started = rpc.handle({
            "id": "start",
            "method": "work_start",
            "params": {
                "thread_id": thread_id,
                "task": _TASK,
                "kind": "desktop_user_event",
                "priority": 0,
                "payload": {"model_policy": "on_demand"},
            },
        })
        self.assertTrue(started["ok"])
        return str(started["result"]["progress"]["event_id"])

    def _run_to_terminal(self, env, event_id: str, timeout: float = 40.0):
        resident = env["resident"]
        result = None
        trace = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and result is None:
            current = resident.live_once()
            current_for_event = (
                current
                if current is not None and current.event.event_id == event_id
                else None
            )
            state = resident.store.get_working_state()
            semantic = state.data.get(
                getattr(
                    resident,
                    "_SEMANTIC_LOOKUP_STATE_KEY",
                    "resident_user_browser_semantic_lookup",
                )
            )
            semantic = semantic if isinstance(semantic, dict) else {}
            trace.append({
                "stage": state.stage,
                "phase": semantic.get("phase"),
                "fresh_root_rebound_after_popup": semantic.get("fresh_root_rebound_after_popup"),
                "root_target_replaced_after_popup": semantic.get("root_target_replaced_after_popup"),
                "local_failure": str(state.data.get("local_failure") or "") or None,
                "result_success": current_for_event.success if current_for_event is not None else None,
                "result_reason": current_for_event.reason if current_for_event is not None else None,
            })
            if current_for_event is not None:
                result = current_for_event
            if result is None:
                time.sleep(0.03)
        return result, trace

    def test_existing_session_causal_child_returns_to_exact_root_and_regrounds(self) -> None:
        self._require_input_desktop()
        env = self._make_runtime()
        extra_process = None
        try:
            resident = env["resident"]
            authorization_before = dict(resident.user_browser_authorization())
            root_tab_id = int(authorization_before["tab_id"])
            root_generation = str(authorization_before.get("attached_at") or "")
            self.assertTrue(root_generation)

            unrelated_url = f"http://{_HOST}:{env['port']}/unrelated"
            extra_process = subprocess.Popen(
                [
                    str(env["executable"]),
                    f"--user-data-dir={env['fixture'].profile}",
                    "--no-first-run",
                    unrelated_url,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and env["server"].unrelated_requests < 1:  # type: ignore[attr-defined]
                time.sleep(0.05)
            self.assertGreaterEqual(env["server"].unrelated_requests, 1)  # type: ignore[attr-defined]
            self.assertEqual(int(resident.user_browser_authorization()["tab_id"]), root_tab_id)
            env["fixture"].activate()

            event_id = self._start_work(env)
            result, trace = self._run_to_terminal(env, event_id)
            self.assertIsNotNone(result, json.dumps(trace[-20:], ensure_ascii=False, default=str))
            self.assertTrue(result.success, result.reason)
            self.assertEqual(result.response, f"{_ORDER}: {_STATUS}")
            self.assertEqual(env["server"].child_requests, 1)  # type: ignore[attr-defined]
            self.assertEqual(env["server"].child_orders, [_ORDER])  # type: ignore[attr-defined]
            self.assertGreaterEqual(env["server"].root_dom_replaced, 1)  # type: ignore[attr-defined]
            self.assertEqual(env["server"].login_requests, 1)  # type: ignore[attr-defined]
            self.assertEqual(env["server"].unauthorized_requests, 0)  # type: ignore[attr-defined]

            authorization_after = dict(resident.user_browser_authorization())
            self.assertEqual(int(authorization_after["tab_id"]), root_tab_id)
            self.assertEqual(str(authorization_after.get("attached_at") or ""), root_generation)

            actions = [
                action
                for action in resident.body.recent_actions(512)
                if action.event_id == event_id
            ]
            submits = [
                action
                for action in actions
                if action.kind == "browser_click_named_button_to_url"
            ]
            self.assertEqual(len(submits), 1)
            data = dict(submits[0].data or {})
            self.assertEqual(
                data.get("postcondition"),
                "causal_child_verified_and_returned_to_exact_root",
            )
            self.assertEqual(data.get("root_tab_id"), root_tab_id)
            self.assertTrue(data.get("opener_matches_root"))
            self.assertTrue(data.get("fresh_child_identity"))
            self.assertTrue(data.get("child_authority_task_scoped"))
            self.assertTrue(data.get("child_debugger_detached"))
            self.assertTrue(data.get("root_authorization_preserved"))
            self.assertTrue(data.get("root_generation_unchanged"))
            self.assertTrue(data.get("returned_to_exact_root_tab"))
            self.assertTrue(data.get("fresh_root_resense_after_return"))
            self.assertTrue(data.get("child_url_matches_expected"))
            self.assertNotEqual(int(data.get("child_tab_id") or 0), root_tab_id)
            self.assertNotIn(_CHILD_TITLE, repr(data))

            resident.revoke_user_browser_extension_tab()
            self.assertFalse(resident.user_browser_extension_status().get("authorized"))
            account_before = int(env["server"].account_requests)  # type: ignore[attr-defined]
            subprocess.Popen(
                [
                    str(env["executable"]),
                    f"--user-data-dir={env['fixture'].profile}",
                    "--no-first-run",
                    f"http://{_HOST}:{env['port']}/account",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and env["server"].account_requests <= account_before:  # type: ignore[attr-defined]
                time.sleep(0.05)
            self.assertGreater(env["server"].account_requests, account_before)  # type: ignore[attr-defined]
            self.assertEqual(env["server"].login_requests, 1)  # type: ignore[attr-defined]
            self.assertEqual(env["server"].unauthorized_requests, 0)  # type: ignore[attr-defined]

            print("ZN_E2E07_USER_BROWSER_CAUSAL_POPUP_EVIDENCE=" + json.dumps({
                "provider": env["provider"],
                "existing_authenticated_session": True,
                "root_authorization_preserved": True,
                "popup_causally_attributed": True,
                "popup_opener_matches_root": True,
                "unrelated_tabs_not_claimed": True,
                "child_authority_task_scoped": True,
                "returned_to_exact_root_tab": True,
                "fresh_root_resense_after_return": True,
                "stale_root_target_replaced": True,
                "login_not_replayed": True,
                "session_not_destroyed": True,
            }, ensure_ascii=False, sort_keys=True))
        finally:
            if extra_process is not None and extra_process.poll() is None:
                try:
                    extra_process.terminate()
                    extra_process.wait(timeout=2)
                except Exception:
                    try:
                        extra_process.kill()
                    except Exception:
                        pass
            self._close_runtime(env)


if __name__ == "__main__":
    unittest.main(verbosity=2)
