from __future__ import annotations

"""General semantic GUI control through ZN's existing machine Body.

This layer admits exact foreground application identity, then delegates one
semantic UIA control mutation to the native control-pattern driver. It does not
own planning, task loops, application routing, or a second action store.
"""

import uuid
from pathlib import Path
from typing import Any

from .automation_control_action import (
    AutomationControlObservation,
    AutomationControlSelector,
    NativeAutomationControlAction,
    text_sha256,
)
from .automation_named_control_sense import NativeNamedAutomationControlSense
from .body import BodyAction, BodyActionResult
from .desktop_scene import (
    DesktopSceneForegroundBinding,
    NativeDesktopSceneBuilder,
)
from .machine_capability_body import MachineCapabilityBody
from .models import utc_now


class GuiAutomationBody(MachineCapabilityBody):
    _LIST_KIND = "automation_controls_list"
    _READ_KIND = "automation_control_read"
    _SET_VALUE_KIND = "automation_control_set_value"
    _TYPE_TEXT_KIND = "automation_control_type_text"
    _TOGGLE_KIND = "automation_control_toggle"
    _EXPAND_COLLAPSE_KIND = "automation_control_expand_collapse"
    _SELECT_KIND = "automation_control_select"
    _SCENE_CAPTURE_KIND = "windows_desktop_scene_capture"
    _SCENE_DISPATCH_MARKER = "__zn_desktop_scene_dispatch_admitted"
    _SCENE_WINDOW_ARG = "__zn_desktop_scene_window_handle"
    _SCENE_PROCESS_ARG = "__zn_desktop_scene_process_id"
    _SCENE_PROCESS_NAME_ARG = "__zn_desktop_scene_process_name"
    _SCENE_CLASS_NAME_ARG = "__zn_desktop_scene_class_name"
    _SCENE_PRIVATE_ARGS = frozenset(
        {
            _SCENE_DISPATCH_MARKER,
            _SCENE_WINDOW_ARG,
            _SCENE_PROCESS_ARG,
            _SCENE_PROCESS_NAME_ARG,
            _SCENE_CLASS_NAME_ARG,
        }
    )
    _GUI_KINDS = frozenset(
        {
            _SET_VALUE_KIND,
            _TYPE_TEXT_KIND,
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
        desktop_scene_builder: NativeDesktopSceneBuilder | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._automation_control = automation_control or NativeAutomationControlAction()
        self._automation_control_sense = automation_control_sense or NativeNamedAutomationControlSense()
        self._desktop_scene_builder = desktop_scene_builder or NativeDesktopSceneBuilder(
            automation_sense=self._automation_control_sense,
        )

    def act(self, kind: str, *, event_id: str | None = None, **args: Any) -> BodyActionResult:
        normalized = str(kind or "").strip().lower()
        if normalized == self._LIST_KIND:
            return self._act_gui_list(event_id=event_id, args=dict(args))
        if normalized == self._READ_KIND:
            return self._act_gui_read(event_id=event_id, args=dict(args))
        if normalized == self._SCENE_CAPTURE_KIND:
            return self._act_desktop_scene(event_id=event_id, args=dict(args))
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

    def observe_desktop_scene_foreground(self, *, application_id: str) -> dict[str, Any]:
        """Return privacy-safe fresh foreground identity for scene-bound input guards."""
        app_id = str(application_id or "").strip()
        binding = self._desktop_scene_binding(app_id)
        rect = self._desktop_scene_builder.window_rect_fn(binding.window_handle, binding.process_id)
        return {
            "application_id": binding.application_id,
            "process_name": binding.process_name,
            "class_name": binding.class_name,
            "identity_sha256": binding.identity_sha256,
            "window_rect": rect.audit(),
        }

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
        elif kind == self._TYPE_TEXT_KIND:
            allowed.add("text")
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
            **({"text": target} if kind == self._TYPE_TEXT_KIND else {}),
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

    def _act_desktop_scene(
        self,
        *,
        event_id: str | None,
        args: dict[str, Any],
    ) -> BodyActionResult:
        rejected = sorted(key for key in args if key != "application_id")
        app_id = str(args.get("application_id") or "").strip()
        if rejected:
            return self._gui_preflight_result(
                self._SCENE_CAPTURE_KIND,
                event_id,
                app_id,
                False,
                data={
                    "dispatch_sent": False,
                    "rejected_arguments": rejected,
                },
                error=(
                    "desktop scene capture accepts only application_id; native "
                    "HWND/PID/coordinates are not caller authority: "
                    + ", ".join(rejected)
                ),
            )
        if not app_id:
            return self._gui_preflight_result(
                self._SCENE_CAPTURE_KIND,
                event_id,
                "",
                False,
                data={"dispatch_sent": False},
                error="desktop scene capture requires a resolved application_id",
            )
        normalized_event = str(event_id or "").strip()
        if not normalized_event:
            return self._gui_preflight_result(
                self._SCENE_CAPTURE_KIND,
                event_id,
                app_id,
                False,
                data={"dispatch_sent": False},
                error="desktop scene capture requires a stable event_id",
            )

        artifact_path_fn = getattr(self._desktop_scene_builder, "artifact_path", None)
        if callable(artifact_path_fn):
            try:
                prior_artifact = artifact_path_fn(normalized_event)
            except Exception:
                prior_artifact = None
            if prior_artifact is not None and Path(prior_artifact).is_file():
                # Enter the existing side-effect journal before any fresh foreground
                # requirement. The stable replay signature excludes these transient
                # native placeholders. If no matching prior attempt exists, dispatch
                # still fails closed rather than adopting the artifact as authority.
                return super().act(
                    self._SCENE_CAPTURE_KIND,
                    event_id=normalized_event,
                    application_id=app_id,
                    **{
                        self._SCENE_DISPATCH_MARKER: True,
                        self._SCENE_WINDOW_ARG: 1,
                        self._SCENE_PROCESS_ARG: 1,
                        self._SCENE_PROCESS_NAME_ARG: "artifact-recovery-probe",
                        self._SCENE_CLASS_NAME_ARG: "",
                    },
                )

        try:
            application, process, window = self._foreground_target(app_id)
        except Exception as exc:
            return self._gui_preflight_result(
                self._SCENE_CAPTURE_KIND,
                event_id,
                app_id,
                False,
                data={"dispatch_sent": False},
                error=f"desktop scene preflight failed: {type(exc).__name__}: {exc}",
            )
        return super().act(
            self._SCENE_CAPTURE_KIND,
            event_id=event_id,
            application_id=application.app_id,
            **{
                self._SCENE_DISPATCH_MARKER: True,
                self._SCENE_WINDOW_ARG: int(window.hwnd),
                self._SCENE_PROCESS_ARG: int(process.process_id),
                self._SCENE_PROCESS_NAME_ARG: str(process.process_name),
                self._SCENE_CLASS_NAME_ARG: str(window.class_name or ""),
            },
        )

    def _desktop_scene_binding(
        self,
        app_id: str,
    ) -> DesktopSceneForegroundBinding:
        application, process, window = self._foreground_target(app_id)
        return DesktopSceneForegroundBinding(
            application_id=application.app_id,
            process_id=process.process_id,
            process_name=process.process_name,
            window_handle=window.hwnd,
            class_name=window.class_name,
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
        if kind == cls._TYPE_TEXT_KIND:
            text = args.get("text")
            if not isinstance(text, str):
                raise ValueError("GUI semantic text input requires a string text argument")
            cls.validate_text(text)
            return text
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
        # Installed-app identity is low-churn inventory. Reuse the bounded TTL
        # snapshot here; application_runtime() still reacquires process/window
        # reality on every control action. Dispatch authority never comes from
        # this cache alone.
        application = self.device_capabilities.application_by_id(app_id)
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
        if kind == cls._SCENE_CAPTURE_KIND:
            return args.get(cls._SCENE_DISPATCH_MARKER) is True
        if kind in cls._GUI_KINDS:
            return args.get(cls._DISPATCH_MARKER) is True
        return super()._requires_guard(kind, args)

    @classmethod
    def _signature_hash(cls, kind: str, args: dict[str, Any]) -> str:
        if kind == cls._SCENE_CAPTURE_KIND:
            stable = dict(args)
            for key in cls._SCENE_PRIVATE_ARGS:
                stable.pop(key, None)
            return super()._signature_hash(kind, stable)
        if kind in cls._GUI_KINDS:
            stable = dict(args)
            for key in cls._PRIVATE_ARGS:
                stable.pop(key, None)
            return super()._signature_hash(kind, stable)
        return super()._signature_hash(kind, args)

    def _record(self, action: BodyAction, result: BodyActionResult) -> None:
        if action.kind == self._SCENE_CAPTURE_KIND:
            safe_args = dict(action.args)
            for key in self._SCENE_PRIVATE_ARGS:
                safe_args.pop(key, None)
            action = BodyAction(
                action_id=action.action_id,
                kind=action.kind,
                args=safe_args,
                event_id=action.event_id,
                created_at=action.created_at,
            )
            data = dict(result.data or {})
            scene = data.get("scene") if isinstance(data.get("scene"), dict) else {}
            screenshot = (
                scene.get("screenshot")
                if isinstance(scene.get("screenshot"), dict)
                else {}
            )
            safe_data = {
                "application_id": data.get("application_id"),
                "dispatch_sent": bool(data.get("dispatch_sent")),
                "artifact_created": bool(data.get("artifact_created")),
                "scene_artifact_path": data.get("scene_artifact_path"),
                "scene_id": data.get("scene_id") or scene.get("scene_id"),
                "grounding_mode": data.get("grounding_mode") or scene.get("grounding_mode"),
                "target_count": data.get("target_count"),
                "uia_target_count": data.get("uia_target_count"),
                "visual_target_count": data.get("visual_target_count"),
                "truncated": data.get("truncated"),
                "screenshot_local_path": screenshot.get("local_path"),
                "screenshot_sha256": screenshot.get("sha256"),
                "screenshot_width": screenshot.get("width"),
                "screenshot_height": screenshot.get("height"),
                "scene_payload_redacted": True,
                "side_effect_uncertain": bool(data.get("side_effect_uncertain")),
                "replay_blocked": bool(data.get("replay_blocked")),
            }
            result = BodyActionResult(
                action_id=result.action_id,
                kind=result.kind,
                success=result.success,
                output=result.output,
                data=safe_data,
                error=result.error,
                event_id=result.event_id,
                started_at=result.started_at,
                completed_at=result.completed_at,
            )
        if action.kind in self._GUI_KINDS:
            safe_args = dict(action.args)
            for key in self._PRIVATE_ARGS:
                safe_args.pop(key, None)
            if action.kind == self._SET_VALUE_KIND and "value" in safe_args:
                raw = str(safe_args.pop("value"))
                safe_args["value_redacted"] = True
                safe_args["value_chars"] = len(raw)
                safe_args["value_sha256"] = text_sha256(raw)
            if action.kind == self._TYPE_TEXT_KIND and "text" in safe_args:
                raw = str(safe_args.pop("text"))
                safe_args["text_redacted"] = True
                safe_args["text_chars"] = len(raw)
                safe_args["text_sha256"] = text_sha256(raw)
            action = BodyAction(
                action_id=action.action_id,
                kind=action.kind,
                args=safe_args,
                event_id=action.event_id,
                created_at=action.created_at,
            )
        super()._record(action, result)

    def _dispatch(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.kind == self._SCENE_CAPTURE_KIND:
            return self._dispatch_desktop_scene(action, started)
        if action.kind in self._GUI_KINDS:
            return self._dispatch_gui_control(action, started)
        return super()._dispatch(action, started)

    def _dispatch_desktop_scene(
        self,
        action: BodyAction,
        started: str,
    ) -> BodyActionResult:
        if action.args.get(self._SCENE_DISPATCH_MARKER) is not True:
            raise PermissionError(
                "desktop scene dispatch did not pass foreground-app preflight"
            )
        app_id = str(action.args.get("application_id") or "").strip()
        expected = DesktopSceneForegroundBinding(
            application_id=app_id,
            process_id=int(action.args.get(self._SCENE_PROCESS_ARG) or 0),
            process_name=str(action.args.get(self._SCENE_PROCESS_NAME_ARG) or ""),
            window_handle=int(action.args.get(self._SCENE_WINDOW_ARG) or 0),
            class_name=str(action.args.get(self._SCENE_CLASS_NAME_ARG) or ""),
        )
        try:
            current = self._desktop_scene_binding(app_id)
        except Exception as exc:
            return self._result(
                action,
                started,
                False,
                {
                    "application_id": app_id,
                    "dispatch_sent": False,
                    "artifact_created": False,
                },
                (
                    "desktop scene foreground changed before capture: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )
        if not expected.same_identity(current):
            return self._result(
                action,
                started,
                False,
                {
                    "application_id": app_id,
                    "dispatch_sent": False,
                    "artifact_created": False,
                    "disposition": "foreground_identity_changed",
                },
                "desktop scene exact foreground identity changed before capture",
            )

        try:
            scene, scene_artifact_path = self._desktop_scene_builder.capture(
                event_id=str(action.event_id or ""),
                foreground=current,
                foreground_probe=lambda: self._desktop_scene_binding(app_id),
            )
        except Exception as exc:
            return self._result(
                action,
                started,
                False,
                {
                    "application_id": app_id,
                    "dispatch_sent": True,
                    "artifact_created": False,
                    "side_effect_uncertain": True,
                },
                (
                    "desktop scene capture crossed the artifact dispatch boundary "
                    f"without verified scene completion: {type(exc).__name__}: {exc}"
                ),
            )

        scene_data = scene.audit()
        return self._result(
            action,
            started,
            True,
            {
                "application_id": app_id,
                "dispatch_sent": True,
                "artifact_created": True,
                "scene_artifact_path": scene_artifact_path,
                "scene_id": scene.scene_id,
                "grounding_mode": scene.grounding_mode,
                "target_count": len(scene.targets),
                "uia_target_count": scene.uia_target_count,
                "visual_target_count": scene.visual_target_count,
                "truncated": scene.truncated,
                "scene": scene_data,
            },
            output=(
                f"captured foreground desktop scene with {len(scene.targets)} "
                "bounded targets"
            ),
        )

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
        pattern = self._pattern_for_kind(
            action.kind,
            control_type=selector.control_type,
        )
        target = self._target_for(action.kind, dict(action.args))
        if action.kind == self._TYPE_TEXT_KIND:
            return self._dispatch_gui_type_text(
                action,
                started,
                base_data=base_data,
                selector=selector,
                pattern=pattern,
                target=target,
                process_id=expected_pid,
                process_name=expected_process_name,
                window_handle=expected_hwnd,
            )
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

    def _dispatch_gui_type_text(
        self,
        action: BodyAction,
        started: str,
        *,
        base_data: dict[str, Any],
        selector: AutomationControlSelector,
        pattern: str,
        target: str,
        process_id: int,
        process_name: str,
        window_handle: int,
    ) -> BodyActionResult:
        chars_key = "text_chars" if pattern == "text" else "value_chars"
        hash_key = "text_sha256" if pattern == "text" else "value_sha256"
        expected_hash = text_sha256(target)

        def matches(observation: AutomationControlObservation) -> bool:
            state = dict(observation.state or {})
            return (
                state.get(chars_key) == len(target)
                and state.get(hash_key) == expected_hash
            )

        def data_for(
            *,
            before: AutomationControlObservation | None,
            after: AutomationControlObservation | None,
            focus_dispatched: bool,
            text_dispatch_sent: bool,
            uncertain: bool,
            absence_proven: bool,
            keyboard_result: BodyActionResult | None = None,
        ) -> dict[str, Any]:
            keyboard_data = dict(
                (keyboard_result.data if keyboard_result is not None else {}) or {}
            )
            return {
                **base_data,
                "selector": selector.audit(),
                "pattern": pattern,
                "dispatch_sent": bool(text_dispatch_sent),
                "focus_dispatched": bool(focus_dispatched),
                "postcondition_verified": bool(after is not None and matches(after)),
                "side_effect_uncertain": bool(uncertain),
                "side_effect_absence_proven": bool(absence_proven),
                "expected_text_chars": len(target),
                "expected_text_sha256": expected_hash,
                "input_events_expected": keyboard_data.get("input_events_expected"),
                "input_events_sent": keyboard_data.get("input_events_sent"),
                "before": before.audit() if before is not None else None,
                "after": after.audit() if after is not None else None,
            }

        try:
            before = self._automation_control.read(
                process_id=process_id,
                process_name=process_name,
                window_handle=window_handle,
                selector=selector,
                pattern=pattern,
            )
        except Exception as exc:
            return self._result(
                action,
                started,
                False,
                data_for(
                    before=None,
                    after=None,
                    focus_dispatched=False,
                    text_dispatch_sent=False,
                    uncertain=False,
                    absence_proven=True,
                ),
                f"semantic text preflight failed: {type(exc).__name__}: {exc}",
            )

        if matches(before):
            return self._result(
                action,
                started,
                True,
                data_for(
                    before=before,
                    after=before,
                    focus_dispatched=False,
                    text_dispatch_sent=False,
                    uncertain=False,
                    absence_proven=True,
                ),
                None,
                output="semantic text target already matched requested digest",
            )

        before_chars = (before.state or {}).get(chars_key)
        if before_chars != 0:
            return self._result(
                action,
                started,
                False,
                data_for(
                    before=before,
                    after=before,
                    focus_dispatched=False,
                    text_dispatch_sent=False,
                    uncertain=False,
                    absence_proven=True,
                ),
                (
                    "semantic text input first slice refuses non-empty replacement; "
                    "current text differs from the requested digest"
                ),
            )

        focus = self._automation_control.focus(
            process_id=process_id,
            process_name=process_name,
            window_handle=window_handle,
            selector=selector,
            pattern=pattern,
        )
        focused = focus.after if focus.after is not None else before
        if not focus.success or focus.after is None:
            return self._result(
                action,
                started,
                False,
                data_for(
                    before=before,
                    after=focus.after,
                    focus_dispatched=focus.focus_dispatched,
                    text_dispatch_sent=False,
                    uncertain=False,
                    absence_proven=True,
                ),
                focus.error or "fresh UI Automation evidence did not confirm keyboard focus",
            )
        if focus.after.runtime_id != before.runtime_id:
            return self._result(
                action,
                started,
                False,
                data_for(
                    before=before,
                    after=focus.after,
                    focus_dispatched=focus.focus_dispatched,
                    text_dispatch_sent=False,
                    uncertain=False,
                    absence_proven=True,
                ),
                "semantic text target RuntimeId changed while acquiring keyboard focus",
            )
        focused_chars = (focused.state or {}).get(chars_key)
        if focused_chars != 0:
            return self._result(
                action,
                started,
                False,
                data_for(
                    before=before,
                    after=focused,
                    focus_dispatched=focus.focus_dispatched,
                    text_dispatch_sent=False,
                    uncertain=False,
                    absence_proven=True,
                ),
                "semantic text target changed after focus and is no longer empty",
            )

        keyboard = super().act(
            "keyboard_text",
            event_id=action.event_id,
            text=target,
        )
        keyboard_data = dict(keyboard.data or {})
        try:
            sent = max(0, int(keyboard_data.get("input_events_sent") or 0))
        except (TypeError, ValueError):
            sent = 0
        text_dispatch_sent = sent > 0

        try:
            after = self._automation_control.read(
                process_id=process_id,
                process_name=process_name,
                window_handle=window_handle,
                selector=selector,
                pattern=pattern,
            )
        except Exception as exc:
            return self._result(
                action,
                started,
                False,
                data_for(
                    before=before,
                    after=None,
                    focus_dispatched=focus.focus_dispatched,
                    text_dispatch_sent=text_dispatch_sent,
                    uncertain=text_dispatch_sent,
                    absence_proven=not text_dispatch_sent,
                    keyboard_result=keyboard,
                ),
                (
                    "keyboard input crossed the dispatch boundary but fresh semantic "
                    f"text readback failed: {type(exc).__name__}: {exc}"
                ),
            )

        verified = after.runtime_id == before.runtime_id and matches(after)
        uncertain = bool(text_dispatch_sent and not verified)
        absence_proven = bool(not text_dispatch_sent)
        error = None
        if not verified:
            error = (
                keyboard.error
                or "fresh semantic text digest did not match the requested input"
            )
        return self._result(
            action,
            started,
            verified,
            data_for(
                before=before,
                after=after,
                focus_dispatched=focus.focus_dispatched,
                text_dispatch_sent=text_dispatch_sent,
                uncertain=uncertain,
                absence_proven=absence_proven,
                keyboard_result=keyboard,
            ),
            error,
            output=(
                "semantic keyboard text digest verified"
                if verified
                else ""
            ),
        )

    @classmethod
    def _pattern_for_kind(cls, kind: str, *, control_type: str = "") -> str:
        if kind == cls._TYPE_TEXT_KIND:
            normalized = str(control_type or "").strip().lower().replace("-", "_")
            if normalized == "document":
                return "text"
            if normalized == "edit":
                return "value"
            raise ValueError(
                "semantic text input is limited to exact UI Automation edit/document controls"
            )
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
