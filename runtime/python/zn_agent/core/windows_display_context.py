from __future__ import annotations

"""Bounded read-only Windows display topology for companion-aware Work.

Windows uses virtual-screen coordinates across monitors and secondary displays can
legitimately have negative coordinates.  The Resident therefore needs native
monitor geometry instead of assuming that the primary screen is the whole user
desktop.  Device names, EDID, serial numbers and other hardware identifiers are
intentionally excluded from this first slice.
"""

import ctypes
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .models import utc_now

DisplayProbe = Callable[[], Mapping[str, Any]]
_MAX_MONITORS = 16


@dataclass(frozen=True, slots=True)
class WindowsMonitorObservation:
    index: int
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
class WindowsDisplayObservation:
    platform_supported: bool
    monitor_count: int
    enumerated_monitor_count: int
    primary_monitor_count: int
    primary_width: int | None
    primary_height: int | None
    virtual_left: int | None
    virtual_top: int | None
    virtual_width: int | None
    virtual_height: int | None
    monitors: tuple[WindowsMonitorObservation, ...]
    truncated: bool
    observed_at: str
    source: tuple[str, ...] = ("windows-display",)


class NativeWindowsDisplayContextSense:
    """Observe display topology with Win32 monitor APIs and no model call."""

    def __init__(self, *, probe: DisplayProbe | None = None) -> None:
        self._probe = probe or _native_display_probe

    def probe(self) -> WindowsDisplayObservation:
        try:
            raw = self._probe()
        except Exception:
            raw = {}
        if not isinstance(raw, Mapping):
            raw = {}
        return _display_observation(raw)


def _display_observation(raw: Mapping[str, Any]) -> WindowsDisplayObservation:
    supported = bool(raw.get("platform_supported", os.name == "nt"))
    monitor_count = _nonnegative_int(raw.get("monitor_count"))
    primary_width = _optional_positive_int(raw.get("primary_width"))
    primary_height = _optional_positive_int(raw.get("primary_height"))
    virtual_left = _optional_int(raw.get("virtual_left"))
    virtual_top = _optional_int(raw.get("virtual_top"))
    virtual_width = _optional_positive_int(raw.get("virtual_width"))
    virtual_height = _optional_positive_int(raw.get("virtual_height"))

    monitors: list[WindowsMonitorObservation] = []
    rows = raw.get("monitors")
    if isinstance(rows, (tuple, list)):
        for row in rows[:_MAX_MONITORS]:
            if not isinstance(row, Mapping):
                continue
            monitor = _monitor_observation(row, index=len(monitors))
            if monitor is not None:
                monitors.append(monitor)

    primary_count = sum(1 for monitor in monitors if monitor.primary)
    raw_enumerated = _nonnegative_int(raw.get("enumerated_monitor_count"))
    enumerated_count = max(raw_enumerated, len(monitors))
    truncated = bool(raw.get("truncated")) or enumerated_count > len(monitors)

    # Do not invent a physical monitor count from invalid topology. The Win32
    # SM_CMONITORS count is kept independently from EnumDisplayMonitors output.
    return WindowsDisplayObservation(
        platform_supported=supported,
        monitor_count=monitor_count,
        enumerated_monitor_count=enumerated_count,
        primary_monitor_count=primary_count,
        primary_width=primary_width,
        primary_height=primary_height,
        virtual_left=virtual_left,
        virtual_top=virtual_top,
        virtual_width=virtual_width,
        virtual_height=virtual_height,
        monitors=tuple(monitors),
        truncated=truncated,
        observed_at=utc_now(),
        source=_source_tuple(raw.get("source"), "windows-display"),
    )


