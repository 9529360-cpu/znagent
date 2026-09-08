from __future__ import annotations

import ctypes
import json
import sqlite3
import subprocess
from ctypes import wintypes
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
_TITLE = "ZN User Browser Bridge E2E"
_RESULT_TITLE = "ZN Customer Order Result E2E"
_TEXT = "alice@example.test"
_STATUS = "已发货"
_TASK = f"在这个已经登录的网站里，把 {_TEXT} 这个客户的订单找出来，确认现在是什么状态。"
_SESSION_COOKIE = "zn_semantic_browser_session=already-authenticated-before-zn"
_OTP = "814205"


class _SemanticBrowserCognition:
    def __init__(self):
        self.calls = 0
        self.questions: list[str] = []

    @staticmethod
    def _observed_name(question: str, name: str) -> bool:
        return f'"name": "{name}"' in question

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        del context
        self.calls += 1
        self.questions.append(question)
        if "Interpret only the user's desired outcome in the current browser" in question:
            value = {
                "kind": "user_browser_semantic_lookup",
                "subject_value": _TEXT,
                "subject_semantics": "客户邮箱或客户账号",
                "operation": "查找这个客户的订单",
                "desired_result": "确认当前订单状态",
            }
        elif "Select the one safe textbox" in question:
            if self._observed_name(question, "安全代码"):
                value = {"status": "selected", "name": "安全代码"}
            elif self._observed_name(question, "客户账号"):
                value = {"status": "selected", "name": "客户账号"}
            elif self._observed_name(question, "客户邮箱"):
                value = {"status": "selected", "name": "客户邮箱"}
            else:
                value = {"status": "ambiguous"}
        elif "Select the button" in question:
            if self._observed_name(question, "查询订单"):
                value = {"status": "selected", "name": "查询订单"}
            elif self._observed_name(question, "搜索订单"):
                value = {"status": "selected", "name": "搜索订单"}
            else:
                value = {"status": "ambiguous"}
        elif "extract the business fact" in question:
            value = {"status": "verified", "result": _STATUS}
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
            mode = parse_qs(parsed.query).get("mode", ["normal"])[0]
            self.server.login_requests += 1  # type: ignore[attr-defined]
            self.send_response(302)
            self.send_header("Set-Cookie", f"{_SESSION_COOKIE}; Path=/; HttpOnly; SameSite=Strict")
            self.send_header("Location", f"/account?mode={mode}")
            self.end_headers()
            return

        if parsed.path == "/mfa-complete":
            values = parse_qs(parsed.query, keep_blank_values=True).get("otp", [])
            if len(values) != 1 or values[0] != _OTP:
                self._write(403, "text/plain; charset=utf-8", b"invalid otp")
                return
            self.server.mfa_completions += 1  # type: ignore[attr-defined]
            self.send_response(302)
            self.send_header("Location", "/account?mode=normal")
            self.end_headers()
            return

        if parsed.path == "/drift":
            body = json.dumps({"drift": bool(self.server.enable_drift)}).encode("utf-8")  # type: ignore[attr-defined]
            self._write(200, "application/json", body)
            return

        if parsed.path == "/drift-applied":
            self.server.drift_applied += 1  # type: ignore[attr-defined]
            self._write(200, "text/plain; charset=utf-8", b"ok")
            return

        if parsed.path == "/account":
            if not self._has_existing_session():
                self.server.unauthorized_requests += 1  # type: ignore[attr-defined]
                self._write(401, "text/plain; charset=utf-8", b"existing browser login required")
                return
            mode = parse_qs(parsed.query).get("mode", ["normal"])[0]
            self.server.account_requests[mode] = self.server.account_requests.get(mode, 0) + 1  # type: ignore[attr-defined]
            self._write(200, "text/html; charset=utf-8", self._account_page(mode))
            return

        if parsed.path in {"/results", "/results-decoy"}:
            if not self._has_existing_session():
                self.server.unauthorized_requests += 1  # type: ignore[attr-defined]
                self._write(401, "text/plain; charset=utf-8", b"existing browser login required")
                return
            route = "authorized" if parsed.path == "/results" else "decoy"
            self.server.result_requests[route] = self.server.result_requests.get(route, 0) + 1  # type: ignore[attr-defined]
            values = parse_qs(parsed.query, keep_blank_values=True).get("customer", [])
            value = values[0] if len(values) == 1 else ""
            self.server.result_queries[route].append(value)  # type: ignore[attr-defined]
            if value != _TEXT:
                self._write(400, "text/plain; charset=utf-8", b"unexpected customer query")
                return
            status = _STATUS if route == "authorized" else "已取消"
            body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{_RESULT_TITLE}</title></head>
