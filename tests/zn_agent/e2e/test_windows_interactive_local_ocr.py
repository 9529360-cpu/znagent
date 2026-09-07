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
        if not self.hwnd or not self.label_hwnd:
            raise RuntimeError("local OCR fixture did not expose window handles")

    def close(self) -> None:
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
                user32.PostThreadMessageW(
                    int(self._thread.native_id),
                    0x0012,
                    0,
                    0,
                )
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
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD,
                wintypes.LPCWSTR,
                wintypes.LPCWSTR,
                wintypes.DWORD,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.HWND,
                wintypes.HMENU,
                wintypes.HINSTANCE,
                wintypes.LPVOID,
            ]
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.SendMessageW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            user32.SendMessageW.restype = ctypes.c_ssize_t
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.UpdateWindow.argtypes = [wintypes.HWND]
            user32.BringWindowToTop.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.GetMessageW.argtypes = [
                ctypes.POINTER(wintypes.MSG),
                wintypes.HWND,
                wintypes.UINT,
                wintypes.UINT,
            ]
            user32.GetMessageW.restype = wintypes.BOOL
            user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.DestroyWindow.argtypes = [wintypes.HWND]
            gdi32.CreateFontW.restype = wintypes.HANDLE
            gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
            gdi32.DeleteObject.restype = wintypes.BOOL

            WS_OVERLAPPEDWINDOW = 0x00CF0000
            WS_VISIBLE = 0x10000000
            WS_CHILD = 0x40000000
            SS_CENTER = 0x00000001
            WM_SETFONT = 0x0030
            FW_BOLD = 700

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
            if not self.hwnd:
                raise OSError("CreateWindowExW failed for local OCR fixture")
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
            if not self.label_hwnd:
                raise OSError("CreateWindowExW failed for local OCR label")

            self.font_handle = int(
                gdi32.CreateFontW(
                    48,
                    0,
                    0,
                    0,
                    FW_BOLD,
                    0,
                    0,
                    0,
                    1,
                    0,
                    0,
                    5,
                    0,
                    "Segoe UI",
                )
                or 0
            )
            if not self.font_handle:
                raise OSError("CreateFontW failed for local OCR fixture")
            user32.SendMessageW(self.label_hwnd, WM_SETFONT, self.font_handle, 1)
            user32.ShowWindow(self.hwnd, 5)
            user32.UpdateWindow(self.hwnd)
            user32.BringWindowToTop(self.hwnd)
            user32.SetForegroundWindow(self.hwnd)
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
        user32.SetProcessDPIAware.argtypes = []
        user32.SetProcessDPIAware.restype = wintypes.BOOL
        user32.SetProcessDPIAware()
        user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        user32.OpenInputDesktop.restype = wintypes.HANDLE
        user32.SwitchDesktop.argtypes = [wintypes.HANDLE]
        user32.SwitchDesktop.restype = wintypes.BOOL
        user32.CloseDesktop.argtypes = [wintypes.HANDLE]
        user32.CloseDesktop.restype = wintypes.BOOL
        desktop = user32.OpenInputDesktop(0, False, 0x0001 | 0x0080 | 0x0100)
        if not desktop:
            raise AssertionError(
                "local OCR E2E requires an unlocked Windows interactive input desktop"
            )
        try:
            if not user32.SwitchDesktop(desktop):
                raise AssertionError("runner cannot switch to the Windows input desktop")
        finally:
            user32.CloseDesktop(desktop)

    @staticmethod
    def _wait_for_foreground(title: str, timeout: float = 4.0):
        sense = NativeForegroundWindowSense()
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            try:
                last = sense.probe()
            except Exception:
                last = None
            if last is not None and last.title == title:
                return last
            time.sleep(0.05)
        raise AssertionError(f"fixture did not become foreground; last={last!r}")

    def test_real_windows_media_ocr_reads_owned_native_fixture(self) -> None:
        self._require_input_desktop()
        fixture = _Win32OcrFixture()
        fixture.start()
        try:
            foreground = self._wait_for_foreground(fixture.TITLE)
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
            if "ZNAGENT" not in compact:
                word_compact = "".join(
                    ch
                    for word in observation.words
                    for ch in word.text.upper()
                    if ch.isalnum()
                )
                compact += word_compact
            self.assertIn(
                "ZNAGENT",
                compact,
                f"real Windows OCR did not recover fixture token: {observation!r}",
            )
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
            self._wait_for_foreground(fixture.TITLE)
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
