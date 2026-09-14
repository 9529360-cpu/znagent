from __future__ import annotations

import ctypes
import os
import subprocess
import time
import unittest
import uuid
from ctypes import wintypes
from pathlib import Path

START_TITLE = "ZN 工作记录整理 E2E"
RESULT_TITLE = "ZN 工作记录已保存"
FIELD_NAME = "工作记录"
SAVE_NAME = "保存"
RESULT_NAME = "保存内容"


def require_input_desktop() -> None:
    if os.name != "nt":
        raise unittest.SkipTest("Windows interactive E2E runs only on Windows")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.SwitchDesktop.argtypes = [wintypes.HANDLE]
    user32.SwitchDesktop.restype = wintypes.BOOL
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.restype = wintypes.BOOL
    desktop = user32.OpenInputDesktop(0, False, 0x0001 | 0x0080 | 0x0100)
    if not desktop:
        raise AssertionError(
            "GitHub runner process cannot open the Windows input desktop; "
            "E2E-13 requires an unlocked interactive user session"
        )
    try:
        if not user32.SwitchDesktop(desktop):
            raise AssertionError("GitHub runner process cannot switch to the Windows input desktop")
    finally:
        user32.CloseDesktop(desktop)


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
    api.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    api.PostMessageW.restype = wintypes.BOOL
    return api


