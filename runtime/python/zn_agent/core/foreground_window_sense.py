from __future__ import annotations

"""Fresh foreground-window identity evidence owned directly by the resident.

This Sense is intentionally stateless and read-only. It asks the operating
system which top-level window is currently foreground and returns only bounded
window/application identity metadata. It does not inspect screen pixels, use
OCR, call a model, or create input authority.
"""

import os
from dataclasses import dataclass
from typing import Callable

from .models import utc_now


@dataclass(frozen=True, slots=True)
class ForegroundWindowObservation:
    process_id: int
    title: str
    process_name: str
    class_name: str
    captured_at: str
    source: str = "windows-user32"
    window_handle: int = 0


ForegroundWindowProbeFn = Callable[[], ForegroundWindowObservation]


class NativeForegroundWindowSense:
    """Read the current foreground application's exact window identity."""

    def __init__(self, *, probe_fn: ForegroundWindowProbeFn | None = None):
        self.probe_fn = probe_fn or self._probe_windows_foreground_window

    def probe(self) -> ForegroundWindowObservation:
        observation = self.probe_fn()
        if not isinstance(observation, ForegroundWindowObservation):
            raise TypeError("foreground window probe must return ForegroundWindowObservation")
        if int(observation.process_id) <= 0:
            raise ValueError("foreground window probe returned an invalid process id")
        if int(observation.window_handle) < 0:
            raise ValueError("foreground window probe returned an invalid window handle")
        if not str(observation.process_name or "").strip():
            raise ValueError("foreground window probe returned no process name")
        if not (str(observation.title or "").strip() or str(observation.class_name or "").strip()):
            raise ValueError("foreground window probe returned no bounded window identity")
        return observation

    @staticmethod
    def _probe_windows_foreground_window() -> ForegroundWindowObservation:
        if os.name != "nt":
            raise RuntimeError("foreground window sense is available only on Windows")

        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            raise RuntimeError("Windows did not report a foreground window")

        title_length = max(0, int(user32.GetWindowTextLengthW(hwnd)))
        title_buffer = ctypes.create_unicode_buffer(max(1, title_length + 1))
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        title = str(title_buffer.value or "")

        process_id = wintypes.DWORD(0)
        thread_id = int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id)))
        if thread_id <= 0 or int(process_id.value) <= 0:
            raise RuntimeError("foreground window process identity is unavailable")

        class_buffer = ctypes.create_unicode_buffer(256)
        class_length = int(user32.GetClassNameW(hwnd, class_buffer, len(class_buffer)))
        class_name = str(class_buffer.value or "") if class_length > 0 else ""

        try:
            import psutil

            process_name = str(psutil.Process(int(process_id.value)).name() or "").strip()
        except Exception as exc:
            raise RuntimeError("foreground window process name is unavailable") from exc
        if not process_name:
            raise RuntimeError("foreground window process name is unavailable")

        return ForegroundWindowObservation(
            process_id=int(process_id.value),
            title=title,
            process_name=process_name,
            class_name=class_name,
            captured_at=utc_now(),
            source="windows-user32",
            window_handle=int(hwnd),
        )