<body><main><table><tbody><tr><td>客户: {_TEXT}</td><td>订单: #ZN-731</td><td>状态: {status}</td></tr></tbody></table></main></body></html>""".encode("utf-8")
            self._write(200, "text/html; charset=utf-8", body)
            return

        self.send_response(404)
        self.end_headers()

    def _account_page(self, mode: str) -> bytes:
        result_path = "/results-decoy" if mode == "decoy" else "/results"
        if mode == "ambiguous":
            fields = """
<label>客户邮箱<input aria-label="客户邮箱" name="customer" type="text" autocomplete="off"></label>
<label>客户邮箱<input aria-label="客户邮箱" type="text" autocomplete="off"></label>
<label>备注<textarea aria-label="备注"></textarea></label>"""
            button = "搜索订单"
        elif mode == "sensitive":
            body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{_TITLE}</title></head>
<body><h1>需要多因素验证</h1>
<form action="/mfa-complete" method="get">
<label>安全代码<input aria-label="安全代码" name="otp" type="password" autocomplete="one-time-code"></label>
<button type="submit" aria-label="继续">继续</button>
</form></body></html>"""
            return body.encode("utf-8")
        elif mode == "credential":
            fields = """
<label>客户名称<input aria-label="客户名称" type="text" autocomplete="off"></label>
<label>安全代码<input aria-label="安全代码" name="customer" type="password" autocomplete="current-password"></label>
<label>备注<textarea aria-label="备注"></textarea></label>"""
            button = "搜索订单"
        else:
            fields = """
<label>客户名称<input aria-label="客户名称" type="text" autocomplete="off"></label>
<label>客户邮箱<input aria-label="客户邮箱" name="customer" type="text" autocomplete="off"></label>
<label>备注<textarea aria-label="备注"></textarea></label>"""
            button = "搜索订单"
        drift_script = ""
        if mode == "drift":
            drift_script = f"""
<script>
let changed = false;
setInterval(async () => {{
  if (changed) return;
  const response = await fetch('/drift', {{cache: 'no-store'}});
  const state = await response.json();
  if (!state.drift) return;
  changed = true;
  const form = document.getElementById('orders');
  form.innerHTML = `
    <label>客户<input aria-label="客户" type="text" autocomplete="off"></label>
    <label>客户账号<input aria-label="客户账号" name="customer" type="text" autocomplete="off"></label>
    <label>备注信息<textarea aria-label="备注信息"></textarea></label>
    <button type="submit" aria-label="查询订单">查询订单</button>`;
  await fetch('/drift-applied', {{cache: 'no-store'}});
}}, 50);
</script>"""
        body = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>{_TITLE}</title>
<style>body{{font-family:sans-serif}} form{{display:grid;gap:12px;width:720px}} input,textarea,button{{padding:14px;font-size:20px}}</style>
</head>
<body>
<h1>Customer order portal</h1>
<form id="orders" action="{result_path}" method="get">
{fields}
<button type="submit" aria-label="{button}">{button}</button>
</form>
{drift_script}
</body></html>"""
        return body.encode("utf-8")

    def _has_existing_session(self) -> bool:
        cookies = [item.strip() for item in str(self.headers.get("Cookie") or "").split(";") if item.strip()]
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


