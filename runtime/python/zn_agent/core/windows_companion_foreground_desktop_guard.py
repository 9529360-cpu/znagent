from __future__ import annotations

"""Bind foreground-desktop goals to the Windows context at Work ingress.

The existing desktop-goal runtime deliberately grounds every concrete movement
from fresh foreground/UIA evidence. That protects execution authority, but a
natural request such as "put this in the software I have open now" can become a
typed ``workspace_to_foreground_desktop`` goal only after Work ingress. Without
this seam, a later foreground application could be silently reinterpreted as the
user's original referent after the first grounding or after a failed stale
movement is sent back to investigation.

This guard is an optimistic semantic precondition only. Until the one
non-replayable submit is durably known to have been dispatched, every desktop
investigation and native-action entry must still match the bounded session and
foreground identity captured at Work ingress. Once submit has been dispatched,
the historical foreground identity stops gating completion so the application is
free to change its own title/state as the requested result. Fresh Resident/UIA
contracts remain the sole execution authority throughout.
"""

from typing import Any

from .desktop_task_goal import desktop_task_goal
from .windows_companion_current_app_guard import (
    evaluate_windows_companion_start_context,
)

_STATE_KEY = "foreground_desktop_windows_companion_start_guard"
_INSTALL_MARKER = "_windows_companion_foreground_desktop_guard_installed"
_DEFAULT_PROGRESS_KEY = "resident_desktop_task_progress"


def install_windows_companion_foreground_desktop_guard(resident) -> None:
    """Reject stale Work context before pre-submit desktop grounding or input."""

    if getattr(resident, _INSTALL_MARKER, False):
        return

    original_investigation = resident._desktop_task_investigation
    original_native_action = resident._native_action_step
    progress_key = str(
        getattr(resident, "_DESKTOP_TASK_PROGRESS_KEY", _DEFAULT_PROGRESS_KEY)
        or _DEFAULT_PROGRESS_KEY
    )

    def guard_start_context(event, state, *, phase: str):
        progress = state.data.get(progress_key)
        if isinstance(progress, dict) and progress.get("submit_dispatched") is True:
            prior = state.data.get(_STATE_KEY)
            audit = dict(prior) if isinstance(prior, dict) else {}
            audit.update(
                {
                    "post_submit_guard_skipped": True,
                    "last_guard_phase": phase,
                    "historical_context_is_execution_authority": False,
                }
            )
            state.data[_STATE_KEY] = audit
            resident.store.save_working_state(state)
            return True, None

        status = evaluate_windows_companion_start_context(
            event.payload,
            device_capabilities=resident.device_capabilities,
        )
        admitted = bool((not status.bound) or status.ready)
        audit: dict[str, Any] = {
            **status.audit(),
            "pre_submit_context_admitted": admitted,
            "post_submit_guard_skipped": False,
            "last_guard_phase": phase,
            "historical_context_is_execution_authority": False,
        }
        if not status.bound:
            # Preserve compatibility for old/direct ResidentEvents that predate
            # Work context binding. Fresh desktop grounding still owns authority.
            audit["legacy_unbound"] = True

        state.data[_STATE_KEY] = audit
        resident.store.save_working_state(state)

        if status.bound and not status.ready:
            result = resident._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "foreground-desktop Work no longer matches its Windows start context "
                    f"({status.disposition}); refusing to reinterpret the user's original "
                    "current-application reference as a later foreground application"
                ),
            )
            return False, result
        return True, None

    def guarded_investigation(event, state, *, readiness, thought=None):
        allowed, result = guard_start_context(
            event,
            state,
            phase="desktop_investigation",
        )
        if not allowed:
            return result
        return original_investigation(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    def guarded_native_action(event, state, *, readiness, thought=None):
        if desktop_task_goal(event) is not None:
            allowed, result = guard_start_context(
                event,
                state,
                phase="native_action_entry",
            )
            if not allowed:
                return result
        return original_native_action(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    resident._desktop_task_investigation = guarded_investigation
    resident._native_action_step = guarded_native_action
    setattr(resident, _INSTALL_MARKER, True)
