from __future__ import annotations

import ctypes
import json
import os
import secrets
import subprocess
import tempfile
import threading
import time
import unittest
from ctypes import wintypes
from datetime import datetime, time as day_time, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime

import test_windows_interactive_user_browser_bridge as browser_bridge_e2e
import test_windows_interactive_user_browser_extension as extension_e2e


_BROWSER_TITLE = "ZN E2E-24 Customer Status"
_APP_START_TITLE = "ZN E2E-24 Customer Manager"
_SESSION_COOKIE = "zn_e2e24_session=already-authenticated-before-zn"
_TASK = (
    "看看当前网站里的客户状态，把需跟进的客户整理到昨天那份客户状态文件里，"
    "再到我现在开的客户管理软件里把这个异常客户标记待跟进，最后确认文件和软件都处理对了。"
)
_INPUT_NAME = "客户编号"
_MARK_BUTTON_NAME = "标记待跟进"


def _user32():
    api = ctypes.WinDLL("user32", use_last_error=True)
    api.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    api.ShowWindow.restype = wintypes.BOOL
    api.BringWindowToTop.argtypes = [wintypes.HWND]
    api.BringWindowToTop.restype = wintypes.BOOL
    api.SetForegroundWindow.argtypes = [wintypes.HWND]
    api.SetForegroundWindow.restype = wintypes.BOOL
    api.GetForegroundWindow.argtypes = []
    api.GetForegroundWindow.restype = wintypes.HWND
    api.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    api.GetWindowTextLengthW.restype = ctypes.c_int
    api.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    api.GetWindowTextW.restype = ctypes.c_int
    api.IsWindowVisible.argtypes = [wintypes.HWND]
    api.IsWindowVisible.restype = wintypes.BOOL
    api.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    api.GetWindowThreadProcessId.restype = wintypes.DWORD
    api.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    api.PostMessageW.restype = wintypes.BOOL
    return api


class _CustomerStatusHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/login":
            self.server.login_requests += 1  # type: ignore[attr-defined]
            self.send_response(302)
            self.send_header(
                "Set-Cookie",
                f"{_SESSION_COOKIE}; Path=/; HttpOnly; SameSite=Strict",
            )
            self.send_header("Location", "/customers")
            self.end_headers()
            return
        if self.path == "/customers":
            self.server.customer_requests += 1  # type: ignore[attr-defined]
            if not self._has_existing_session():
                self.server.unauthorized_requests += 1  # type: ignore[attr-defined]
                self._write(401, b"existing browser login required")
                return
            self.server.authenticated_customer_requests += 1  # type: ignore[attr-defined]
            rows = (
                (self.server.normal_customer, "正常"),  # type: ignore[attr-defined]
                (self.server.abnormal_customer, "需跟进"),  # type: ignore[attr-defined]
                (self.server.sibling_customer, "正常"),  # type: ignore[attr-defined]
            )
            table = "".join(
                f"<tr><td>{customer}</td><td>{status}</td></tr>"
                for customer, status in rows
            )
            body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{_BROWSER_TITLE}</title></head>
