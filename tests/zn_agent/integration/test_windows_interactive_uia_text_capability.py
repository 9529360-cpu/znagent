from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from ctypes import wintypes
from pathlib import Path

from zn_agent.core.automation_text_state_sense import NativeFocusedAutomationTextSense
from zn_agent.core.focused_text_sense import NativeFocusedTextSense
from zn_agent.core.provider_bridge import build_resident_runtime


class _WpfTextFixture:
    TITLE = "ZN UIA Text Capability Contract"
    AUTOMATION_ID = "zn-wpf-text-target"
    TEXT = "ZN WPF capability marker"

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.process: subprocess.Popen[str] | None = None
        self.hwnd = 0

    def start(self) -> None:
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            raise RuntimeError("Windows PowerShell is required for the WPF UIA fixture")
        root = Path(self._tmp.name)
        script = root / "wpf-text-fixture.ps1"
        ready = root / "wpf-text-ready.txt"
        script.write_text(
            f"""param(
  [Parameter(Mandatory = $true)]
  [string]$ReadyPath
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework
$window = New-Object System.Windows.Window
$window.Title = '{self.TITLE}'
$window.Width = 760
$window.Height = 320
$window.WindowStartupLocation = 'CenterScreen'
$text = New-Object System.Windows.Controls.TextBox
$text.Text = '{self.TEXT}'
$text.FontSize = 22
$text.MinWidth = 520
$text.MinHeight = 56
[System.Windows.Automation.AutomationProperties]::SetAutomationId($text, '{self.AUTOMATION_ID}')
$window.Content = $text
$window.Topmost = $true
$window.Add_ContentRendered({{
  [void]$window.Activate()
  [void]$text.Focus()
  [void][System.Windows.Input.Keyboard]::Focus($text)
  $helper = New-Object System.Windows.Interop.WindowInteropHelper($window)
  $hwnd = [long]$helper.Handle
  if ($hwnd -eq 0) {{
    throw 'WPF fixture rendered without a native window handle'
  }}
  $processId = [System.Diagnostics.Process]::GetCurrentProcess().Id
  Set-Content -LiteralPath $ReadyPath -Value "$processId|$hwnd" -Encoding ASCII -NoNewline
  $window.Topmost = $false
}})
[void]$window.ShowDialog()
""",
            encoding="utf-8",
        )
        self.process = subprocess.Popen(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Sta",
                "-File",
                str(script),
                "-ReadyPath",
                str(ready),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                stdout, stderr = self.process.communicate(timeout=1.0)
                raise RuntimeError(
                    "WPF text fixture exited before publishing rendered-window evidence: "
                    f"stdout={stdout!r} stderr={stderr!r}"
                )
            if ready.is_file():
                evidence = ready.read_text(encoding="ascii").strip()
                try:
                    pid_text, hwnd_text = evidence.split("|", 1)
                    evidence_pid = int(pid_text)
                    hwnd = int(hwnd_text)
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        f"WPF text fixture published invalid rendered-window evidence: {evidence!r}"
                    ) from exc
                if evidence_pid != self.process.pid or hwnd <= 0 or not user32.IsWindow(hwnd):
                    raise RuntimeError(
                        "WPF text fixture rendered-window evidence did not identify its live process/window: "
                        f"expected_pid={self.process.pid} evidence={evidence!r}"
                    )
                owner_pid = wintypes.DWORD()
                if not user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid)):
                    raise RuntimeError("WPF text fixture rendered HWND has no owning window thread")
                if int(owner_pid.value) != self.process.pid:
                    raise RuntimeError(
                        "WPF text fixture rendered HWND belongs to another process: "
                        f"expected_pid={self.process.pid} actual_pid={owner_pid.value}"
                    )
                self.hwnd = hwnd
                user32.ShowWindow(hwnd, 5)
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                return
            time.sleep(0.05)
        raise RuntimeError(
            "WPF text fixture process stayed alive but did not publish rendered-window evidence in time"
        )

    def close(self) -> None:
        try:
            if os.name == "nt" and self.hwnd:
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.PostMessageW.argtypes = [
                    wintypes.HWND,
                    wintypes.UINT,
                    wintypes.WPARAM,
                    wintypes.LPARAM,
                ]
                user32.PostMessageW.restype = wintypes.BOOL
                user32.PostMessageW(self.hwnd, 0x0010, 0, 0)  # WM_CLOSE
            if self.process is not None:
                try:
                    self.process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=2.0)
        finally:
            if self.process is not None:
                for stream in (self.process.stdout, self.process.stderr):
                    if stream is not None:
                        stream.close()
            self._tmp.cleanup()


