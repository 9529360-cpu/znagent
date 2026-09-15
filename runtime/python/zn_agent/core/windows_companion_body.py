from __future__ import annotations

"""Windows companion admission for real OS-wide input movements.

The Product Resident already owns pointer/keyboard movements through one Body.
This layer does not add another execution surface. It adds a fresh Windows
session/input-desktop preflight immediately before movements that synthesize or
redirect OS-wide interactive input, plus one read-only context movement through
the same Body for deliberate inspection.

UI Automation pattern operations such as ValuePattern.SetValue are deliberately
not covered by this gate: they are semantic UIA actions rather than SendInput-
style input injection and retain their existing exact-target/recovery contracts.
"""

import ctypes
import os
import uuid
from dataclasses import asdict
from typing import Any

from .body import BodyAction, BodyActionResult
from .current_app_text_body import CurrentAppTextAwareBody
from .models import utc_now


class WindowsCompanionAwareBody(CurrentAppTextAwareBody):
    """Keep one final Body while failing closed on non-interactive input sessions."""

    _WINDOWS_CONTEXT_KIND = "windows_companion_context"
    _INTERACTIVE_INPUT_KINDS = frozenset({
        "pointer_move",
        "pointer_click",
        "keyboard_text",
    })

    def act(
        self,
        kind: str,
        *,
        event_id: str | None = None,
        **args: Any,
    ) -> BodyActionResult:
        normalized = str(kind or "").strip().lower()
        if normalized in self._INTERACTIVE_INPUT_KINDS:
            failure = self._interactive_input_admission_failure(
                normalized,
                event_id=event_id,
            )
            if failure is not None:
                return failure
        return super().act(normalized, event_id=event_id, **args)

    def _dispatch(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.kind == self._WINDOWS_CONTEXT_KIND:
            if action.args:
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={"dispatch_sent": False, "disposition": "unexpected_arguments"},
                    error="windows_companion_context is read-only and accepts no action arguments",
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )
            snapshot = self.device_capabilities.companion_context()
            return self._ok(
                action,
                started,
                data={
                    "session": asdict(snapshot.session),
                    "power": asdict(snapshot.power),
                    "network": asdict(snapshot.network),
                    "observed_at": snapshot.observed_at,
                    "read_only": True,
                    "dispatch_sent": False,
                },
            )
        return super()._dispatch(action, started)

    def activate_admitted_application_window(
        self,
        *,
        event_id: str | None,
        application_id: str,
        expected_window_handle: int,
        expected_process_id: int,
        observed_at: str | None = None,
    ) -> BodyActionResult:
        # Exact HWND/PID authority is still owned by MachineCapabilityBody. This
        # extra gate only proves that the current Windows session can accept an
        # interactive foreground transition before native activation is reached.
        failure = self._interactive_input_admission_failure(
            "activate_application_window",
            event_id=event_id,
        )
        if failure is not None:
            data = dict(failure.data or {})
            data.update({
                "application_id": str(application_id or "").strip(),
                "window_handle": int(expected_window_handle or 0),
                "process_id": int(expected_process_id or 0),
                "dispatch_sent": False,
            })
            return BodyActionResult(
                action_id=failure.action_id,
                kind=failure.kind,
                success=False,
                output="",
                data=data,
                error=failure.error,
                event_id=event_id,
                started_at=failure.started_at,
                completed_at=failure.completed_at,
            )
        return super().activate_admitted_application_window(
            event_id=event_id,
            application_id=application_id,
            expected_window_handle=expected_window_handle,
            expected_process_id=expected_process_id,
            observed_at=observed_at,
        )

    def _interactive_input_admission_failure(
        self,
        kind: str,
        *,
        event_id: str | None,
    ) -> BodyActionResult | None:
        graph = getattr(self, "device_capabilities", None)
        context_reader = getattr(graph, "companion_context", None)
        if not callable(context_reader):
            return self._blocked_input_result(
                kind,
                event_id=event_id,
                disposition="companion_context_unavailable",
                evidence={},
                error=(
                    "Windows interactive input requires fresh companion session evidence; "
                    "the current Body has no companion-context sense"
                ),
            )

        try:
            context = context_reader()
        except Exception as exc:
            return self._blocked_input_result(
                kind,
                event_id=event_id,
                disposition="companion_context_probe_failed",
                evidence={},
                error=(
                    "Windows interactive input companion preflight failed before dispatch: "
                    f"{type(exc).__name__}"
                ),
            )

        session = context.session
        # Non-Windows test/development hosts retain the historical downstream
        # platform error rather than pretending that Windows session facts exist.
        if not session.platform_supported:
            return None

        evidence = {
            "process_session_id": session.process_session_id,
            "active_console_session_id": session.active_console_session_id,
            "attached_to_active_console": session.attached_to_active_console,
            "remote_session": session.remote_session,
            "input_desktop_openable": session.input_desktop_openable,
            "session_connection_state": None,
            "dispatch_sent": False,
        }

        if session.process_session_id is None:
            return self._blocked_input_result(
                kind,
                event_id=event_id,
                disposition="session_identity_unknown",
                evidence=evidence,
                error="Windows interactive input refused because current process session identity is unknown",
            )
        if int(session.process_session_id) == 0:
            return self._blocked_input_result(
                kind,
                event_id=event_id,
                disposition="session_zero_noninteractive",
                evidence=evidence,
                error="Windows interactive input refused from Session 0",
            )
        if session.input_desktop_openable is not True:
            return self._blocked_input_result(
                kind,
                event_id=event_id,
                disposition="input_desktop_unavailable",
                evidence=evidence,
                error=(
                    "Windows interactive input refused because the current input desktop is not "
                    "freshly openable by the Resident session"
                ),
            )

        connection_state = self._current_session_connection_state(
            int(session.process_session_id)
        )
        evidence["session_connection_state"] = connection_state
        if connection_state != "active":
            disposition = (
                "session_connection_state_unknown"
                if connection_state is None
                else "session_not_actively_connected"
            )
            return self._blocked_input_result(
                kind,
                event_id=event_id,
                disposition=disposition,
                evidence=evidence,
                error=(
                    "Windows interactive input requires an actively connected user session; "
                    f"current WTS state is {connection_state or 'unknown'}"
                ),
            )
        return None

    def _blocked_input_result(
        self,
        kind: str,
        *,
        event_id: str | None,
        disposition: str,
        evidence: dict[str, Any],
        error: str,
    ) -> BodyActionResult:
        # Do not persist text/coordinates or other action arguments on a blocked
        # path. Only bounded session evidence reaches durable Body history.
        action = BodyAction(
            action_id=f"body-{uuid.uuid4().hex[:12]}",
            kind=kind,
            args={"interactive_input_preflight": True},
            event_id=event_id,
        )
        started = utc_now()
        result = BodyActionResult(
            action_id=action.action_id,
            kind=kind,
            success=False,
            data={**evidence, "disposition": disposition, "dispatch_sent": False},
            error=error,
            event_id=event_id,
            started_at=started,
            completed_at=utc_now(),
        )
        self._record(action, result)
        return result

    @staticmethod
    def _current_session_connection_state(session_id: int) -> str | None:
        """Return WTS connection state for the exact current process session.

        `OpenInputDesktop` alone is intentionally insufficient: Microsoft notes
        that a disconnected session can still return the desktop that becomes
        active after reconnect. WTSActive is therefore required before OS-wide
        input injection/foreground activation.
        """

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
        # WTS_CURRENT_SERVER_HANDLE = NULL, WTSConnectState = 8. Use a void
        # pointer because this information class returns a binary enum value,
        # despite the generic API spelling the output as LPWSTR*.
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
