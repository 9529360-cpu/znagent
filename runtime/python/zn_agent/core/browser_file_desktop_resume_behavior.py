from __future__ import annotations

"""Resume the bounded E2E-24 seam at its durable post-file checkpoint.

`native_orient` is intentionally a durable handoff marker emitted only after the
verified file write/reread. Before the generic resident stage normalizer can
collapse that marker back to ordinary orientation, re-establish current desktop
authority and enter the existing typed Desktop goal path on the same event.
"""

from .browser_file_desktop_handoff_behavior import (
    _STATE_KEY,
    _ground_desktop_goal,
    _progress,
    _request,
)


_INSTALL_MARKER = "_zn_e2e24_browser_file_desktop_resume_installed"


def install_browser_file_desktop_resume_behavior(resident) -> None:
    if getattr(resident, _INSTALL_MARKER, False):
        return

    original_advance = resident._advance_event_step

    def advance_event_step(
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        request = _request(event)
        progress = _progress(state)
        if (
            request is not None
            and progress.get("phase") == "desktop_ground"
            and state.stage == "native_orient"
        ):
            # The previous cycle already established Browser evidence, exact
            # file authority, one verified file mutation and a fresh reread.
            # Do not reuse either Browser or file authority here; bind the
            # current foreground application/HWND/PID/UIA tree from scratch.
            state.data.pop("native_completion", None)
            return _ground_desktop_goal(resident, event, state, request=request)
        return original_advance(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    resident._advance_event_step = advance_event_step
    setattr(resident, _INSTALL_MARKER, True)
