from __future__ import annotations

import ctypes
import json
import subprocess
import time
import unittest
from ctypes import wintypes
from http.server import ThreadingHTTPServer

from test_windows_interactive_user_browser_semantic_grounding import (
    _HOST,
    _STATUS,
    _TASK,
    _TEXT,
    _Handler,
    WindowsInteractiveUserBrowserSemanticGroundingContractTests,
)


_DECOY_TITLE = "ZN Decoy Browser Page Contract"


class _ContextHandler(_Handler):
    def _account_page(self, mode: str) -> bytes:
        if mode == "decoy":
            return super()._account_page(mode).replace(
                b"<title>ZN User Browser Bridge Contract</title>",
                f"<title>{_DECOY_TITLE}</title>".encode("utf-8"),
                1,
            )
        if mode != "drift-ambiguous":
            return super()._account_page(mode)
        body = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>ZN User Browser Bridge Contract</title>
<style>body{font-family:sans-serif} form{display:grid;gap:12px;width:720px} input,textarea,button{padding:14px;font-size:20px}</style>
</head>
<body>
<h1>Customer order portal</h1>
<form id="orders" action="/results" method="get">
<label>客户名称<input aria-label="客户名称" type="text" autocomplete="off"></label>
<label>客户邮箱<input aria-label="客户邮箱" name="customer" type="text" autocomplete="off"></label>
<label>备注<textarea aria-label="备注"></textarea></label>
<button type="submit" aria-label="搜索订单">搜索订单</button>
</form>
<script>
let changed = false;
setInterval(async () => {
  if (changed) return;
  const response = await fetch('/drift', {cache: 'no-store'});
  const state = await response.json();
  if (!state.drift) return;
  changed = true;
  document.title = 'ZN Ambiguous Replacement Contract';
  const form = document.getElementById('orders');
  form.innerHTML = `
    <label>客户账号<input aria-label="客户账号" name="customer" type="text" autocomplete="off"></label>
    <label>客户账号<input aria-label="客户账号" type="text" autocomplete="off"></label>
    <label>备注信息<textarea aria-label="备注信息"></textarea></label>
    <button type="submit" aria-label="查询订单">查询订单</button>`;
  await fetch('/drift-applied', {cache: 'no-store'});
}, 50);
</script>
</body></html>"""
        return body.encode("utf-8")


class WindowsInteractiveUserBrowserTaskContextContractTests(unittest.TestCase):
    _require_input_desktop = staticmethod(
        WindowsInteractiveUserBrowserSemanticGroundingContractTests._require_input_desktop
    )
    _enable_cognition = staticmethod(
        WindowsInteractiveUserBrowserSemanticGroundingContractTests._enable_cognition
    )
    _make_runtime = WindowsInteractiveUserBrowserSemanticGroundingContractTests._make_runtime
    _close_runtime = WindowsInteractiveUserBrowserSemanticGroundingContractTests._close_runtime
    _start_work = WindowsInteractiveUserBrowserSemanticGroundingContractTests._start_work
    _run_to_terminal = WindowsInteractiveUserBrowserSemanticGroundingContractTests._run_to_terminal

    def _start_server(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _ContextHandler)
        server.login_requests = 0  # type: ignore[attr-defined]
        server.account_requests = {}  # type: ignore[attr-defined]
        server.result_requests = {"authorized": 0, "decoy": 0}  # type: ignore[attr-defined]
        server.result_queries = {"authorized": [], "decoy": []}  # type: ignore[attr-defined]
        server.unauthorized_requests = 0  # type: ignore[attr-defined]
        server.enable_drift = False  # type: ignore[attr-defined]
        server.drift_applied = 0  # type: ignore[attr-defined]
        import threading

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    @staticmethod
    def _press_ctrl_w() -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.keybd_event.argtypes = [
            wintypes.BYTE,
            wintypes.BYTE,
            wintypes.DWORD,
            ctypes.c_size_t,
        ]
        user32.keybd_event.restype = None
        key_up = 0x0002
        vk_control = 0x11
        vk_w = 0x57
        user32.keybd_event(vk_control, 0, 0, 0)
        user32.keybd_event(vk_w, 0, 0, 0)
        user32.keybd_event(vk_w, 0, key_up, 0)
        user32.keybd_event(vk_control, 0, key_up, 0)

    def _launch_decoy(self, env):
        decoy_url = f"http://{_HOST}:{env['port']}/account?mode=decoy"
        args = [
            str(env["executable"]),
            f"--user-data-dir={env['fixture'].profile}",
            "--no-first-run",
            "--new-window",
            decoy_url,
        ]
        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if env["server"].account_requests.get("decoy", 0) >= 1:  # type: ignore[attr-defined]
                break
            time.sleep(0.05)
        self.assertGreaterEqual(
            env["server"].account_requests.get("decoy", 0),  # type: ignore[attr-defined]
            1,
        )
        return process

    def test_same_work_survives_foreground_decoy_and_semantic_drift_on_original_authorized_context(self) -> None:
        self._require_input_desktop()
        env = self._make_runtime("drift")
        decoy_process = None
        try:
            resident = env["resident"]
            authorized = resident.user_browser_extension.authorized_tab()
            self.assertIsNotNone(authorized)
            original_tab = authorized.tab_id
            original_generation = authorized.attached_at
            event_id = self._start_work(env, "task-context-drift")
            drifted = False
            decoy_opened = False
            regrounded = False
            old_target = ""

            def hook(_state, semantic, actions):
                nonlocal drifted, decoy_opened, decoy_process, regrounded, old_target
                if (
                    not drifted
                    and semantic.get("phase") == "input_grounded"
                    and semantic.get("input_name") == "客户邮箱"
                ):
                    self.assertEqual(actions, [])
                    old_target = str(semantic.get("input_target_id") or "")
                    self.assertTrue(old_target)
                    env["server"].enable_drift = True  # type: ignore[attr-defined]
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if int(env["server"].drift_applied) >= 1:  # type: ignore[attr-defined]
                            drifted = True
                            break
                        time.sleep(0.05)
                    self.assertTrue(drifted)
                    decoy_process = self._launch_decoy(env)
                    decoy_opened = True
                    time.sleep(0.25)
                if (
                    drifted
                    and semantic.get("phase") == "input_grounded"
                    and semantic.get("input_name") == "客户账号"
                ):
                    regrounded = True
                    self.assertNotEqual(str(semantic.get("input_target_id") or ""), old_target)

            result, trace = self._run_to_terminal(
                env,
                event_id,
                hook=hook,
                timeout=45.0,
            )
            self.assertTrue(drifted, json.dumps(trace[-20:], ensure_ascii=False, default=str))
            self.assertTrue(decoy_opened)
            self.assertTrue(regrounded, json.dumps(trace[-20:], ensure_ascii=False, default=str))
            self.assertIsNotNone(result, json.dumps(trace[-24:], ensure_ascii=False, default=str))
            self.assertTrue(result.success, result.reason)
            self.assertEqual(result.response, f"{_TEXT}: {_STATUS}")

            current = resident.user_browser_extension.authorized_tab()
            self.assertIsNotNone(current)
            self.assertEqual(current.tab_id, original_tab)
            self.assertEqual(current.attached_at, original_generation)
            final_event = resident.store.get_event(event_id)
            context = final_event.payload.get("_resident_user_browser_task_context") or {}
            self.assertEqual(context.get("tab_id"), original_tab)
            self.assertEqual(context.get("attached_at"), original_generation)
            self.assertEqual(env["server"].result_requests["authorized"], 1)  # type: ignore[attr-defined]
            self.assertEqual(env["server"].result_queries["authorized"], [_TEXT])  # type: ignore[attr-defined]
            self.assertEqual(env["server"].result_requests["decoy"], 0)  # type: ignore[attr-defined]
            actions = [
                action
                for action in resident.body.recent_actions(512)
                if action.event_id == event_id
            ]
            self.assertEqual(
                sum(action.kind == "browser_type_named_text" for action in actions),
                1,
            )
            self.assertEqual(
                sum(action.kind == "browser_click_named_button_to_url" for action in actions),
                1,
            )
            user_action_results = [
                action
                for action in actions
                if action.kind
                in {"browser_type_named_text", "browser_click_named_button_to_url"}
            ]
            self.assertTrue(
                all(
                    action.data.get("authorization_attached_at") == original_generation
                    for action in user_action_results
                )
            )
            self.assertEqual(env["cognition"].calls, 5)
            self.assertNotIn("tab_id", "\n".join(env["cognition"].questions))
            self.assertNotIn("attached_at", "\n".join(env["cognition"].questions))
            print(
                "ZN_USER_BROWSER_TASK_CONTEXT_Contract_EVIDENCE="
                + json.dumps(
                    {
                        "ordinary_language_task": _TASK,
                        "existing_authenticated_session": True,
                        "explicit_authorization_generation_preserved": True,
                        "authorized_tab_id_preserved": original_tab,
                        "foreground_decoy_opened": True,
                        "decoy_result_side_effects": 0,
                        "semantic_label_drift": [
                            "客户邮箱->客户账号",
                            "搜索订单->查询订单",
                        ],
                        "stale_target_rejected": True,
                        "semantic_reground": True,
                        "text_side_effects": 1,
                        "submit_side_effects": 1,
                        "fresh_anchored_result": f"{_TEXT}: {_STATUS}",
                        "independent_server_result_requests": 1,
                        "no_cookie_or_profile_copy": True,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        finally:
            if decoy_process is not None and decoy_process.poll() is None:
                try:
                    decoy_process.terminate()
                except Exception:
                    pass
            self._close_runtime(env)

    def test_closed_authorized_page_fails_closed_even_when_similar_decoy_remains(self) -> None:
        self._require_input_desktop()
        env = self._make_runtime("normal")
        decoy_process = None
        try:
            decoy_process = self._launch_decoy(env)
            env["fixture"].activate()
            event_id = self._start_work(env, "closed-context")
            closed = False

            def hook(_state, semantic, actions):
                nonlocal closed
                if not closed and semantic.get("phase") == "input_grounded":
                    self.assertEqual(actions, [])
                    env["fixture"].activate()
                    self._press_ctrl_w()
                    deadline = time.monotonic() + 6
                    while time.monotonic() < deadline:
                        if not env["resident"].user_browser_extension_status().get("authorized"):
                            closed = True
                            break
                        time.sleep(0.05)
                    self.assertTrue(closed, "closing the authorized page did not revoke its extension authority")

            result, trace = self._run_to_terminal(
                env,
                event_id,
                hook=hook,
                timeout=30.0,
            )
            self.assertTrue(closed)
            self.assertIsNotNone(result, json.dumps(trace[-18:], ensure_ascii=False, default=str))
            self.assertFalse(result.success)
            actions = [
                action
                for action in env["resident"].body.recent_actions(512)
                if action.event_id == event_id
            ]
            self.assertEqual(actions, [])
            self.assertEqual(env["server"].result_requests["authorized"], 0)  # type: ignore[attr-defined]
            self.assertEqual(env["server"].result_requests["decoy"], 0)  # type: ignore[attr-defined]
        finally:
            if decoy_process is not None and decoy_process.poll() is None:
                try:
                    decoy_process.terminate()
                except Exception:
                    pass
            self._close_runtime(env)

    def test_ambiguous_replacement_after_stale_binding_fails_closed_without_input(self) -> None:
        self._require_input_desktop()
        env = self._make_runtime("drift-ambiguous")
        try:
            event_id = self._start_work(env, "ambiguous-replacement")
            drifted = False
            old_target = ""

            def hook(_state, semantic, actions):
                nonlocal drifted, old_target
                if not drifted and semantic.get("phase") == "input_grounded":
                    self.assertEqual(actions, [])
                    old_target = str(semantic.get("input_target_id") or "")
                    self.assertTrue(old_target)
                    env["server"].enable_drift = True  # type: ignore[attr-defined]
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if int(env["server"].drift_applied) >= 1:  # type: ignore[attr-defined]
                            drifted = True
                            break
                        time.sleep(0.05)
                    self.assertTrue(drifted)

            result, trace = self._run_to_terminal(
                env,
                event_id,
                hook=hook,
                timeout=30.0,
            )
            self.assertTrue(drifted)
            self.assertIsNotNone(result, json.dumps(trace[-18:], ensure_ascii=False, default=str))
            self.assertFalse(result.success)
            self.assertTrue(any(item.get("regrounds") for item in trace))
            actions = [
                action
                for action in env["resident"].body.recent_actions(512)
                if action.event_id == event_id
            ]
            self.assertEqual(actions, [])
            self.assertEqual(env["server"].result_requests["authorized"], 0)  # type: ignore[attr-defined]
            self.assertEqual(env["server"].result_requests["decoy"], 0)  # type: ignore[attr-defined]
        finally:
            self._close_runtime(env)


if __name__ == "__main__":
    unittest.main(verbosity=2)
