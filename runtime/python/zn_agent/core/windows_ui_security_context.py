from __future__ import annotations

"""Read-only Windows UI security context for companion-aware interaction.

Windows `SendInput` is constrained by User Interface Privilege Isolation (UIPI):
a process may inject input only toward an equal-or-lower integrity target.  ZN
therefore needs to observe the resident and current foreground token levels before
interpreting input failures or deciding whether an OS-wide input path is viable.

This module only queries access-token metadata. It never enables privileges,
changes a token, launches elevated code, bypasses UAC, or grants action authority.
"""

import ctypes
import os
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping

from .models import utc_now

IntegrityLabel = Literal[
    "untrusted",
    "low",
    "medium",
    "medium_plus",
    "high",
    "system",
    "protected",
    "unknown",
]
TokenProbe = Callable[[int], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class WindowsProcessSecurityObservation:
    process_id: int
    observable: bool
    integrity_rid: int | None
    integrity_label: IntegrityLabel
    elevated: bool | None
    ui_access: bool | None
    observed_at: str
    source: tuple[str, ...] = ("windows-process-token",)


@dataclass(frozen=True, slots=True)
class WindowsUiSecurityContext:
    platform_supported: bool
    resident: WindowsProcessSecurityObservation
    foreground: WindowsProcessSecurityObservation | None
    input_integrity_compatible: bool | None
    disposition: str
    observed_at: str


class NativeWindowsUiSecurityContextSense:
    """Compare Resident and current foreground integrity without mutating either."""

    def __init__(
        self,
        *,
        token_probe: TokenProbe | None = None,
        current_process_id: Callable[[], int] | None = None,
    ) -> None:
        self._token_probe = token_probe or _native_process_token_probe
        self._current_process_id = current_process_id or os.getpid

    def probe(self, *, foreground_process_id: int | None) -> WindowsUiSecurityContext:
        resident_pid = _positive_int(self._current_process_id()) or 0
        resident = self._observe(resident_pid)
        foreground_pid = _positive_int(foreground_process_id)
        foreground = self._observe(foreground_pid) if foreground_pid is not None else None

        supported = os.name == "nt" or self._token_probe is not _native_process_token_probe
        compatible: bool | None = None
        disposition = "unknown"
        if not supported:
            disposition = "unsupported_platform"
        elif not resident.observable or resident.integrity_rid is None:
            disposition = "resident_integrity_unknown"
        elif foreground is None:
            disposition = "foreground_process_unavailable"
        elif not foreground.observable or foreground.integrity_rid is None:
            disposition = "foreground_integrity_unknown"
        else:
            compatible = resident.integrity_rid >= foreground.integrity_rid
            disposition = "compatible" if compatible else "foreground_higher_integrity"

        return WindowsUiSecurityContext(
            platform_supported=supported,
            resident=resident,
            foreground=foreground,
            input_integrity_compatible=compatible,
            disposition=disposition,
            observed_at=utc_now(),
        )

    def _observe(self, process_id: int) -> WindowsProcessSecurityObservation:
        if process_id <= 0:
            return _unknown_process(process_id)
        try:
            raw = self._token_probe(process_id)
        except Exception:
            raw = {}
        if not isinstance(raw, Mapping):
            raw = {}
        observable = bool(raw.get("observable"))
        rid = _nonnegative_int(raw.get("integrity_rid")) if observable else None
        label = _integrity_label(rid)
        return WindowsProcessSecurityObservation(
            process_id=process_id,
            observable=observable and rid is not None,
            integrity_rid=rid,
            integrity_label=label,
            elevated=_optional_bool(raw.get("elevated")) if observable else None,
            ui_access=_optional_bool(raw.get("ui_access")) if observable else None,
            observed_at=utc_now(),
            source=_source_tuple(raw.get("source"), "windows-process-token"),
        )


def _native_process_token_probe(process_id: int) -> Mapping[str, Any]:
    if os.name != "nt" or int(process_id) <= 0:
        return {"observable": False, "source": ("unsupported-platform",)}

    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    process_query_limited_information = 0x1000
    token_query = 0x0008
    token_elevation = 20
    token_integrity_level = 25
    token_ui_access = 26

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetSidSubAuthorityCount.argtypes = [wintypes.LPVOID]
    advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    advapi32.GetSidSubAuthority.argtypes = [wintypes.LPVOID, wintypes.DWORD]
    advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)

    process = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        wintypes.DWORD(int(process_id)),
    )
    if not process:
        return {"observable": False, "source": ("open-process-denied",)}

    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(process, token_query, ctypes.byref(token)):
            return {"observable": False, "source": ("open-process-token-denied",)}
        try:
            rid = _query_integrity_rid(advapi32, token, token_integrity_level)
            elevated = _query_token_dword(advapi32, token, token_elevation)
            ui_access = _query_token_dword(advapi32, token, token_ui_access)
            if rid is None:
                return {
                    "observable": False,
                    "source": ("token-integrity-unavailable",),
                }
            return {
                "observable": True,
                "integrity_rid": rid,
                "elevated": None if elevated is None else bool(elevated),
                "ui_access": None if ui_access is None else bool(ui_access),
                "source": (
                    "open-process-query-limited-information",
                    "open-process-token-query",
                    "get-token-information",
                ),
            }
        finally:
            if token:
                kernel32.CloseHandle(token)
    finally:
        kernel32.CloseHandle(process)


