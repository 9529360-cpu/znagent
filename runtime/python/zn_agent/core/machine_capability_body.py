from __future__ import annotations

"""Identity-bound application launch/activation through ZN's existing durable Body."""

import ctypes
import platform
import uuid
from typing import Any

from .body import BodyAction, BodyActionResult
from .browser_form_submit_body import BrowserFormSubmitBody
from .device_capability_graph import DeviceCapabilityGraph
from .machine_capability import InstalledApplication
from .models import utc_now
from .windows_screen_capture import (
    ScreenCaptureArtifact,
    capture_primary_screen_artifact,
)


class MachineCapabilityBody(BrowserFormSubmitBody):
    """Extend the current final Body with safe application movements.

    Public application authority is always the resolved ``application_id``. Raw
    executable paths and native window/process identifiers are never caller
    authority. Public activation derives its native target from fresh machine
    facts; the Resident-only admitted-target seam preserves an already-authorized
    exact HWND/PID without reopening those identifiers in the public ``act`` API.
    """

    _LAUNCH_KIND = "launch_application"
    _ACTIVATE_KIND = "activate_application_window"
    _SCREEN_CAPTURE_KIND = "windows_screen_capture"
    _LAUNCH_DISPATCH_MARKER = "__zn_machine_launch_dispatch_admitted"
    _SCREEN_CAPTURE_DISPATCH_MARKER = "__zn_screen_capture_dispatch_admitted"
    _ACTIVATE_DISPATCH_MARKER = "__zn_machine_activation_dispatch_admitted"
    _ACTIVATE_WINDOW_ARG = "__zn_machine_activation_window_handle"
    _ACTIVATE_PROCESS_ARG = "__zn_machine_activation_process_id"
    _ACTIVATE_OBSERVED_AT_ARG = "__zn_machine_activation_observed_at"
    _FORBIDDEN_LAUNCH_ARGS = frozenset({
        "path", "executable", "executable_path", "command", "shell", "launch_target",
        "parameters", "args", "arguments", "protocol", "url",
    })

    def __init__(self, *args, device_capabilities: DeviceCapabilityGraph | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.device_capabilities = device_capabilities or DeviceCapabilityGraph()

    def act(self, kind: str, *, event_id: str | None = None, **args: Any) -> BodyActionResult:
        normalized = str(kind or "").strip().lower()
        if normalized == self._LAUNCH_KIND:
            return self._act_launch(event_id=event_id, args=dict(args))
        if normalized == self._ACTIVATE_KIND:
            return self._act_activate(event_id=event_id, args=dict(args))
        if normalized == self._SCREEN_CAPTURE_KIND:
            return self._act_screen_capture(event_id=event_id, args=dict(args))
        return super().act(kind, event_id=event_id, **args)

    def _act_launch(self, *, event_id: str | None, args: dict[str, Any]) -> BodyActionResult:
        # Never trust a caller-supplied internal marker.
        args.pop(self._LAUNCH_DISPATCH_MARKER, None)
        forbidden = sorted(key for key in args if str(key).casefold() in self._FORBIDDEN_LAUNCH_ARGS)
        app_id = str(args.get("application_id") or "").strip()
        if forbidden:
            return self._preflight_result(
                self._LAUNCH_KIND, event_id, app_id, False,
                data={"dispatch_sent": False, "rejected_arguments": forbidden},
                error=("launch_application accepts only a resolved application_id; raw launch material is not action authority: " + ", ".join(forbidden)),
            )
        if not app_id:
            return self._preflight_result(
                self._LAUNCH_KIND, event_id, "", False,
                data={"dispatch_sent": False},
                error="launch_application requires a resolved application_id",
            )

        application = self.device_capabilities.application_by_id(app_id, force_refresh=True)
        if application is None:
            return self._preflight_result(
                self._LAUNCH_KIND, event_id, app_id, False,
                data={"dispatch_sent": False, "disposition": "not_installed"},
                error="resolved application identity is no longer installed",
            )
        if not application.launchable:
            return self._preflight_result(
                self._LAUNCH_KIND, event_id, app_id, False,
                data={"dispatch_sent": False, "disposition": "not_launchable"},
                error="installed application has no safe launch target in current machine evidence",
            )

        processes, windows = self.device_capabilities.application_runtime(application)
        visible = tuple(window for window in windows if window.visible)
        if visible:
            return self._preflight_result(
                self._LAUNCH_KIND, event_id, app_id, True,
                output=f"{application.canonical_name} is already running",
                data={
                    "application_id": app_id, "canonical_name": application.canonical_name,
                    "dispatch_sent": False, "disposition": "already_running",
                    "process_ids": [row.process_id for row in processes],
                    "window_handles": [row.hwnd for row in visible],
                },
            )
        if processes:
            return self._preflight_result(
                self._LAUNCH_KIND, event_id, app_id, False,
                data={
                    "application_id": app_id, "canonical_name": application.canonical_name,
                    "dispatch_sent": False, "disposition": "already_running_without_visible_window",
                    "process_ids": [row.process_id for row in processes],
                },
                error=("application is already running without a currently visible top-level window; ZN refuses a duplicate launch"),
            )

        return super().act(
            self._LAUNCH_KIND,
            event_id=event_id,
            application_id=application.app_id,
            **{self._LAUNCH_DISPATCH_MARKER: True},
        )

    def _act_activate(self, *, event_id: str | None, args: dict[str, Any]) -> BodyActionResult:
        # The public authority schema is intentionally narrower than launch: the
        # caller may provide exactly one field, application_id. In particular,
        # a forged private marker/HWND/PID is rejected rather than stripped.
        rejected = sorted(key for key in args if str(key) != "application_id")
        app_id = str(args.get("application_id") or "").strip()
        if rejected:
            return self._preflight_result(
                self._ACTIVATE_KIND, event_id, app_id, False,
                data={"dispatch_sent": False, "rejected_arguments": rejected},
                error=(
                    "activate_application_window accepts only application_id; native window/process "
                    "identity is derived from fresh machine facts: " + ", ".join(rejected)
                ),
            )
        if not app_id:
            return self._preflight_result(
                self._ACTIVATE_KIND, event_id, "", False,
                data={"dispatch_sent": False},
                error="activate_application_window requires a resolved application_id",
            )

        application = self.device_capabilities.application_by_id(app_id, force_refresh=True)
        if application is None:
            return self._preflight_result(
                self._ACTIVATE_KIND, event_id, app_id, False,
                data={"dispatch_sent": False, "disposition": "not_installed"},
                error="resolved application identity is no longer installed",
            )

        processes, windows = self.device_capabilities.application_runtime(application)
        matching_processes = tuple(
            row for row in processes if row.resolved_app_id == application.app_id
        )
        visible = tuple(
            window for window in windows
            if window.visible and window.resolved_app_id == application.app_id
        )
        foreground = tuple(window for window in visible if window.foreground)
        if foreground:
            window = foreground[0]
            return self._preflight_result(
                self._ACTIVATE_KIND, event_id, app_id, True,
                output=f"{application.canonical_name} is already foreground",
                data={
                    "application_id": app_id, "canonical_name": application.canonical_name,
                    "window_handle": window.hwnd, "process_id": window.process_id,
                    "dispatch_sent": False, "disposition": "already_foreground",
                },
            )
        if not matching_processes:
            return self._preflight_result(
                self._ACTIVATE_KIND, event_id, app_id, False,
                data={"application_id": app_id, "dispatch_sent": False, "disposition": "not_running"},
                error="application has no freshly observed matching process to activate",
            )
        if not visible:
            return self._preflight_result(
                self._ACTIVATE_KIND, event_id, app_id, False,
                data={
                    "application_id": app_id, "canonical_name": application.canonical_name,
                    "dispatch_sent": False, "disposition": "already_running_without_visible_window",
                    "process_ids": [row.process_id for row in matching_processes],
                },
                error=(
                    "application is running without a currently visible matching top-level window; "
                    "ZN refuses both activation guessing and duplicate launch"
                ),
            )
        if len(visible) != 1:
            return self._preflight_result(
                self._ACTIVATE_KIND, event_id, app_id, False,
                data={
                    "application_id": app_id, "canonical_name": application.canonical_name,
                    "dispatch_sent": False, "disposition": "ambiguous_visible_windows",
                    "window_handles": [row.hwnd for row in visible],
                },
                error=(
                    "multiple visible matching application windows are present and none is foreground; "
                    "first-slice activation refuses to choose one arbitrarily"
                ),
            )

        window = visible[0]
        process = next(
            (row for row in matching_processes if row.process_id == window.process_id),
            None,
        )
        if process is None:
            return self._preflight_result(
                self._ACTIVATE_KIND, event_id, app_id, False,
                data={
                    "application_id": app_id, "canonical_name": application.canonical_name,
                    "window_handle": window.hwnd, "process_id": window.process_id,
                    "dispatch_sent": False, "disposition": "window_process_identity_unproven",
                },
                error="visible matching window lacks a matching current process identity",
            )

        return self.activate_admitted_application_window(
            event_id=event_id,
            application_id=application.app_id,
            expected_window_handle=int(window.hwnd),
            expected_process_id=int(window.process_id),
            observed_at=str(window.observed_at),
        )

    def _act_screen_capture(
        self,
        *,
        event_id: str | None,
        args: dict[str, Any],
    ) -> BodyActionResult:
        rejected = sorted(str(key) for key in args)
        if rejected:
            return self._screen_capture_preflight_result(
                event_id,
                False,
                data={
                    "dispatch_sent": False,
                    "rejected_arguments": rejected,
                },
                error=(
                    "windows_screen_capture accepts no caller-controlled "
                    "arguments; ZN owns the artifact path"
                ),
            )
        if not str(event_id or "").strip():
            return self._screen_capture_preflight_result(
                event_id,
                False,
                data={"dispatch_sent": False},
                error="windows_screen_capture requires a stable event_id",
            )
        return super().act(
            self._SCREEN_CAPTURE_KIND,
            event_id=event_id,
            **{self._SCREEN_CAPTURE_DISPATCH_MARKER: True},
        )

    def activate_admitted_application_window(
        self,
        *,
        event_id: str | None,
        application_id: str,
        expected_window_handle: int,
        expected_process_id: int,
        observed_at: str | None = None,
    ) -> BodyActionResult:
        """Enter activation with one Resident-admitted exact application target.

        This is an internal Resident/runtime seam, not the public ``act`` schema.
        The public action continues to accept only ``application_id``. Here the
        exact HWND/PID are already authority selected by Resident deliberation;
        fresh machine facts may confirm that identity or reject it, but may never
        replace it with another same-application window.
        """

        app_id = str(application_id or "").strip()
        try:
            expected_hwnd = int(expected_window_handle)
            expected_pid = int(expected_process_id)
        except (TypeError, ValueError):
            expected_hwnd = 0
            expected_pid = 0
        base_data = {
            "application_id": app_id,
            "window_handle": expected_hwnd,
            "process_id": expected_pid,
            "dispatch_sent": False,
        }
        if not app_id or expected_hwnd <= 0 or expected_pid <= 0:
            return self._preflight_result(
                self._ACTIVATE_KIND, event_id, app_id, False,
                data={**base_data, "disposition": "invalid_admitted_target"},
                error="resident-admitted application activation requires a non-empty app id and positive HWND/PID",
            )

        application = self.device_capabilities.application_by_id(app_id, force_refresh=True)
        if application is None or application.app_id != app_id:
            return self._preflight_result(
                self._ACTIVATE_KIND, event_id, app_id, False,
                data={**base_data, "disposition": "admitted_application_drift"},
                error="resident-admitted application identity is no longer present in fresh inventory",
            )

        processes, windows = self.device_capabilities.application_runtime(application)
        exact_process = next(
            (
                process
                for process in processes
                if process.process_id == expected_pid and process.resolved_app_id == app_id
            ),
            None,
        )
        visible = tuple(
            window
            for window in windows
            if window.visible and window.resolved_app_id == app_id
        )
        exact_window = next(
            (
                window
                for window in visible
                if window.hwnd == expected_hwnd
                and window.process_id == expected_pid
                and window.resolved_app_id == app_id
            ),
            None,
        )
        if exact_process is None:
            return self._preflight_result(
                self._ACTIVATE_KIND, event_id, app_id, False,
                data={**base_data, "disposition": "admitted_process_drift"},
                error="resident-admitted activation PID is no longer the same application process",
            )
        if len(visible) != 1:
            return self._preflight_result(
                self._ACTIVATE_KIND, event_id, app_id, False,
                data={
                    **base_data,
                    "disposition": "admitted_window_topology_drift",
                    "window_handles": [window.hwnd for window in visible],
                },
                error="visible application-window topology changed after Resident admission; re-investigation is required",
            )
        if exact_window is None:
            current = visible[0]
            return self._preflight_result(
                self._ACTIVATE_KIND, event_id, app_id, False,
                data={
                    **base_data,
                    "disposition": "admitted_window_identity_drift",
                    "observed_window_handle": current.hwnd,
                    "observed_process_id": current.process_id,
                },
                error="the unique visible application window no longer matches the Resident-admitted HWND/PID",
            )

        return super().act(
            self._ACTIVATE_KIND,
            event_id=event_id,
            application_id=application.app_id,
            **{
                self._ACTIVATE_DISPATCH_MARKER: True,
                self._ACTIVATE_WINDOW_ARG: expected_hwnd,
                self._ACTIVATE_PROCESS_ARG: expected_pid,
                self._ACTIVATE_OBSERVED_AT_ARG: str(observed_at or exact_window.observed_at),
            },
        )

    @classmethod
    def _requires_guard(cls, kind: str, args: dict[str, Any]) -> bool:
        if kind == cls._LAUNCH_KIND:
            return args.get(cls._LAUNCH_DISPATCH_MARKER) is True
        if kind == cls._ACTIVATE_KIND:
            return args.get(cls._ACTIVATE_DISPATCH_MARKER) is True
        if kind == cls._SCREEN_CAPTURE_KIND:
            return args.get(cls._SCREEN_CAPTURE_DISPATCH_MARKER) is True
        return super()._requires_guard(kind, args)

    @classmethod
    def _signature_hash(cls, kind: str, args: dict[str, Any]) -> str:
        if kind == cls._ACTIVATE_KIND:
            # Observation timestamps are audit evidence, not replay identity.
            # Keep the exact app/HWND/PID stable so a fresh observation of the
            # same target cannot bypass the existing side-effect journal.
            stable = dict(args)
            stable.pop(cls._ACTIVATE_OBSERVED_AT_ARG, None)
            return super()._signature_hash(kind, stable)
        return super()._signature_hash(kind, args)

    def _record(self, action: BodyAction, result: BodyActionResult) -> None:
        private_args: tuple[str, ...] = ()
        if action.kind == self._LAUNCH_KIND:
            private_args = (self._LAUNCH_DISPATCH_MARKER,)
        elif action.kind == self._ACTIVATE_KIND:
            private_args = (
                self._ACTIVATE_DISPATCH_MARKER,
                self._ACTIVATE_WINDOW_ARG,
                self._ACTIVATE_PROCESS_ARG,
                self._ACTIVATE_OBSERVED_AT_ARG,
            )
        elif action.kind == self._SCREEN_CAPTURE_KIND:
            private_args = (self._SCREEN_CAPTURE_DISPATCH_MARKER,)
        if private_args and any(key in action.args for key in private_args):
            safe_args = dict(action.args)
            for key in private_args:
                safe_args.pop(key, None)
            action = BodyAction(
                action_id=action.action_id, kind=action.kind, args=safe_args,
                event_id=action.event_id, created_at=action.created_at,
            )
        super()._record(action, result)

    def _dispatch(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.kind == self._LAUNCH_KIND:
            return self._dispatch_launch(action, started)
        if action.kind == self._ACTIVATE_KIND:
            return self._dispatch_activation(action, started)
        if action.kind == self._SCREEN_CAPTURE_KIND:
            return self._dispatch_screen_capture(action, started)
        return super()._dispatch(action, started)

    def _dispatch_launch(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.args.get(self._LAUNCH_DISPATCH_MARKER) is not True:
            raise PermissionError("launch_application dispatch did not pass machine-fact preflight")

        app_id = str(action.args.get("application_id") or "").strip()
        application = self.device_capabilities.application_by_id(app_id, force_refresh=True)
        if application is None:
            return self._result(action, started, False, {"application_id": app_id, "dispatch_sent": False}, "application disappeared from fresh inventory before launch dispatch")
        if not application.launchable:
            return self._result(action, started, False, {"application_id": app_id, "dispatch_sent": False}, "application lost its safe launch target before dispatch")

        # Recheck immediately after the side-effect guard starts. A race may have
        # made the app visible; that must not manufacture a second instance.
        processes, windows = self.device_capabilities.application_runtime(application)
        visible = tuple(window for window in windows if window.visible)
        if visible:
            return self._result(
                action, started, True,
                {
                    "application_id": app_id, "canonical_name": application.canonical_name,
                    "launch_kind": application.launch_kind, "dispatch_sent": False,
                    "disposition": "already_running_race",
                    "process_ids": [row.process_id for row in processes],
                    "window_handles": [row.hwnd for row in visible],
                },
                output=f"{application.canonical_name} is already running",
            )
        if processes:
            return self._result(
                action, started, False,
                {
                    "application_id": app_id, "canonical_name": application.canonical_name,
                    "launch_kind": application.launch_kind, "dispatch_sent": False,
                    "disposition": "already_running_without_visible_window",
                    "process_ids": [row.process_id for row in processes],
                },
                "application became running without a visible window before dispatch; refusing a duplicate launch",
            )

        pid = self._dispatch_resolved_application(application)
        return self._result(
            action, started, True,
            {
                "application_id": app_id, "canonical_name": application.canonical_name,
                "launch_kind": application.launch_kind, "dispatch_sent": True,
                "disposition": "dispatch_succeeded", "dispatched_process_id": pid,
            },
            output=f"launch dispatch accepted for {application.canonical_name}",
        )

    def _dispatch_activation(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.args.get(self._ACTIVATE_DISPATCH_MARKER) is not True:
            raise PermissionError("activate_application_window dispatch did not pass machine-fact preflight")

        app_id = str(action.args.get("application_id") or "").strip()
        expected_hwnd = int(action.args.get(self._ACTIVATE_WINDOW_ARG) or 0)
        expected_pid = int(action.args.get(self._ACTIVATE_PROCESS_ARG) or 0)
        observed_at = str(action.args.get(self._ACTIVATE_OBSERVED_AT_ARG) or "")
        application = self.device_capabilities.application_by_id(app_id, force_refresh=True)
        base_data = {
            "application_id": app_id,
            "window_handle": expected_hwnd,
            "process_id": expected_pid,
            "preflight_observed_at": observed_at,
            "dispatch_sent": False,
        }
        if application is None:
            return self._result(
                action, started, False, base_data,
                "resolved application identity disappeared before activation dispatch",
            )
        base_data["canonical_name"] = application.canonical_name

        processes, windows = self.device_capabilities.application_runtime(application)
        exact_process = next(
            (
                row for row in processes
                if row.process_id == expected_pid and row.resolved_app_id == app_id
            ),
            None,
        )
        exact_window = next((row for row in windows if row.hwnd == expected_hwnd), None)
        if exact_process is None:
            return self._result(
                action, started, False,
                {**base_data, "disposition": "stale_process_identity"},
                "exact activation process identity is no longer present in fresh application runtime",
            )
        if exact_window is None:
            return self._result(
                action, started, False,
                {**base_data, "disposition": "stale_window_handle"},
                "exact preflight HWND disappeared before activation dispatch; refusing silent retarget",
            )
        if exact_window.process_id != expected_pid:
            return self._result(
                action, started, False,
                {**base_data, "observed_process_id": exact_window.process_id, "disposition": "stale_window_process"},
                "exact preflight HWND now belongs to a different process; refusing activation",
            )
        if exact_window.resolved_app_id != app_id:
            return self._result(
                action, started, False,
                {**base_data, "observed_application_id": exact_window.resolved_app_id, "disposition": "stale_window_application"},
                "exact preflight HWND no longer resolves to the admitted application identity",
            )
        if not exact_window.visible:
            return self._result(
                action, started, False,
                {**base_data, "disposition": "window_became_hidden"},
                "exact preflight HWND is no longer visible; refusing activation",
            )

        visible_matching = tuple(
            window
            for window in windows
            if window.visible and window.resolved_app_id == app_id
        )
        if (
            len(visible_matching) != 1
            or visible_matching[0].hwnd != expected_hwnd
            or visible_matching[0].process_id != expected_pid
        ):
            return self._result(
                action, started, False,
                {
                    **base_data,
                    "disposition": "window_topology_changed",
                    "window_handles": [window.hwnd for window in visible_matching],
                },
                "visible application-window topology changed before native activation; refusing old authority",
            )
        if exact_window.foreground:
            return self._result(
                action, started, True,
                {**base_data, "disposition": "already_foreground_race"},
                output=f"{application.canonical_name} became foreground before activation dispatch",
            )

        native = self._native_activate_exact_application_window(expected_hwnd, expected_pid)
        data = {
            **base_data,
            "was_minimized": bool(native.get("was_minimized")),
            "restore_requested": bool(native.get("restore_requested")),
            "restore_returned_true": bool(native.get("restore_returned_true")),
            "set_foreground_returned_true": bool(native.get("set_foreground_returned_true")),
            "dispatch_sent": bool(native.get("dispatch_sent")),
            "disposition": str(native.get("disposition") or "activation_requested"),
        }
        if not bool(native.get("success")):
            return self._result(
                action, started, False, data,
                str(native.get("error") or "native application window activation failed"),
            )
        return self._result(
            action, started, True, data,
            output=f"foreground activation requested for {application.canonical_name}",
        )

    def _dispatch_screen_capture(
        self,
        action: BodyAction,
        started: str,
    ) -> BodyActionResult:
        if action.args.get(self._SCREEN_CAPTURE_DISPATCH_MARKER) is not True:
            raise PermissionError(
                "windows_screen_capture dispatch did not pass ZN artifact preflight"
            )
        event_id = str(action.event_id or "").strip()
        artifact = self._native_capture_primary_screen(event_id)
        return self._result(
            action,
            started,
            True,
            {
                "artifact_created": True,
                "dispatch_sent": True,
                "local_path": artifact.local_path,
                "width": artifact.width,
                "height": artifact.height,
                "size_bytes": artifact.size_bytes,
                "sha256": artifact.sha256,
                "source": artifact.source,
            },
            output="captured the primary screen to a ZN-owned artifact",
        )

    @staticmethod
    def _native_capture_primary_screen(event_id: str) -> ScreenCaptureArtifact:
        return capture_primary_screen_artifact(event_id)

    @staticmethod
    def _native_activate_exact_application_window(hwnd: int, expected_pid: int) -> dict[str, Any]:
        return _activate_exact_application_window(hwnd, expected_pid)

    def _screen_capture_preflight_result(
        self,
        event_id: str | None,
        success: bool,
        *,
        data: dict[str, Any],
        error: str | None = None,
    ) -> BodyActionResult:
        action = BodyAction(
            action_id=f"body-{uuid.uuid4().hex[:12]}",
            kind=self._SCREEN_CAPTURE_KIND,
            args={},
            event_id=event_id,
        )
        started = utc_now()
        result = BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=success,
            data=data,
            error=error,
            event_id=event_id,
            started_at=started,
            completed_at=utc_now(),
        )
        self._record(action, result)
        return result

    def _preflight_result(
        self,
        kind: str,
        event_id: str | None,
        app_id: str,
        success: bool,
        *,
        data: dict[str, Any],
        error: str | None = None,
        output: str = "",
    ) -> BodyActionResult:
        action = BodyAction(
            action_id=f"body-{uuid.uuid4().hex[:12]}", kind=kind,
            args={"application_id": app_id} if app_id else {}, event_id=event_id,
        )
        started = utc_now()
        result = BodyActionResult(
            action_id=action.action_id, kind=action.kind, success=success,
            output=output, data=data, error=error, event_id=event_id,
            started_at=started, completed_at=utc_now(),
        )
        self._record(action, result)
        return result

    @staticmethod
    def _result(
        action: BodyAction,
        started: str,
        success: bool,
        data: dict[str, Any],
        error: str | None = None,
        *,
        output: str = "",
    ) -> BodyActionResult:
        return BodyActionResult(
            action_id=action.action_id, kind=action.kind, success=success,
            output=output, data=data, error=error, event_id=action.event_id,
            started_at=started, completed_at=utc_now(),
        )

    @staticmethod
    def _dispatch_resolved_application(application: InstalledApplication) -> int | None:
        if platform.system() != "Windows":
            raise RuntimeError("application launch is currently supported only on Windows")
        target = str(application.launch_target or "").strip()
        if not target:
            raise ValueError("resolved application has no launch target")
        if application.launch_kind == "aumid":
            target = "shell:AppsFolder\\" + target
        elif application.launch_kind not in {"executable", "shell_item"}:
            raise ValueError(f"unsupported resolved launch kind: {application.launch_kind}")
        return _shell_execute_exact_target(target)


class _WindowsUser32ActivationApi:
    """Small injectable Win32 boundary for exact-window activation."""

    SW_RESTORE = 9

    def __init__(self) -> None:
        if platform.system() != "Windows":
            raise RuntimeError("application window activation is currently supported only on Windows")
        from ctypes import wintypes

        self._wintypes = wintypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._user32.IsWindow.restype = wintypes.BOOL
        self._user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self._user32.IsWindowVisible.restype = wintypes.BOOL
        self._user32.IsIconic.argtypes = [wintypes.HWND]
        self._user32.IsIconic.restype = wintypes.BOOL
        self._user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.ShowWindowAsync.restype = wintypes.BOOL
        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.SetForegroundWindow.restype = wintypes.BOOL

    def is_window(self, hwnd: int) -> bool:
        return bool(self._user32.IsWindow(int(hwnd)))

    def window_process_id(self, hwnd: int) -> int:
        pid = self._wintypes.DWORD(0)
        self._user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
        return int(pid.value)

    def is_window_visible(self, hwnd: int) -> bool:
        return bool(self._user32.IsWindowVisible(int(hwnd)))

    def is_iconic(self, hwnd: int) -> bool:
        return bool(self._user32.IsIconic(int(hwnd)))

    def show_window_async(self, hwnd: int, command: int) -> bool:
        return bool(self._user32.ShowWindowAsync(int(hwnd), int(command)))

    def set_foreground_window(self, hwnd: int) -> bool:
        return bool(self._user32.SetForegroundWindow(int(hwnd)))


def _activate_exact_application_window(
    hwnd: int,
    expected_pid: int,
    *,
    api: Any | None = None,
) -> dict[str, Any]:
    """Validate and request activation for one already-authorized exact HWND.

    Windows may reject ``SetForegroundWindow`` by policy. No keyboard/input hack,
    thread-input attachment, taskbar click, coordinate click, or retry is used to
    bypass that policy. The return value is dispatch evidence only; Resident owns
    the subsequent fresh foreground postcondition proof.
    """

    native = api or _WindowsUser32ActivationApi()
    if not native.is_window(hwnd):
        return {
            "success": False, "dispatch_sent": False,
            "disposition": "native_window_missing",
            "error": "exact HWND is no longer a valid native window",
        }
    observed_pid = int(native.window_process_id(hwnd) or 0)
    if observed_pid != int(expected_pid):
        return {
            "success": False, "dispatch_sent": False,
            "disposition": "native_process_mismatch", "observed_process_id": observed_pid,
            "error": "exact HWND no longer belongs to the expected process",
        }
    if not native.is_window_visible(hwnd):
        return {
            "success": False, "dispatch_sent": False,
            "disposition": "native_window_hidden",
            "error": "exact HWND is no longer visible",
        }

    minimized = bool(native.is_iconic(hwnd))
    restore_requested = False
    restore_returned_true = False
    dispatch_sent = False
    if minimized:
        restore_requested = True
        restore_returned_true = bool(native.show_window_async(hwnd, native.SW_RESTORE))
        dispatch_sent = True

    foreground_returned_true = bool(native.set_foreground_window(hwnd))
    dispatch_sent = True
    data = {
        "success": foreground_returned_true,
        "dispatch_sent": dispatch_sent,
        "was_minimized": minimized,
        "restore_requested": restore_requested,
        "restore_returned_true": restore_returned_true,
        "set_foreground_returned_true": foreground_returned_true,
        "disposition": "activation_requested" if foreground_returned_true else "foreground_policy_rejected",
    }
    if not foreground_returned_true:
        data["error"] = (
            "Windows did not accept SetForegroundWindow for the exact existing application window; "
            "foreground policy was not bypassed"
        )
    return data


def _shell_execute_exact_target(target: str) -> int | None:
    """ShellExecuteEx one already-resolved target; never construct shell text."""

    from ctypes import wintypes

    class ShellExecuteInfoW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", wintypes.LPVOID), ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
        ]

    ole32 = ctypes.OleDLL("ole32")
    ole32.CoInitializeEx.argtypes = [wintypes.LPVOID, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    # ShellExecuteEx may delegate to COM shell extensions. Microsoft documents
    # that callers should initialize COM first; STA is the broadly compatible
    # apartment for shell extensions.
    hr = int(ole32.CoInitializeEx(None, 0x2))  # COINIT_APARTMENTTHREADED
    co_initialized = hr in (0, 1)  # S_OK / S_FALSE both require CoUninitialize.

    info = ShellExecuteInfoW()
    info.cbSize = ctypes.sizeof(ShellExecuteInfoW)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "open"
    info.lpFile = target
    info.nShow = 1  # SW_SHOWNORMAL
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfoW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    try:
        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            code = ctypes.get_last_error()
            raise OSError(code, f"ShellExecuteExW rejected resolved application target: WinError {code}")
        if not info.hProcess:
            return None
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetProcessId.argtypes = [wintypes.HANDLE]
        kernel32.GetProcessId.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        try:
            pid = int(kernel32.GetProcessId(info.hProcess) or 0)
            return pid or None
        finally:
            kernel32.CloseHandle(info.hProcess)
            info.hProcess = None
    finally:
        if co_initialized:
            ole32.CoUninitialize()
