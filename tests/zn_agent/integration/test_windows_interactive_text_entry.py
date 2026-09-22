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
from zn_agent.core.focused_text_sense import NativeFocusedTextSense
from zn_agent.core.keyboard_text_body import KeyboardTextBody
from zn_agent.core.provider_bridge import build_resident_runtime


class _Win32EditFixture:
    TITLE = "ZN Interactive Text Entry Contract"
    TARGET_CONTROL_ID = 1103

    def __init__(self) -> None:
        self.ready = threading.Event()
        self.error: BaseException | None = None
        self.hwnd = 0
        self.target_hwnd = 0
        self._thread = threading.Thread(
            target=self._run,
            name="zn-interactive-text-contract-window",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()
        if not self.ready.wait(5.0):
            raise RuntimeError("interactive text fixture did not initialize in time")
        if self.error is not None:
            raise RuntimeError(
                f"interactive text fixture failed: {type(self.error).__name__}: {self.error}"
            )
        if not self.hwnd or not self.target_hwnd:
            raise RuntimeError("interactive text fixture did not expose native window handles")
        self.activate_once()

    def activate_once(self) -> None:
        """Establish exact foreground/focus only for this same-process test fixture."""

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.AttachThreadInput.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.BOOL,
        ]
        user32.AttachThreadInput.restype = wintypes.BOOL
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.SetFocus.restype = wintypes.HWND
        user32.GetFocus.argtypes = []
        user32.GetFocus.restype = wintypes.HWND
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        def wait_exact(timeout: float) -> bool:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if int(user32.GetForegroundWindow() or 0) == int(self.hwnd):
                    return True
                time.sleep(0.01)
            return int(user32.GetForegroundWindow() or 0) == int(self.hwnd)

        user32.BringWindowToTop(int(self.hwnd))
        direct_accepted = bool(user32.SetForegroundWindow(int(self.hwnd)))
        if wait_exact(0.35):
            target_pid = wintypes.DWORD(0)
            target_thread = int(
                user32.GetWindowThreadProcessId(int(self.hwnd), ctypes.byref(target_pid)) or 0
            )
            current_thread = int(kernel32.GetCurrentThreadId() or 0)
            if (
                target_thread
                and current_thread
                and current_thread != target_thread
                and int(target_pid.value) == os.getpid()
                and user32.AttachThreadInput(current_thread, target_thread, True)
            ):
                try:
                    user32.SetFocus(int(self.target_hwnd))
                    focused = int(user32.GetFocus() or 0) == int(self.target_hwnd)
                finally:
                    user32.AttachThreadInput(current_thread, target_thread, False)
                if focused:
                    print("text_entry_fixture.foreground_mode=direct", flush=True)
                    return

        target_pid = wintypes.DWORD(0)
        target_thread = int(
            user32.GetWindowThreadProcessId(int(self.hwnd), ctypes.byref(target_pid)) or 0
        )
        current_thread = int(kernel32.GetCurrentThreadId() or 0)
        if not target_thread or int(target_pid.value) != os.getpid():
            raise AssertionError(
                "text-entry fixture lost its exact in-process HWND/thread identity before foreground bootstrap"
            )
        if not current_thread or current_thread == target_thread:
            raise AssertionError(
                "text-entry fixture direct foreground activation failed without a distinct fixture input queue; "
                f"SetForegroundWindow returned {direct_accepted}"
            )
        if not user32.AttachThreadInput(current_thread, target_thread, True):
            raise AssertionError(
                "text-entry fixture could not share its two in-process test input queues: "
                f"WinError {ctypes.get_last_error()}"
            )

        fallback_accepted = False
        reached_exact = False
        target_focused = False
        try:
            user32.BringWindowToTop(int(self.hwnd))
            fallback_accepted = bool(user32.SetForegroundWindow(int(self.hwnd)))
            user32.SetFocus(int(self.target_hwnd))
            reached_exact = wait_exact(2.0)
            target_focused = int(user32.GetFocus() or 0) == int(self.target_hwnd)
        finally:
            detached = bool(user32.AttachThreadInput(current_thread, target_thread, False))
            detach_error = ctypes.get_last_error() if not detached else 0

        if not detached:
            raise AssertionError(
                "text-entry fixture could not detach its temporary in-process input queues: "
                f"WinError {detach_error}"
            )
        if reached_exact and target_focused:
            print("text_entry_fixture.foreground_mode=shared-input-bootstrap", flush=True)
            return
        raise AssertionError(
            "text-entry fixture did not establish exact foreground/Edit focus after bounded in-process input sharing; "
            f"direct SetForegroundWindow returned {direct_accepted}; "
            f"fallback returned {fallback_accepted}; target_focused={target_focused}"
        )

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
            user32.PostThreadMessageW.argtypes = [
                wintypes.DWORD,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            user32.PostThreadMessageW.restype = wintypes.BOOL
            if self._thread.native_id:
                user32.PostThreadMessageW(
                    int(self._thread.native_id),
                    0x0012,  # WM_QUIT
                    0,
                    0,
                )
        self._thread.join(timeout=3.0)

    def target_text(self) -> str:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        user32.GetWindowTextW.restype = ctypes.c_int
        length = max(0, int(user32.GetWindowTextLengthW(self.target_hwnd)))
        buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        user32.GetWindowTextW(self.target_hwnd, buffer, len(buffer))
        return str(buffer.value or "")

    def wait_for_text(self, expected: str, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            last = self.target_text()
            if last == expected:
                return
            time.sleep(0.02)
        raise AssertionError(
            f"real Windows Edit did not receive expected text; expected={expected!r} last={last!r}"
        )

    def _run(self) -> None:
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

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
            user32.DestroyWindow.argtypes = [wintypes.HWND]
            user32.DestroyWindow.restype = wintypes.BOOL
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
            user32.DispatchMessageW.restype = ctypes.c_ssize_t

            WS_OVERLAPPEDWINDOW = 0x00CF0000
            WS_VISIBLE = 0x10000000
            WS_CHILD = 0x40000000
            WS_TABSTOP = 0x00010000
            WS_BORDER = 0x00800000
            ES_AUTOHSCROLL = 0x0080

            instance = kernel32.GetModuleHandleW(None)
            self.hwnd = int(
                user32.CreateWindowExW(
                    0,
                    "STATIC",
                    self.TITLE,
                    WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                    100,
                    100,
                    760,
                    360,
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

            self.target_hwnd = int(
                user32.CreateWindowExW(
                    0,
                    "EDIT",
                    "",
                    WS_CHILD | WS_VISIBLE | WS_TABSTOP | WS_BORDER | ES_AUTOHSCROLL,
                    100,
                    110,
                    520,
                    48,
                    self.hwnd,
                    wintypes.HMENU(self.TARGET_CONTROL_ID),
                    instance,
                    None,
                )
                or 0
            )
            if not self.target_hwnd:
                raise OSError("CreateWindowExW failed for the fixture Edit control")

            user32.ShowWindow(self.hwnd, 5)
            user32.UpdateWindow(self.hwnd)
            user32.BringWindowToTop(self.hwnd)
            user32.SetForegroundWindow(self.hwnd)
            user32.SetFocus(self.target_hwnd)
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
            if self.hwnd:
                try:
                    ctypes.windll.user32.DestroyWindow(self.hwnd)
                except Exception:
                    pass


class WindowsInteractiveTextEntryContractTests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        if os.name != "nt":
            raise unittest.SkipTest("Windows interactive text Contract runs only on Windows")
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
                "interactive text Contract requires an unlocked interactive user session"
            )
        try:
            if not user32.SwitchDesktop(desktop):
                raise AssertionError(
                    "GitHub runner process cannot switch to the Windows input desktop"
                )
        finally:
            user32.CloseDesktop(desktop)

    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 20) -> None:
        for _ in range(limit):
            if resident.store.get_working_state().stage == stage:
                return
            result = resident.live_once()
            if result is not None:
                raise AssertionError(f"event reached terminal result before {stage}: {result}")
        raise AssertionError(f"resident did not reach {stage}")

    def test_real_resident_types_unicode_into_exact_focused_native_edit(self) -> None:
        self._require_input_desktop()
        fixture = _Win32EditFixture()
        fixture.start()
        resident = None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                resident = build_resident_runtime(
                    config={"model": {}},
                    store_path=Path(tmp) / "kernel.db",
                )
                try:
                    self.assertIsInstance(resident.body, KeyboardTextBody)
                    foreground = resident.foreground_window.probe()
                    self.assertEqual(foreground.process_id, os.getpid())
                    self.assertEqual(foreground.title, fixture.TITLE)

                    focused_native = resident.focused_control.probe()
                    self.assertEqual(focused_native.control_class_name.lower(), "edit")
                    self.assertEqual(focused_native.control_id, fixture.TARGET_CONTROL_ID)

                    focused_uia = resident.automation_element.probe_focused()
                    self.assertEqual(focused_uia.process_id, os.getpid())
                    self.assertTrue(focused_uia.has_keyboard_focus)
                    self.assertEqual(
                        focused_uia.native_window_handle,
                        fixture.target_hwnd,
                    )

                    focused_text = resident.focused_text.probe()
                    self.assertEqual(focused_text.native_window_handle, fixture.target_hwnd)
                    self.assertEqual(focused_text.text_length, 0)
                    self.assertEqual(
                        focused_text.text_sha256,
                        NativeFocusedTextSense.digest_text(""),
                    )
                    self.assertFalse(hasattr(focused_text, "text"))
                    self.assertEqual(fixture.target_text(), "")

                    desired = "ZN native 世界"
                    resident.enqueue(
                        "type bounded Unicode text into the exact focused native Edit",
                        kind="ui_state_transition",
                        payload={
                            "body_action": {
                                "kind": "keyboard_text",
                                "args": {"text": desired},
                            },
                            "expected_outcome": {
                                "kind": "focused_text_equals_action_text",
                            },
                            "completion_scope": {
                                "kind": "focused_native_edit_text",
                                "process_name": foreground.process_name,
                                "title_equals": fixture.TITLE,
                                "control_class_name": focused_native.control_class_name,
                                "control_id": focused_native.control_id,
                                "control_type": focused_uia.control_type,
                                "class_name_equals": focused_uia.class_name,
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
                    state = resident.store.get_working_state()
                    prepared = state.data.get(resident._TEXT_PRECONDITION_KEY)
                    self.assertIsInstance(prepared, dict)
                    self.assertEqual(fixture.target_text(), "")
                    self.assertNotIn("text", prepared.get("text_observation", {}))

                    self.assertIsNone(resident.live_once())
                    fixture.wait_for_text(desired)
                    self.assertEqual(
                        resident.store.get_working_state().stage,
                        "native_verification",
                    )

                    result = resident.live_once()
                    self.assertIsNotNone(result)
                    self.assertTrue(result.success, result)
                    self.assertEqual(result.execution_path, ExecutionPath.BODY)
                    self.assertEqual(result.model_invocations, 0)
                    self.assertIn("text-digest", result.reason)

                    after_text = resident.focused_text.probe()
                    after_uia = resident.automation_element.probe_focused()
                    self.assertEqual(after_uia.runtime_id, focused_uia.runtime_id)
                    self.assertEqual(after_text.native_window_handle, fixture.target_hwnd)
                    self.assertEqual(after_text.text_length, len(desired))
                    self.assertEqual(
                        after_text.text_sha256,
                        NativeFocusedTextSense.digest_text(desired),
                    )
                    self.assertFalse(hasattr(after_text, "text"))
                    self.assertEqual(fixture.target_text(), desired)
                finally:
                    resident.store.close()
                    resident = None
        finally:
            if resident is not None:
                resident.store.close()
            fixture.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
