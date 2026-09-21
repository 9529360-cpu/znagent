from __future__ import annotations

"""General semantic GUI control through ZN's existing machine Body.

This layer admits exact foreground application identity, then delegates one
semantic UIA control mutation to the native control-pattern driver. It does not
own planning, task loops, application routing, or a second action store.
"""

import uuid
from typing import Any

from .automation_control_action import (
    AutomationControlObservation,
    AutomationControlSelector,
    NativeAutomationControlAction,
    text_sha256,
)
from .automation_named_control_sense import NativeNamedAutomationControlSense
from .body import BodyAction, BodyActionResult
from .machine_capability_body import MachineCapabilityBody
from .models import utc_now


class GuiAutomationBody(MachineCapabilityBody):
    _LIST_KIND = "automation_controls_list"
    _READ_KIND = "automation_control_read"
    _SET_VALUE_KIND = "automation_control_set_value"
    _TOGGLE_KIND = "automation_control_toggle"
    _EXPAND_COLLAPSE_KIND = "automation_control_expand_collapse"
    _SELECT_KIND = "automation_control_select"
    _GUI_KINDS = frozenset(
        {
            _SET_VALUE_KIND,
            _TOGGLE_KIND,
            _EXPAND_COLLAPSE_KIND,
            _SELECT_KIND,
        }
    )
    _DISPATCH_MARKER = "__zn_gui_control_dispatch_admitted"
    _WINDOW_ARG = "__zn_gui_control_window_handle"
    _PROCESS_ARG = "__zn_gui_control_process_id"
    _PROCESS_NAME_ARG = "__zn_gui_control_process_name"
    _OBSERVED_AT_ARG = "__zn_gui_control_observed_at"
    _PRIVATE_ARGS = frozenset(
        {
            _DISPATCH_MARKER,
            _WINDOW_ARG,
            _PROCESS_ARG,
            _PROCESS_NAME_ARG,
            _OBSERVED_AT_ARG,
        }
    )

    def __init__(
        self,
        *args,
        automation_control: NativeAutomationControlAction | None = None,
        automation_control_sense: NativeNamedAutomationControlSense | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._automation_control = automation_control or NativeAutomationControlAction()
        self._automation_control_sense = automation_control_sense or NativeNamedAutomationControlSense()

    def act(self, kind: str, *, event_id: str | None = None, **args: Any) -> BodyActionResult:
        normalized = str(kind or "").strip().lower()
        if normalized == self._LIST_KIND:
            return self._act_gui_list(event_id=event_id, args=dict(args))
        if normalized == self._READ_KIND:
            return self._act_gui_read(event_id=event_id, args=dict(args))
        if normalized in self._GUI_KINDS:
            return self._act_gui_control(normalized, event_id=event_id, args=dict(args))
        return super().act(kind, event_id=event_id, **args)

    def observe_automation_control(
        self,
        *,
        application_id: str,
        control_type: str,
        control_name: str = "",
        automation_id: str = "",
        pattern: str,
    ) -> AutomationControlObservation:
        app_id = str(application_id or "").strip()
        selector = AutomationControlSelector(
            control_type=control_type,
            name=control_name,
            automation_id=automation_id,
        )
        _, process, window = self._foreground_target(app_id)
        return self._automation_control.read(
            process_id=process.process_id,
            process_name=process.process_name,
            window_handle=window.hwnd,
            selector=selector,
            pattern=pattern,
        )

    def _act_gui_list(
        self,
        *,
        event_id: str | None,
        args: dict[str, Any],
    ) -> BodyActionResult:
        allowed = {"application_id", "control_type"}
        rejected = sorted(key for key in args if key not in allowed)
        app_id = str(args.get("application_id") or "").strip()
        if rejected:
            return self._gui_preflight_result(
                self._LIST_KIND,
                event_id,
                app_id,
                False,
                data={"rejected_arguments": rejected},
                error=(
                    "GUI control inventory accepts only application_id/control_type: "
                    + ", ".join(rejected)
                ),
            )
        try:
            _application, process, _window = self._foreground_target(app_id)
            controls = self._automation_control_sense.list_controls(
                process_id=process.process_id,
                process_name=process.process_name,
                control_type=str(args.get("control_type") or ""),
            )
        except Exception as exc:
            return self._gui_preflight_result(
                self._LIST_KIND,
                event_id,
                app_id,
                False,
                data={},
                error=f"GUI control inventory failed: {type(exc).__name__}: {exc}",
            )
        rows = [
            {
                "runtime_id": list(item.runtime_id),
                "name": item.name,
                "automation_id": item.automation_id,
                "control_type": item.control_type,
                "class_name": item.class_name,
                "is_keyboard_focusable": item.is_keyboard_focusable,
                "has_keyboard_focus": item.has_keyboard_focus,
                "is_password": item.is_password,
                "supported_patterns": list(item.supported_patterns),
                "center_x_fraction": item.center_x_fraction,
                "center_y_fraction": item.center_y_fraction,
                "captured_at": item.captured_at,
            }
            for item in controls
        ]
        action = BodyAction(
            action_id=f"body-{uuid.uuid4().hex[:12]}",
            kind=self._LIST_KIND,
            args={
                "application_id": app_id,
                "control_type": str(args.get("control_type") or "").strip(),
            },
            event_id=event_id,
        )
        started = utc_now()
        result = BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            data={
                "application_id": app_id,
                "control_type": str(args.get("control_type") or "").strip(),
                "count": len(rows),
                "controls": rows,
            },
            event_id=event_id,
            started_at=started,
            completed_at=utc_now(),
        )
        self._record(action, result)
        return result


    def _act_gui_read(
        self,
        *,
        event_id: str | None,
        args: dict[str, Any],
    ) -> BodyActionResult:
        allowed = {
            "application_id",
            "control_type",
            "control_name",
            "automation_id",
            "pattern",
        }
        rejected = sorted(key for key in args if key not in allowed)
        app_id = str(args.get("application_id") or "").strip()
        if rejected:
            return self._gui_preflight_result(
                self._READ_KIND,
                event_id,
                app_id,
                False,
                data={"rejected_arguments": rejected},
                error=(
                    "GUI control read accepts only semantic selector/pattern fields: "
                    + ", ".join(rejected)
                ),
            )
        try:
            observation = self.observe_automation_control(
                application_id=app_id,
                control_type=str(args.get("control_type") or ""),
                control_name=str(args.get("control_name") or ""),
                automation_id=str(args.get("automation_id") or ""),
                pattern=str(args.get("pattern") or ""),
            )
        except Exception as exc:
            return self._gui_preflight_result(
                self._READ_KIND,
                event_id,
                app_id,
                False,
                data={},
                error=f"GUI control read failed: {type(exc).__name__}: {exc}",
            )
        action = BodyAction(
            action_id=f"body-{uuid.uuid4().hex[:12]}",
            kind=self._READ_KIND,
            args={
                "application_id": app_id,
                "control_type": observation.selector.control_type,
                "control_name": observation.selector.name,
                "automation_id": observation.selector.automation_id,
                "pattern": observation.pattern,
            },
            event_id=event_id,
        )
        started = utc_now()
        result = BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            data={"application_id": app_id, **observation.audit()},
            event_id=event_id,
            started_at=started,
            completed_at=utc_now(),
        )
        self._record(action, result)
        return result


    def _act_gui_control(
        self,
        kind: str,
        *,
        event_id: str | None,
        args: dict[str, Any],
    ) -> BodyActionResult:
        allowed = {"application_id", "control_type", "control_name", "automation_id"}
        if kind == self._SET_VALUE_KIND:
            allowed.add("value")
        elif kind in {self._TOGGLE_KIND, self._EXPAND_COLLAPSE_KIND}:
            allowed.add("state")
        rejected = sorted(key for key in args if key not in allowed)
        app_id = str(args.get("application_id") or "").strip()
        if rejected:
            return self._gui_preflight_result(
                kind,
                event_id,
                app_id,
                False,
                data={"dispatch_sent": False, "rejected_arguments": rejected},
                error=(
                    "GUI control action accepts only semantic selector/target fields; "
                    "native HWND/PID/coordinates are not caller authority: "
                    + ", ".join(rejected)
                ),
            )
        if not app_id:
            return self._gui_preflight_result(
                kind,
                event_id,
                app_id,
                False,
                data={"dispatch_sent": False},
                error="GUI control action requires a resolved application_id",
            )

        try:
            selector = AutomationControlSelector(
                control_type=str(args.get("control_type") or ""),
                name=str(args.get("control_name") or ""),
                automation_id=str(args.get("automation_id") or ""),
            )
            target = self._target_for(kind, args)
            application, process, window = self._foreground_target(app_id)
        except Exception as exc:
            return self._gui_preflight_result(
                kind,
                event_id,
                app_id,
                False,
                data={"dispatch_sent": False},
                error=f"GUI control preflight failed: {type(exc).__name__}: {exc}",
            )

        return super().act(
            kind,
            event_id=event_id,
            application_id=application.app_id,
            control_type=selector.control_type,
            control_name=selector.name,
            automation_id=selector.automation_id,
            **({"value": target} if kind == self._SET_VALUE_KIND else {}),
            **(
                {"state": target}
                if kind in {self._TOGGLE_KIND, self._EXPAND_COLLAPSE_KIND}
                else {}
            ),
            **{
                self._DISPATCH_MARKER: True,
                self._WINDOW_ARG: int(window.hwnd),
                self._PROCESS_ARG: int(process.process_id),
                self._PROCESS_NAME_ARG: str(process.process_name),
                self._OBSERVED_AT_ARG: str(window.observed_at),
            },
        )

    @classmethod
    def _target_for(cls, kind: str, args: dict[str, Any]) -> str:
        if kind == cls._SET_VALUE_KIND:
            value = args.get("value")
            if not isinstance(value, str):
                raise ValueError("GUI ValuePattern action requires string value")
            if len(value) > 4096:
                raise ValueError("GUI ValuePattern value exceeds 4096 characters")
            return value
        if kind == cls._TOGGLE_KIND:
            state = str(args.get("state") or "").strip().lower()
            if state not in {"on", "off"}:
                raise ValueError("GUI TogglePattern action state must be on or off")
            return state
        if kind == cls._EXPAND_COLLAPSE_KIND:
            state = str(args.get("state") or "").strip().lower().replace("-", "_")
            if state not in {"expanded", "collapsed"}:
                raise ValueError(
                    "GUI ExpandCollapsePattern action state must be expanded or collapsed"
                )
            return state
        if kind == cls._SELECT_KIND:
            return "selected"
        raise ValueError(f"unsupported GUI control action kind: {kind}")

    def _foreground_target(self, app_id: str):
        application = self.device_capabilities.application_by_id(app_id, force_refresh=True)
        if application is None:
            raise RuntimeError("resolved application identity is no longer installed")
        processes, windows = self.device_capabilities.application_runtime(application)
        foreground = tuple(
            window
            for window in windows
            if window.visible
            and window.foreground
            and window.resolved_app_id == application.app_id
        )
        if len(foreground) != 1:
            raise RuntimeError(
                "GUI control action requires exactly one current foreground window for the admitted application"
            )
        window = foreground[0]
        process = next(
            (
                row
                for row in processes
                if row.process_id == window.process_id
                and row.resolved_app_id == application.app_id
            ),
            None,
        )
        if process is None:
            raise RuntimeError(
                "foreground application window lacks one current matching process identity"
            )
        return application, process, window

    @classmethod
    def _requires_guard(cls, kind: str, args: dict[str, Any]) -> bool:
        if kind in cls._GUI_KINDS:
            return args.get(cls._DISPATCH_MARKER) is True
        return super()._requires_guard(kind, args)

    @classmethod
    def _signature_hash(cls, kind: str, args: dict[str, Any]) -> str:
        if kind in cls._GUI_KINDS:
            stable = dict(args)
            for key in cls._PRIVATE_ARGS:
                stable.pop(key, None)
            return super()._signature_hash(kind, stable)
        return super()._signature_hash(kind, args)

    def _record(self, action: BodyAction, result: BodyActionResult) -> None:
        if action.kind in self._GUI_KINDS:
            safe_args = dict(action.args)
            for key in self._PRIVATE_ARGS:
                safe_args.pop(key, None)
            if action.kind == self._SET_VALUE_KIND and "value" in safe_args:
                raw = str(safe_args.pop("value"))
                safe_args["value_redacted"] = True
                safe_args["value_chars"] = len(raw)
                safe_args["value_sha256"] = text_sha256(raw)
            action = BodyAction(
                action_id=action.action_id,
                kind=action.kind,
                args=safe_args,
                event_id=action.event_id,
                created_at=action.created_at,
            )
        super()._record(action, result)

    def _dispatch(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.kind in self._GUI_KINDS:
            return self._dispatch_gui_control(action, started)
        return super()._dispatch(action, started)

    def _dispatch_gui_control(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.args.get(self._DISPATCH_MARKER) is not True:
            raise PermissionError("GUI control dispatch did not pass machine-fact preflight")
        app_id = str(action.args.get("application_id") or "").strip()
        expected_hwnd = int(action.args.get(self._WINDOW_ARG) or 0)
        expected_pid = int(action.args.get(self._PROCESS_ARG) or 0)
        expected_process_name = str(action.args.get(self._PROCESS_NAME_ARG) or "").strip()
        base_data = {
            "application_id": app_id,
            "dispatch_sent": False,
            "postcondition_verified": False,
        }
        try:
            _, process, window = self._foreground_target(app_id)
        except Exception as exc:
            return self._result(
                action,
                started,
                False,
                base_data,
                f"GUI control target changed before dispatch: {type(exc).__name__}: {exc}",
            )
        if (
            int(window.hwnd) != expected_hwnd
            or int(process.process_id) != expected_pid
            or str(process.process_name).strip().lower()
            != expected_process_name.lower()
        ):
            return self._result(
                action,
                started,
                False,
                {
                    **base_data,
                    "disposition": "foreground_identity_changed",
                },
                "GUI control foreground HWND/PID identity changed before dispatch",
            )

        selector = AutomationControlSelector(
            control_type=str(action.args.get("control_type") or ""),
            name=str(action.args.get("control_name") or ""),
            automation_id=str(action.args.get("automation_id") or ""),
        )
        pattern = self._pattern_for_kind(action.kind)
        target = self._target_for(action.kind, dict(action.args))
        result = self._automation_control.mutate(
            process_id=expected_pid,
            process_name=expected_process_name,
            window_handle=expected_hwnd,
            selector=selector,
            pattern=pattern,
            target=target,
        )
        data = {
            **base_data,
            "selector": selector.audit(),
            "pattern": pattern,
            "dispatch_sent": bool(result.mutation_dispatched),
            "postcondition_verified": bool(result.postcondition_verified),
            "side_effect_uncertain": bool(
                result.mutation_dispatched and not result.postcondition_verified
            ),
            "before": result.before.audit() if result.before is not None else None,
            "after": result.after.audit() if result.after is not None else None,
        }
        return self._result(
            action,
            started,
            bool(result.success),
            data,
            result.error,
            output=(
                f"UI Automation {pattern} target state verified"
                if result.success
                else ""
            ),
        )

    @classmethod
    def _pattern_for_kind(cls, kind: str) -> str:
        return {
            cls._SET_VALUE_KIND: "value",
            cls._TOGGLE_KIND: "toggle",
            cls._EXPAND_COLLAPSE_KIND: "expand_collapse",
            cls._SELECT_KIND: "selection_item",
        }[kind]

    def _gui_preflight_result(
        self,
        kind: str,
        event_id: str | None,
        app_id: str,
        success: bool,
        *,
        data: dict[str, Any],
        error: str | None = None,
    ) -> BodyActionResult:
        action = BodyAction(
            action_id=f"body-{uuid.uuid4().hex[:12]}",
            kind=kind,
            args={"application_id": app_id} if app_id else {},
            event_id=event_id,
        )
        started = utc_now()
        result = BodyActionResult(
            action_id=action.action_id,
            kind=kind,
            success=success,
            data=data,
            error=error,
            event_id=event_id,
            started_at=started,
            completed_at=utc_now(),
        )
        self._record(action, result)
        return result
