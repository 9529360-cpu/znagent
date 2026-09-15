from __future__ import annotations

"""Privacy-bounded current-foreground context for the Windows companion layer.

The resident already has a strict native foreground-window sense for task-specific
Desktop work. This composition turns that exact current window into a small
companion context that can be retained safely: raw window title/class text never
leaves the probe, while current process/window identity and monitor placement
remain available for drift detection and current-context attachment.
"""

import ctypes
import hashlib
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .foreground_window_sense import (
    ForegroundWindowObservation,
    NativeForegroundWindowSense,
)
from .models import utc_now

MonitorProbe = Callable[[int], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class ForegroundMonitorObservation:
    left: int
    top: int
    right: int
    bottom: int
    width: int
    height: int
    work_left: int
    work_top: int
    work_right: int
    work_bottom: int
    work_width: int
    work_height: int
    primary: bool


@dataclass(frozen=True, slots=True)
class WindowsForegroundCompanionObservation:
    platform_supported: bool
    available: bool
    process_id: int | None
    process_name: str | None
    window_handle: int | None
    title_chars: int
    title_sha256: str | None
    class_name_chars: int
    class_name_sha256: str | None
    monitor: ForegroundMonitorObservation | None
    observed_at: str
    source: tuple[str, ...]


class NativeWindowsForegroundCompanionSense:
    """Observe the exact foreground window without retaining raw title/class text."""

    def __init__(
        self,
        *,
        foreground_sense: NativeForegroundWindowSense | None = None,
        monitor_probe: MonitorProbe | None = None,
    ) -> None:
        self._foreground_sense = foreground_sense or NativeForegroundWindowSense()
        self._monitor_probe = monitor_probe or _native_monitor_for_window_probe

    def probe(self) -> WindowsForegroundCompanionObservation:
        if os.name != "nt" and self._is_native_default():
            return _unavailable(platform_supported=False, source=("unsupported-platform",))
        try:
            foreground = self._foreground_sense.probe()
        except Exception:
            return _unavailable(
                platform_supported=os.name == "nt" or not self._is_native_default(),
                source=("foreground-window-unavailable",),
            )
        if int(foreground.window_handle) <= 0:
            return _unavailable(
                platform_supported=True,
                source=("foreground-window-invalid-handle",),
            )
        return self._from_foreground(foreground)

    def _is_native_default(self) -> bool:
        probe_fn = getattr(self._foreground_sense, "probe_fn", None)
        return (
            probe_fn is None
            or probe_fn == NativeForegroundWindowSense._probe_windows_foreground_window
        )

    def _from_foreground(
        self,
        foreground: ForegroundWindowObservation,
    ) -> WindowsForegroundCompanionObservation:
        title = str(foreground.title or "")
        class_name = str(foreground.class_name or "")
        process_name = " ".join(str(foreground.process_name or "").strip().split())[:260]
        monitor: ForegroundMonitorObservation | None = None
        monitor_source = "monitor-unavailable"
        try:
            raw_monitor = self._monitor_probe(int(foreground.window_handle))
        except Exception:
            raw_monitor = {}
        if isinstance(raw_monitor, Mapping):
            monitor = _monitor_observation(raw_monitor)
            if monitor is not None:
                monitor_source = "monitor-from-window"

        return WindowsForegroundCompanionObservation(
            platform_supported=True,
            available=True,
            process_id=int(foreground.process_id),
            process_name=process_name or None,
            window_handle=int(foreground.window_handle),
            title_chars=len(title),
            title_sha256=_sha256_or_none(title),
            class_name_chars=len(class_name),
            class_name_sha256=_sha256_or_none(class_name),
            monitor=monitor,
            observed_at=utc_now(),
            source=("foreground-window", monitor_source),
        )


def foreground_context_changed(
    previous: WindowsForegroundCompanionObservation,
    current: WindowsForegroundCompanionObservation,
) -> bool:
    """Return whether the user-visible foreground identity materially changed."""

    return any(
        (
            previous.available != current.available,
            previous.process_id != current.process_id,
            previous.process_name != current.process_name,
            previous.window_handle != current.window_handle,
            previous.title_chars != current.title_chars,
            previous.title_sha256 != current.title_sha256,
            previous.class_name_chars != current.class_name_chars,
            previous.class_name_sha256 != current.class_name_sha256,
            previous.monitor != current.monitor,
        )
    )


def _unavailable(
    *,
    platform_supported: bool,
    source: tuple[str, ...],
) -> WindowsForegroundCompanionObservation:
    return WindowsForegroundCompanionObservation(
        platform_supported=platform_supported,
        available=False,
        process_id=None,
        process_name=None,
        window_handle=None,
        title_chars=0,
        title_sha256=None,
        class_name_chars=0,
        class_name_sha256=None,
        monitor=None,
        observed_at=utc_now(),
        source=source,
    )


def _sha256_or_none(value: str) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _monitor_observation(raw: Mapping[str, Any]) -> ForegroundMonitorObservation | None:
    values: dict[str, int] = {}
    for key in (
        "left",
        "top",
        "right",
        "bottom",
        "work_left",
        "work_top",
        "work_right",
        "work_bottom",
    ):
        value = raw.get(key)
        if value is None or isinstance(value, bool):
            return None
        try:
            values[key] = int(value)
        except (TypeError, ValueError, OverflowError):
            return None

    width = values["right"] - values["left"]
    height = values["bottom"] - values["top"]
    work_width = values["work_right"] - values["work_left"]
    work_height = values["work_bottom"] - values["work_top"]
    if min(width, height, work_width, work_height) <= 0:
        return None
    if (
        values["work_left"] < values["left"]
        or values["work_top"] < values["top"]
        or values["work_right"] > values["right"]
        or values["work_bottom"] > values["bottom"]
    ):
        return None
    return ForegroundMonitorObservation(
        left=values["left"],
        top=values["top"],
        right=values["right"],
        bottom=values["bottom"],
        width=width,
        height=height,
        work_left=values["work_left"],
        work_top=values["work_top"],
        work_right=values["work_right"],
        work_bottom=values["work_bottom"],
        work_width=work_width,
        work_height=work_height,
        primary=bool(raw.get("primary")),
    )


def _native_monitor_for_window_probe(hwnd: int) -> Mapping[str, Any]:
    if os.name != "nt":
        return {}
    if int(hwnd) <= 0:
        return {}

    from ctypes import wintypes

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = ctypes.c_void_p
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL

    # MONITOR_DEFAULTTONULL: we need evidence that the current window really
    # intersects a monitor, not a guessed nearest/primary monitor.
    monitor = user32.MonitorFromWindow(wintypes.HWND(int(hwnd)), 0)
    if not monitor:
        return {}
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return {}
    return {
        "left": int(info.rcMonitor.left),
        "top": int(info.rcMonitor.top),
        "right": int(info.rcMonitor.right),
        "bottom": int(info.rcMonitor.bottom),
        "work_left": int(info.rcWork.left),
        "work_top": int(info.rcWork.top),
        "work_right": int(info.rcWork.right),
        "work_bottom": int(info.rcWork.bottom),
        "primary": bool(int(info.dwFlags) & 1),
    }
