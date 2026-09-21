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
from .windows_audio import (
    read_default_render_volume_percent,
    set_default_render_volume_percent,
    validate_volume_percent,
)
from .windows_brightness import (
    WindowsBrightnessDispatchUncertain,
    read_active_brightness,
    set_active_brightness,
    validate_brightness_percent,
)
from .windows_wifi import read_windows_wifi_state


class WindowsCompanionAwareBody(CurrentAppTextAwareBody):
    """Keep one final Body while failing closed on non-interactive input sessions."""

    _WINDOWS_CONTEXT_KIND = "windows_companion_context"
    _WINDOWS_VOLUME_READ_KIND = "windows_audio_volume_read"
    _WINDOWS_VOLUME_SET_KIND = "windows_audio_volume_set"
    _WINDOWS_BRIGHTNESS_READ_KIND = "windows_display_brightness_read"
    _WINDOWS_BRIGHTNESS_SET_KIND = "windows_display_brightness_set"
    _WINDOWS_WIFI_READ_KIND = "windows_network_wifi_read"
    _INTERACTIVE_INPUT_KINDS = frozenset({
        "pointer_move",
        "pointer_click",
        "keyboard_text",
    })

    @classmethod
    def _requires_guard(cls, kind: str, args: dict[str, Any]) -> bool:
        if kind in {cls._WINDOWS_VOLUME_SET_KIND, cls._WINDOWS_BRIGHTNESS_SET_KIND}:
            return True
        return super()._requires_guard(kind, args)

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
        if action.kind == self._WINDOWS_VOLUME_READ_KIND:
            if action.args:
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={"dispatch_sent": False, "disposition": "unexpected_arguments"},
                    error="windows_audio_volume_read accepts no action arguments",
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )
            level = read_default_render_volume_percent()
            return self._ok(
                action,
                started,
                data={
                    "level_percent": level,
                    "source": "windows_core_audio",
                    "read_only": True,
                    "dispatch_sent": False,
                },
            )

        if action.kind == self._WINDOWS_VOLUME_SET_KIND:
            if set(action.args) != {"level_percent"}:
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={"dispatch_sent": False, "disposition": "invalid_arguments"},
                    error="windows_audio_volume_set requires only level_percent",
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )
            requested = validate_volume_percent(action.args["level_percent"])
            previous = read_default_render_volume_percent()
            observed = set_default_render_volume_percent(requested)
            verified = abs(observed - requested) <= 0.5
            data = {
                "previous_level_percent": previous,
                "requested_level_percent": requested,
                "observed_level_percent": observed,
                "verification_tolerance_percent": 0.5,
                "verified": verified,
                "source": "windows_core_audio",
                "dispatch_sent": True,
            }
            if not verified:
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data=data,
                    error=(
                        "Core Audio accepted the volume write but the fresh "
                        "default-endpoint readback did not prove the requested level"
                    ),
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )
            return self._ok(action, started, data=data)

        if action.kind == self._WINDOWS_BRIGHTNESS_READ_KIND:
            if action.args:
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={"dispatch_sent": False, "disposition": "unexpected_arguments"},
                    error="windows_display_brightness_read accepts no action arguments",
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )
            observed = read_active_brightness()
            return self._ok(
                action,
                started,
                data={
                    "level_percent": observed.level_percent,
                    "instance_name": observed.instance_name,
                    "source": "windows_wmi_brightness",
                    "read_only": True,
                    "dispatch_sent": False,
                },
            )

        if action.kind == self._WINDOWS_BRIGHTNESS_SET_KIND:
            if set(action.args) != {"level_percent"}:
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={"dispatch_sent": False, "disposition": "invalid_arguments"},
                    error="windows_display_brightness_set requires only level_percent",
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )
            requested = validate_brightness_percent(action.args["level_percent"])
            previous = read_active_brightness()
            try:
                observed = set_active_brightness(
                    requested,
                    expected_instance_name=previous.instance_name,
                )
            except WindowsBrightnessDispatchUncertain as exc:
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={
                        "instance_name": previous.instance_name,
                        "previous_level_percent": previous.level_percent,
                        "requested_level_percent": requested,
                        "verified": False,
                        "source": "windows_wmi_brightness",
                        "dispatch_sent": True,
                        "side_effect_uncertain": True,
                    },
                    error=str(exc),
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )
            verified = (
                observed.instance_name == previous.instance_name
                and abs(observed.level_percent - requested) <= 0.5
            )
            data = {
                "instance_name": observed.instance_name,
                "previous_level_percent": previous.level_percent,
                "requested_level_percent": requested,
                "observed_level_percent": observed.level_percent,
                "verification_tolerance_percent": 0.5,
                "verified": verified,
                "source": "windows_wmi_brightness",
                "dispatch_sent": True,
            }
            if not verified:
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data=data,
                    error=(
                        "WMI accepted the brightness write but fresh active-monitor "
                        "readback did not prove the requested level"
                    ),
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )
            return self._ok(action, started, data=data)

        if action.kind == self._WINDOWS_WIFI_READ_KIND:
            if action.args:
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={"dispatch_sent": False, "disposition": "unexpected_arguments"},
                    error="windows_network_wifi_read accepts no action arguments",
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )
            observed = read_windows_wifi_state()
            return self._ok(
                action,
                started,
                data={
                    "interfaces": [asdict(item) for item in observed.interfaces],
                    "interface_count": observed.interface_count,
                    "connected_interface_count": observed.connected_interface_count,
                    "connected": observed.connected,
                    "observed_at": observed.observed_at,
                    "source": "windows_native_wifi",
                    "read_only": True,
                    "dispatch_sent": False,
                },
            )

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
            display = self.device_capabilities.display_context()
            return self._ok(
                action,
                started,
                data={
                    "session": asdict(snapshot.session),
                    "power": asdict(snapshot.power),
                    "network": asdict(snapshot.network),
                    "display": asdict(display),
                    "interactive_input": self._interactive_input_status(snapshot.session),
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

    def _native_activate_exact_application_window(
        self,
        hwnd: int,
        expected_pid: int,
    ) -> dict[str, Any]:
        """Re-prove interactive-session authority at the native foreground seam.

        The admitted application path intentionally rechecks app/PID/HWND identity
        after its first companion gate. Those fresh machine-fact reads can take
        enough time for the user session to lock or disconnect, so WTS/input-
        desktop authority is sampled again immediately before SetForegroundWindow.
        This seam adds no new target authority: it can only veto the already-
        admitted exact HWND/PID.
        """

        failure = self._interactive_input_admission()
        if failure is not None:
            disposition, _evidence, error = failure
            return {
                "success": False,
                "dispatch_sent": False,
                "disposition": disposition,
                "error": error,
            }
        return super()._native_activate_exact_application_window(hwnd, expected_pid)

    def _interactive_input_admission_failure(
        self,
        kind: str,
        *,
        event_id: str | None,
    ) -> BodyActionResult | None:
        failure = self._interactive_input_admission()
        if failure is None:
            return None
        disposition, evidence, error = failure
        return self._blocked_input_result(
            kind,
            event_id=event_id,
            disposition=disposition,
            evidence=evidence,
            error=error,
        )

    def _interactive_input_admission(
        self,
    ) -> tuple[str, dict[str, Any], str] | None:
        """Return bounded blocking evidence, or None when input may proceed."""

        graph = getattr(self, "device_capabilities", None)
        context_reader = getattr(graph, "companion_context", None)
        if not callable(context_reader):
            return (
                "companion_context_unavailable",
                {},
                "Windows interactive input requires fresh companion session evidence; "
                "the current Body has no companion-context sense",
            )

        try:
            context = context_reader()
        except Exception as exc:
            return (
                "companion_context_probe_failed",
                {},
                "Windows interactive input companion preflight failed before dispatch: "
                f"{type(exc).__name__}",
            )

        status = self._interactive_input_status(context.session)
        if status["platform_supported"] is False:
            # Non-Windows test/development hosts retain the historical downstream
            # platform error rather than pretending that Windows evidence exists.
            return None
        if status["ready"] is True:
            return None

        disposition = str(status.get("disposition") or "interactive_input_unavailable")
        errors = {
            "session_identity_unknown": (
                "Windows interactive input refused because current process session identity is unknown"
            ),
            "session_zero_noninteractive": "Windows interactive input refused from Session 0",
            "input_desktop_unavailable": (
                "Windows interactive input refused because the current input desktop is not "
                "freshly openable by the Resident session"
            ),
            "session_connection_state_unknown": (
                "Windows interactive input requires an actively connected user session; "
                "current WTS state is unknown"
            ),
            "session_not_actively_connected": (
                "Windows interactive input requires an actively connected user session; "
                f"current WTS state is {status.get('session_connection_state') or 'unknown'}"
            ),
        }
        evidence = {
            key: value
            for key, value in status.items()
            if key not in {"ready", "disposition"}
        }
        return (
            disposition,
            evidence,
            errors.get(disposition, "Windows interactive input is not currently admitted"),
        )

    def _interactive_input_status(self, session: Any) -> dict[str, Any]:
        status: dict[str, Any] = {
            "platform_supported": bool(session.platform_supported),
            "process_session_id": session.process_session_id,
            "active_console_session_id": session.active_console_session_id,
            "attached_to_active_console": session.attached_to_active_console,
            "remote_session": session.remote_session,
            "input_desktop_openable": session.input_desktop_openable,
            "session_connection_state": None,
            "ready": None,
            "disposition": "unsupported_platform",
        }
        if not session.platform_supported:
            return status
        if session.process_session_id is None:
            status.update(ready=False, disposition="session_identity_unknown")
            return status
        if int(session.process_session_id) == 0:
            status.update(ready=False, disposition="session_zero_noninteractive")
            return status
        if session.input_desktop_openable is not True:
            status.update(ready=False, disposition="input_desktop_unavailable")
            return status

        connection_state = self._current_session_connection_state(int(session.process_session_id))
        status["session_connection_state"] = connection_state
        if connection_state is None:
            status.update(ready=False, disposition="session_connection_state_unknown")
            return status
        if connection_state != "active":
            status.update(ready=False, disposition="session_not_actively_connected")
            return status
        status.update(ready=True, disposition="ready")
        return status

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
