from __future__ import annotations

import ctypes
import os
import tempfile
import threading
import time
import unittest
import uuid
from ctypes import wintypes
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime


class _OwnedForegroundFixture:
    """Tiny ZN-owned Win32 window used only to put the target app in background."""

    WM_CLOSE = 0x0010
    WM_DESTROY = 0x0002
    SW_SHOW = 5
    WS_OVERLAPPEDWINDOW = 0x00CF0000

    def __init__(self) -> None:
        self.hwnd = 0
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._class_name = f"ZNApplicationActivationFixture-{uuid.uuid4().hex}"
        self._wndproc = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()
        if not self._ready.wait(5.0):
            raise AssertionError("ZN fixture window did not initialize")
        if self._error is not None:
            raise AssertionError(f"ZN fixture window failed: {self._error}")
        if not self.hwnd:
            raise AssertionError("ZN fixture window did not expose an HWND")

    def activate_once(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        accepted = bool(user32.SetForegroundWindow(int(self.hwnd)))
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if int(user32.GetForegroundWindow() or 0) == int(self.hwnd):
                return
            time.sleep(0.05)
        raise AssertionError(
            "ZN-owned fixture did not become foreground; "
            f"SetForegroundWindow returned {accepted}"
        )

    def close(self) -> None:
        if self.hwnd:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.PostMessageW.restype = wintypes.BOOL
            user32.PostMessageW(int(self.hwnd), self.WM_CLOSE, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self.hwnd = 0

    def _thread_main(self) -> None:
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )

            class WNDCLASSW(ctypes.Structure):
                _fields_ = [
                    ("style", wintypes.UINT),
                    ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HANDLE),
                    ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HANDLE),
                    ("lpszMenuName", wintypes.LPCWSTR),
                    ("lpszClassName", wintypes.LPCWSTR),
                ]

            user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.DefWindowProcW.restype = ctypes.c_ssize_t
            user32.DestroyWindow.argtypes = [wintypes.HWND]
            user32.DestroyWindow.restype = wintypes.BOOL
            user32.PostQuitMessage.argtypes = [ctypes.c_int]
            user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
            user32.RegisterClassW.restype = wintypes.WORD
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
                wintypes.HANDLE,
                wintypes.HINSTANCE,
                wintypes.LPVOID,
            ]
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL
            user32.UpdateWindow.argtypes = [wintypes.HWND]
            user32.UpdateWindow.restype = wintypes.BOOL
            user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
            user32.GetMessageW.restype = wintypes.BOOL
            user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.TranslateMessage.restype = wintypes.BOOL
            user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.DispatchMessageW.restype = ctypes.c_ssize_t
            user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
            user32.UnregisterClassW.restype = wintypes.BOOL
            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE

            @WNDPROC
            def wndproc(hwnd, message, wparam, lparam):
                if message == self.WM_CLOSE:
                    user32.DestroyWindow(hwnd)
                    return 0
                if message == self.WM_DESTROY:
                    user32.PostQuitMessage(0)
                    return 0
                return user32.DefWindowProcW(hwnd, message, wparam, lparam)

            self._wndproc = wndproc
            instance = kernel32.GetModuleHandleW(None)
            window_class = WNDCLASSW()
            window_class.lpfnWndProc = wndproc
            window_class.hInstance = instance
            window_class.lpszClassName = self._class_name
            if not user32.RegisterClassW(ctypes.byref(window_class)):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                hwnd = user32.CreateWindowExW(
                    0,
                    self._class_name,
                    "ZN Application Activation Fixture",
                    self.WS_OVERLAPPEDWINDOW,
                    40,
                    40,
                    360,
                    180,
                    None,
                    None,
                    instance,
                    None,
                )
                if not hwnd:
                    raise ctypes.WinError(ctypes.get_last_error())
                self.hwnd = int(hwnd)
                user32.ShowWindow(hwnd, self.SW_SHOW)
                user32.UpdateWindow(hwnd)
                self._ready.set()
                message = wintypes.MSG()
                while True:
                    status = int(user32.GetMessageW(ctypes.byref(message), None, 0, 0))
                    if status == -1:
                        raise ctypes.WinError(ctypes.get_last_error())
                    if status == 0:
                        break
                    user32.TranslateMessage(ctypes.byref(message))
                    user32.DispatchMessageW(ctypes.byref(message))
            finally:
                user32.UnregisterClassW(self._class_name, instance)
        except BaseException as exc:
            self._error = exc
            self._ready.set()


