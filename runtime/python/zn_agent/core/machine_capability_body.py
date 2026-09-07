from __future__ import annotations

"""Identity-bound application launch through ZN's existing durable Body."""

import ctypes
import platform
import uuid
from typing import Any

from .body import BodyAction, BodyActionResult
from .browser_form_submit_body import BrowserFormSubmitBody
from .machine_capability import DeviceCapabilityGraph, InstalledApplication
from .models import utc_now


class MachineCapabilityBody(BrowserFormSubmitBody):
    """Extend the current final Body with one safe application launch movement.

    The caller supplies only ``application_id``.  Raw executable paths, command
    strings, parameters, protocols and URLs are not action authority.  The exact
    native launch target is re-read from fresh DeviceCapabilityGraph facts at the
    final dispatch boundary, and the inherited side-effect journal prevents blind
    replay after uncertain/observed dispatch.
    """

    _LAUNCH_KIND = "launch_application"
    _DISPATCH_MARKER = "__zn_machine_launch_dispatch_admitted"
    _FORBIDDEN_LAUNCH_ARGS = frozenset({
        "path", "executable", "executable_path", "command", "shell", "launch_target",
        "parameters", "args", "arguments", "protocol", "url",
    })

    def __init__(self, *args, device_capabilities: DeviceCapabilityGraph | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.device_capabilities = device_capabilities or DeviceCapabilityGraph()

    def act(self, kind: str, *, event_id: str | None = None, **args: Any) -> BodyActionResult:
        normalized = str(kind or "").strip().lower()
        if normalized != self._LAUNCH_KIND:
            return super().act(kind, event_id=event_id, **args)

        # Never trust a caller-supplied internal marker.
        args.pop(self._DISPATCH_MARKER, None)
        forbidden = sorted(key for key in args if str(key).casefold() in self._FORBIDDEN_LAUNCH_ARGS)
        app_id = str(args.get("application_id") or "").strip()
        if forbidden:
            return self._preflight_result(
                event_id, app_id, False,
                data={"dispatch_sent": False, "rejected_arguments": forbidden},
                error=("launch_application accepts only a resolved application_id; raw launch material is not action authority: " + ", ".join(forbidden)),
            )
        if not app_id:
            return self._preflight_result(event_id, "", False, data={"dispatch_sent": False}, error="launch_application requires a resolved application_id")

        application = self.device_capabilities.application_by_id(app_id, force_refresh=True)
        if application is None:
            return self._preflight_result(event_id, app_id, False, data={"dispatch_sent": False, "disposition": "not_installed"}, error="resolved application identity is no longer installed")
        if not application.launchable:
            return self._preflight_result(event_id, app_id, False, data={"dispatch_sent": False, "disposition": "not_launchable"}, error="installed application has no safe launch target in current machine evidence")

        processes, windows = self.device_capabilities.application_runtime(application)
        visible = tuple(window for window in windows if window.visible)
        if visible:
            return self._preflight_result(
                event_id, app_id, True,
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
                event_id, app_id, False,
                data={
                    "application_id": app_id, "canonical_name": application.canonical_name,
                    "dispatch_sent": False, "disposition": "already_running_without_visible_window",
                    "process_ids": [row.process_id for row in processes],
                },
                error=("application is already running without a currently visible top-level window; focus/activation is not implemented in V1, so ZN refuses a duplicate launch"),
            )

        return super().act(
            normalized,
            event_id=event_id,
            application_id=application.app_id,
            **{self._DISPATCH_MARKER: True},
        )

    @classmethod
    def _requires_guard(cls, kind: str, args: dict[str, Any]) -> bool:
        if kind == cls._LAUNCH_KIND:
            return args.get(cls._DISPATCH_MARKER) is True
        return super()._requires_guard(kind, args)

    def _record(self, action: BodyAction, result: BodyActionResult) -> None:
        if action.kind == self._LAUNCH_KIND and self._DISPATCH_MARKER in action.args:
            safe_args = dict(action.args)
            safe_args.pop(self._DISPATCH_MARKER, None)
            action = BodyAction(
                action_id=action.action_id, kind=action.kind, args=safe_args,
                event_id=action.event_id, created_at=action.created_at,
            )
        super()._record(action, result)

    def _dispatch(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.kind != self._LAUNCH_KIND:
            return super()._dispatch(action, started)
        if action.args.get(self._DISPATCH_MARKER) is not True:
            raise PermissionError("launch_application dispatch did not pass machine-fact preflight")

        app_id = str(action.args.get("application_id") or "").strip()
        application = self.device_capabilities.application_by_id(app_id, force_refresh=True)
        if application is None:
            return self._result(action, started, False, {"application_id": app_id, "dispatch_sent": False}, "application disappeared from fresh inventory before launch dispatch")
        if not application.launchable:
            return self._result(action, started, False, {"application_id": app_id, "dispatch_sent": False}, "application lost its safe launch target before dispatch")

        # Recheck immediately after the side-effect guard starts.  A race may have
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

    def _preflight_result(
        self,
        event_id: str | None,
        app_id: str,
        success: bool,
        *,
        data: dict[str, Any],
        error: str | None = None,
        output: str = "",
    ) -> BodyActionResult:
        action = BodyAction(
            action_id=f"body-{uuid.uuid4().hex[:12]}", kind=self._LAUNCH_KIND,
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

    info = ShellExecuteInfoW()
    info.cbSize = ctypes.sizeof(ShellExecuteInfoW)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "open"
    info.lpFile = target
    info.nShow = 1  # SW_SHOWNORMAL
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfoW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
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
