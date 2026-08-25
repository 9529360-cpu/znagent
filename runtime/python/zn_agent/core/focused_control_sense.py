from __future__ import annotations

"""Fresh focused native-control evidence owned directly by the resident.

This Sense is intentionally read-only and narrow. On Windows it observes the
foreground GUI thread, requires that keyboard focus belongs to a real child or
descendant HWND of the current foreground window, and returns only bounded
window/control identity and input-state metadata. It does not read control
text, inspect pixels, invoke accessibility mutation APIs, or create action
authority by itself.
"""

import os
from dataclasses import dataclass
from typing import Callable

from .models import utc_now


@dataclass(frozen=True, slots=True)
class FocusedControlObservation:
    process_id: int
    process_name: str
    foreground_title: str
    foreground_class_name: str
    control_class_name: str
    control_id: int
    enabled: bool
    visible: bool
    captured_at: str
    source: str = "windows-user32-gui-thread"


FocusedControlProbeFn = Callable[[], FocusedControlObservation]


class NativeFocusedControlSense:
    """Read exact identity of the focused native child control on Windows."""

    def __init__(self, *, probe_fn: FocusedControlProbeFn | None = None):
        self.probe_fn = probe_fn or self._probe_windows_focused_control

    def probe(self) -> FocusedControlObservation:
        observation = self.probe_fn()
        if not isinstance(observation, FocusedControlObservation):
            raise TypeError("focused control probe must return FocusedControlObservation")
        if int(observation.process_id) <= 0:
            raise ValueError("focused control probe returned an invalid process id")
        if not str(observation.process_name or "").strip():
            raise ValueError("focused control probe returned no process name")
        if not str(observation.foreground_title or "").strip():
            raise ValueError("focused control probe returned no foreground title")
        if not str(observation.control_class_name or "").strip():
            raise ValueError("focused control probe returned no control class")
        if int(observation.control_id) <= 0:
            raise ValueError("focused control probe returned no stable positive control id")
        return observation

    @staticmethod
    def _probe_windows_focused_control() -> FocusedControlObservation:
        if os.name != "nt":
            raise RuntimeError("focused control sense is available only on Windows")

        import ctypes
        from ctypes import wintypes

        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND),
                ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND),
                ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND),
                ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT),
            ]

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetGUIThreadInfo.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(GUITHREADINFO),
        ]
        user32.GetGUIThreadInfo.restype = wintypes.BOOL
        user32.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
        user32.IsChild.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetClassNameW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.GetDlgCtrlID.argtypes = [wintypes.HWND]
        user32.GetDlgCtrlID.restype = ctypes.c_int
        user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        user32.IsWindowEnabled.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL

        foreground = user32.GetForegroundWindow()
        if not foreground:
            raise RuntimeError("Windows did not report a foreground window")

        process_id = wintypes.DWORD(0)
        thread_id = int(
            user32.GetWindowThreadProcessId(foreground, ctypes.byref(process_id))
        )
        if thread_id <= 0 or int(process_id.value) <= 0:
            raise RuntimeError("foreground GUI-thread identity is unavailable")

        gui = GUITHREADINFO()
        gui.cbSize = ctypes.sizeof(GUITHREADINFO)
        ctypes.set_last_error(0)
        if not user32.GetGUIThreadInfo(thread_id, ctypes.byref(gui)):
            error = ctypes.get_last_error()
            raise RuntimeError(f"GetGUIThreadInfo failed with WinError {error}")

        focused = gui.hwndFocus
        if not focused:
            raise RuntimeError("foreground GUI thread has no focused window")
        if focused == foreground or not bool(user32.IsChild(foreground, focused)):
            raise RuntimeError(
                "foreground GUI thread focus is not a native child/descendant control"
            )

        focused_process_id = wintypes.DWORD(0)
        focused_thread_id = int(
            user32.GetWindowThreadProcessId(focused, ctypes.byref(focused_process_id))
        )
        if (
            focused_thread_id <= 0
            or int(focused_process_id.value) != int(process_id.value)
        ):
            raise RuntimeError("focused control does not belong to the foreground process")

        title_length = max(0, int(user32.GetWindowTextLengthW(foreground)))
        title_buffer = ctypes.create_unicode_buffer(max(1, title_length + 1))
        user32.GetWindowTextW(foreground, title_buffer, len(title_buffer))
        foreground_title = str(title_buffer.value or "")
        if not foreground_title.strip():
            raise RuntimeError("focused control foreground title is unavailable")

        foreground_class_buffer = ctypes.create_unicode_buffer(256)
        foreground_class_length = int(
            user32.GetClassNameW(
                foreground,
                foreground_class_buffer,
                len(foreground_class_buffer),
            )
        )
        foreground_class_name = (
            str(foreground_class_buffer.value or "")
            if foreground_class_length > 0
            else ""
        )

        control_class_buffer = ctypes.create_unicode_buffer(256)
        control_class_length = int(
            user32.GetClassNameW(
                focused,
                control_class_buffer,
                len(control_class_buffer),
            )
        )
        control_class_name = (
            str(control_class_buffer.value or "") if control_class_length > 0 else ""
        )
        if not control_class_name.strip():
            raise RuntimeError("focused control class identity is unavailable")

        ctypes.set_last_error(0)
        control_id = int(user32.GetDlgCtrlID(focused))
        if control_id <= 0:
            raise RuntimeError(
                "focused native control has no stable positive dialog/control id"
            )

        try:
            import psutil

            process_name = str(psutil.Process(int(process_id.value)).name() or "").strip()
        except Exception as exc:
            raise RuntimeError("focused control process name is unavailable") from exc
        if not process_name:
            raise RuntimeError("focused control process name is unavailable")

        return FocusedControlObservation(
            process_id=int(process_id.value),
            process_name=process_name,
            foreground_title=foreground_title,
            foreground_class_name=foreground_class_name,
            control_class_name=control_class_name,
            control_id=control_id,
            enabled=bool(user32.IsWindowEnabled(focused)),
            visible=bool(user32.IsWindowVisible(focused)),
            captured_at=utc_now(),
            source="windows-user32-gui-thread",
        )
