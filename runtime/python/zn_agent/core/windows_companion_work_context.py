from __future__ import annotations

"""Bind privacy-bounded Windows context to one durable Work ingress event.

The binding is historical evidence only. It never carries an HWND or any raw
window, network, display, or clipboard content, and it never grants execution
authority. Any later mutation must reacquire fresh authority from the normal
Resident/Body senses.
"""

import re
from typing import Any

_WINDOWS_COMPANION_START_CONTEXT_KEY = "windows_companion_start_context"
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_FRAME_VERSION = "windows-companion-frame:v1"


def bind_windows_companion_work_context(
    event_payload: dict[str, Any],
    *,
    device_capabilities: Any,
) -> dict[str, Any] | None:
    """Replace caller-supplied context with one fresh, bounded Resident frame.

    Context capture is additive product context, not a Work admission gate. A
    missing/unsupported frame therefore removes any spoofed caller value and
    leaves the event otherwise unchanged rather than blocking unrelated Work.
    """

    if not isinstance(event_payload, dict):
        raise ValueError("Work event payload must be an object")

    # This namespace is Resident-owned. Never preserve caller-provided content
    # if the current device frame cannot be proven.
    event_payload.pop(_WINDOWS_COMPANION_START_CONTEXT_KEY, None)

    reader = getattr(device_capabilities, "companion_frame", None)
    if not callable(reader):
        return None
    try:
        frame = reader()
    except Exception:
        return None

    bounded = bounded_windows_companion_work_context(frame)
    if bounded is None:
        return None
    event_payload[_WINDOWS_COMPANION_START_CONTEXT_KEY] = bounded
    return bounded


def bounded_windows_companion_work_context(frame: Any) -> dict[str, Any] | None:
    """Project a frame through a fixed allowlist suitable for durable Work.

    The projection intentionally excludes ``foreground_window_handle`` even
    though the transient frame contains it. Persisted Work context is evidence
    about where the request started, never a reusable UI authority token.
    """

    version = str(getattr(frame, "frame_version", "") or "").strip()
    if version != _FRAME_VERSION:
        return None

    fingerprint_names = (
        "fingerprint",
        "session_fingerprint",
        "power_fingerprint",
        "network_fingerprint",
        "display_fingerprint",
        "foreground_fingerprint",
    )
    fingerprints: dict[str, str] = {}
    for name in fingerprint_names:
        value = str(getattr(frame, name, "") or "").strip().lower()
        if _FINGERPRINT_RE.fullmatch(value) is None:
            return None
        fingerprints[name] = value

    process_id = _positive_int(getattr(frame, "foreground_process_id", None))
    process_name = _bounded_text(
        getattr(frame, "foreground_process_name", None),
        limit=260,
    )
    if process_id is None or process_name is None:
        # A Work start-context that claims a Windows foreground without one
        # exact current process identity is more misleading than no attachment.
        return None

    monitor_count = _bounded_nonnegative_int(
        getattr(frame, "monitor_count", None),
        maximum=16,
    )
    if monitor_count is None:
        return None

    network_available = _optional_bool(
        getattr(frame, "has_non_loopback_network", None)
    )
    input_desktop_openable = _optional_bool(
        getattr(frame, "input_desktop_openable", None)
    )
    ac_status = str(getattr(frame, "ac_status", "") or "").strip().lower()
    if ac_status not in {"online", "offline", "unknown"}:
        return None
    captured_at = _bounded_text(getattr(frame, "observed_at", None), limit=64)
    if captured_at is None:
        return None

    return {
        "frame_version": version,
        "fingerprint": fingerprints["fingerprint"],
        "components": {
            "session": fingerprints["session_fingerprint"],
            "power": fingerprints["power_fingerprint"],
            "network": fingerprints["network_fingerprint"],
            "display": fingerprints["display_fingerprint"],
            "foreground": fingerprints["foreground_fingerprint"],
        },
        "foreground": {
            "process_id": process_id,
            "process_name": process_name,
        },
        "monitor_count": monitor_count,
        "network_available": network_available,
        "ac_status": ac_status,
        "input_desktop_openable": input_desktop_openable,
        "captured_at": captured_at,
        "execution_authority": False,
        "fresh_revalidation_required": True,
    }


def _bounded_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).strip().split())
    return normalized[:limit] if normalized else None


def _positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0 else None


def _bounded_nonnegative_int(value: Any, *, maximum: int) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed < 0 or parsed > int(maximum):
        return None
    return parsed


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None
