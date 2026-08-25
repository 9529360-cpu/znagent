from __future__ import annotations

import ctypes
import os
import tempfile
import threading
import time
import unittest
from ctypes import wintypes
from pathlib import Path

from zn_agent.core import ExecutionPath
from zn_agent.core.automation_element_sense import NativeAutomationElementSense
from zn_agent.core.focused_control_sense import NativeFocusedControlSense
from zn_agent.core.foreground_window_sense import NativeForegroundWindowSense
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.visual_region_sense import NativeVisualRegionSense


class _Win32FocusFixture:
    TITLE = "ZN Interactive Desktop E2E"
    SOURCE_CONTROL_ID = 1001
    TARGET_CONTROL_ID = 1002

    def __init__(self) -> None:
        self.ready = threading.Event()
        self.clicked = threading.Event()
        self.error: BaseException | None = None
        self.hwnd = 0
        self.source_hwnd = 0
        self.target_hwnd = 0
        self._class_name = f"ZNInteractiveE2E_{os.getpid()}_{id(self):x}"
        self._thread = threading.Thread(
            target=self._run,
            name="zn-interactive-e2e-window",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()
        if not self.ready.wait(5.0):
            raise RuntimeError("interactive fixture window did not initialize in time")
        if self.error is not None:
            raise RuntimeError(
                f"interactive fixture failed: {type(self.error).__name__}: {self.error}"
            )
        if not self.hwnd or not self.target_hwnd:
            raise RuntimeError("interactive fixture did not expose native window handles")

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
            user32.PostMessageW(self.hwnd, 0x0010, 0, 0)  # WM_CLOSE
        self._thread.join(timeout=3.0)

    def target_center(self) -> tuple[int, int]:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        rect = wintypes.RECT()
        if not user32.GetWindowRect(self.target_hwnd, ctypes.byref(rect)):
            raise OSError("GetWindowRect failed for the E2E target")
        return (
            (int(rect.left) + int(rect.right)) // 2,
            (int(rect.top) + int(rect.bottom)) // 2,
        )

    def _run(self) -> None:
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            lresult_t = ctypes.c_ssize_t
            wndproc_t = ctypes.WINFUNCTYPE(
                lresult_t,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )

            class WNDCLASSEXW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.UINT),
                    ("style", wintypes.UINT),
                    ("lpfnWndProc", wndproc_t),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR),
                    ("lpszClassName", wintypes.LPCWSTR),
                    ("hIconSm", wintypes.HICON),
                ]

            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE
            user32.DefWindowProcW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            user32.DefWindowProcW.restype = lresult_t
            user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
            user32.RegisterClassExW.restype = wintypes.ATOM
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
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL
            user32.UpdateWindow.argtypes = [wintypes.HWND]
            user32.UpdateWindow.restype = wintypes.BOOL
            user32.BringWindowToTop.argtypes = [wintypes.HWND]
            user32.BringWindowToTop.restype = wintypes.BOOL
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow.restype = wintypes.BOOL
            user32.SetFocus.argtypes = [wintypes.HWND]
            user32.SetFocus.restype = wintypes.HWND
            user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
            user32.SetWindowTextW.restype = wintypes.BOOL
            user32.PostQuitMessage.argtypes = [ctypes.c_int]
            user32.GetMessageW.argtypes = [
                ctypes.POINTER(wintypes.MSG),
                wintypes.HWND,
                wintypes.UINT,
                wintypes.UINT,
            ]
            user32.GetMessageW.restype = wintypes.BOOL
            user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.TranslateMessage.restype = wintypes.BOOL
            user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.DispatchMessageW.restype = lresult_t
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

            WM_COMMAND = 0x0111
            WM_DESTROY = 0x0002
            BN_CLICKED = 0
            SWP_NOZORDER = 0x0004
            WS_OVERLAPPEDWINDOW = 0x00CF0000
            WS_VISIBLE = 0x10000000
            WS_CHILD = 0x40000000
            WS_TABSTOP = 0x00010000

            @wndproc_t
            def wndproc(hwnd, message, wparam, lparam):
                if message == WM_COMMAND:
                    control_id = int(wparam) & 0xFFFF
                    notification = (int(wparam) >> 16) & 0xFFFF
                    if (
                        control_id == self.TARGET_CONTROL_ID
                        and notification == BN_CLICKED
                    ):
                        if self.target_hwnd:
                            user32.SetWindowTextW(self.target_hwnd, "Clicked")
                            if not user32.SetWindowPos(
                                self.target_hwnd,
                                None,
                                80,
                                280,
                                200,
                                100,
                                SWP_NOZORDER,
                            ):
                                self.error = OSError("SetWindowPos failed after click")
                            self.clicked.set()
                        return 0
                if message == WM_DESTROY:
                    user32.PostQuitMessage(0)
                    return 0
                return user32.DefWindowProcW(hwnd, message, wparam, lparam)

            self._wndproc = wndproc
            instance = kernel32.GetModuleHandleW(None)
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = wndproc
            wc.hInstance = instance
            wc.hbrBackground = wintypes.HBRUSH(6)  # COLOR_WINDOW + 1
            wc.lpszClassName = self._class_name
            if not user32.RegisterClassExW(ctypes.byref(wc)):
                raise OSError(
                    f"RegisterClassExW failed with WinError {ctypes.get_last_error()}"
                )

            self.hwnd = int(
                user32.CreateWindowExW(
                    0,
                    self._class_name,
                    self.TITLE,
                    WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                    80,
                    80,
                    720,
                    440,
                    None,
                    None,
                    instance,
                    None,
                )
                or 0
            )
            if not self.hwnd:
                raise OSError(
                    f"CreateWindowExW failed with WinError {ctypes.get_last_error()}"
                )

            self.source_hwnd = int(
                user32.CreateWindowExW(
                    0,
                    "BUTTON",
                    "Source",
                    WS_CHILD | WS_VISIBLE | WS_TABSTOP,
                    80,
                    120,
                    200,
                    100,
                    self.hwnd,
                    wintypes.HMENU(self.SOURCE_CONTROL_ID),
                    instance,
                    None,
                )
                or 0
            )
            self.target_hwnd = int(
                user32.CreateWindowExW(
                    0,
                    "BUTTON",
                    "Target",
                    WS_CHILD | WS_VISIBLE | WS_TABSTOP,
                    380,
                    120,
                    200,
                    100,
                    self.hwnd,
                    wintypes.HMENU(self.TARGET_CONTROL_ID),
                    instance,
                    None,
                )
                or 0
            )
            if not self.source_hwnd or not self.target_hwnd:
                raise OSError("CreateWindowExW failed for fixture child controls")

            user32.ShowWindow(self.hwnd, 5)
            user32.UpdateWindow(self.hwnd)
            user32.BringWindowToTop(self.hwnd)
            user32.SetForegroundWindow(self.hwnd)
            user32.SetFocus(self.source_hwnd)
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
            self.clicked.set()


