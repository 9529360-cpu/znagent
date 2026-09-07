from __future__ import annotations

import ctypes
import os
import threading
import time
import unittest
from ctypes import wintypes

from zn_agent.core.automation_element_sense import NativeAutomationElementSense
from zn_agent.core.foreground_window_sense import NativeForegroundWindowSense
from zn_agent.core.local_perception_grounding import LocalGroundingLevel, LocalPerceptionGrounder
from zn_agent.core.visual_ocr_sense import WindowsLocalOcrSense


class _Win32OcrFixture:
    TITLE = "ZN Local OCR Interactive E2E"
    TEXT = "ZNAGENT OCR TEST"
    LABEL_ID = 4101

    def __init__(self) -> None:
        self.ready = threading.Event()
        self.error: BaseException | None = None
        self.hwnd = 0
        self.label_hwnd = 0
        self.font_handle = 0
        self.previous_foreground_hwnd = 0
        self._thread = threading.Thread(
            target=self._run,
            name="zn-local-ocr-e2e-window",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()
        if not self.ready.wait(5.0):
            raise RuntimeError("local OCR fixture did not initialize in time")
        if self.error is not None:
            raise RuntimeError(
                f"local OCR fixture failed: {type(self.error).__name__}: {self.error}"
            )
        if not self.hwnd or not self.label_hwnd or not self._thread.native_id:
            raise RuntimeError("local OCR fixture did not expose window/thread handles")

    def activate(self) -> None:
        """Temporarily attach input queues and make the owned fixture foreground."""

        if os.name != "nt" or not self.hwnd or not self._thread.native_id:
            raise RuntimeError("local OCR fixture is not active on Windows")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        user32.AttachThreadInput.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.SetFocus.restype = wintypes.HWND
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        foreground = int(user32.GetForegroundWindow() or 0)
        if foreground and not self.previous_foreground_hwnd:
            self.previous_foreground_hwnd = foreground
        foreground_tid = int(
            user32.GetWindowThreadProcessId(wintypes.HWND(foreground), None)
            if foreground
            else 0
        )
        current_tid = int(kernel32.GetCurrentThreadId())
        fixture_tid = int(self._thread.native_id)
        attached: list[tuple[int, int]] = []

        def attach(source: int, target: int) -> None:
            if not source or not target or source == target:
                return
            if user32.AttachThreadInput(source, target, True):
                attached.append((source, target))

        try:
            # The test thread performs USER calls and has a message queue. Attach
            # both it and the fixture UI thread to the current foreground queue.
            # This is the documented mechanism for sharing focus/input state.
            attach(current_tid, foreground_tid)
            attach(fixture_tid, foreground_tid)
            attach(current_tid, fixture_tid)
            user32.ShowWindow(self.hwnd, 9)  # SW_RESTORE
            flags = 0x0001 | 0x0002 | 0x0040  # NOSIZE | NOMOVE | SHOWWINDOW
            if not user32.SetWindowPos(
                self.hwnd,
                wintypes.HWND(-1),  # HWND_TOPMOST
                0,
                0,
                0,
                0,
                flags,
            ):
                raise OSError(
                    f"SetWindowPos(HWND_TOPMOST) failed with WinError {ctypes.get_last_error()}"
                )
            user32.BringWindowToTop(self.hwnd)
            user32.SetForegroundWindow(self.hwnd)
            user32.SetFocus(self.label_hwnd)
        finally:
            for source, target in reversed(attached):
                user32.AttachThreadInput(source, target, False)

    def restore_previous_foreground(self) -> None:
        previous = int(self.previous_foreground_hwnd or 0)
        if not previous or previous == self.hwnd or os.name != "nt":
            return
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        if not user32.IsWindow(previous):
            return
        try:
            self._activate_external_window(previous)
        except Exception:
            pass

    @staticmethod
    def _activate_external_window(hwnd: int) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        user32.AttachThreadInput.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        current = int(kernel32.GetCurrentThreadId())
        foreground = int(user32.GetForegroundWindow() or 0)
        foreground_tid = int(
            user32.GetWindowThreadProcessId(wintypes.HWND(foreground), None)
            if foreground
            else 0
        )
        target_tid = int(user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), None))
        attached: list[tuple[int, int]] = []
        for source, target in ((current, foreground_tid), (current, target_tid)):
            if source and target and source != target and user32.AttachThreadInput(source, target, True):
                attached.append((source, target))
        try:
            user32.SetWindowPos(hwnd, wintypes.HWND(-2), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
            user32.SetForegroundWindow(hwnd)
        finally:
            for source, target in reversed(attached):
                user32.AttachThreadInput(source, target, False)

    def close(self) -> None:
        self.restore_previous_foreground()
        if os.name == "nt" and self.hwnd:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.PostMessageW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            user32.PostMessageW.restype = wintypes.BOOL
            user32.PostMessageW(self.hwnd, 0x0010, 0, 0)
            if self._thread.native_id:
                user32.PostThreadMessageW(int(self._thread.native_id), 0x0012, 0, 0)
        self._thread.join(timeout=3.0)

    def label_center(self) -> tuple[int, int]:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        rect = wintypes.RECT()
        if not user32.GetWindowRect(self.label_hwnd, ctypes.byref(rect)):
            raise OSError("GetWindowRect failed for local OCR label")
        return (
            (int(rect.left) + int(rect.right)) // 2,
            (int(rect.top) + int(rect.bottom)) // 2,
        )

    @staticmethod
    def screen_size() -> tuple[int, int]:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.restype = ctypes.c_int
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))

    def _run(self) -> None:
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.SendMessageW.restype = ctypes.c_ssize_t
            user32.GetMessageW.restype = wintypes.BOOL
            gdi32.CreateFontW.restype = wintypes.HANDLE

            WS_OVERLAPPEDWINDOW = 0x00CF0000
            WS_VISIBLE = 0x10000000
            WS_CHILD = 0x40000000
            SS_CENTER = 0x00000001
            instance = kernel32.GetModuleHandleW(None)
            self.hwnd = int(
                user32.CreateWindowExW(
                    0,
                    "STATIC",
                    self.TITLE,
                    WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                    120,
                    120,
                    760,
                    420,
                    None,
                    None,
                    instance,
                    None,
                )
                or 0
            )
            self.label_hwnd = int(
                user32.CreateWindowExW(
                    0,
                    "STATIC",
                    self.TEXT,
                    WS_CHILD | WS_VISIBLE | SS_CENTER,
                    90,
                    120,
                    560,
                    110,
                    self.hwnd,
                    wintypes.HMENU(self.LABEL_ID),
                    instance,
                    None,
                )
                or 0
            )
            if not self.hwnd or not self.label_hwnd:
                raise OSError("CreateWindowExW failed for local OCR fixture")
            self.font_handle = int(
                gdi32.CreateFontW(48, 0, 0, 0, 700, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI") or 0
            )
            if not self.font_handle:
                raise OSError("CreateFontW failed for local OCR fixture")
            user32.SendMessageW(self.label_hwnd, 0x0030, self.font_handle, 1)  # WM_SETFONT
            user32.ShowWindow(self.hwnd, 5)
            user32.UpdateWindow(self.hwnd)
            self.ready.set()
            message = wintypes.MSG()
            while True:
                status = int(user32.GetMessageW(ctypes.byref(message), None, 0, 0))
                if status <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except BaseException as exc:
            self.error = exc
            self.ready.set()
        finally:
            if self.font_handle:
                try:
                    ctypes.windll.gdi32.DeleteObject(self.font_handle)
                except Exception:
                    pass
            if self.hwnd:
                try:
                    ctypes.windll.user32.DestroyWindow(self.hwnd)
                except Exception:
                    pass


class _ForbiddenOcr:
    def probe(self, **kwargs):
        raise AssertionError("OCR must not run when real UIA already grounded the point")


class WindowsInteractiveLocalOcrE2ETests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        if os.name != "nt":
            raise unittest.SkipTest("Windows interactive local OCR E2E runs only on Windows")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetProcessDPIAware()
        user32.OpenInputDesktop.restype = wintypes.HANDLE
        desktop = user32.OpenInputDesktop(0, False, 0x0001 | 0x0080 | 0x0100)
        if not desktop:
            raise AssertionError("local OCR E2E requires an unlocked Windows input desktop")
        try:
            if not user32.SwitchDesktop(desktop):
                raise AssertionError("runner cannot switch to the Windows input desktop")
        finally:
            user32.CloseDesktop(desktop)

    @staticmethod
    def _wait_for_foreground(fixture: _Win32OcrFixture, timeout: float = 5.0):
        sense = NativeForegroundWindowSense()
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            fixture.activate()
            time.sleep(0.05)
            try:
                last = sense.probe()
            except Exception:
                last = None
            if last is not None and last.title == fixture.TITLE:
                return last
        raise AssertionError(f"fixture did not become foreground; last={last!r}")

    def test_real_windows_media_ocr_reads_owned_native_fixture(self) -> None:
        self._require_input_desktop()
        fixture = _Win32OcrFixture()
        fixture.start()
        try:
            foreground = self._wait_for_foreground(fixture)
            self.assertEqual(foreground.process_id, os.getpid())
            center_x, center_y = fixture.label_center()
            screen_width, screen_height = fixture.screen_size()
            observation = WindowsLocalOcrSense().probe(
                center_x_fraction=round((center_x + 0.5) / screen_width, 6),
                center_y_fraction=round((center_y + 0.5) / screen_height, 6),
                width_fraction=0.36,
                height_fraction=0.18,
            )
            compact = "".join(ch for ch in observation.text.upper() if ch.isalnum())
            compact += "".join(
                ch for word in observation.words for ch in word.text.upper() if ch.isalnum()
            )
            self.assertIn("ZNAGENT", compact, f"real Windows OCR missed fixture token: {observation!r}")
            self.assertEqual(observation.source, "windows-media-ocr")
            self.assertFalse(observation.raw_frame_persisted)
            self.assertGreater(len(observation.words), 0)
        finally:
            fixture.close()

    def test_real_uia_short_circuits_local_ocr_in_perception_chain(self) -> None:
        self._require_input_desktop()
        fixture = _Win32OcrFixture()
        fixture.start()
        try:
            self._wait_for_foreground(fixture)
            center_x, center_y = fixture.label_center()
            screen_width, screen_height = fixture.screen_size()
            result = LocalPerceptionGrounder(
                foreground=NativeForegroundWindowSense(),
                automation=NativeAutomationElementSense(),
                ocr=_ForbiddenOcr(),
            ).ground_point(
                x=center_x,
                y=center_y,
                screen_width=screen_width,
                screen_height=screen_height,
            )
            self.assertEqual(result.level, LocalGroundingLevel.UIA)
            self.assertIsNotNone(result.automation)
            assert result.automation is not None
            self.assertEqual(result.automation.process_id, os.getpid())
            self.assertIsNone(result.ocr)
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()
