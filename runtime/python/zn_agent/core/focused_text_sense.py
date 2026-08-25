from __future__ import annotations

"""Bounded read-only digest evidence for one focused native Windows Edit control."""

import hashlib
import os
from dataclasses import dataclass
from typing import Callable

from .models import utc_now


_MAX_TEXT_CHARS = 4096


@dataclass(frozen=True, slots=True)
class FocusedTextObservation:
    native_window_handle: int
    process_id: int
    process_name: str
    foreground_title: str
    control_class_name: str
    control_id: int
    enabled: bool
    visible: bool
    text_length: int
    text_sha256: str
    is_password: bool
    is_read_only: bool
    captured_at: str
    source: str = "windows-user32-focused-edit-digest"


FocusedTextProbeFn = Callable[[], FocusedTextObservation]


class NativeFocusedTextSense:
    """Observe exact text state without exporting the dynamic text itself.

    The first text-entry slice is deliberately limited to a real focused native
    Win32 Edit child control. Password and read-only edits are rejected. The
    Sense returns only identity, length and SHA-256, so dynamic user text does
    not become a general UIA property or model-context surface.
    """

    def __init__(self, *, probe_fn: FocusedTextProbeFn | None = None):
        self.probe_fn = probe_fn or self._probe_windows_focused_text

    def probe(self) -> FocusedTextObservation:
        observation = self.probe_fn()
        if not isinstance(observation, FocusedTextObservation):
            raise TypeError("focused text probe must return FocusedTextObservation")
        if int(observation.native_window_handle) <= 0:
            raise ValueError("focused text probe returned no native window handle")
        if int(observation.process_id) <= 0:
            raise ValueError("focused text probe returned an invalid process id")
        if not str(observation.process_name or "").strip():
            raise ValueError("focused text probe returned no process name")
        if not str(observation.foreground_title or "").strip():
            raise ValueError("focused text probe returned no foreground title")
        if str(observation.control_class_name or "").strip().lower() != "edit":
            raise ValueError("focused text probe is limited to native Edit controls")
        if int(observation.control_id) <= 0:
            raise ValueError("focused text probe returned no stable positive control id")
        if not observation.enabled or not observation.visible:
            raise ValueError("focused text probe requires an enabled visible Edit control")
        if observation.is_password:
            raise ValueError("focused text probe refuses password controls")
        if observation.is_read_only:
            raise ValueError("focused text probe refuses read-only controls")
        if not 0 <= int(observation.text_length) <= _MAX_TEXT_CHARS:
            raise ValueError("focused text probe returned an invalid bounded text length")
        digest = str(observation.text_sha256 or "").strip().lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("focused text probe returned an invalid SHA-256 digest")
        return observation

    @staticmethod
    def digest_text(text: str) -> str:
        return hashlib.sha256(str(text).encode("utf-8")).hexdigest()

    @staticmethod
    def _probe_windows_focused_text() -> FocusedTextObservation:
        if os.name != "nt":
            raise RuntimeError("focused text sense is available only on Windows")

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

        if hasattr(user32, "GetWindowLongPtrW"):
            get_window_long = user32.GetWindowLongPtrW
            get_window_long.restype = ctypes.c_ssize_t
        else:
            get_window_long = user32.GetWindowLongW
            get_window_long.restype = ctypes.c_long
        get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]

        result_type = ctypes.c_size_t
        user32.SendMessageTimeoutW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.POINTER(result_type),
        ]
        user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t

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
            raise RuntimeError("focused text control does not belong to the foreground process")

        title_length = max(0, int(user32.GetWindowTextLengthW(foreground)))
        title_buffer = ctypes.create_unicode_buffer(max(1, title_length + 1))
        user32.GetWindowTextW(foreground, title_buffer, len(title_buffer))
        foreground_title = str(title_buffer.value or "")
        if not foreground_title.strip():
            raise RuntimeError("focused text foreground title is unavailable")

        class_buffer = ctypes.create_unicode_buffer(256)
        class_length = int(
            user32.GetClassNameW(focused, class_buffer, len(class_buffer))
        )
        control_class_name = (
            str(class_buffer.value or "") if class_length > 0 else ""
        )
        if control_class_name.strip().lower() != "edit":
            raise RuntimeError("focused text sense currently supports only native Edit controls")

        control_id = int(user32.GetDlgCtrlID(focused))
        if control_id <= 0:
            raise RuntimeError("focused native Edit has no stable positive control id")

        style = int(get_window_long(focused, -16))  # GWL_STYLE
        es_password = 0x0020
        es_readonly = 0x0800
        is_password = bool(style & es_password)
        is_read_only = bool(style & es_readonly)
        if is_password:
            raise RuntimeError("focused text sense refuses password Edit controls")
        if is_read_only:
            raise RuntimeError("focused text sense refuses read-only Edit controls")

        smto_block = 0x0001
        smto_abortifhung = 0x0002
        flags = smto_block | smto_abortifhung
        timeout_ms = 750
        wm_gettext = 0x000D
        wm_gettextlength = 0x000E

        length_result = result_type(0)
        ctypes.set_last_error(0)
        if not user32.SendMessageTimeoutW(
            focused,
            wm_gettextlength,
            0,
            0,
            flags,
            timeout_ms,
            ctypes.byref(length_result),
        ):
            error = ctypes.get_last_error()
            raise RuntimeError(f"WM_GETTEXTLENGTH timed out or failed with WinError {error}")
        text_length = int(length_result.value)
        if text_length < 0 or text_length > _MAX_TEXT_CHARS:
            raise RuntimeError(
                f"focused native Edit text exceeds the {_MAX_TEXT_CHARS}-character evidence bound"
            )

        buffer = ctypes.create_unicode_buffer(max(1, text_length + 1))
        copied_result = result_type(0)
        ctypes.set_last_error(0)
        if not user32.SendMessageTimeoutW(
            focused,
            wm_gettext,
            len(buffer),
            ctypes.addressof(buffer),
            flags,
            timeout_ms,
            ctypes.byref(copied_result),
        ):
            error = ctypes.get_last_error()
            raise RuntimeError(f"WM_GETTEXT timed out or failed with WinError {error}")
        text = str(buffer.value or "")
        if len(text) > _MAX_TEXT_CHARS:
            raise RuntimeError("focused native Edit text exceeded its evidence bound after read")

        try:
            import psutil

            process_name = str(psutil.Process(int(process_id.value)).name() or "").strip()
        except Exception as exc:
            raise RuntimeError("focused text process name is unavailable") from exc
        if not process_name:
            raise RuntimeError("focused text process name is unavailable")

        return FocusedTextObservation(
            native_window_handle=int(focused),
            process_id=int(process_id.value),
            process_name=process_name,
            foreground_title=foreground_title,
            control_class_name=control_class_name,
            control_id=control_id,
            enabled=bool(user32.IsWindowEnabled(focused)),
            visible=bool(user32.IsWindowVisible(focused)),
            text_length=len(text),
            text_sha256=NativeFocusedTextSense.digest_text(text),
            is_password=is_password,
            is_read_only=is_read_only,
            captured_at=utc_now(),
            source="windows-user32-focused-edit-digest",
        )