class WindowsInteractivePointerUiAE2ETests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        if os.name != "nt":
            raise unittest.SkipTest("Windows interactive desktop E2E runs only on Windows")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetProcessDPIAware.argtypes = []
        user32.SetProcessDPIAware.restype = wintypes.BOOL
        user32.SetProcessDPIAware()
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
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
        user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        user32.SetCursorPos.restype = wintypes.BOOL
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.restype = ctypes.c_int
        DESKTOP_READOBJECTS = 0x0001
        DESKTOP_WRITEOBJECTS = 0x0080
        DESKTOP_SWITCHDESKTOP = 0x0100
        desktop = user32.OpenInputDesktop(
            0,
            False,
            DESKTOP_READOBJECTS | DESKTOP_WRITEOBJECTS | DESKTOP_SWITCHDESKTOP,
        )
        if not desktop:
            raise AssertionError(
                "GitHub runner process cannot open the Windows input desktop; "
                "interactive E2E requires a runner launched in an unlocked interactive user session"
            )
        try:
            if not user32.SwitchDesktop(desktop):
                raise AssertionError(
                    "GitHub runner process can open but cannot switch to the input desktop; "
                    "interactive E2E is not authoritative in this session"
                )
        finally:
            user32.CloseDesktop(desktop)

        original = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(original)):
            raise AssertionError("interactive E2E cannot read the real Windows cursor")
        width = int(user32.GetSystemMetrics(0))
        height = int(user32.GetSystemMetrics(1))
        if width <= 1 or height <= 0:
            raise AssertionError("interactive E2E cannot read primary screen dimensions")
        probe_x = int(original.x) + 1 if int(original.x) + 1 < width else max(0, int(original.x) - 1)
        probe_y = max(0, min(height - 1, int(original.y)))
        probe = wintypes.POINT()
        try:
            if not user32.SetCursorPos(probe_x, probe_y):
                raise AssertionError(
                    "Windows input desktop is visible but rejects SetCursorPos; "
                    "the runner must execute in an unlocked interactive user session"
                )
            if not user32.GetCursorPos(ctypes.byref(probe)):
                raise AssertionError("interactive E2E cannot re-read the cursor after SetCursorPos")
            if int(probe.x) != probe_x or int(probe.y) != probe_y:
                raise AssertionError(
                    "Windows input desktop did not retain a reversible cursor movement; "
                    f"requested=({probe_x},{probe_y}) observed=({int(probe.x)},{int(probe.y)})"
                )
        finally:
            user32.SetCursorPos(int(original.x), int(original.y))

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
        raise AssertionError(
            f"fixture did not become foreground; last observation={last!r}"
        )

    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 20) -> None:
        for _ in range(limit):
            if resident.store.get_working_state().stage == stage:
                return
            result = resident.live_once()
            if result is not None:
                raise AssertionError(
                    f"event reached terminal result before {stage}: {result}"
                )
        raise AssertionError(f"resident did not reach {stage}")

    @staticmethod
    def _body_trace(resident, limit: int = 8) -> list[dict[str, object]]:
        return [
            {
                "kind": item.kind,
                "success": item.success,
                "error": item.error,
                "data": item.data,
            }
            for item in reversed(resident.body.recent_actions(limit))
        ]

    def test_real_resident_click_proves_visual_foreground_and_uia_focus(self) -> None:
        self._require_input_desktop()
        fixture = _Win32FocusFixture()
        fixture.start()
        resident = None
        original_pointer: tuple[int, int] | None = None
        try:
            foreground = self._wait_for_foreground(fixture.TITLE)
            self.assertEqual(foreground.process_id, os.getpid())

            focused_native = NativeFocusedControlSense().probe()
            self.assertEqual(focused_native.control_id, fixture.SOURCE_CONTROL_ID)
            self.assertTrue(focused_native.enabled)
            self.assertTrue(focused_native.visible)

            target_x, target_y = fixture.target_center()
            automation = NativeAutomationElementSense()
            target_before = automation.probe_at_point(target_x, target_y)
            focused_before = automation.probe_focused()
            self.assertNotEqual(target_before.runtime_id, focused_before.runtime_id)
            self.assertEqual(target_before.process_id, os.getpid())
            self.assertTrue(target_before.is_enabled)
            self.assertTrue(target_before.is_keyboard_focusable)
            self.assertFalse(target_before.is_offscreen)

            with tempfile.TemporaryDirectory() as tmp:
                resident = build_resident_runtime(
                    config={"model": {}},
                    store_path=Path(tmp) / "kernel.db",
                )
                try:
                    pointer = resident.body.act("pointer_state")
                    self.assertTrue(pointer.success, pointer.error)
                    original_pointer = (int(pointer.data["x"]), int(pointer.data["y"]))
                    width = int(pointer.data["screen_width"])
                    height = int(pointer.data["screen_height"])
                    self.assertGreater(width, 0)
                    self.assertGreater(height, 0)

                    x_fraction = round(target_x / max(1, width - 1), 6)
                    y_fraction = round(target_y / max(1, height - 1), 6)
                    predicted_x = int(round(x_fraction * max(0, width - 1)))
                    predicted_y = int(round(y_fraction * max(0, height - 1)))
                    self.assertLessEqual(abs(predicted_x - target_x), 1)
                    self.assertLessEqual(abs(predicted_y - target_y), 1)

                    visual = NativeVisualRegionSense().probe(
                        center_x_fraction=x_fraction,
                        center_y_fraction=y_fraction,
                        width_fraction=0.08,
                        height_fraction=0.08,
                    )
                    self.assertTrue(visual.signature)
                    self.assertFalse(visual.raw_frame_persisted)

                    resident.enqueue(
                        "focus the exact owned UI element at the pointer target",
                        kind="ui_state_transition",
                        payload={
                            "body_action": {
                                "kind": "pointer_click",
                                "args": {
                                    "x_fraction": x_fraction,
                                    "y_fraction": y_fraction,
                                    "button": "left",
                                },
                            },
                            "expected_outcome": {
                                "kind": "visual_region_changed",
                                "width_fraction": 0.08,
                                "height_fraction": 0.08,
                            },
                            "completion_scope": {
                                "kind": "focused_automation_element_at_pointer",
                                "process_name": foreground.process_name,
                                "title_equals": fixture.TITLE,
                            },
                            "action_precondition": {
                                "kind": "foreground_window_matches",
                                "process_name": foreground.process_name,
                                "title_equals": fixture.TITLE,
                            },
                            "model_policy": "never",
                        },
                    )
                    self._advance_until_stage(resident, "native_action")

                    self.assertIsNone(resident.live_once())
                    state_after_move = resident.store.get_working_state()
                    prepared = state_after_move.data.get(
                        resident._POINTER_CLICK_PRECONDITION_KEY
                    )
                    if (
                        state_after_move.stage != "native_action"
                        or not isinstance(prepared, dict)
                        or not prepared.get("position_verified")
                    ):
                        self.fail(
                            "resident did not establish durable pointer-click preparation after "
                            "the first native_action pulse; "
                            f"stage={state_after_move.stage!r} "
                            f"local_failure={state_after_move.data.get('local_failure')!r} "
                            f"body_actions={self._body_trace(resident)!r}"
                        )
                    self.assertEqual(int(prepared["target_x"]), predicted_x)
                    self.assertEqual(int(prepared["target_y"]), predicted_y)

                    moved = resident.body.act("pointer_state")
                    self.assertTrue(moved.success, moved.error)
                    if (
                        abs(int(moved.data["x"]) - predicted_x) > 1
                        or abs(int(moved.data["y"]) - predicted_y) > 1
                    ):
                        self.fail(
                            "resident recorded a verified pointer preparation but the real cursor "
                            "no longer matches it before the next pulse; another input source may "
                            "have moved the cursor or the desktop stopped accepting pointer state. "
                            f"expected=({predicted_x},{predicted_y}) "
                            f"observed=({moved.data['x']},{moved.data['y']}) "
                            f"body_actions={self._body_trace(resident)!r}"
                        )

                    self.assertIsNone(resident.live_once())
                    self.assertTrue(
                        fixture.clicked.wait(3.0),
                        "real SendInput click did not reach the owned target control",
                    )
                    if fixture.error is not None:
                        raise AssertionError(
                            "fixture failed after click: "
                            f"{type(fixture.error).__name__}: {fixture.error}"
                        )

                    result = resident.live_once()
                    self.assertIsNotNone(result)
                    self.assertTrue(result.success, result)
                    self.assertEqual(result.execution_path, ExecutionPath.BODY)
                    self.assertIn("exact opaque element", result.reason)

                    focused_after = automation.probe_focused()
                    self.assertEqual(focused_after.runtime_id, target_before.runtime_id)
                    self.assertTrue(focused_after.has_keyboard_focus)
                    focused_native_after = NativeFocusedControlSense().probe()
                    self.assertEqual(
                        focused_native_after.control_id,
                        fixture.TARGET_CONTROL_ID,
                    )
                finally:
                    resident.store.close()
                    resident = None
        finally:
            if resident is not None:
                resident.store.close()
            if original_pointer is not None and os.name == "nt":
                ctypes.windll.user32.SetCursorPos(*original_pointer)
            fixture.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