def _query_token_dword(advapi32: Any, token: Any, info_class: int) -> int | None:
    from ctypes import wintypes

    value = wintypes.DWORD(0)
    returned = wintypes.DWORD(0)
    if not advapi32.GetTokenInformation(
        token,
        info_class,
        ctypes.byref(value),
        ctypes.sizeof(value),
        ctypes.byref(returned),
    ):
        return None
    return int(value.value)


def _query_integrity_rid(advapi32: Any, token: Any, info_class: int) -> int | None:
    from ctypes import wintypes

    required = wintypes.DWORD(0)
    advapi32.GetTokenInformation(token, info_class, None, 0, ctypes.byref(required))
    if int(required.value) <= 0 or int(required.value) > 65536:
        return None
    buffer = ctypes.create_string_buffer(int(required.value))
    if not advapi32.GetTokenInformation(
        token,
        info_class,
        buffer,
        required,
        ctypes.byref(required),
    ):
        return None

    # TOKEN_MANDATORY_LABEL begins with SID_AND_ATTRIBUTES. The first field is
    # the SID pointer; alignment is naturally provided by ctypes.Structure.
    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]

    class TOKEN_MANDATORY_LABEL(ctypes.Structure):
        _fields_ = [("Label", SID_AND_ATTRIBUTES)]

    label = ctypes.cast(buffer, ctypes.POINTER(TOKEN_MANDATORY_LABEL)).contents
    sid = label.Label.Sid
    if not sid:
        return None
    count_ptr = advapi32.GetSidSubAuthorityCount(sid)
    if not count_ptr:
        return None
    count = int(count_ptr.contents.value)
    if count <= 0:
        return None
    rid_ptr = advapi32.GetSidSubAuthority(sid, count - 1)
    if not rid_ptr:
        return None
    return int(rid_ptr.contents.value)


def _integrity_label(rid: int | None) -> IntegrityLabel:
    if rid is None:
        return "unknown"
    if rid < 0x1000:
        return "untrusted"
    if rid < 0x2000:
        return "low"
    if rid < 0x2100:
        return "medium"
    if rid < 0x3000:
        return "medium_plus"
    if rid < 0x4000:
        return "high"
    if rid < 0x5000:
        return "system"
    return "protected"


def _unknown_process(process_id: int) -> WindowsProcessSecurityObservation:
    return WindowsProcessSecurityObservation(
        process_id=int(process_id or 0),
        observable=False,
        integrity_rid=None,
        integrity_label="unknown",
        elevated=None,
        ui_access=None,
        observed_at=utc_now(),
        source=("process-id-unavailable",),
    )


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _positive_int(value: Any) -> int | None:
    parsed = _nonnegative_int(value)
    return parsed if parsed is not None and parsed > 0 else None


def _source_tuple(value: Any, default: str) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else (default,)
    if isinstance(value, (tuple, list)):
        rows = tuple(str(item).strip() for item in value if str(item).strip())
        return rows or (default,)
    return (default,)