class WindowsInteractiveUserBrowserSemanticGroundingE2ETests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        WindowsInteractiveUserBrowserBridgeProviderE2ETests._require_input_desktop()

    @staticmethod
    def _enable_cognition(resident, cognition: _SemanticBrowserCognition) -> None:
        resident.kernel.reconfigure_resources(
            routes=[
                ModelRoute(
                    route_id="e2e-user-browser-semantic-grounding",
                    provider="fixture",
                    model="bounded-language-fixture",
                    capabilities={"language_understanding": 1.0, "general": 0.8},
                )
            ],
            worker_factory=CognitiveResourceWorkerFactory(
                resource_builder=lambda _route: cognition,
            ),
            max_attempts=1,
            resource_status={"available": True, "error": None},
        )

    def _start_server(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.login_requests = 0  # type: ignore[attr-defined]
        server.account_requests = {}  # type: ignore[attr-defined]
        server.result_requests = {"authorized": 0, "decoy": 0}  # type: ignore[attr-defined]
        server.result_queries = {"authorized": [], "decoy": []}  # type: ignore[attr-defined]
        server.unauthorized_requests = 0  # type: ignore[attr-defined]
        server.enable_drift = False  # type: ignore[attr-defined]
        server.drift_applied = 0  # type: ignore[attr-defined]
        server.mfa_completions = 0  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def _make_runtime(self, mode: str):
        browsers = _find_installed_browsers()
        if not browsers:
            self.fail("interactive Windows runner has neither stable Edge nor Chrome")
        server, server_thread = self._start_server()
        port = int(server.server_address[1])
        login_url = f"http://{_HOST}:{port}/login?mode={mode}"
        repo_root = Path(__file__).resolve().parents[3]
        extension = repo_root / "apps" / "desktop" / "browser-extension"
        provider, executable = browsers[0]
        fixture = _ExtensionBrowserFixture(provider, executable, login_url, extension)
        runtime_tmp = tempfile.TemporaryDirectory()
        cognition = _SemanticBrowserCognition()
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
            while time.monotonic() < deadline:
                if server.account_requests.get(mode, 0) >= 1:  # type: ignore[attr-defined]
                    break
                time.sleep(0.05)
            self.assertGreaterEqual(server.account_requests.get(mode, 0), 1)  # type: ignore[attr-defined]
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
                authorization = resident.user_browser_authorization()
                if authorization.get("provider") == "zn-extension-user-browser":
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
        fixture = env.get("fixture")
        server = env.get("server")
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
        if fixture is not None:
            try:
                fixture.close()
            except Exception:
                pass
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
        thread = env.get("server_thread")
        if thread is not None:
            try:
                thread.join(timeout=2)
            except Exception:
                pass
        runtime_tmp = env.get("runtime_tmp")
        if runtime_tmp is not None:
            try:
                runtime_tmp.cleanup()
            except Exception:
                pass

    def _start_work(self, env, suffix: str) -> str:
        rpc = env["rpc"]
        thread_id = f"semantic-browser-{suffix}"
        created = rpc.handle({
            "id": "create",
            "method": "work_create",
            "params": {"thread_id": thread_id, "title": "Semantic browser task"},
        })
        self.assertTrue(created["ok"])
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

    def _run_to_terminal(self, env, event_id: str, *, hook=None, timeout: float = 35.0):
        resident = env["resident"]
        result = None
        trace = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and result is None:
            state = resident.store.get_working_state()
            semantic = state.data.get(getattr(resident, "_SEMANTIC_LOOKUP_STATE_KEY", "resident_user_browser_semantic_lookup"))
            semantic = semantic if isinstance(semantic, dict) else {}
            actions = [action for action in resident.body.recent_actions(512) if action.event_id == event_id]
            if hook is not None:
                hook(state, semantic, actions)
            current = resident.live_once()
            current_for_event = current if current is not None and current.event.event_id == event_id else None
            post = resident.store.get_working_state()
            post_semantic = post.data.get(getattr(resident, "_SEMANTIC_LOOKUP_STATE_KEY", "resident_user_browser_semantic_lookup"))
            post_semantic = post_semantic if isinstance(post_semantic, dict) else {}
            trace.append({
                "stage": post.stage,
                "phase": post_semantic.get("phase"),
                "input_name": post_semantic.get("input_name"),
                "button_name": post_semantic.get("button_name"),
                "regrounds": post_semantic.get("regrounds"),
                "actions": [action.kind for action in resident.body.recent_actions(512) if action.event_id == event_id],
                "local_failure": str(post.data.get("local_failure") or "") or None,
                "result_success": current_for_event.success if current_for_event is not None else None,
                "result_reason": current_for_event.reason if current_for_event is not None else None,
            })
            if current_for_event is not None:
                result = current_for_event
            if result is None:
                time.sleep(0.03)
        return result, trace

    @staticmethod
    def _human_type_otp_and_submit(fixture) -> None:
        fixture.activate()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
        user32.keybd_event.restype = None
        key_up = 0x0002
        keys = [0x09, *[0x30 + int(char) for char in _OTP], 0x0D]
        for key in keys:
            user32.keybd_event(key, 0, 0, 0)
            user32.keybd_event(key, 0, key_up, 0)
            time.sleep(0.03)

    def test_one_time_code_waits_for_user_without_model_or_body_action_then_resumes_same_work(self) -> None:
        self._require_input_desktop()
        env = self._make_runtime("sensitive")
        try:
            event_id = self._start_work(env, "otp")
            resident = env["resident"]
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                resident.live_once()
                state = resident.store.get_working_state()
                if state.blocked_by == "user_presence_required":
                    break
                time.sleep(0.03)
            state = resident.store.get_working_state()
            self.assertEqual(state.current_event_id, event_id)
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(state.blocked_by, "user_presence_required")
            blocker = state.data[resident._USER_PRESENCE_BLOCKER_STATE_KEY]
            authorization = resident.user_browser_extension.authorized_tab()
            self.assertEqual(blocker["kind"], "one_time_code")
            self.assertEqual(blocker["tab_id"], authorization.tab_id)
            self.assertEqual(blocker["attached_at"], authorization.attached_at)
            self.assertEqual(set(blocker), {"kind", "tab_id", "attached_at", "origin", "detected_at", "resume_phase"})

            calls_at_block = env["cognition"].calls
            self.assertEqual(calls_at_block, 1)
            actions_at_block = [a for a in resident.body.recent_actions(512) if a.event_id == event_id]
            self.assertEqual(actions_at_block, [])
            self.assertNotIn('"name": "安全代码"', "\n".join(env["cognition"].questions))
            progress = env["rpc"].handle({
                "id": "progress-otp",
                "method": "work_progress",
                "params": {"thread_id": "semantic-browser-otp", "event_id": event_id},
            })["result"]["progress"]
            self.assertEqual(progress["stage"], "waiting_for_user")
            self.assertEqual(progress["blocked_by"], "user_presence_required")
            self.assertFalse(progress["terminal"])
            for _ in range(3):
                resident.live_once()
            self.assertEqual(env["cognition"].calls, calls_at_block)
            self.assertEqual([a for a in resident.body.recent_actions(512) if a.event_id == event_id], [])

            sense = resident._extension_user_browser.observe_semantic_candidates()
            encoded_sense = json.dumps(sense, ensure_ascii=False, sort_keys=True)
            self.assertNotIn(_OTP, encoded_sense)
            otp_candidates = [item for item in sense["candidates"] if item.get("sensitive_kind") == "one_time_code"]
            self.assertEqual(len(otp_candidates), 1)
            self.assertEqual(otp_candidates[0]["text_length"], 0)

            self._human_type_otp_and_submit(env["fixture"])
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if int(env["server"].mfa_completions) == 1:  # type: ignore[attr-defined]
                    break
                time.sleep(0.05)
            self.assertEqual(int(env["server"].mfa_completions), 1)  # type: ignore[attr-defined]

            result, trace = self._run_to_terminal(env, event_id)
            self.assertIsNotNone(result, json.dumps(trace[-20:], ensure_ascii=False, default=str))
            self.assertTrue(result.success, result.reason)
            self.assertEqual(result.response, f"{_TEXT}: {_STATUS}")
            authorization_after = resident.user_browser_extension.authorized_tab()
            self.assertEqual(authorization_after.tab_id, authorization.tab_id)
            self.assertEqual(authorization_after.attached_at, authorization.attached_at)
            self.assertEqual(env["server"].result_queries["authorized"], [_TEXT])  # type: ignore[attr-defined]

            final_state = resident.store.get_working_state()
            all_actions = [a for a in resident.body.recent_actions(512) if a.event_id == event_id]
            secret_surfaces = [
                "\n".join(env["cognition"].questions),
                json.dumps(final_state.data, ensure_ascii=False, default=str),
                json.dumps(progress, ensure_ascii=False, default=str),
                repr(all_actions),
            ]
            for surface in secret_surfaces:
                self.assertNotIn(_OTP, surface)
            db_path = Path(env["runtime_tmp"].name) / "kernel.db"
            with sqlite3.connect(db_path) as conn:
                work_messages = conn.execute(
                    "SELECT text, detail_json FROM work_messages WHERE thread_id=? ORDER BY created_at",
                    ("semantic-browser-otp",),
                ).fetchall()
            self.assertNotIn(_OTP, json.dumps(work_messages, ensure_ascii=False, default=str))
            db_bytes = db_path.read_bytes()
            self.assertNotIn(_OTP.encode("utf-8"), db_bytes)
        finally:
            self._close_runtime(env)

    def test_user_presence_reauthorization_generation_change_fails_closed(self) -> None:
        self._require_input_desktop()
        env = self._make_runtime("sensitive")
        try:
            event_id = self._start_work(env, "otp-reauthorize")
            resident = env["resident"]
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                resident.live_once()
                if resident.store.get_working_state().blocked_by == "user_presence_required":
                    break
                time.sleep(0.03)
            original = resident.user_browser_extension.authorized_tab()
            env["fixture"].activate()
            _press_extension_action_shortcut()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and resident.user_browser_extension_status().get("authorized"):
                time.sleep(0.05)
            env["fixture"].activate()
            _press_extension_action_shortcut()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                current = resident.user_browser_extension.authorized_tab()
                if current is not None and current.attached_at != original.attached_at:
                    break
                time.sleep(0.05)
            current = resident.user_browser_extension.authorized_tab()
            self.assertIsNotNone(current)
            self.assertNotEqual(current.attached_at, original.attached_at)
            result, trace = self._run_to_terminal(env, event_id, timeout=10)
            self.assertIsNotNone(result, json.dumps(trace[-12:], ensure_ascii=False, default=str))
            self.assertFalse(result.success)
            self.assertEqual([a for a in resident.body.recent_actions(512) if a.event_id == event_id], [])
        finally:
            self._close_runtime(env)

    def test_ordinary_goal_regrounds_after_semantic_label_and_node_drift_then_verifies_result(self) -> None:
        self._require_input_desktop()
        env = self._make_runtime("drift")
        try:
            event_id = self._start_work(env, "drift")
            resident = env["resident"]
            drifted = False
            regrounded = False
            old_target = ""

            def hook(_state, semantic, actions):
                nonlocal drifted, regrounded, old_target
                if (
                    not drifted
                    and semantic.get("phase") == "input_grounded"
                    and semantic.get("input_name") == "客户邮箱"
                ):
                    self.assertEqual(actions, [], "side effect occurred before forced page drift")
                    old_target = str(semantic.get("input_target_id") or "")
                    self.assertTrue(old_target)
                    env["server"].enable_drift = True  # type: ignore[attr-defined]
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if int(env["server"].drift_applied) >= 1:  # type: ignore[attr-defined]
                            drifted = True
                            break
                        time.sleep(0.05)
                    self.assertTrue(drifted, "real authorized page did not apply semantic drift")
                if (
                    drifted
                    and semantic.get("phase") == "input_grounded"
                    and semantic.get("input_name") == "客户账号"
                ):
                    regrounded = True
                    self.assertNotEqual(str(semantic.get("input_target_id") or ""), old_target)

            result, trace = self._run_to_terminal(env, event_id, hook=hook)
            self.assertTrue(drifted, json.dumps(trace[-15:], ensure_ascii=False, default=str))
            self.assertTrue(regrounded, json.dumps(trace[-20:], ensure_ascii=False, default=str))
            self.assertIsNotNone(result, json.dumps(trace[-20:], ensure_ascii=False, default=str))
            self.assertTrue(result.success, result.reason)
            self.assertEqual(env["server"].result_requests["authorized"], 1)  # type: ignore[attr-defined]
            self.assertEqual(env["server"].result_queries["authorized"], [_TEXT])  # type: ignore[attr-defined]
            self.assertEqual(env["server"].result_requests["decoy"], 0)  # type: ignore[attr-defined]
            actions = [action for action in resident.body.recent_actions(512) if action.event_id == event_id]
            self.assertEqual(sum(action.kind == "browser_type_named_text" for action in actions), 1)
            self.assertEqual(sum(action.kind == "browser_click_named_button_to_url" for action in actions), 1)
            self.assertEqual(env["cognition"].calls, 5)
            self.assertIn("客户邮箱", env["cognition"].questions[1])
            self.assertTrue(any("客户账号" in question for question in env["cognition"].questions))
            self.assertNotIn("backend:", "\n".join(env["cognition"].questions))
            self.assertNotIn("tab_id", "\n".join(env["cognition"].questions))
            self.assertEqual(result.response, f"{_TEXT}: {_STATUS}")
            print("ZN_USER_BROWSER_SEMANTIC_GROUNDING_E2E_EVIDENCE=" + json.dumps({
                "provider": env["provider"],
                "ordinary_language": True,
                "user_supplied_url": False,
                "user_supplied_control_name": False,
                "user_supplied_selector": False,
                "existing_authenticated_session": True,
                "authorized_tab_only": True,
                "semantic_label_drift": ["客户邮箱->客户账号", "搜索订单->查询订单"],
                "old_exact_binding_rejected": True,
                "semantic_reground": True,
                "text_side_effects": 1,
                "submit_side_effects": 1,
                "independent_server_result_requests": 1,
                "fresh_anchored_result_verified": True,
            }, ensure_ascii=False, sort_keys=True))
        finally:
            self._close_runtime(env)

    def test_ambiguous_duplicate_semantic_inputs_fail_closed_with_zero_side_effects(self) -> None:
        self._require_input_desktop()
        env = self._make_runtime("ambiguous")
        try:
            event_id = self._start_work(env, "ambiguous")
            result, trace = self._run_to_terminal(env, event_id)
            self.assertIsNotNone(result, json.dumps(trace[-12:], ensure_ascii=False, default=str))
            self.assertFalse(result.success)
            actions = [action for action in env["resident"].body.recent_actions(512) if action.event_id == event_id]
            self.assertEqual(actions, [])
            self.assertEqual(env["server"].result_requests["authorized"], 0)  # type: ignore[attr-defined]
        finally:
            self._close_runtime(env)

    def test_non_otp_sensitive_credential_remains_ineligible_for_autonomous_entry(self) -> None:
        self._require_input_desktop()
        env = self._make_runtime("credential")
        try:
            event_id = self._start_work(env, "credential")
            result, trace = self._run_to_terminal(env, event_id)
            self.assertIsNotNone(result, json.dumps(trace[-12:], ensure_ascii=False, default=str))
            self.assertFalse(result.success)
            actions = [action for action in env["resident"].body.recent_actions(512) if action.event_id == event_id]
            self.assertEqual(actions, [])
            self.assertEqual(env["server"].result_requests["authorized"], 0)  # type: ignore[attr-defined]
        finally:
            self._close_runtime(env)

    def test_revoked_authorized_tab_after_grounding_stops_without_replay_or_substitution(self) -> None:
        self._require_input_desktop()
        env = self._make_runtime("normal")
        try:
            event_id = self._start_work(env, "revoke")
            revoked = False

            def hook(_state, semantic, actions):
                nonlocal revoked
                if not revoked and semantic.get("phase") == "input_grounded":
                    self.assertEqual(actions, [])
                    env["fixture"].activate()
                    _press_extension_action_shortcut()
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if not env["resident"].user_browser_extension_status().get("authorized"):
                            revoked = True
                            break
                        time.sleep(0.05)
                    self.assertTrue(revoked)

            result, trace = self._run_to_terminal(env, event_id, hook=hook)
            self.assertTrue(revoked)
            self.assertIsNotNone(result, json.dumps(trace[-12:], ensure_ascii=False, default=str))
            self.assertFalse(result.success)
            actions = [action for action in env["resident"].body.recent_actions(512) if action.event_id == event_id]
            self.assertEqual(actions, [])
            self.assertEqual(env["server"].result_requests["authorized"], 0)  # type: ignore[attr-defined]
        finally:
            self._close_runtime(env)

    def test_foreground_decoy_identical_tab_never_receives_authority(self) -> None:
        self._require_input_desktop()
        env = self._make_runtime("normal")
        decoy_process = None
        try:
            decoy_url = f"http://{_HOST}:{env['port']}/account?mode=decoy"
            args = [
                str(env["executable"]),
                f"--user-data-dir={env['fixture'].profile}",
                "--no-first-run",
                "--new-window",
                decoy_url,
            ]
            decoy_process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if env["server"].account_requests.get("decoy", 0) >= 1:  # type: ignore[attr-defined]
                    break
                time.sleep(0.05)
            self.assertGreaterEqual(env["server"].account_requests.get("decoy", 0), 1)  # type: ignore[attr-defined]
            authorized_before = dict(env["resident"].user_browser_authorization())
            event_id = self._start_work(env, "decoy")
            result, trace = self._run_to_terminal(env, event_id)
            self.assertIsNotNone(result, json.dumps(trace[-16:], ensure_ascii=False, default=str))
            self.assertTrue(result.success, result.reason)
            authorized_after = dict(env["resident"].user_browser_authorization())
            self.assertEqual(authorized_after.get("tab_id"), authorized_before.get("tab_id"))
            self.assertEqual(env["server"].result_requests["authorized"], 1)  # type: ignore[attr-defined]
            self.assertEqual(env["server"].result_requests["decoy"], 0)  # type: ignore[attr-defined]
        finally:
            if decoy_process is not None and decoy_process.poll() is None:
                try:
                    decoy_process.terminate()
                    decoy_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    decoy_process.kill()
                    decoy_process.wait(timeout=2)
                except Exception:
                    pass
            self._close_runtime(env)


if __name__ == "__main__":
    unittest.main(verbosity=2)