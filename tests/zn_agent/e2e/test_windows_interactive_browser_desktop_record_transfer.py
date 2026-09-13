from __future__ import annotations

import ctypes
import json
import secrets
import subprocess
import tempfile
import time
import unittest
from ctypes import wintypes
from http.server import ThreadingHTTPServer
from pathlib import Path

from zn_agent.core.browser_desktop_record_transfer_behavior import _STATE_KEY
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.resident_server import ResidentSocketService
from zn_agent.core.work_restore_control import RestoreAwareWorkControl

import test_windows_interactive_browser_file_desktop_work as e2e24
import test_windows_interactive_user_browser_bridge as browser_bridge_e2e
import test_windows_interactive_user_browser_extension as extension_e2e


TASK = "把当前浏览器里唯一需跟进客户的跟进状态填到我现在开的客户管理软件对应记录里，然后保存并确认填对了。"
_ACCEPTANCE = "fresh USER Browser source identity/value equals the exact saved current desktop customer record"
_APP_START_TITLE = "ZN E2E-14 Customer Manager"
_APP_RESULT_TITLE = "ZN E2E-14 客户记录已保存"
_KEY_NAME = "客户编号"
_FIELD_NAME = "跟进状态"
_SAVE_NAME = "保存"


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
    api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    api.GetWindowThreadProcessId.restype = wintypes.DWORD
    api.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    api.AttachThreadInput.restype = wintypes.BOOL
    api.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    api.PostMessageW.restype = wintypes.BOOL
    return api