class WindowsInteractiveApplicationActivationE2ETests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        if os.name != "nt":
            raise unittest.SkipTest("Windows application activation E2E runs only on Windows")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        user32.OpenInputDesktop.restype = wintypes.HANDLE
        user32.SwitchDesktop.argtypes = [wintypes.HANDLE]
        user32.SwitchDesktop.restype = wintypes.BOOL
        user32.CloseDesktop.argtypes = [wintypes.HANDLE]
        user32.CloseDesktop.restype = wintypes.BOOL
        desktop = user32.OpenInputDesktop(0, False, 0x0001 | 0x0080 | 0x0100)
        if not desktop:
            raise AssertionError("zn-interactive runner cannot open the Windows input desktop")
        try:
            if not user32.SwitchDesktop(desktop):
                raise AssertionError("zn-interactive runner cannot switch to the Windows input desktop")
        finally:
            user32.CloseDesktop(desktop)

    @staticmethod
    def _run_to_terminal(resident, limit: int = 50):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
            time.sleep(0.10)
        raise AssertionError("resident did not reach a terminal result within bounded pulses")

    @staticmethod
    def _foreground_hwnd() -> int:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        return int(user32.GetForegroundWindow() or 0)

    @staticmethod
    def _restore_foreground_once(hwnd: int) -> None:
        if not hwnd:
            return
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        if user32.IsWindow(int(hwnd)):
            user32.SetForegroundWindow(int(hwnd))

    @staticmethod
    def _close_created_windows(windows, created_pids: set[int]) -> None:
        if not created_pids:
            return
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW.restype = wintypes.BOOL
        for window in windows:
            if int(window.process_id) in created_pids:
                user32.PostMessageW(int(window.hwnd), 0x0010, 0, 0)

    @staticmethod
    def _wait_for_single_window(graph, application):
        stable = None
        count = 0
        latest = ((), ())
        for _ in range(30):
            processes, windows = graph.application_runtime(application)
            latest = (processes, windows)
            visible = tuple(window for window in windows if window.visible)
            if len(visible) > 1:
                return None, processes, windows
            if processes and len(visible) == 1:
                key = (visible[0].hwnd, visible[0].process_id, tuple(row.process_id for row in processes))
                count = count + 1 if key == stable else 1
                stable = key
                if count >= 3:
                    return visible[0], processes, windows
            else:
                stable = None
                count = 0
            time.sleep(0.10)
        return None, latest[0], latest[1]

    @staticmethod
    def _actions(resident, kind: str, app_id: str):
        return [
            action for action in resident.body.recent_actions(100)
            if action.kind == kind and action.data.get("application_id") == app_id
        ]

    def test_existing_background_application_is_activated_without_duplicate_launch(self) -> None:
        self._require_input_desktop()
        original_foreground = self._foreground_hwnd()
        fixture = None
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            resident = build_resident_runtime(
                config={"model": {}}, store_path=Path(tmp) / "kernel.db"
            )
            selected = None
            selected_window = None
            created_pids: set[int] = set()
            diagnostics: list[str] = []
            try:
                graph = resident.device_capabilities
                for name in ("Notepad", "Microsoft Paint", "Command Prompt", "Windows Terminal"):
                    resolution = graph.resolve_application(name, force_refresh=True)
                    if resolution.status != "resolved" or resolution.application is None:
                        diagnostics.append(f"{name}:resolution={resolution.status}")
                        continue
                    candidate = resolution.application
                    if not candidate.launchable:
                        diagnostics.append(f"{name}:not-launchable")
                        continue
                    before_processes, before_windows = graph.application_runtime(candidate)
                    if before_processes or before_windows:
                        diagnostics.append(f"{name}:already-running")
                        continue
                    resident.enqueue(
                        f"打开 {candidate.canonical_name}", kind="desktop_user_event",
                        payload={"model_policy": "never"},
                    )
                    first = self._run_to_terminal(resident)
                    if not first.success:
                        diagnostics.append(f"{name}:launch-failed={first.reason}")
                        continue
                    self.assertEqual(first.model_invocations, 0)
                    window, processes, windows = self._wait_for_single_window(graph, candidate)
                    new_pids = {row.process_id for row in processes}
                    if window is None or not new_pids:
                        self._close_created_windows(windows, new_pids)
                        diagnostics.append(f"{name}:no-stable-single-window")
                        time.sleep(0.20)
                        continue
                    selected = candidate
                    selected_window = window
                    created_pids = new_pids
                    break

                self.assertIsNotNone(
                    selected,
                    "zn-interactive needs one discovered benign launchable app with one stable window; "
                    + "; ".join(diagnostics),
                )
                assert selected is not None and selected_window is not None
                before_second_processes, _ = graph.application_runtime(selected)
                first_pids = {row.process_id for row in before_second_processes}
                exact_hwnd = int(selected_window.hwnd)
                exact_pid = int(selected_window.process_id)
                self.assertIn(exact_pid, first_pids)

                launch_before = self._actions(resident, "launch_application", selected.app_id)
                self.assertEqual(len([a for a in launch_before if a.data.get("dispatch_sent")]), 1)

                fixture = _OwnedForegroundFixture()
                fixture.start()
                fixture.activate_once()
                self.assertEqual(self._foreground_hwnd(), fixture.hwnd)
                background_processes, background_windows = graph.application_runtime(selected)
                self.assertEqual({row.process_id for row in background_processes}, first_pids)
                target = next(window for window in background_windows if window.hwnd == exact_hwnd)
                self.assertTrue(target.visible)
                self.assertFalse(target.foreground)

                resident.enqueue(
                    f"打开 {selected.canonical_name}", kind="desktop_user_event",
                    payload={"model_policy": "never"},
                )
                second = self._run_to_terminal(resident)
                self.assertTrue(second.success, second)
                self.assertEqual(second.model_invocations, 0)

                after_processes, after_windows = graph.application_runtime(selected)
                self.assertEqual({row.process_id for row in after_processes}, first_pids)
                target_after = next(window for window in after_windows if window.hwnd == exact_hwnd)
                self.assertTrue(target_after.foreground)
                self.assertEqual(self._foreground_hwnd(), exact_hwnd)
                foreground = graph.foreground_application()
                self.assertIsNotNone(foreground)
                self.assertEqual(foreground.window.hwnd, exact_hwnd)
                self.assertEqual(foreground.window.process_id, exact_pid)
                self.assertEqual(foreground.window.resolved_app_id, selected.app_id)
                self.assertIsNotNone(foreground.application)
                self.assertEqual(foreground.application.app_id, selected.app_id)

                launch_after = self._actions(resident, "launch_application", selected.app_id)
                activation = self._actions(resident, "activate_application_window", selected.app_id)
                self.assertEqual(len(launch_after), len(launch_before))
                self.assertEqual(len([a for a in launch_after if a.data.get("dispatch_sent")]), 1)
                self.assertEqual(len(activation), 1)
                self.assertTrue(activation[0].data.get("dispatch_sent"))
                self.assertEqual(activation[0].data.get("window_handle"), exact_hwnd)
                self.assertEqual(activation[0].data.get("process_id"), exact_pid)
            finally:
                if fixture is not None:
                    fixture.close()
                if selected is not None:
                    _, windows = resident.device_capabilities.application_runtime(selected)
                    self._close_created_windows(windows, created_pids)
                    time.sleep(0.20)
                self._restore_foreground_once(original_foreground)
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
