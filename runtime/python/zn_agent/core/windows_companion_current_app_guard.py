from __future__ import annotations

"""Fail closed when a current-app Work target drifts after user ingress.

This is an optimistic-precondition guard over the privacy-bounded historical
context captured by ``windows_companion_work_context``. It does not authorize a
mutation; matching only means the task still refers to the same session and
foreground identity. The downstream current-app path must continue to reacquire
fresh exact UIA/Body authority before every effect.
"""

import re
from dataclasses import asdict, dataclass
from typing import Any

from .current_app_text_cleanup_goal import current_app_text_cleanup_goal
from .windows_companion_work_context import bounded_windows_companion_work_context

_CONTEXT_KEY = "windows_companion_start_context"
_STATE_KEY = "e2e13_windows_companion_start_guard"
_INSTALL_MARKER = "_windows_companion_current_app_guard_installed"
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_KEYS = frozenset(
    {
        "window_handle",
        "foreground_window_handle",
        "title",
        "class_name",
        "clipboard",
        "text",
        "content",
        "files",
        "data",
    }
)


@dataclass(frozen=True, slots=True)
class WindowsCompanionStartGuardStatus:
    bound: bool
    ready: bool
    disposition: str
    session_matches: bool | None = None
    foreground_matches: bool | None = None
    start_fingerprint: str | None = None
    fresh_fingerprint: str | None = None
    checked_at: str | None = None

    def audit(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_windows_companion_start_context(
    event_payload: dict[str, Any],
    *,
    device_capabilities: Any,
) -> WindowsCompanionStartGuardStatus:
    """Compare only session + foreground identity against a fresh frame.

    Power, network and display changes are intentionally not blocking for this
    current-app text task. They remain available in the historical frame but do
    not redefine which application the user's "现在这个软件" referred to.
    """

    if not isinstance(event_payload, dict):
        return WindowsCompanionStartGuardStatus(
            bound=True,
            ready=False,
            disposition="event_payload_invalid",
        )

    if _CONTEXT_KEY not in event_payload:
        return WindowsCompanionStartGuardStatus(
            bound=False,
            ready=True,
            disposition="legacy_unbound",
        )
    raw = event_payload.get(_CONTEXT_KEY)
    start = _validated_bound_context(raw)
    if start is None:
        return WindowsCompanionStartGuardStatus(
            bound=True,
            ready=False,
            disposition="bound_context_invalid",
        )

    reader = getattr(device_capabilities, "companion_frame", None)
    if not callable(reader):
        return WindowsCompanionStartGuardStatus(
            bound=True,
            ready=False,
            disposition="fresh_context_unavailable",
            start_fingerprint=start["fingerprint"],
        )
    try:
        frame = reader()
    except Exception:
        return WindowsCompanionStartGuardStatus(
            bound=True,
            ready=False,
            disposition="fresh_context_unavailable",
            start_fingerprint=start["fingerprint"],
        )
    fresh = bounded_windows_companion_work_context(frame)
    if fresh is None:
        return WindowsCompanionStartGuardStatus(
            bound=True,
            ready=False,
            disposition="fresh_context_unavailable",
            start_fingerprint=start["fingerprint"],
        )

    session_matches = (
        start["components"]["session"] == fresh["components"]["session"]
    )
    foreground_matches = bool(
        start["components"]["foreground"] == fresh["components"]["foreground"]
        and start["foreground"] == fresh["foreground"]
    )
    if not session_matches:
        disposition = "session_drift"
        ready = False
    elif not foreground_matches:
        disposition = "foreground_drift"
        ready = False
    else:
        disposition = "ready"
        ready = True

    return WindowsCompanionStartGuardStatus(
        bound=True,
        ready=ready,
        disposition=disposition,
        session_matches=session_matches,
        foreground_matches=foreground_matches,
        start_fingerprint=start["fingerprint"],
        fresh_fingerprint=fresh["fingerprint"],
        checked_at=fresh["captured_at"],
    )


def install_windows_companion_current_app_guard(resident) -> None:
    """Guard E2E-13 before it grounds any execution-time current app."""

    if getattr(resident, _INSTALL_MARKER, False):
        return
    original_advance = resident._advance_event_step

    def advance_event_step(event, state, *, readiness, learning_evidence, thought=None):
        if str(state.stage or "") == "orient" and current_app_text_cleanup_goal(event) is not None:
            status = evaluate_windows_companion_start_context(
                event.payload,
                device_capabilities=resident.device_capabilities,
            )
            if status.bound:
                state.data[_STATE_KEY] = status.audit()
                resident.store.save_working_state(state)
                if not status.ready:
                    return resident._checkpoint_terminal_failure(
                        event,
                        state,
                        reason=(
                            "current-app Work no longer matches its Windows start context "
                            f"({status.disposition}); refusing to retarget the user's request "
                            "to a later foreground application"
                        ),
                    )
        return original_advance(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    resident._advance_event_step = advance_event_step
    setattr(resident, _INSTALL_MARKER, True)


def _validated_bound_context(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or _contains_forbidden_key(value):
        return None
    if value.get("frame_version") != "windows-companion-frame:v1":
        return None
    if value.get("execution_authority") is not False:
        return None
    if value.get("fresh_revalidation_required") is not True:
        return None

    fingerprint = _fingerprint(value.get("fingerprint"))
    components = value.get("components")
    foreground = value.get("foreground")
    if fingerprint is None or not isinstance(components, dict) or not isinstance(foreground, dict):
        return None

    normalized_components: dict[str, str] = {}
    for name in ("session", "power", "network", "display", "foreground"):
        parsed = _fingerprint(components.get(name))
        if parsed is None:
            return None
        normalized_components[name] = parsed

    process_id = _positive_int(foreground.get("process_id"))
    process_name = _bounded_text(foreground.get("process_name"), limit=260)
    if process_id is None or process_name is None:
        return None

    return {
        "fingerprint": fingerprint,
        "components": normalized_components,
        "foreground": {
            "process_id": process_id,
            "process_name": process_name,
        },
    }


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).strip().lower() in _FORBIDDEN_KEYS:
                return True
            if _contains_forbidden_key(item):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _fingerprint(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if value != value.strip().lower():
        return None
    return value if _FINGERPRINT_RE.fullmatch(value) is not None else None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _bounded_text(value: Any, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().split())
    if not normalized or normalized != value or len(value) > int(limit):
        return None
    return value