class _CustomerRecordApp:
    def __init__(self, root: Path, *, customer_id: str):
        self.root = root
        self.customer_id = customer_id
        self.script = root / "e2e14-customer-record.ps1"
        self.recreate_flag = root / "e2e14-recreate-status.flag"
        self.save_count = root / "e2e14-save-count.txt"
        self.saved_log = root / "e2e14-saved.txt"
        self.process: subprocess.Popen | None = None
        self.hwnd = 0
        self.result_hwnd = 0

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
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("E2E-14 WinForms fixture exited early")
            self.hwnd = self._find_title(_APP_START_TITLE)
            if self.hwnd:
                self.activate(self.hwnd)
                return
            time.sleep(0.05)
        raise RuntimeError("E2E-14 source customer window was not found")

    @staticmethod
    def _wait_foreground(api, hwnd: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if int(api.GetForegroundWindow() or 0) == hwnd:
                return True
            time.sleep(0.02)
        return False

    def activate(self, hwnd: int | None = None) -> None:
        hwnd = int(hwnd or self.hwnd)
        api = _user32()
        api.ShowWindow(hwnd, 5)
        api.BringWindowToTop(hwnd)
        api.SetForegroundWindow(hwnd)
        if self._wait_foreground(api, hwnd, 0.25):
            return

        foreground_hwnd = int(api.GetForegroundWindow() or 0)
        foreground_thread = (
            int(api.GetWindowThreadProcessId(foreground_hwnd, None) or 0)
            if foreground_hwnd
            else 0
        )
        target_thread = int(api.GetWindowThreadProcessId(hwnd, None) or 0)
        attached = False
        if foreground_thread and target_thread and foreground_thread != target_thread:
            attached = bool(api.AttachThreadInput(target_thread, foreground_thread, True))
        try:
            api.ShowWindow(hwnd, 5)
            api.BringWindowToTop(hwnd)
            api.SetForegroundWindow(hwnd)
            if self._wait_foreground(api, hwnd, 2):
                return
        finally:
            if attached:
                api.AttachThreadInput(target_thread, foreground_thread, False)
        raise RuntimeError("E2E-14 fixture could not become foreground")

    def trigger_recreate(self) -> None:
        self.recreate_flag.write_text("1", encoding="utf-8")

    def wait_flag_consumed(self, timeout: float = 6) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.recreate_flag.exists():
                return
            time.sleep(0.03)
        raise RuntimeError("E2E-14 fixture did not recreate the status control")

    def wait_result(self, timeout: float = 0.03) -> int:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = self._find_title(_APP_RESULT_TITLE)
            if found:
                self.result_hwnd = found
                return found
            time.sleep(0.01)
        return 0

    def saved_count_value(self) -> int:
        if not self.save_count.exists():
            return 0
        return int(self.save_count.read_text(encoding="utf-8-sig").strip() or "0")

    def saved_records(self) -> list[str]:
        if not self.saved_log.exists():
            return []
        return [
            line.strip()
            for line in self.saved_log.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]

    def close(self) -> None:
        api = _user32()
        for hwnd in (self.result_hwnd, self.hwnd):
            if hwnd:
                try:
                    api.PostMessageW(hwnd, 0x0010, 0, 0)
                except Exception:
                    pass
        if self.process is not None:
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)

    def _find_title(self, title: str) -> int:
        api = _user32()
        callback_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        api.EnumWindows.argtypes = [callback_t, wintypes.LPARAM]
        api.EnumWindows.restype = wintypes.BOOL
        matches: list[int] = []

        @callback_t
        def visit(hwnd, _):
            pid = wintypes.DWORD()
            api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if self.process is not None and int(pid.value) == self.process.pid and api.IsWindowVisible(hwnd):
                length = int(api.GetWindowTextLengthW(hwnd))
                buffer = ctypes.create_unicode_buffer(max(1, length + 1))
                api.GetWindowTextW(hwnd, buffer, len(buffer))
                if buffer.value == title:
                    matches.append(int(hwnd))
            return True

        api.EnumWindows(visit, 0)
        return matches[0] if len(matches) == 1 else 0

    @staticmethod
    def _ps(value: str) -> str:
        return value.replace("'", "''")

    def _script_text(self) -> str:
        customer = self._ps(self.customer_id)
        recreate = self._ps(str(self.recreate_flag))
        save_count = self._ps(str(self.save_count))
        saved_log = self._ps(str(self.saved_log))
        return f'''Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object System.Windows.Forms.Form
$form.Text = '{_APP_START_TITLE}'
$form.StartPosition = 'CenterScreen'
$form.ClientSize = '760,360'
$recreateFlag = '{recreate}'
$saveCountFile = '{save_count}'
$savedLog = '{saved_log}'
$script:statusBox = $null
$script:resultForm = $null

$keyBox = New-Object System.Windows.Forms.TextBox
$keyBox.AccessibleName = '{_KEY_NAME}'
$keyBox.Location = '65,75'
$keyBox.Size = '430,38'
$keyBox.Font = 'Segoe UI,14'
$keyBox.ReadOnly = $true
$keyBox.Text = '{customer}'
$heading = New-Object System.Windows.Forms.Label
$heading.Text = '当前客户记录'
$heading.Location = '65,25'
$heading.Size = '400,35'
$heading.Font = 'Segoe UI,16'
$save = New-Object System.Windows.Forms.Button
$save.AccessibleName = '{_SAVE_NAME}'
$save.Text = '{_SAVE_NAME}'
$save.Location = '555,190'
$save.Size = '120,46'
$form.Controls.AddRange(@($heading, $keyBox, $save))

function Add-StatusBox {{
    $script:statusBox = New-Object System.Windows.Forms.TextBox
    $script:statusBox.AccessibleName = '{_FIELD_NAME}'
    $script:statusBox.Location = '65,145'
    $script:statusBox.Size = '430,40'
    $script:statusBox.Font = 'Segoe UI,14'
    $script:statusBox.Text = '未跟进'
    $form.Controls.Add($script:statusBox)
}}
Add-StatusBox

$save.Add_Click({{
    $count = 0
    if (Test-Path -LiteralPath $saveCountFile) {{
        try {{ $count = [int](Get-Content -LiteralPath $saveCountFile -Raw) }} catch {{ $count = 0 }}
    }}
    $count++
    Set-Content -LiteralPath $saveCountFile -Value ([string]$count) -Encoding UTF8
    Add-Content -LiteralPath $savedLog -Value ($keyBox.Text + '|' + $script:statusBox.Text) -Encoding UTF8
    $savedKey = $keyBox.Text
    $savedStatus = $script:statusBox.Text
    $form.Hide()
    $script:resultForm = New-Object System.Windows.Forms.Form
    $script:resultForm.Text = '{_APP_RESULT_TITLE}'
    $script:resultForm.StartPosition = 'CenterScreen'
    $script:resultForm.ClientSize = '720,310'
    $resultKey = New-Object System.Windows.Forms.TextBox
    $resultKey.AccessibleName = '{_KEY_NAME}'
    $resultKey.Location = '65,75'
    $resultKey.Size = '430,38'
    $resultKey.Font = 'Segoe UI,14'
    $resultKey.ReadOnly = $true
    $resultKey.Text = $savedKey
    $resultStatus = New-Object System.Windows.Forms.TextBox
    $resultStatus.AccessibleName = '{_FIELD_NAME}'
    $resultStatus.Location = '65,145'
    $resultStatus.Size = '430,40'
    $resultStatus.Font = 'Segoe UI,14'
    $resultStatus.ReadOnly = $true
    $resultStatus.Text = $savedStatus
    $close = New-Object System.Windows.Forms.Button
    $close.AccessibleName = '关闭'
    $close.Text = '关闭'
    $close.Location = '545,200'
    $close.Size = '105,40'
    $script:resultForm.Controls.AddRange(@($resultKey, $resultStatus, $close))
    $script:resultForm.Add_Shown({{ $script:resultForm.Activate(); $close.Focus() }})
    $script:resultForm.Show()
    $script:resultForm.Activate()
}})

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 70
$timer.Add_Tick({{
    if (Test-Path -LiteralPath $recreateFlag) {{
        Remove-Item -LiteralPath $recreateFlag -Force -ErrorAction SilentlyContinue
        if ($script:statusBox -ne $null) {{
            $oldText = $script:statusBox.Text
            $form.Controls.Remove($script:statusBox)
            $script:statusBox.Dispose()
            $script:statusBox = New-Object System.Windows.Forms.TextBox
            $script:statusBox.AccessibleName = '{_FIELD_NAME}'
            $script:statusBox.Location = '65,145'
            $script:statusBox.Size = '430,40'
            $script:statusBox.Font = 'Segoe UI,14'
            $script:statusBox.Text = $oldText
            $form.Controls.Add($script:statusBox)
            $script:statusBox.CreateControl()
            $save.Focus()
        }}
    }}
}})
$timer.Start()
$form.Add_Shown({{ $save.Focus() }})
[System.Windows.Forms.Application]::Run($form)
'''