def _monitor_observation(
    row: Mapping[str, Any],
    *,
    index: int,
) -> WindowsMonitorObservation | None:
    left = _optional_int(row.get("left"))
    top = _optional_int(row.get("top"))
    right = _optional_int(row.get("right"))
    bottom = _optional_int(row.get("bottom"))
    work_left = _optional_int(row.get("work_left"))
    work_top = _optional_int(row.get("work_top"))
    work_right = _optional_int(row.get("work_right"))
    work_bottom = _optional_int(row.get("work_bottom"))
    values = (
        left,
        top,
        right,
        bottom,
        work_left,
        work_top,
        work_right,
        work_bottom,
    )
    if any(value is None for value in values):
        return None
    assert left is not None
    assert top is not None
    assert right is not None
    assert bottom is not None
    assert work_left is not None
    assert work_top is not None
    assert work_right is not None
    assert work_bottom is not None

    width = right - left
    height = bottom - top
    work_width = work_right - work_left
    work_height = work_bottom - work_top
    if width <= 0 or height <= 0 or work_width <= 0 or work_height <= 0:
        return None
    if (
        work_left < left
        or work_top < top
        or work_right > right
        or work_bottom > bottom
    ):
        return None

    return WindowsMonitorObservation(
        index=index,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        width=width,
        height=height,
        work_left=work_left,
        work_top=work_top,
        work_right=work_right,
        work_bottom=work_bottom,
        work_width=work_width,
        work_height=work_height,
        primary=bool(row.get("primary")),
    )


def _native_display_probe() -> Mapping[str, Any]:
    if os.name != "nt":
        return {"platform_supported": False, "source": ("unsupported-platform",)}

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
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL

    monitor_rows: list[dict[str, Any]] = []
    enumerated_count = 0
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(RECT),
        wintypes.LPARAM,
    )

    def _monitor_callback(hmonitor, hdc, rect_ptr, data):
        del hdc, rect_ptr, data
        nonlocal enumerated_count
        enumerated_count += 1
        if len(monitor_rows) >= _MAX_MONITORS:
            return True
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            return True
        monitor_rows.append(
            {
                "left": int(info.rcMonitor.left),
                "top": int(info.rcMonitor.top),
                "right": int(info.rcMonitor.right),
                "bottom": int(info.rcMonitor.bottom),
                "work_left": int(info.rcWork.left),
                "work_top": int(info.rcWork.top),
                "work_right": int(info.rcWork.right),
                "work_bottom": int(info.rcWork.bottom),
                "primary": bool(int(info.dwFlags) & 1),  # MONITORINFOF_PRIMARY
            }
        )
        return True

    callback = callback_type(_monitor_callback)
    user32.EnumDisplayMonitors.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(RECT),
        callback_type,
        wintypes.LPARAM,
    ]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    enumerated_ok = bool(user32.EnumDisplayMonitors(None, None, callback, 0))

    # GetSystemMetrics constants documented for multiple-monitor systems.
    sm_cxscreen = 0
    sm_cyscreen = 1
    sm_xvirtualscreen = 76
    sm_yvirtualscreen = 77
    sm_cxvirtualscreen = 78
    sm_cyvirtualscreen = 79
    sm_cmonitors = 80

    return {
        "platform_supported": True,
        "monitor_count": max(0, int(user32.GetSystemMetrics(sm_cmonitors))),
        "enumerated_monitor_count": enumerated_count,
        "primary_width": max(0, int(user32.GetSystemMetrics(sm_cxscreen))),
        "primary_height": max(0, int(user32.GetSystemMetrics(sm_cyscreen))),
        "virtual_left": int(user32.GetSystemMetrics(sm_xvirtualscreen)),
        "virtual_top": int(user32.GetSystemMetrics(sm_yvirtualscreen)),
        "virtual_width": max(0, int(user32.GetSystemMetrics(sm_cxvirtualscreen))),
        "virtual_height": max(0, int(user32.GetSystemMetrics(sm_cyvirtualscreen))),
        "monitors": monitor_rows,
        "truncated": enumerated_count > len(monitor_rows),
        "source": (
            "user32-get-system-metrics",
            "user32-enum-display-monitors" if enumerated_ok else "user32-enum-display-monitors-failed",
            "user32-get-monitor-info",
        ),
    }


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _nonnegative_int(value: Any) -> int:
    parsed = _optional_int(value)
    return parsed if parsed is not None and parsed >= 0 else 0


def _optional_positive_int(value: Any) -> int | None:
    parsed = _optional_int(value)
    return parsed if parsed is not None and parsed > 0 else None


def _source_tuple(value: Any, default: str) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else (default,)
    if isinstance(value, (tuple, list)):
        rows = tuple(str(item).strip() for item in value if str(item).strip())
        return rows or (default,)
    return (default,)
