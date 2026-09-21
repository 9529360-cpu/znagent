from __future__ import annotations

"""Read-only Windows Wi-Fi interface state through Native Wi-Fi.

This module deliberately avoids SSID/BSSID/current-network queries. Modern
Windows can gate those details behind location consent; ZN's first Wi-Fi
substrate only needs non-sensitive interface state and therefore stays on
WlanEnumInterfaces.
"""

import ctypes
import platform
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

from .models import utc_now


class WindowsWifiError(RuntimeError):
    """Base error for bounded Native Wi-Fi reads."""


class WindowsWifiUnavailable(WindowsWifiError):
    """Raised when Native Wi-Fi cannot be queried on this machine."""


@dataclass(frozen=True, slots=True)
class WindowsWifiInterfaceObservation:
    description: str
    state: str
    connected: bool


@dataclass(frozen=True, slots=True)
class WindowsWifiObservation:
    interfaces: tuple[WindowsWifiInterfaceObservation, ...]
    observed_at: str

    @property
    def interface_count(self) -> int:
        return len(self.interfaces)

    @property
    def connected_interface_count(self) -> int:
        return sum(1 for item in self.interfaces if item.connected)

    @property
    def connected(self) -> bool:
        return self.connected_interface_count > 0


_WLAN_MAX_NAME_LENGTH = 256
_WLAN_CLIENT_VERSION_LONGHORN = 2
_ERROR_SUCCESS = 0
_ERROR_NOT_SUPPORTED = 50
_ERROR_SERVICE_NOT_ACTIVE = 1062
_MAX_INTERFACES = 64

_INTERFACE_STATE_NAMES = {
    0: "not_ready",
    1: "connected",
    2: "ad_hoc_network_formed",
    3: "disconnecting",
    4: "disconnected",
    5: "associating",
    6: "discovering",
    7: "authenticating",
}


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


class _WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [
        ("InterfaceGuid", _GUID),
        ("strInterfaceDescription", wintypes.WCHAR * _WLAN_MAX_NAME_LENGTH),
        ("isState", ctypes.c_int),
    ]


class _WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [
        ("dwNumberOfItems", wintypes.DWORD),
        ("dwIndex", wintypes.DWORD),
        ("InterfaceInfo", _WLAN_INTERFACE_INFO * 1),
    ]


def read_windows_wifi_state() -> WindowsWifiObservation:
    """Return fresh enabled Native Wi-Fi interface state without network identity."""

    if platform.system() != "Windows":
        raise WindowsWifiUnavailable(
            "Windows Native Wi-Fi is unavailable on the current platform"
        )
    interfaces = _enumerate_windows_wifi_interfaces()
    return WindowsWifiObservation(tuple(interfaces), utc_now())


def _enumerate_windows_wifi_interfaces() -> tuple[WindowsWifiInterfaceObservation, ...]:
    wlanapi = _load_wlan_api()
    negotiated = wintypes.DWORD()
    handle = wintypes.HANDLE()
    interface_list = ctypes.POINTER(_WLAN_INTERFACE_INFO_LIST)()

    result = int(
        wlanapi.WlanOpenHandle(
            _WLAN_CLIENT_VERSION_LONGHORN,
            None,
            ctypes.byref(negotiated),
            ctypes.byref(handle),
        )
    )
    if result != _ERROR_SUCCESS:
        _raise_native_error("WlanOpenHandle", result)

    try:
        result = int(
            wlanapi.WlanEnumInterfaces(
                handle,
                None,
                ctypes.byref(interface_list),
            )
        )
        if result != _ERROR_SUCCESS:
            _raise_native_error("WlanEnumInterfaces", result)
        if not interface_list:
            raise WindowsWifiError(
                "WlanEnumInterfaces succeeded without an interface list"
            )
        return _parse_interface_list(interface_list)
    finally:
        if interface_list:
            wlanapi.WlanFreeMemory(interface_list)
        if handle.value:
            wlanapi.WlanCloseHandle(handle, None)


def _parse_interface_list(
    interface_list: ctypes.POINTER(_WLAN_INTERFACE_INFO_LIST),
) -> tuple[WindowsWifiInterfaceObservation, ...]:
    header = interface_list.contents
    count = int(header.dwNumberOfItems)
    if count < 0 or count > _MAX_INTERFACES:
        raise WindowsWifiError(
            f"Native Wi-Fi returned an invalid interface count: {count}"
        )

    base = (
        ctypes.addressof(header)
        + _WLAN_INTERFACE_INFO_LIST.InterfaceInfo.offset
    )
    size = ctypes.sizeof(_WLAN_INTERFACE_INFO)
    rows: list[WindowsWifiInterfaceObservation] = []
    for index in range(count):
        row = _WLAN_INTERFACE_INFO.from_address(base + (index * size))
        description = str(row.strInterfaceDescription or "").strip()
        raw_state = int(row.isState)
        state = _interface_state_name(raw_state)
        rows.append(
            WindowsWifiInterfaceObservation(
                description=description or "Windows Wi-Fi interface",
                state=state,
                connected=raw_state == 1,
            )
        )
    return tuple(rows)


def _interface_state_name(raw_state: Any) -> str:
    try:
        value = int(raw_state)
    except (TypeError, ValueError):
        return "unknown"
    return _INTERFACE_STATE_NAMES.get(value, "unknown")


def _load_wlan_api():
    try:
        wlanapi = ctypes.WinDLL("wlanapi", use_last_error=True)
    except Exception as exc:
        raise WindowsWifiUnavailable(
            f"Windows Native Wi-Fi API is unavailable: {type(exc).__name__}"
        ) from exc

    wlanapi.WlanOpenHandle.argtypes = [
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.HANDLE),
    ]
    wlanapi.WlanOpenHandle.restype = wintypes.DWORD

    wlanapi.WlanEnumInterfaces.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.POINTER(_WLAN_INTERFACE_INFO_LIST)),
    ]
    wlanapi.WlanEnumInterfaces.restype = wintypes.DWORD

    wlanapi.WlanFreeMemory.argtypes = [ctypes.c_void_p]
    wlanapi.WlanFreeMemory.restype = None

    wlanapi.WlanCloseHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    wlanapi.WlanCloseHandle.restype = wintypes.DWORD
    return wlanapi


def _raise_native_error(operation: str, error_code: int) -> None:
    code = int(error_code)
    message = _format_windows_error(code)
    detail = f"{operation} failed with Windows error {code}"
    if message:
        detail += f": {message}"
    if code in {_ERROR_NOT_SUPPORTED, _ERROR_SERVICE_NOT_ACTIVE}:
        raise WindowsWifiUnavailable(detail)
    raise WindowsWifiError(detail)


def _format_windows_error(error_code: int) -> str:
    try:
        return str(ctypes.FormatError(int(error_code)) or "").strip()
    except Exception:
        return ""