class WorkRecordApp:
    def __init__(self, root: Path, *, ambiguous: bool = False, mismatch: bool = False):
        self.root = root
        self.ambiguous = ambiguous
        self.mismatch = mismatch
        self.suffix = uuid.uuid4().hex[:8]
        self.script = root / "e2e13-work-record.ps1"
        self.recreate_flag = root / "recreate-edit.flag"
        self.drift_flag = root / "drift-edit.flag"
        self.save_count = root / "save-count.txt"
        self.process: subprocess.Popen | None = None
        self.hwnd = 0
        self.result_hwnd = 0
        self.lines = [
            f"客户已确认方案-{self.suffix}",
            f"等待合同-{self.suffix}",
            f"下周回访-{self.suffix}",
        ]
        self.expected = "\r\n".join(self.lines)

    @property
    def source(self) -> str:
        return (
            f"  {self.lines[0]}  \r\n"
            "   \r\n"
            f"{self.lines[1]}\r\n"
            f"\t{self.lines[0]}\t\r\n"
            f" {self.lines[2]} \r\n"
            f"{self.lines[1]}   "
        )

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
                raise RuntimeError("E2E-13 WinForms fixture exited early")
            self.hwnd = self._find_title(START_TITLE)
            if self.hwnd:
                self.activate(self.hwnd)
                return
            time.sleep(0.05)
        raise RuntimeError("E2E-13 source window was not found")

    def activate(self, hwnd: int | None = None) -> None:
        hwnd = int(hwnd or self.hwnd)
        api = _user32()
        api.ShowWindow(hwnd, 5)
        api.BringWindowToTop(hwnd)
        api.SetForegroundWindow(hwnd)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if int(api.GetForegroundWindow() or 0) == hwnd:
                return
            time.sleep(0.02)
        raise RuntimeError("E2E-13 fixture could not become foreground")

    def trigger_recreate(self) -> None:
        self.recreate_flag.write_text("1", encoding="utf-8")

    def trigger_drift(self) -> None:
        self.drift_flag.write_text("1", encoding="utf-8")

    def wait_flag_consumed(self, flag: Path, timeout: float = 6) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not flag.exists():
                return
            time.sleep(0.03)
        raise RuntimeError(f"fixture did not consume {flag.name}")

    def saved_count(self) -> int:
        if not self.save_count.exists():
            return 0
        return int(self.save_count.read_text(encoding="utf-8").strip() or "0")

    def wait_result(self, timeout: float = 6) -> int:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.result_hwnd = self._find_title(RESULT_TITLE)
            if self.result_hwnd:
                return self.result_hwnd
            time.sleep(0.03)
        return 0

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
                length = api.GetWindowTextLengthW(hwnd)
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
        source = self._ps(self.source)
        recreate = self._ps(str(self.recreate_flag))
        drift = self._ps(str(self.drift_flag))
        save_count = self._ps(str(self.save_count))
        ambiguous = "$true" if self.ambiguous else "$false"
        mismatch = "$true" if self.mismatch else "$false"
        drift_value = self._ps(self.source + f"\r\n 新增真实行-{self.suffix} ")
        return f'''Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$sourceForm = New-Object System.Windows.Forms.Form
$sourceForm.Text = '{START_TITLE}'
$sourceForm.StartPosition = 'CenterScreen'
$sourceForm.ClientSize = '820,520'
$sourceForm.TopMost = $false
$recreateFlag = '{recreate}'
$driftFlag = '{drift}'
$saveCountFile = '{save_count}'
$ambiguous = {ambiguous}
$mismatch = {mismatch}
$script:workBox = $null
$script:saveButton = $null
$script:resultForm = $null

$customer = New-Object System.Windows.Forms.TextBox
$customer.AccessibleName = '客户名称'
$customer.Location = '55,35'
$customer.Size = '350,32'
$customer.Text = '无关客户'
$cancel = New-Object System.Windows.Forms.Button
$cancel.AccessibleName = '取消'
$cancel.Text = '取消'
$cancel.Location = '650,430'
$cancel.Size = '100,38'
$sourceForm.Controls.AddRange(@($customer, $cancel))

function Add-WorkControls {{
    $script:workBox = New-Object System.Windows.Forms.TextBox
    $script:workBox.AccessibleName = '{FIELD_NAME}'
    $script:workBox.Multiline = $true
    $script:workBox.ScrollBars = 'Vertical'
    $script:workBox.Location = '55,90'
    $script:workBox.Size = '560,290'
    $script:workBox.Font = 'Segoe UI,12'
    $script:workBox.Text = '{source}'
    $script:saveButton = New-Object System.Windows.Forms.Button
    $script:saveButton.AccessibleName = '{SAVE_NAME}'
    $script:saveButton.Text = '{SAVE_NAME}'
    $script:saveButton.Location = '650,330'
    $script:saveButton.Size = '100,44'
    $script:saveButton.Add_Click({{
        $count = 0
        if (Test-Path -LiteralPath $saveCountFile) {{
            try {{ $count = [int](Get-Content -LiteralPath $saveCountFile -Raw) }} catch {{ $count = 0 }}
        }}
        $count++
        Set-Content -LiteralPath $saveCountFile -Value ([string]$count) -Encoding UTF8
        $saved = $script:workBox.Text
        $sourceForm.Hide()
        $script:resultForm = New-Object System.Windows.Forms.Form
        $script:resultForm.Text = '{RESULT_TITLE}'
        $script:resultForm.StartPosition = 'CenterScreen'
        $script:resultForm.ClientSize = '760,430'
        $resultBox = New-Object System.Windows.Forms.TextBox
        $resultBox.AccessibleName = '{RESULT_NAME}'
        $resultBox.Multiline = $true
        $resultBox.ReadOnly = $true
        $resultBox.Location = '55,70'
        $resultBox.Size = '570,250'
        $resultBox.Font = 'Segoe UI,12'
        if ($mismatch) {{
            $resultBox.Text = '错误保存内容-' + [Guid]::NewGuid().ToString('N').Substring(0,8)
        }} else {{
            $resultBox.Text = $saved
        }}
        $noise = New-Object System.Windows.Forms.TextBox
        $noise.AccessibleName = '状态备注'
        $noise.ReadOnly = $true
        $noise.Location = '55,345'
        $noise.Size = '300,30'
        $noise.Text = '保存完成'
        $close = New-Object System.Windows.Forms.Button
        $close.AccessibleName = '关闭'
        $close.Text = '关闭'
        $close.Location = '630,345'
        $close.Size = '90,35'
        $script:resultForm.Controls.AddRange(@($resultBox, $noise, $close))
        $script:resultForm.Add_Shown({{ $script:resultForm.Activate(); $resultBox.Focus() }})
        $script:resultForm.Show()
        $script:resultForm.Activate()
    }})
    $sourceForm.Controls.Add($script:workBox)
    $sourceForm.Controls.Add($script:saveButton)
}}

Add-WorkControls
if ($ambiguous) {{
    $dup = New-Object System.Windows.Forms.TextBox
    $dup.AccessibleName = '{FIELD_NAME}'
    $dup.Multiline = $true
    $dup.Location = '55,390'
    $dup.Size = '450,60'
    $dup.Text = '第二个同名字段'
    $sourceForm.Controls.Add($dup)
}}
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 70
$timer.Add_Tick({{
    if (Test-Path -LiteralPath $recreateFlag) {{
        Remove-Item -LiteralPath $recreateFlag -Force -ErrorAction SilentlyContinue
        if ($script:workBox -ne $null) {{
            $oldText = $script:workBox.Text
            $sourceForm.Controls.Remove($script:workBox)
            $script:workBox.Dispose()
            $script:workBox = New-Object System.Windows.Forms.TextBox
            $script:workBox.AccessibleName = '{FIELD_NAME}'
            $script:workBox.Multiline = $true
            $script:workBox.ScrollBars = 'Vertical'
            $script:workBox.Location = '55,90'
            $script:workBox.Size = '560,290'
            $script:workBox.Font = 'Segoe UI,12'
            $script:workBox.Text = $oldText
            $sourceForm.Controls.Add($script:workBox)
            $script:workBox.CreateControl()
            $cancel.Focus()
        }}
    }}
    if (Test-Path -LiteralPath $driftFlag) {{
        Remove-Item -LiteralPath $driftFlag -Force -ErrorAction SilentlyContinue
        $script:workBox.Text = '{drift_value}'
        $cancel.Focus()
    }}
}})
$timer.Start()
$sourceForm.Add_Shown({{ $cancel.Focus() }})
[System.Windows.Forms.Application]::Run($sourceForm)
'''
