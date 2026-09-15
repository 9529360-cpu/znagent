from __future__ import annotations

import ctypes
import json
import secrets
import subprocess
import tempfile
import time
import unittest
from ctypes import wintypes
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.resident_server import ResidentSocketService

import test_windows_interactive_browser_file_desktop_work as e2e24
import test_windows_interactive_user_browser_bridge as browser_bridge_e2e
import test_windows_interactive_user_browser_extension as extension_e2e


_TASK = (
    "把当前网站里需跟进客户的状态填到我现在开的客户管理软件对应记录的“客户状态”字段里，"
    "并确认没有填错客户。"
)
_FIELD_NAME = "客户状态"
_STATUS = "需跟进"


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


class _CustomerRecordApp:
    def __init__(self, root: Path, *, customer_id: str, name: str) -> None:
        self.customer_id = customer_id
        self.start_title = f"客户 {customer_id} — 当前记录"
        self.script = root / f"e2e14-customer-record-{name}.ps1"
        self.mutation_log = root / f"e2e14-customer-record-{name}-mutations.txt"
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
                raise RuntimeError("E2E-14 customer-record fixture exited early")
            self.hwnd = self._find_window()
            if self.hwnd:
                self.activate()
                return
            time.sleep(0.05)
        raise RuntimeError("E2E-14 customer-record window was not found")

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
        raise RuntimeError("E2E-14 customer-record fixture could not become foreground")

    def title(self) -> str:
        user32 = _user32()
        length = int(user32.GetWindowTextLengthW(self.hwnd))
        buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        user32.GetWindowTextW(self.hwnd, buffer, len(buffer))
        return buffer.value

    def mutations(self) -> list[str]:
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
        self.hwnd = 0

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
                if buffer.value == self.start_title:
                    matches.append(int(hwnd))
            return True

        user32.EnumWindows(visit, 0)
        return matches[0] if len(matches) == 1 else 0

    def _script_text(self) -> str:
        customer = self.customer_id.replace("'", "''")
        mutation_log = str(self.mutation_log).replace("'", "''")
        return f'''Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object System.Windows.Forms.Form
$form.Text = '客户 {customer} — 当前记录'
$form.StartPosition = 'CenterScreen'
$form.ClientSize = '760,330'
$mutationLog = '{mutation_log}'
$customer = '{customer}'
$heading = New-Object System.Windows.Forms.Label
$heading.Text = "客户记录 $customer"
$heading.Location = '55,25'
$heading.Size = '600,38'
$heading.Font = 'Segoe UI,18'
$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Text = '客户状态'
$statusLabel.Location = '55,95'
$statusLabel.Size = '130,30'
$statusLabel.Font = 'Segoe UI,12'
$statusBox = New-Object System.Windows.Forms.TextBox
$statusBox.AccessibleName = '{_FIELD_NAME}'
$statusBox.Location = '190,90'
$statusBox.Size = '420,40'
$statusBox.Font = 'Segoe UI,14'
$statusBox.Text = '未同步'
$notes = New-Object System.Windows.Forms.TextBox
$notes.AccessibleName = '客户备注'
$notes.Location = '190,165'
$notes.Size = '420,55'
$notes.Font = 'Segoe UI,12'
$statusBox.Add_TextChanged({{
    $value = $statusBox.Text
    Add-Content -LiteralPath $mutationLog -Value "$customer|$value" -Encoding UTF8
    $form.Text = "客户 $customer — 状态 $value"
}})
$form.Controls.Add($heading)
$form.Controls.Add($statusLabel)
$form.Controls.Add($statusBox)
$form.Controls.Add($notes)
$form.Add_Shown({{ $notes.Focus() }})
[System.Windows.Forms.Application]::Run($form)
'''


