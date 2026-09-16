from __future__ import annotations

"""Stable privacy-bounded context frames over current Windows companion senses.

A frame is not a new world-state authority. It is compact optimistic-precondition
evidence over fresh DeviceCapabilityGraph observations. Because the underlying OS
senses are not an atomic Windows snapshot, material samples are read repeatedly
and accepted only after two consecutive fingerprints agree. Persistent drift
fails closed instead of durable code retaining a composite that may never have
existed at one instant.
"""

import ctypes
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Callable

from .models import utc_now

SessionConnectionStateProbe = Callable[[int], str | None]


@dataclass(frozen=True, slots=True)
class WindowsCompanionFrame:
    frame_version: str
    fingerprint: str
    session_fingerprint: str
    power_fingerprint: str
    network_fingerprint: str
    display_fingerprint: str
    foreground_fingerprint: str
    foreground_process_id: int | None
    foreground_process_name: str | None
    foreground_window_handle: int | None
    monitor_count: int
    has_non_loopback_network: bool | None
    ac_status: str
    input_desktop_openable: bool | None
    session_connection_state: str | None
    observed_at: str


@dataclass(frozen=True, slots=True)
class WindowsCompanionFrameDelta:
    session_changed: bool
    power_changed: bool
    network_changed: bool
    display_changed: bool
    foreground_changed: bool

    @property
    def material_change(self) -> bool:
        return any(
            (
                self.session_changed,
                self.power_changed,
                self.network_changed,
                self.display_changed,
                self.foreground_changed,
            )
        )


@dataclass(frozen=True, slots=True)
class _MaterialFrameSample:
    fingerprint: str
    session_fingerprint: str
    power_fingerprint: str
    network_fingerprint: str
    display_fingerprint: str
    foreground_fingerprint: str
    foreground_process_id: int | None
    foreground_process_name: str | None
    foreground_window_handle: int | None
    monitor_count: int
    has_non_loopback_network: bool | None
    ac_status: str
    input_desktop_openable: bool | None
    session_connection_state: str | None


class WindowsCompanionFrameUnstableError(RuntimeError):
    """Raised when bounded fresh reads never converge on one material context."""


class WindowsCompanionFrameSense:
    """Compose one internally stabilized frame from Resident-owned fresh senses."""

    _VERSION = "windows-companion-frame:v1"
    _DEFAULT_STABILITY_READS = 4
    _MAX_STABILITY_READS = 8

    def __init__(
        self,
        graph: Any,
        *,
        session_connection_state_probe: SessionConnectionStateProbe | None = None,
        stability_reads: int = _DEFAULT_STABILITY_READS,
    ) -> None:
        reads = int(stability_reads)
        if reads < 2 or reads > self._MAX_STABILITY_READS:
            raise ValueError(
                f"stability_reads must be between 2 and {self._MAX_STABILITY_READS}"
            )
        self._graph = graph
        self._session_connection_state_probe = (
            session_connection_state_probe or _native_session_connection_state
        )
        self._stability_reads = reads

    def probe(self) -> WindowsCompanionFrame:
        previous = self._capture_material_sample()
        for _ in range(1, self._stability_reads):
            current = self._capture_material_sample()
            if current.fingerprint == previous.fingerprint:
                return WindowsCompanionFrame(
                    frame_version=self._VERSION,
                    fingerprint=current.fingerprint,
                    session_fingerprint=current.session_fingerprint,
                    power_fingerprint=current.power_fingerprint,
                    network_fingerprint=current.network_fingerprint,
                    display_fingerprint=current.display_fingerprint,
                    foreground_fingerprint=current.foreground_fingerprint,
                    foreground_process_id=current.foreground_process_id,
                    foreground_process_name=current.foreground_process_name,
                    foreground_window_handle=current.foreground_window_handle,
                    monitor_count=current.monitor_count,
                    has_non_loopback_network=current.has_non_loopback_network,
                    ac_status=current.ac_status,
                    input_desktop_openable=current.input_desktop_openable,
                    session_connection_state=current.session_connection_state,
                    observed_at=utc_now(),
                )
            previous = current
        raise WindowsCompanionFrameUnstableError(
            "Windows companion material context did not stabilize across "
            f"{self._stability_reads} bounded reads"
        )

    def _capture_material_sample(self) -> _MaterialFrameSample:
        companion = self._graph.companion_context()
        display = self._graph.display_context()
        foreground_reader = getattr(self._graph, "foreground_companion_context", None)
        foreground = foreground_reader() if callable(foreground_reader) else None

        session_connection_state = None
        if (
            companion.session.platform_supported
            and companion.session.process_session_id is not None
        ):
            try:
                session_connection_state = _normalized_session_connection_state(
                    self._session_connection_state_probe(
                        int(companion.session.process_session_id)
                    )
                )
            except Exception:
                session_connection_state = None

        session_payload = {
            "platform_supported": bool(companion.session.platform_supported),
            "process_session_id": companion.session.process_session_id,
            "active_console_session_id": companion.session.active_console_session_id,
            "attached_to_active_console": companion.session.attached_to_active_console,
            "remote_session": companion.session.remote_session,
            "input_desktop_openable": companion.session.input_desktop_openable,
            "session_connection_state": session_connection_state,
        }
        power_payload = {
            "platform_supported": bool(companion.power.platform_supported),
            "ac_status": companion.power.ac_status,
            "battery_present": companion.power.battery_present,
            "battery_charging": companion.power.battery_charging,
            "battery_saver": companion.power.battery_saver,
        }
        network_payload = {
            "platform_supported": bool(companion.network.platform_supported),
            "has_non_loopback_address": companion.network.has_non_loopback_address,
            "has_ipv4": companion.network.has_ipv4,
            "has_ipv6": companion.network.has_ipv6,
        }
        display_payload = {
            "platform_supported": bool(display.platform_supported),
            "monitor_count": display.monitor_count,
            "enumerated_monitor_count": display.enumerated_monitor_count,
            "primary_monitor_count": display.primary_monitor_count,
            "primary_width": display.primary_width,
            "primary_height": display.primary_height,
            "virtual_left": display.virtual_left,
            "virtual_top": display.virtual_top,
            "virtual_width": display.virtual_width,
            "virtual_height": display.virtual_height,
            "truncated": bool(display.truncated),
            "monitors": [
                {
                    "left": monitor.left,
                    "top": monitor.top,
                    "right": monitor.right,
                    "bottom": monitor.bottom,
                    "work_left": monitor.work_left,
                    "work_top": monitor.work_top,
                    "work_right": monitor.work_right,
                    "work_bottom": monitor.work_bottom,
                    "primary": monitor.primary,
                }
                for monitor in display.monitors
            ],
        }
        foreground_payload = self._foreground_payload(foreground)

        parts = {
            "session": _fingerprint(session_payload),
            "power": _fingerprint(power_payload),
            "network": _fingerprint(network_payload),
            "display": _fingerprint(display_payload),
            "foreground": _fingerprint(foreground_payload),
        }
        full_payload = {"version": self._VERSION, **parts}
        return _MaterialFrameSample(
            fingerprint=_fingerprint(full_payload),
            session_fingerprint=parts["session"],
            power_fingerprint=parts["power"],
            network_fingerprint=parts["network"],
            display_fingerprint=parts["display"],
            foreground_fingerprint=parts["foreground"],
            foreground_process_id=(None if foreground is None else foreground.process_id),
            foreground_process_name=(None if foreground is None else foreground.process_name),
            foreground_window_handle=(
                None if foreground is None else foreground.window_handle
            ),
            monitor_count=int(display.monitor_count),
            has_non_loopback_network=companion.network.has_non_loopback_address,
            ac_status=str(companion.power.ac_status),
            input_desktop_openable=companion.session.input_desktop_openable,
            session_connection_state=session_connection_state,
        )

    @staticmethod
    def _foreground_payload(foreground: Any) -> dict[str, Any]:
        if foreground is None:
            return {"available": False}
        monitor = foreground.monitor
        return {
            "platform_supported": bool(foreground.platform_supported),
            "available": bool(foreground.available),
            "process_id": foreground.process_id,
            "process_name": foreground.process_name,
            "window_handle": foreground.window_handle,
            "title_chars": foreground.title_chars,
            "title_sha256": foreground.title_sha256,
            "class_name_chars": foreground.class_name_chars,
            "class_name_sha256": foreground.class_name_sha256,
            "monitor": (
                None
                if monitor is None
                else {
                    "left": monitor.left,
                    "top": monitor.top,
                    "right": monitor.right,
                    "bottom": monitor.bottom,
                    "work_left": monitor.work_left,
                    "work_top": monitor.work_top,
                    "work_right": monitor.work_right,
                    "work_bottom": monitor.work_bottom,
                    "primary": monitor.primary,
                }
            ),
        }