<body><main><h1>客户状态</h1>
<table aria-label="客户状态"><thead><tr><th>客户编号</th><th>状态</th></tr></thead>
<tbody>{table}</tbody></table></main></body></html>""".encode("utf-8")
            self._write(200, body, content_type="text/html; charset=utf-8")
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

    def _write(self, status: int, body: bytes, *, content_type: str = "text/plain; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return None


class _CustomerManagerApp:
    def __init__(
        self,
        root: Path,
        *,
        abnormal_customer: str,
        normal_customer: str,
        sibling_customer: str,
    ) -> None:
        self.script = root / "e2e24-customer-manager.ps1"
        self.recreate_flag = root / "e2e24-recreate-controls.flag"
        self.mutation_log = root / "e2e24-mutations.txt"
        self.abnormal_customer = abnormal_customer
        self.normal_customer = normal_customer
        self.sibling_customer = sibling_customer
        self.process: subprocess.Popen | None = None
        self.hwnd = 0

    def start(self) -> None:
        self.script.write_text(self._script_text(), encoding="utf-8-sig")
        self.process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-Sta",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.script),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("E2E-24 customer-manager fixture exited early")
            self.hwnd = self._find_window()
            if self.hwnd:
                self.activate()
                return
            time.sleep(0.05)
        raise RuntimeError("E2E-24 customer-manager window was not found")

    def activate(self) -> None:
        user32 = _user32()
        user32.ShowWindow(self.hwnd, 5)
        user32.BringWindowToTop(self.hwnd)
        user32.SetForegroundWindow(self.hwnd)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if int(user32.GetForegroundWindow() or 0) == self.hwnd:
                return
            time.sleep(0.02)
        raise RuntimeError("E2E-24 customer-manager fixture could not become foreground")

    def title(self) -> str:
        user32 = _user32()
        length = int(user32.GetWindowTextLengthW(self.hwnd))
        buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        user32.GetWindowTextW(self.hwnd, buffer, len(buffer))
        return buffer.value

    def trigger_recreation(self) -> None:
        self.recreate_flag.write_text("recreate", encoding="utf-8")

    def mutation_ids(self) -> list[str]:
        if not self.mutation_log.exists():
            return []
        return [
            line.strip()
            for line in self.mutation_log.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]

    def close(self) -> None:
        if self.hwnd:
            try:
                _user32().PostMessageW(self.hwnd, 0x0010, 0, 0)
            except Exception:
                pass
        if self.process is not None:
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)

    def _find_window(self) -> int:
        user32 = _user32()
        callback_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [callback_t, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        matches: list[int] = []

        @callback_t
        def visit(hwnd, _):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if (
                self.process is not None
                and int(pid.value) == self.process.pid
                and user32.IsWindowVisible(hwnd)
            ):
                length = int(user32.GetWindowTextLengthW(hwnd))
                buffer = ctypes.create_unicode_buffer(max(1, length + 1))
                user32.GetWindowTextW(hwnd, buffer, len(buffer))
                if buffer.value == _APP_START_TITLE:
                    matches.append(int(hwnd))
            return True

        user32.EnumWindows(visit, 0)
        return matches[0] if len(matches) == 1 else 0

    def _script_text(self) -> str:
        flag = str(self.recreate_flag).replace("'", "''")
        log = str(self.mutation_log).replace("'", "''")
        abnormal = self.abnormal_customer.replace("'", "''")
        normal = self.normal_customer.replace("'", "''")
        sibling = self.sibling_customer.replace("'", "''")
        return f'''Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object System.Windows.Forms.Form
$form.Text = '{_APP_START_TITLE}'
$form.StartPosition = 'CenterScreen'
$form.ClientSize = '820,390'
$recreateFlag = '{flag}'
$mutationLog = '{log}'
$records = @{{
    '{abnormal}' = '未标记'
    '{normal}' = '正常'
    '{sibling}' = '正常'
}}
$script:customerBox = $null
$script:markButton = $null
$heading = New-Object System.Windows.Forms.Label
$heading.Text = '客户管理'
$heading.Location = '65,25'
$heading.Size = '500,38'
$heading.Font = 'Segoe UI,18'
$notes = New-Object System.Windows.Forms.TextBox
$notes.AccessibleName = '客户备注'
$notes.Location = '65,180'
$notes.Size = '500,38'
$notes.Font = 'Segoe UI,14'
$otherButton = New-Object System.Windows.Forms.Button
$otherButton.AccessibleName = '关闭记录'
$otherButton.Text = '关闭记录'
$otherButton.Location = '590,245'
$otherButton.Size = '150,45'
$form.Controls.Add($heading)
$form.Controls.Add($notes)
$form.Controls.Add($otherButton)
function Add-CustomerControls {{
    $script:customerBox = New-Object System.Windows.Forms.TextBox
    $script:customerBox.AccessibleName = '{_INPUT_NAME}'
    $script:customerBox.Location = '65,95'
    $script:customerBox.Size = '500,42'
    $script:customerBox.Font = 'Segoe UI,15'
    $script:customerBox.Add_TextChanged({{
        $id = $script:customerBox.Text
        if ($records.ContainsKey($id)) {{
            $form.Text = "客户 $id — 当前: $($records[$id])"
        }} elseif ($id) {{
            $form.Text = "客户 $id — 未找到"
        }} else {{
            $form.Text = '{_APP_START_TITLE}'
        }}
    }})
    $script:markButton = New-Object System.Windows.Forms.Button
    $script:markButton.AccessibleName = '{_MARK_BUTTON_NAME}'
    $script:markButton.Text = '{_MARK_BUTTON_NAME}'
    $script:markButton.Location = '590,93'
    $script:markButton.Size = '165,48'
    $script:markButton.Add_Click({{
        $id = $script:customerBox.Text
        if ($records.ContainsKey($id)) {{
            $records[$id] = '需跟进'
            Add-Content -LiteralPath $mutationLog -Value $id -Encoding UTF8
            $form.Text = "客户 $id — 需跟进"
        }}
    }})
    $form.Controls.Add($script:customerBox)
    $form.Controls.Add($script:markButton)
}}
Add-CustomerControls
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 80
$timer.Add_Tick({{
    if (Test-Path -LiteralPath $recreateFlag) {{
        Remove-Item -LiteralPath $recreateFlag -Force -ErrorAction SilentlyContinue
        if ($script:customerBox -ne $null) {{
            $form.Controls.Remove($script:customerBox)
            $script:customerBox.Dispose()
            $script:customerBox = $null
        }}
        if ($script:markButton -ne $null) {{
            $form.Controls.Remove($script:markButton)
            $script:markButton.Dispose()
            $script:markButton = $null
        }}
        $siblingEdit = New-Object System.Windows.Forms.TextBox
        $siblingEdit.AccessibleName = '客户备注编号'
        $siblingEdit.Location = '65,300'
        $siblingEdit.Size = '300,34'
        $form.Controls.Add($siblingEdit)
        $siblingButton = New-Object System.Windows.Forms.Button
        $siblingButton.AccessibleName = '标记其他客户'
        $siblingButton.Text = '标记其他客户'
        $siblingButton.Location = '390,300'
        $siblingButton.Size = '150,38'
        $form.Controls.Add($siblingButton)
        Add-CustomerControls
        $otherButton.Focus()
    }}
}})
$timer.Start()
$form.Add_Shown({{ $otherButton.Focus() }})
[System.Windows.Forms.Application]::Run($form)
'''


class WindowsInteractiveBrowserFileDesktopWorkE2ETests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        browser_bridge_e2e.WindowsInteractiveUserBrowserBridgeProviderE2ETests._require_input_desktop()

    @staticmethod
    def _stamp(path: Path, days_ago: int) -> None:
        now = datetime.now().astimezone()
        stamp = datetime.combine(
            now.date() - timedelta(days=days_ago),
            day_time(12),
            tzinfo=now.tzinfo,
        ).timestamp()
        os.utime(path, (stamp, stamp))

    @staticmethod
    def _authorize_current_tab(resident, browser) -> dict:
        # A real user gesture can be missed while Windows is still settling focus.
        # Retry the gesture only after proving no authorization exists; never
        # auto-authorize or bypass the extension's explicit-current-tab boundary.
        for _ in range(3):
            current = resident.user_browser_authorization()
            if current.get("authorized") and current.get("provider") == "zn-extension-user-browser":
                return current
            browser.activate()
            time.sleep(0.12)
            extension_e2e._press_extension_action_shortcut()
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                candidate = resident.user_browser_authorization()
                if (
                    candidate.get("authorized")
                    and candidate.get("provider") == "zn-extension-user-browser"
                ):
                    return candidate
                time.sleep(0.05)
        return resident.user_browser_authorization()

    @staticmethod
    def _run_to_terminal(
        resident,
        rpc,
        *,
        thread_id: str,
        event_id: str,
        timeout: float = 55.0,
        hook=None,
    ):
        final = None
        trace: list[dict] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if hook is not None:
                hook()
            resident.live_once()
            state = resident.store.get_working_state()
            desktop_key = getattr(
                resident,
                "_DESKTOP_TASK_OBSERVATION_KEY",
                "resident_desktop_task_observation",
            )
            desktop = state.data.get(desktop_key)
            desktop = desktop if isinstance(desktop, dict) else {}
            trace.append(
                {
                    "stage": state.stage,
                    "next_action": state.next_action,
                    "desktop_phase": desktop.get("phase"),
                    "local_failure": str(state.data.get("local_failure") or "") or None,
                }
            )
            polled = rpc.handle(
                {
                    "id": "progress",
                    "method": "work_progress",
                    "params": {
                        "thread_id": thread_id,
                        "event_id": event_id,
                        "message_limit": 160,
                    },
                }
            )
            if polled["result"]["progress"]["terminal"]:
                final = polled["result"]
                break
            time.sleep(0.04)
        return final, trace

    def test_same_root_work_carries_exact_browser_customer_through_file_into_desktop(self) -> None:
        self._require_input_desktop()
        browsers = browser_bridge_e2e._find_installed_browsers()
        if not browsers:
            self.fail("interactive Windows runner has neither stable Edge nor Chrome")

        abnormal_customer = "CUST-" + secrets.token_hex(5).upper()
        normal_customer = "CUST-" + secrets.token_hex(5).upper()
        sibling_customer = "CUST-" + secrets.token_hex(5).upper()
        self.assertEqual(len({abnormal_customer, normal_customer, sibling_customer}), 3)

        server = ThreadingHTTPServer(("127.0.0.1", 0), _CustomerStatusHandler)
        server.abnormal_customer = abnormal_customer  # type: ignore[attr-defined]
        server.normal_customer = normal_customer  # type: ignore[attr-defined]
        server.sibling_customer = sibling_customer  # type: ignore[attr-defined]
        server.login_requests = 0  # type: ignore[attr-defined]
        server.customer_requests = 0  # type: ignore[attr-defined]
        server.authenticated_customer_requests = 0  # type: ignore[attr-defined]
        server.unauthorized_requests = 0  # type: ignore[attr-defined]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        repo_root = Path(__file__).resolve().parents[3]
        extension = repo_root / "apps" / "desktop" / "browser-extension"
        provider, executable = browsers[0]
        login_url = f"http://{extension_e2e._HOST}:{int(server.server_address[1])}/login"
        browser = extension_e2e._ExtensionBrowserFixture(
            provider,
            executable,
            login_url,
            extension,
            window_title_marker=_BROWSER_TITLE,
        )
        runtime_tmp = tempfile.TemporaryDirectory()
        resident = None
        rpc = None
        app = None
        try:
            root = Path(runtime_tmp.name)
            workspace = root / "authorized-workspace"
            workspace.mkdir()
            target = workspace / "客户状态-华东.txt"
            decoy_file = workspace / "客户状态-华南.txt"
            target.write_text("当前无异常", encoding="utf-8")
            decoy_original = "华南客户保持原状"
            decoy_file.write_text(decoy_original, encoding="utf-8")
            self._stamp(target, 1)
            self._stamp(decoy_file, 2)

            browser.start()
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if int(server.authenticated_customer_requests) >= 1:  # type: ignore[attr-defined]
                    break
                time.sleep(0.05)
            self.assertGreaterEqual(int(server.authenticated_customer_requests), 1)  # type: ignore[attr-defined]
            self.assertEqual(int(server.unauthorized_requests), 0)  # type: ignore[attr-defined]

            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            rpc = ResidentRpcServer(resident=resident)
            rpc.service.acquire()
            authorization_summary = self._authorize_current_tab(resident, browser)
            self.assertTrue(authorization_summary.get("authorized"), authorization_summary)
            self.assertEqual(
                authorization_summary.get("provider"),
                "zn-extension-user-browser",
            )
            self.assertEqual(
                authorization_summary.get("authorization_scope"),
                "explicit_current_tab",
            )
            authorization = resident.user_browser_extension.authorized_tab()
            self.assertIsNotNone(authorization)

            app = _CustomerManagerApp(
                root,
                abnormal_customer=abnormal_customer,
                normal_customer=normal_customer,
                sibling_customer=sibling_customer,
            )
            app.start()
            app.activate()

            thread_id = "e2e24-browser-file-desktop"
            self.assertTrue(
                rpc.handle(
                    {
                        "id": "create",
                        "method": "work_create",
                        "params": {"thread_id": thread_id, "title": "E2E-24 customer status"},
                    }
                )["ok"]
            )
            self.assertTrue(
                rpc.handle(
                    {
                        "id": "attach",
                        "method": "work_attach_workspace",
                        "params": {
                            "thread_id": thread_id,
                            "workspace_path": str(workspace),
                            "workspace_name": "Customer status workspace",
                        },
                    }
                )["ok"]
            )
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

            recreated = False
            old_runtime: tuple[int, ...] = ()
            fresh_runtime: tuple[int, ...] = ()

            def hook() -> None:
                nonlocal recreated, old_runtime, fresh_runtime
                if recreated:
                    return
                state = resident.store.get_working_state()
                raw = state.data.get(
                    getattr(
                        resident,
                        "_DESKTOP_TASK_OBSERVATION_KEY",
                        "resident_desktop_task_observation",
                    )
                )
                observation = raw if isinstance(raw, dict) else {}
                target_observation = observation.get("target")
                target_observation = (
                    target_observation if isinstance(target_observation, dict) else {}
                )
                if observation.get("phase") != "focus" or not target_observation.get("runtime_id"):
                    return
                if any(
                    action.event_id == event_id
                    and action.kind in {"pointer_click", "keyboard_text"}
                    for action in resident.body.recent_actions(512)
                ):
                    return
                old_runtime = tuple(int(value) for value in target_observation["runtime_id"])
                app.trigger_recreation()
                deadline = time.monotonic() + 8.0
                while time.monotonic() < deadline:
                    app.activate()
                    try:
                        foreground = resident.foreground_window.probe()
                        current = resident.named_automation_control.find_unique_edit(
                            process_id=int(foreground.process_id),
                            process_name=str(foreground.process_name).lower(),
                            name=_INPUT_NAME,
                        )
                    except Exception:
                        time.sleep(0.05)
                        continue
                    if tuple(current.runtime_id) != old_runtime:
                        fresh_runtime = tuple(current.runtime_id)
                        recreated = True
                        break
                    time.sleep(0.05)
                self.assertTrue(recreated, "real UIA control recreation did not change RuntimeId")

            final, trace = self._run_to_terminal(
                resident,
                rpc,
                thread_id=thread_id,
                event_id=event_id,
                hook=hook,
            )
            self.assertIsNotNone(final, json.dumps(trace[-30:], ensure_ascii=False))
            assert final is not None
            self.assertTrue(
                final["progress"]["finalized"],
                json.dumps(trace[-30:], ensure_ascii=False),
            )
            self.assertTrue(recreated, json.dumps(trace[-30:], ensure_ascii=False))
            self.assertTrue(old_runtime)
            self.assertTrue(fresh_runtime)
            self.assertNotEqual(old_runtime, fresh_runtime)

            self.assertEqual(final["thread"]["messages"][0]["text"], _TASK)
            self.assertNotIn("http://", _TASK.lower())
            self.assertNotIn("selector", _TASK.lower())
            self.assertNotIn("hwnd", _TASK.lower())
            self.assertNotIn("runtime", _TASK.lower())
            self.assertNotIn(str(workspace).lower(), _TASK.lower())
            for customer in (abnormal_customer, normal_customer, sibling_customer):
                self.assertNotIn(customer, _TASK)

            self.assertEqual(target.read_text(encoding="utf-8"), abnormal_customer)
            self.assertEqual(decoy_file.read_text(encoding="utf-8"), decoy_original)
            self.assertEqual(app.title(), f"客户 {abnormal_customer} — 需跟进")
            self.assertEqual(app.mutation_ids(), [abnormal_customer])
            self.assertNotIn(normal_customer, app.mutation_ids())
            self.assertNotIn(sibling_customer, app.mutation_ids())

            actions = [
                action
                for action in reversed(resident.body.recent_actions(1024))
                if action.event_id == event_id
            ]
            self.assertEqual(sum(action.kind == "write_text" for action in actions), 1)
            self.assertEqual(sum(action.kind == "keyboard_text" for action in actions), 1)
            write_index = next(index for index, action in enumerate(actions) if action.kind == "write_text")
            desktop_index = next(
                index
                for index, action in enumerate(actions)
                if action.kind in {"keyboard_text", "pointer_click"}
            )
            self.assertLess(write_index, desktop_index)
            self.assertTrue(
                any(action.kind == "read_text" for action in actions[write_index + 1 :]),
                "exact target file was not freshly reread after the write",
            )

            authorization_after = resident.user_browser_extension.authorized_tab()
            self.assertIsNotNone(authorization_after)
            self.assertEqual(authorization_after.tab_id, authorization.tab_id)
            self.assertEqual(authorization_after.attached_at, authorization.attached_at)
            self.assertEqual(int(server.unauthorized_requests), 0)  # type: ignore[attr-defined]

            ambiguous_workspace = root / "ambiguous-workspace"
            ambiguous_workspace.mkdir()
            ambiguous_a = ambiguous_workspace / "客户状态-华东.txt"
            ambiguous_b = ambiguous_workspace / "客户状态-华北.txt"
            ambiguous_a.write_text("候选 A", encoding="utf-8")
            ambiguous_b.write_text("候选 B", encoding="utf-8")
            self._stamp(ambiguous_a, 1)
            self._stamp(ambiguous_b, 1)
            ambiguous_thread = "e2e24-browser-file-desktop-ambiguous"
            self.assertTrue(
                rpc.handle(
                    {
                        "id": "create-ambiguous",
                        "method": "work_create",
                        "params": {"thread_id": ambiguous_thread, "title": "E2E-24 ambiguity"},
                    }
                )["ok"]
            )
            self.assertTrue(
                rpc.handle(
                    {
                        "id": "attach-ambiguous",
                        "method": "work_attach_workspace",
                        "params": {
                            "thread_id": ambiguous_thread,
                            "workspace_path": str(ambiguous_workspace),
                            "workspace_name": "Ambiguous workspace",
                        },
                    }
                )["ok"]
            )
            ambiguous_started = rpc.handle(
                {
                    "id": "start-ambiguous",
                    "method": "work_start",
                    "params": {
                        "thread_id": ambiguous_thread,
                        "task": _TASK,
                        "kind": "desktop_user_event",
                        "priority": 0,
                        "payload": {"model_policy": "never"},
                    },
                }
            )
            ambiguous_event = str(ambiguous_started["result"]["progress"]["event_id"])
            ambiguous_final, ambiguous_trace = self._run_to_terminal(
                resident,
                rpc,
                thread_id=ambiguous_thread,
                event_id=ambiguous_event,
                timeout=20.0,
            )
            self.assertIsNotNone(
                ambiguous_final,
                json.dumps(ambiguous_trace[-20:], ensure_ascii=False),
            )
            ambiguous_actions = [
                action
                for action in resident.body.recent_actions(1024)
                if action.event_id == ambiguous_event
                and action.kind in {"write_text", "keyboard_text", "pointer_click"}
            ]
            self.assertEqual(ambiguous_actions, [])
            self.assertEqual(ambiguous_a.read_text(encoding="utf-8"), "候选 A")
            self.assertEqual(ambiguous_b.read_text(encoding="utf-8"), "候选 B")
            self.assertEqual(app.mutation_ids(), [abnormal_customer])

            print(
                "ZN_E2E24_BROWSER_FILE_DESKTOP_EVIDENCE="
                + json.dumps(
                    {
                        "provider": provider,
                        "normal_language_task": _TASK,
                        "same_root_work_event_id": event_id,
                        "random_browser_customers": {
                            "abnormal": abnormal_customer,
                            "normal": normal_customer,
                            "sibling": sibling_customer,
                        },
                        "user_supplied_internal_identifiers": False,
                        "authorized_user_browser_generation_preserved": True,
                        "browser_abnormal_customer": abnormal_customer,
                        "file_persisted_customer": target.read_text(encoding="utf-8"),
                        "desktop_mutated_customer": app.mutation_ids()[0],
                        "decoy_file_unchanged": True,
                        "desktop_decoys_unchanged": True,
                        "file_write_exactly_once": True,
                        "desktop_mutation_exactly_once": True,
                        "desktop_stale_runtime_rejected": old_runtime != fresh_runtime,
                        "ambiguous_file_targets_fail_closed": ambiguous_actions == [],
                        "independent_final_ui_title": app.title(),
                    },
                    ensure_ascii=False,
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
            if app is not None:
                app.close()
            browser.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2.0)
            runtime_tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
