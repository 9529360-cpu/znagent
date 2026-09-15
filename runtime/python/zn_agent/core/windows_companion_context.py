from __future__ import annotations

"""Bounded, model-free Windows companion context for the resident DeviceCapabilityGraph.

This module intentionally stays read-only.  It observes the Resident's current
Windows session, power and local network-interface state without creating a
second agent, event loop, permission system or persistence universe.  Raw
network addresses/interface names are never returned.
"""

import ctypes
import ipaddress
import os
import socket
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping

import psutil

from .models import utc_now

AcPowerStatus = Literal["online", "offline", "unknown"]
SessionProbe = Callable[[], Mapping[str, Any]]
PowerProbe = Callable[[], Mapping[str, Any]]
NetworkProbe = Callable[[], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class WindowsSessionObservation:
    platform_supported: bool
    process_session_id: int | None
    active_console_session_id: int | None
    attached_to_active_console: bool | None
    remote_session: bool | None
    input_desktop_openable: bool | None
    idle_seconds: float | None
    observed_at: str
    source: tuple[str, ...] = ("windows-session",)


@dataclass(frozen=True, slots=True)
class WindowsPowerObservation:
    platform_supported: bool
    ac_status: AcPowerStatus
    battery_present: bool | None
    battery_percent: int | None
    battery_charging: bool | None
    battery_saver: bool | None
    battery_life_seconds: int | None
    observed_at: str
    source: tuple[str, ...] = ("windows-power",)


@dataclass(frozen=True, slots=True)
class WindowsNetworkObservation:
    platform_supported: bool
    interface_count: int
    up_interface_count: int
    non_loopback_up_interface_count: int
    has_non_loopback_address: bool | None
    has_ipv4: bool | None
    has_ipv6: bool | None
    max_link_speed_mbps: int | None
    observed_at: str
    source: tuple[str, ...] = ("psutil-net-if",)


@dataclass(frozen=True, slots=True)
class WindowsCompanionContextSnapshot:
    session: WindowsSessionObservation
    power: WindowsPowerObservation
    network: WindowsNetworkObservation
    observed_at: str


@dataclass(frozen=True, slots=True)
class WindowsCompanionContextDelta:
    session_identity_changed: bool
    input_desktop_availability_changed: bool
    remote_session_changed: bool
    power_source_changed: bool
    battery_saver_changed: bool
    network_availability_changed: bool

    @property
    def material_change(self) -> bool:
        return any((
            self.session_identity_changed,
            self.input_desktop_availability_changed,
            self.remote_session_changed,
            self.power_source_changed,
            self.battery_saver_changed,
            self.network_availability_changed,
        ))


class NativeWindowsCompanionContextSense:
    """Observe cheap Windows-native context without a model or external network call."""

    def __init__(
        self,
        *,
        session_probe: SessionProbe | None = None,
        power_probe: PowerProbe | None = None,
        network_probe: NetworkProbe | None = None,
    ) -> None:
        self._session_probe = session_probe or _native_session_probe
        self._power_probe = power_probe or _native_power_probe
        self._network_probe = network_probe or _native_network_probe

    def probe(self) -> WindowsCompanionContextSnapshot:
        session = _session_observation(self._safe_probe(self._session_probe))
        power = _power_observation(self._safe_probe(self._power_probe))
        network = _network_observation(self._safe_probe(self._network_probe))
        return WindowsCompanionContextSnapshot(
            session=session,
            power=power,
            network=network,
            observed_at=utc_now(),
        )

    @staticmethod
    def _safe_probe(probe: Callable[[], Mapping[str, Any]]) -> Mapping[str, Any]:
        try:
            value = probe()
        except Exception:
            return {}
        return value if isinstance(value, Mapping) else {}


def compare_windows_companion_context(
    previous: WindowsCompanionContextSnapshot,
    current: WindowsCompanionContextSnapshot,
) -> WindowsCompanionContextDelta:
    """Return only material environment transitions; ordinary idle-time drift is ignored."""

    return WindowsCompanionContextDelta(
        session_identity_changed=(
            previous.session.process_session_id != current.session.process_session_id
            or previous.session.active_console_session_id != current.session.active_console_session_id
            or previous.session.attached_to_active_console != current.session.attached_to_active_console
        ),
        input_desktop_availability_changed=(
            previous.session.input_desktop_openable != current.session.input_desktop_openable
        ),
        remote_session_changed=(previous.session.remote_session != current.session.remote_session),
        power_source_changed=(previous.power.ac_status != current.power.ac_status),
        battery_saver_changed=(previous.power.battery_saver != current.power.battery_saver),
        network_availability_changed=(
            previous.network.has_non_loopback_address != current.network.has_non_loopback_address
            or previous.network.non_loopback_up_interface_count
            != current.network.non_loopback_up_interface_count
        ),
    )


def _session_observation(raw: Mapping[str, Any]) -> WindowsSessionObservation:
    supported = bool(raw.get("platform_supported", os.name == "nt"))
    process_session_id = _optional_nonnegative_int(raw.get("process_session_id"))
    active_console_session_id = _optional_nonnegative_int(raw.get("active_console_session_id"))
    attached = _optional_bool(raw.get("attached_to_active_console"))
    if attached is None and process_session_id is not None and active_console_session_id is not None:
        attached = process_session_id == active_console_session_id
    idle = _optional_nonnegative_float(raw.get("idle_seconds"))
    return WindowsSessionObservation(
        platform_supported=supported,
        process_session_id=process_session_id,
        active_console_session_id=active_console_session_id,
        attached_to_active_console=attached,
        remote_session=_optional_bool(raw.get("remote_session")),
        input_desktop_openable=_optional_bool(raw.get("input_desktop_openable")),
        idle_seconds=idle,
        observed_at=utc_now(),
        source=_source_tuple(raw.get("source"), "windows-session"),
    )


def _power_observation(raw: Mapping[str, Any]) -> WindowsPowerObservation:
    supported = bool(raw.get("platform_supported", os.name == "nt"))
    ac = str(raw.get("ac_status") or "unknown").strip().lower()
    if ac not in {"online", "offline", "unknown"}:
        ac = "unknown"
    percent = _optional_nonnegative_int(raw.get("battery_percent"))
    if percent is not None and percent > 100:
        percent = None
    return WindowsPowerObservation(
        platform_supported=supported,
        ac_status=ac,  # type: ignore[arg-type]
        battery_present=_optional_bool(raw.get("battery_present")),
        battery_percent=percent,
        battery_charging=_optional_bool(raw.get("battery_charging")),
        battery_saver=_optional_bool(raw.get("battery_saver")),
        battery_life_seconds=_optional_nonnegative_int(raw.get("battery_life_seconds")),
        observed_at=utc_now(),
        source=_source_tuple(raw.get("source"), "windows-power"),
    )


def _network_observation(raw: Mapping[str, Any]) -> WindowsNetworkObservation:
    supported = bool(raw.get("platform_supported", True))
    interface_count = _nonnegative_int(raw.get("interface_count"))
    up_count = min(interface_count, _nonnegative_int(raw.get("up_interface_count")))
    non_loopback_up = min(up_count, _nonnegative_int(raw.get("non_loopback_up_interface_count")))
    speed = _optional_nonnegative_int(raw.get("max_link_speed_mbps"))
    return WindowsNetworkObservation(
        platform_supported=supported,
        interface_count=interface_count,
        up_interface_count=up_count,
        non_loopback_up_interface_count=non_loopback_up,
        has_non_loopback_address=_optional_bool(raw.get("has_non_loopback_address")),
        has_ipv4=_optional_bool(raw.get("has_ipv4")),
        has_ipv6=_optional_bool(raw.get("has_ipv6")),
        max_link_speed_mbps=speed,
        observed_at=utc_now(),
        source=_source_tuple(raw.get("source"), "psutil-net-if"),
    )


def _native_session_probe() -> Mapping[str, Any]:
    if os.name != "nt":
        return {"platform_supported": False, "source": ("unsupported-platform",)}

    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    kernel32.GetCurrentProcessId.argtypes = []
    kernel32.GetCurrentProcessId.restype = wintypes.DWORD
    kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
    kernel32.WTSGetActiveConsoleSessionId.argtypes = []
    kernel32.WTSGetActiveConsoleSessionId.restype = wintypes.DWORD
    kernel32.GetTickCount.argtypes = []
    kernel32.GetTickCount.restype = wintypes.DWORD

    current_session = wintypes.DWORD()
    process_session_id: int | None = None
    if kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(), ctypes.byref(current_session)):
        process_session_id = int(current_session.value)

    active_raw = int(kernel32.WTSGetActiveConsoleSessionId())
    active_session_id = None if active_raw == 0xFFFFFFFF else active_raw

    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    remote_session = bool(user32.GetSystemMetrics(0x1000))  # SM_REMOTESESSION

    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.restype = wintypes.BOOL
    desktop = user32.OpenInputDesktop(0, False, 0x0001 | 0x0100)  # READOBJECTS | SWITCHDESKTOP
    input_desktop_openable = bool(desktop)
    if desktop:
        user32.CloseDesktop(desktop)

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
    user32.GetLastInputInfo.restype = wintypes.BOOL
    last_input = LASTINPUTINFO()
    last_input.cbSize = ctypes.sizeof(LASTINPUTINFO)
    idle_seconds: float | None = None
    if user32.GetLastInputInfo(ctypes.byref(last_input)):
        now_tick = int(kernel32.GetTickCount())
        # Both values are 32-bit ticks. Unsigned subtraction preserves the
        # correct bounded delta across GetTickCount wrap-around.
        idle_millis = (now_tick - int(last_input.dwTime)) & 0xFFFFFFFF
        idle_seconds = idle_millis / 1000.0

    return {
        "platform_supported": True,
        "process_session_id": process_session_id,
        "active_console_session_id": active_session_id,
        "attached_to_active_console": (
            process_session_id == active_session_id
            if process_session_id is not None and active_session_id is not None
            else None
        ),
        "remote_session": remote_session,
        "input_desktop_openable": input_desktop_openable,
        "idle_seconds": idle_seconds,
        "source": ("kernel32-session", "user32-input"),
    }