def compare_windows_companion_frames(
    previous: WindowsCompanionFrame,
    current: WindowsCompanionFrame,
) -> WindowsCompanionFrameDelta:
    return WindowsCompanionFrameDelta(
        session_changed=previous.session_fingerprint != current.session_fingerprint,
        power_changed=previous.power_fingerprint != current.power_fingerprint,
        network_changed=previous.network_fingerprint != current.network_fingerprint,
        display_changed=previous.display_fingerprint != current.display_fingerprint,
        foreground_changed=(
            previous.foreground_fingerprint != current.foreground_fingerprint
        ),
    )


def _normalized_session_connection_state(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {
        "active",
        "connected",
        "connect_query",
        "shadow",
        "disconnected",
        "idle",
        "listen",
        "reset",
        "down",
        "init",
    } else None


def _native_session_connection_state(session_id: int) -> str | None:
    """Return the exact current WTS connection state for one Windows session."""

    if os.name != "nt" or int(session_id) < 0:
        return None

    from ctypes import wintypes

    states = {
        0: "active",
        1: "connected",
        2: "connect_query",
        3: "shadow",
        4: "disconnected",
        5: "idle",
        6: "listen",
        7: "reset",
        8: "down",
        9: "init",
    }
    wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
    buffer = ctypes.c_void_p()
    bytes_returned = wintypes.DWORD(0)
    wtsapi32.WTSQuerySessionInformationW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    wtsapi32.WTSQuerySessionInformationW.restype = wintypes.BOOL
    wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]
    wtsapi32.WTSFreeMemory.restype = None
    ok = bool(
        wtsapi32.WTSQuerySessionInformationW(
            None,
            wintypes.DWORD(int(session_id)),
            8,
            ctypes.byref(buffer),
            ctypes.byref(bytes_returned),
        )
    )
    if not ok or not buffer.value or int(bytes_returned.value) < ctypes.sizeof(ctypes.c_int):
        if buffer.value:
            wtsapi32.WTSFreeMemory(buffer)
        return None
    try:
        state_value = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_int)).contents.value
    finally:
        wtsapi32.WTSFreeMemory(buffer)
    return states.get(int(state_value))


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