class WindowsInteractiveUiATextCapabilityContractTests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        if os.name != "nt":
            raise unittest.SkipTest("Windows interactive UIA text Contract runs only on Windows")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.OpenInputDesktop.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        user32.OpenInputDesktop.restype = wintypes.HANDLE
        user32.SwitchDesktop.argtypes = [wintypes.HANDLE]
        user32.SwitchDesktop.restype = wintypes.BOOL
        user32.CloseDesktop.argtypes = [wintypes.HANDLE]
        user32.CloseDesktop.restype = wintypes.BOOL
        desktop = user32.OpenInputDesktop(0, False, 0x0001 | 0x0080 | 0x0100)
        if not desktop:
            raise AssertionError(
                "GitHub runner process cannot open the Windows input desktop; "
                "interactive UIA text Contract requires an unlocked interactive user session"
            )
        try:
            if not user32.SwitchDesktop(desktop):
                raise AssertionError(
                    "GitHub runner process cannot switch to the Windows input desktop"
                )
        finally:
            user32.CloseDesktop(desktop)

    def test_real_resident_identifies_non_native_wpf_text_capability(self) -> None:
        self._require_input_desktop()
        fixture = _WpfTextFixture()
        resident = None
        try:
            fixture.start()
            with tempfile.TemporaryDirectory() as tmp:
                resident = build_resident_runtime(
                    config={"model": {}},
                    store_path=Path(tmp) / "kernel.db",
                )
                try:
                    self.assertTrue(hasattr(resident, "automation_text_state"))
                    deadline = time.monotonic() + 6.0
                    focused = None
                    text_state = None
                    last_error = None
                    while time.monotonic() < deadline:
                        try:
                            foreground = resident.foreground_window.probe()
                            candidate = resident.automation_element.probe_focused()
                            state_candidate = resident.automation_text_state.probe()
                            if (
                                foreground.title == fixture.TITLE
                                and fixture.process is not None
                                and foreground.process_id == fixture.process.pid
                                and candidate.process_id == fixture.process.pid
                                and state_candidate.process_id == fixture.process.pid
                                and candidate.automation_id == fixture.AUTOMATION_ID
                                and state_candidate.automation_id == fixture.AUTOMATION_ID
                                and candidate.has_keyboard_focus
                                and state_candidate.has_keyboard_focus
                                and tuple(candidate.runtime_id) == tuple(state_candidate.runtime_id)
                            ):
                                focused = candidate
                                text_state = state_candidate
                                break
                        except Exception as exc:
                            last_error = exc
                        time.sleep(0.05)
                    if focused is None or text_state is None:
                        raise AssertionError(
                            "resident did not observe the focused WPF TextBox current state in time; "
                            f"last_error={last_error!r}"
                        )

                    self.assertEqual(focused.control_type, 50004)  # UIA_EditControlTypeId
                    self.assertEqual(focused.native_window_handle, 0)
                    self.assertTrue(focused.is_enabled)
                    self.assertTrue(focused.is_keyboard_focusable)
                    self.assertFalse(focused.is_offscreen)
                    self.assertFalse(focused.is_password)
                    self.assertTrue(focused.is_value_pattern_available)
                    self.assertTrue(focused.is_text_pattern_available)
                    self.assertFalse(focused.value_is_read_only)
                    self.assertFalse(hasattr(focused, "value"))
                    self.assertFalse(hasattr(focused, "text"))
                    self.assertFalse(hasattr(focused, "name"))

                    self.assertEqual(text_state.control_type, 50004)
                    self.assertEqual(text_state.native_window_handle, 0)
                    self.assertFalse(text_state.is_password)
                    self.assertTrue(text_state.is_value_pattern_available)
                    self.assertFalse(text_state.value_is_read_only)
                    self.assertEqual(text_state.text_length, len(fixture.TEXT))
                    self.assertEqual(
                        text_state.text_sha256,
                        NativeFocusedAutomationTextSense.digest_text(fixture.TEXT),
                    )
                    self.assertFalse(hasattr(text_state, "text"))
                    self.assertFalse(hasattr(text_state, "value"))

                    with self.assertRaises((RuntimeError, ValueError)):
                        NativeFocusedTextSense().probe()
                finally:
                    resident.store.close()
                    resident = None
        finally:
            if resident is not None:
                resident.store.close()
            fixture.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