def _native_power_probe() -> Mapping[str, Any]:
    if os.name != "nt":
        return {"platform_supported": False, "ac_status": "unknown", "source": ("unsupported-platform",)}

    from ctypes import wintypes

    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", wintypes.BYTE),
            ("BatteryFlag", wintypes.BYTE),
            ("BatteryLifePercent", wintypes.BYTE),
            ("SystemStatusFlag", wintypes.BYTE),
            ("BatteryLifeTime", wintypes.DWORD),
            ("BatteryFullLifeTime", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetSystemPowerStatus.argtypes = [ctypes.POINTER(SYSTEM_POWER_STATUS)]
    kernel32.GetSystemPowerStatus.restype = wintypes.BOOL
    status = SYSTEM_POWER_STATUS()
    if not kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return {
            "platform_supported": True,
            "ac_status": "unknown",
            "source": ("kernel32-get-system-power-status-failed",),
        }

    ac_status = {0: "offline", 1: "online"}.get(int(status.ACLineStatus), "unknown")
    flag = int(status.BatteryFlag)
    battery_present: bool | None
    if flag == 255:
        battery_present = None
    else:
        battery_present = not bool(flag & 128)
    percent = int(status.BatteryLifePercent)
    if percent == 255 or battery_present is False:
        percent = None  # type: ignore[assignment]
    life = int(status.BatteryLifeTime)
    if life == 0xFFFFFFFF or battery_present is False:
        life = None  # type: ignore[assignment]

    return {
        "platform_supported": True,
        "ac_status": ac_status,
        "battery_present": battery_present,
        "battery_percent": percent,
        "battery_charging": bool(flag & 8) if battery_present else False if battery_present is False else None,
        "battery_saver": bool(int(status.SystemStatusFlag)),
        "battery_life_seconds": life,
        "source": ("kernel32-get-system-power-status",),
    }


def _native_network_probe() -> Mapping[str, Any]:
    stats = psutil.net_if_stats()
    addresses = psutil.net_if_addrs()
    up_names = {name for name, stat in stats.items() if bool(stat.isup)}
    non_loopback_names: set[str] = set()
    has_ipv4 = False
    has_ipv6 = False

    for name in up_names:
        for address in addresses.get(name, ()):
            if address.family not in {socket.AF_INET, socket.AF_INET6}:
                continue
            raw_address = str(address.address or "").split("%", 1)[0]
            try:
                parsed = ipaddress.ip_address(raw_address)
            except ValueError:
                continue
            if parsed.is_loopback:
                continue
            non_loopback_names.add(name)
            if address.family == socket.AF_INET:
                has_ipv4 = True
            elif address.family == socket.AF_INET6:
                has_ipv6 = True

    speeds = [int(stats[name].speed) for name in non_loopback_names if int(stats[name].speed or 0) > 0]
    return {
        "platform_supported": os.name == "nt",
        "interface_count": len(stats),
        "up_interface_count": len(up_names),
        "non_loopback_up_interface_count": len(non_loopback_names),
        "has_non_loopback_address": bool(non_loopback_names),
        "has_ipv4": has_ipv4,
        "has_ipv6": has_ipv6,
        "max_link_speed_mbps": max(speeds) if speeds else None,
        "source": ("psutil-net-if-stats", "psutil-net-if-addrs"),
    }


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return None


def _nonnegative_int(value: Any) -> int:
    parsed = _optional_nonnegative_int(value)
    return parsed if parsed is not None else 0


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _optional_nonnegative_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed < 0 or parsed != parsed or parsed == float("inf"):
        return None
    return parsed


def _source_tuple(value: Any, default: str) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else (default,)
    if isinstance(value, (tuple, list)):
        rows = tuple(str(item).strip() for item in value if str(item).strip())
        return rows or (default,)
    return (default,)
