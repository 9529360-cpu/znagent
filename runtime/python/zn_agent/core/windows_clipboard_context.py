from __future__ import annotations

"""Privacy-safe clipboard state for the Windows companion layer.

The default companion sense intentionally never opens or reads clipboard content.
It observes only the per-window-station sequence number, a bounded set of native
format-availability flags, and the optional clipboard-owner process id.  This is
enough to detect/change-bind clipboard context without silently copying user data.
"""

import ctypes
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .models import utc_now

ClipboardProbe = Callable[[], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class WindowsClipboardObservation:
    platform_supported: bool
    sequence_number: int | None
    sequence_available: bool
    unicode_text_available: bool | None
    file_drop_available: bool | None
    bitmap_available: bool | None
    dib_available: bool | None
    owner_process_id: int | None
    observed_at: str
    source: tuple[str, ...] = ("windows-clipboard-metadata",)

    @property
    def has_supported_content(self) -> bool | None:
        flags = (
            self.unicode_text_available,
            self.file_drop_available,
            self.bitmap_available,
            self.dib_available,
        )
        known = tuple(flag for flag in flags if flag is not None)
        if not known:
            return None
        return any(known)


class NativeWindowsClipboardContextSense:
    """Read clipboard metadata without `OpenClipboard` or content access."""

    def __init__(self, *, probe: ClipboardProbe | None = None) -> None:
        self._probe = probe or _native_clipboard_probe

    def probe(self) -> WindowsClipboardObservation:
        try:
            raw = self._probe()
        except Exception:
            raw = {}
        if not isinstance(raw, Mapping):
            raw = {}
        return _clipboard_observation(raw)


def clipboard_context_changed(
    previous: WindowsClipboardObservation,
    current: WindowsClipboardObservation,
) -> bool:
    """Detect clipboard identity/format/owner change while ignoring observation time."""

    return any(
        (
            previous.sequence_number != current.sequence_number,
            previous.sequence_available != current.sequence_available,
            previous.unicode_text_available != current.unicode_text_available,
            previous.file_drop_available != current.file_drop_available,
            previous.bitmap_available != current.bitmap_available,
            previous.dib_available != current.dib_available,
            previous.owner_process_id != current.owner_process_id,
        )
    )


def _clipboard_observation(raw: Mapping[str, Any]) -> WindowsClipboardObservation:
    supported = bool(raw.get("platform_supported", os.name == "nt"))
    sequence = _optional_nonnegative_int(raw.get("sequence_number"))
    sequence_available_raw = raw.get("sequence_available")
    sequence_available = (
        bool(sequence_available_raw)
        if isinstance(sequence_available_raw, bool)
        else sequence is not None and sequence > 0
    )
    if not sequence_available:
        sequence = None

    return WindowsClipboardObservation(
        platform_supported=supported,
        sequence_number=sequence,
        sequence_available=sequence_available,
        unicode_text_available=_optional_bool(raw.get("unicode_text_available")),
        file_drop_available=_optional_bool(raw.get("file_drop_available")),
        bitmap_available=_optional_bool(raw.get("bitmap_available")),
        dib_available=_optional_bool(raw.get("dib_available")),
        owner_process_id=_optional_positive_int(raw.get("owner_process_id")),
        observed_at=utc_now(),
        source=_source_tuple(raw.get("source"), "windows-clipboard-metadata"),
    )


def _native_clipboard_probe() -> Mapping[str, Any]:
    if os.name != "nt":
        return {
            "platform_supported": False,
            "sequence_available": False,
            "source": ("unsupported-platform",),
        }

    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetClipboardSequenceNumber.argtypes = []
    user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.GetClipboardOwner.argtypes = []
    user32.GetClipboardOwner.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    sequence = int(user32.GetClipboardSequenceNumber())
    sequence_available = sequence > 0

    # Standard Clipboard Formats from Winuser.h. No registered/custom format is
    # created merely for sensing, and content bytes are never opened/read.
    cf_bitmap = 2
    cf_dib = 8
    cf_unicode_text = 13
    cf_hdrop = 15

    owner_pid: int | None = None
    owner = user32.GetClipboardOwner()
    if owner:
        pid = wintypes.DWORD(0)
        if user32.GetWindowThreadProcessId(owner, ctypes.byref(pid)):
            parsed_pid = int(pid.value)
            if parsed_pid > 0:
                owner_pid = parsed_pid

    return {
        "platform_supported": True,
        "sequence_number": sequence if sequence_available else None,
        "sequence_available": sequence_available,
        "unicode_text_available": bool(user32.IsClipboardFormatAvailable(cf_unicode_text)),
        "file_drop_available": bool(user32.IsClipboardFormatAvailable(cf_hdrop)),
        "bitmap_available": bool(user32.IsClipboardFormatAvailable(cf_bitmap)),
        "dib_available": bool(user32.IsClipboardFormatAvailable(cf_dib)),
        "owner_process_id": owner_pid,
        "source": (
            "user32-get-clipboard-sequence-number",
            "user32-is-clipboard-format-available",
            "user32-get-clipboard-owner",
        ),
    }


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _optional_positive_int(value: Any) -> int | None:
    parsed = _optional_nonnegative_int(value)
    return parsed if parsed is not None and parsed > 0 else None


def _source_tuple(value: Any, default: str) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else (default,)
    if isinstance(value, (tuple, list)):
        rows = tuple(str(item).strip() for item in value if str(item).strip())
        return rows or (default,)
    return (default,)