class WindowsInteractiveBrowserDesktopRecordTransferE2ETests(unittest.TestCase):
    @staticmethod
    def _read_status(resident):
        foreground = resident.foreground_window.probe()
        edit = resident.named_automation_control.find_unique_edit(
            process_id=int(foreground.process_id),
            process_name=str(foreground.process_name).lower(),
            name=_FIELD_NAME,
        )
        return resident.current_app_text_content.read_exact(
            process_id=int(foreground.process_id),
            process_name=str(foreground.process_name).lower(),
            window_handle=int(foreground.window_handle),
            name=_FIELD_NAME,
            runtime_id=tuple(edit.runtime_id),
            allow_read_only=False,
        ).text

    @staticmethod
    def _start_work(rpc, *, thread_id: str):
        created = rpc.handle(
            {
                "id": f"create-{thread_id}",
                "method": "work_create",
                "params": {"thread_id": thread_id, "title": "E2E-14 browser desktop record"},
            }
        )
        if not created["ok"]:
            raise AssertionError(created)
        started = rpc.handle(
            {
                "id": f"start-{thread_id}",
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
        if not started["ok"]:
            raise AssertionError(started)
        return str(started["result"]["progress"]["event_id"])

    def test_browser_customer_identity_reaches_only_the_corresponding_desktop_record(self) -> None:
        e2e24.WindowsInteractiveBrowserFileDesktopWorkE2ETests._require_input_desktop()
        browsers = browser_bridge_e2e._find_installed_browsers()
        if not browsers:
            self.fail("interactive Windows runner has neither stable Edge nor Chrome")

        abnormal_customer = "CUST-" + secrets.token_hex(5).upper()
        normal_customer = "CUST-" + secrets.token_hex(5).upper()
        sibling_customer = "CUST-" + secrets.token_hex(5).upper()
        self.assertEqual(len({abnormal_customer, normal_customer, sibling_customer}), 3)

        server = e2e24.ThreadingHTTPServer(("127.0.0.1", 0), e2e24._CustomerStatusHandler)
        server.abnormal_customer = abnormal_customer  # type: ignore[attr-defined]
        server.normal_customer = normal_customer  # type: ignore[attr-defined]
        server.sibling_customer = sibling_customer  # type: ignore[attr-defined]
        server.login_requests = 0  # type: ignore[attr-defined]
        server.customer_requests = 0  # type: ignore[attr-defined]
        server.authenticated_customer_requests = 0  # type: ignore[attr-defined]
        server.unauthorized_requests = 0  # type: ignore[attr-defined]
        server_thread = e2e24.threading.Thread(target=server.serve_forever, daemon=True)
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
            window_title_marker=e2e24._BROWSER_TITLE,
        )
        runtime_tmp = tempfile.TemporaryDirectory()
        resident = None
        rpc = None
        matching_app = None
        wrong_app = None
        try:
            root = Path(runtime_tmp.name)
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
            service = ResidentSocketService(rpc)
            rpc.service.acquire()
            authorization_summary = e2e24.WindowsInteractiveBrowserFileDesktopWorkE2ETests._authorize_current_tab(
                resident,
                browser,
            )
            self.assertTrue(authorization_summary.get("authorized"), authorization_summary)
            authorization = resident.user_browser_extension.authorized_tab()
            self.assertIsNotNone(authorization)
            assert authorization is not None

            matching_app = _CustomerRecordApp(
                root,
                customer_id=abnormal_customer,
                name="matching",
            )
            matching_app.start()
            matching_app.activate()
            event_id = self._start_work(rpc, thread_id="e2e14-browser-desktop-record")
            final, trace = e2e24.WindowsInteractiveBrowserFileDesktopWorkE2ETests._run_to_terminal(
                resident,
                rpc,
                thread_id="e2e14-browser-desktop-record",
                event_id=event_id,
                timeout=35.0,
            )
            self.assertIsNotNone(final, json.dumps(trace[-30:], ensure_ascii=False))
            assert final is not None
            self.assertTrue(final["progress"]["finalized"], json.dumps(trace[-30:], ensure_ascii=False))
            self.assertEqual(final["thread"]["messages"][0]["text"], _TASK)
            for customer in (abnormal_customer, normal_customer, sibling_customer):
                self.assertNotIn(customer, _TASK)
            self.assertNotIn("hwnd", _TASK.lower())
            self.assertNotIn("runtime", _TASK.lower())
            self.assertNotIn("selector", _TASK.lower())

            matching_app.activate()
            self.assertEqual(self._read_status(resident), _STATUS)
            self.assertEqual(matching_app.mutations(), [f"{abnormal_customer}|{_STATUS}"])
            self.assertIn(abnormal_customer, matching_app.title())
            self.assertIn(_STATUS, matching_app.title())
            matching_actions = [
                action
                for action in resident.body.recent_actions(1024)
                if action.event_id == event_id
            ]
            self.assertEqual(
                sum(action.kind == "automation_value_replace" for action in matching_actions),
                1,
            )

            authorization_after = resident.user_browser_extension.authorized_tab()
            self.assertIsNotNone(authorization_after)
            assert authorization_after is not None
            self.assertEqual(authorization_after.tab_id, authorization.tab_id)
            self.assertEqual(authorization_after.attached_at, authorization.attached_at)
            self.assertEqual(int(server.unauthorized_requests), 0)  # type: ignore[attr-defined]

            matching_app.close()
            matching_app = None
            wrong_app = _CustomerRecordApp(
                root,
                customer_id=sibling_customer,
                name="wrong-record",
            )
            wrong_app.start()
            wrong_app.activate()
            wrong_event = self._start_work(rpc, thread_id="e2e14-browser-desktop-wrong-record")
            wrong_final, wrong_trace = e2e24.WindowsInteractiveBrowserFileDesktopWorkE2ETests._run_to_terminal(
                resident,
                rpc,
                thread_id="e2e14-browser-desktop-wrong-record",
                event_id=wrong_event,
                timeout=20.0,
            )
            self.assertIsNotNone(wrong_final, json.dumps(wrong_trace[-20:], ensure_ascii=False))
            wrong_actions = [
                action
                for action in resident.body.recent_actions(1024)
                if action.event_id == wrong_event and action.kind == "automation_value_replace"
            ]
            self.assertEqual(wrong_actions, [])
            self.assertEqual(wrong_app.mutations(), [])
            wrong_app.activate()
            self.assertEqual(self._read_status(resident), "未同步")
            self.assertEqual(int(server.unauthorized_requests), 0)  # type: ignore[attr-defined]

            print(
                "ZN_E2E14_BROWSER_DESKTOP_RECORD_EVIDENCE="
                + json.dumps(
                    {
                        "provider": provider,
                        "normal_language_task": _TASK,
                        "source_customer": abnormal_customer,
                        "matching_desktop_customer": abnormal_customer,
                        "wrong_desktop_customer": sibling_customer,
                        "browser_authorization_generation_preserved": True,
                        "matching_record_status": _STATUS,
                        "matching_record_setvalue_exactly_once": True,
                        "wrong_record_setvalue_count": 0,
                        "wrong_record_unchanged": True,
                        "user_supplied_internal_identifiers": False,
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
            if matching_app is not None:
                matching_app.close()
            if wrong_app is not None:
                wrong_app.close()
            browser.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2.0)
            runtime_tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