class WindowsInteractiveBrowserDesktopRecordTransferE2ETests(unittest.TestCase):
    def test_real_user_browser_record_transfers_to_matching_current_desktop_record_and_saves_once(self):
        browser_bridge_e2e.WindowsInteractiveUserBrowserBridgeProviderE2ETests._require_input_desktop()
        browsers = browser_bridge_e2e._find_installed_browsers()
        if not browsers:
            self.fail("interactive Windows runner has neither stable Edge nor Chrome")

        customer = "CUST-" + secrets.token_hex(5).upper()
        normal = "CUST-" + secrets.token_hex(5).upper()
        sibling = "CUST-" + secrets.token_hex(5).upper()
        self.assertEqual(len({customer, normal, sibling}), 3)

        server = ThreadingHTTPServer(("127.0.0.1", 0), e2e24._CustomerStatusHandler)
        server.abnormal_customer = customer  # type: ignore[attr-defined]
        server.normal_customer = normal  # type: ignore[attr-defined]
        server.sibling_customer = sibling  # type: ignore[attr-defined]
        server.login_requests = 0  # type: ignore[attr-defined]
        server.customer_requests = 0  # type: ignore[attr-defined]
        server.authenticated_customer_requests = 0  # type: ignore[attr-defined]
        server.unauthorized_requests = 0  # type: ignore[attr-defined]
        import threading
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
            window_title_marker=e2e24._BROWSER_TITLE,
        )
        runtime_tmp = tempfile.TemporaryDirectory(prefix="zn-e2e14-", ignore_cleanup_errors=True)
        resident = None
        rpc = None
        app = None
        try:
            root = Path(runtime_tmp.name)
            browser.start()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if int(server.authenticated_customer_requests) >= 1:  # type: ignore[attr-defined]
                    break
                time.sleep(0.05)
            self.assertGreaterEqual(int(server.authenticated_customer_requests), 1)  # type: ignore[attr-defined]
            self.assertEqual(int(server.unauthorized_requests), 0)  # type: ignore[attr-defined]

            resident = build_resident_runtime(config={"model": {}}, store_path=root / "kernel.db")
            rpc = ResidentRpcServer(resident=resident)
            service = ResidentSocketService(rpc)
            self.assertIs(resident.visual_region, service.visual_region)
            rpc.service.acquire()
            authorization = e2e24.WindowsInteractiveBrowserFileDesktopWorkE2ETests._authorize_current_tab(
                resident, browser
            )
            self.assertTrue(authorization.get("authorized"), authorization)
            self.assertEqual(authorization.get("authorization_scope"), "explicit_current_tab")
            authorized_tab = resident.user_browser_extension.authorized_tab()
            self.assertIsNotNone(authorized_tab)

            app = _CustomerRecordApp(root, customer_id=customer)
            app.start()
            app.activate()

            control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
            thread_id = "e2e14-" + secrets.token_hex(4)
            control.ledger.create_thread(thread_id=thread_id)
            _, event = control.start(
                thread_id,
                TASK,
                payload={"model_policy": "never"},
                acceptance_criteria=[_ACCEPTANCE],
            )
            self.assertIsNotNone(resident.work_ledger.work_item_for_event(event.event_id))

            result = None
            trace: list[dict] = []
            old_runtime: tuple[int, ...] = ()
            fresh_runtime: tuple[int, ...] = ()
            recreated = False
            deadline = time.monotonic() + 55
            while time.monotonic() < deadline and result is None:
                if app.wait_result(timeout=0.01):
                    app.activate(app.result_hwnd)
                else:
                    app.activate(app.hwnd)
                current = resident.live_once()
                state = resident.store.get_working_state()
                meta = state.data.get(_STATE_KEY)
                meta = meta if isinstance(meta, dict) else {}
                actions = [
                    action
                    for action in resident.body.recent_actions(1024)
                    if action.event_id == event.event_id
                ]
                trace.append(
                    {
                        "stage": state.stage,
                        "phase": meta.get("phase"),
                        "replacement_dispatch_count": meta.get("replacement_dispatch_count"),
                        "save_dispatch_count": meta.get("save_dispatch_count"),
                        "root_work_status": meta.get("root_work_status"),
                        "actions": [action.kind for action in actions[-8:]],
                    }
                )
                if not recreated and state.stage == "e2e14_replace":
                    initial = meta.get("destination_field_target")
                    initial = initial if isinstance(initial, dict) else {}
                    old_runtime = tuple(int(value) for value in initial.get("runtime_id") or ())
                    self.assertTrue(old_runtime, json.dumps(trace[-10:], ensure_ascii=False))
                    app.trigger_recreate()
                    app.wait_flag_consumed()
                    runtime_deadline = time.monotonic() + 6
                    while time.monotonic() < runtime_deadline:
                        app.activate(app.hwnd)
                        foreground = resident.foreground_window.probe()
                        fresh = resident.named_automation_control.find_unique_edit(
                            process_id=int(foreground.process_id),
                            process_name=str(foreground.process_name).lower(),
                            name=_FIELD_NAME,
                        )
                        fresh_runtime = tuple(fresh.runtime_id)
                        if fresh_runtime != old_runtime:
                            recreated = True
                            break
                        time.sleep(0.03)
                    self.assertTrue(recreated, "recreated destination field kept the stale RuntimeId")
                    continue
                if current is not None and current.event.event_id == event.event_id:
                    result = current
                if result is None:
                    time.sleep(0.03)

            self.assertTrue(recreated, json.dumps(trace[-20:], ensure_ascii=False))
            self.assertNotEqual(old_runtime, fresh_runtime)
            self.assertIsNotNone(result, json.dumps(trace[-30:], ensure_ascii=False))
            assert result is not None
            self.assertTrue(result.success, result.reason)
            self.assertEqual(result.model_invocations, 0)
            self.assertTrue(app.result_hwnd)
            self.assertNotEqual(app.result_hwnd, app.hwnd)
            self.assertEqual(app.saved_count_value(), 1)
            self.assertEqual(app.saved_records(), [f"{customer}|需跟进"])

            actions = [
                action
                for action in resident.body.recent_actions(1024)
                if action.event_id == event.event_id
            ]
            self.assertEqual(sum(action.kind == "automation_value_replace" for action in actions), 1)
            self.assertEqual(sum(action.kind == "pointer_click" for action in actions), 1)
            history = json.dumps([action.data for action in actions], ensure_ascii=False, default=str)
            self.assertNotIn(customer, history)
            self.assertNotIn("需跟进", history)
            self.assertNotIn(normal, app.saved_records())
            self.assertNotIn(sibling, app.saved_records())

            state = resident.store.get_working_state()
            meta = state.data.get(_STATE_KEY)
            self.assertIsInstance(meta, dict)
            self.assertEqual(meta.get("save_dispatch_count"), 1)
            final = meta.get("final_verification")
            self.assertIsInstance(final, dict)
            self.assertTrue(final.get("source_exact"))
            self.assertTrue(final.get("readback_verified"))
            self.assertTrue(final.get("title_saved_postcondition"))
            self.assertTrue(final.get("hwnd_changed"))
            persisted = json.dumps(meta, ensure_ascii=False, sort_keys=True, default=str)
            self.assertNotIn(customer, persisted)
            self.assertNotIn("需跟进", persisted)

            root_work = resident.work_ledger.work_item_for_event(event.event_id)
            self.assertIsNotNone(root_work)
            self.assertEqual(root_work.status, "completed")
            self.assertIn("zn_independent_acceptance", root_work.result or "")
            auth_after = resident.user_browser_extension.authorized_tab()
            self.assertIsNotNone(auth_after)
            self.assertEqual(auth_after.tab_id, authorized_tab.tab_id)
            self.assertEqual(auth_after.attached_at, authorized_tab.attached_at)
            self.assertEqual(int(server.unauthorized_requests), 0)  # type: ignore[attr-defined]

            print(
                "ZN_E2E14_BROWSER_DESKTOP_TRANSFER_EVIDENCE="
                + json.dumps(
                    {
                        "provider": provider,
                        "normal_language_task": TASK,
                        "user_supplied_internal_identifiers": False,
                        "explicit_current_tab_authority_preserved": True,
                        "browser_source_first": True,
                        "business_identity_preserved": True,
                        "destination_runtime_regrounded": old_runtime != fresh_runtime,
                        "value_replacement_exactly_once": True,
                        "save_exactly_once": True,
                        "fresh_result_hwnd": app.result_hwnd != app.hwnd,
                        "independent_root_acceptance": root_work.status == "completed",
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
            if app is not None:
                app.close()
            try:
                browser.close()
            except Exception:
                pass
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)
            if resident is not None:
                resident.store.close()
            runtime_tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
