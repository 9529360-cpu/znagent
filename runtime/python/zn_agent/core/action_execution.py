from __future__ import annotations

"""Unified execution contract for ZN Action Fabric.

Discovery stays in action_fabric. This layer resolves one semantic action
onto the existing Body, keeps existing WorkerRun authority, and treats a Body
return as dispatch evidence until fresh reality verifies the postcondition.
"""

import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping

from .action_authority import (
    ActionAuthorityContext,
    bind_worker_authority_arg,
)
from .action_fabric import ActionDescriptor, ActionFabricRegistry
from .automation_control_action import normalize_control_type, text_sha256
from .body import BodyActionResult
from .office_native_action import scalar_digest
from .desktop_scene import inspect_desktop_scene_artifact
from .models import utc_now
from .windows_screen_capture import (
    inspect_screen_capture_artifact,
    screen_capture_artifact_path,
)


ExecutionStatus = Literal["verified", "pending", "failed", "uncertain"]
VerificationStatus = Literal["verified", "pending", "failed", "uncertain"]


@dataclass(frozen=True, slots=True)
class ActionRequest:
    action_id: str
    args: Mapping[str, Any] = field(default_factory=dict)
    event_id: str | None = None
    authority_context: ActionAuthorityContext | None = None

    def __post_init__(self) -> None:
        action_id = str(self.action_id or "").strip()
        if not action_id:
            raise ValueError("action request action_id must not be empty")
        object.__setattr__(self, "action_id", action_id)
        object.__setattr__(self, "args", dict(self.args or {}))
        event_id = str(self.event_id or "").strip() or None
        object.__setattr__(self, "event_id", event_id)


@dataclass(frozen=True, slots=True)
class ActionObservation:
    action_id: str
    source: str
    data: Mapping[str, Any] = field(default_factory=dict)
    observed_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_id", str(self.action_id or "").strip())
        object.__setattr__(self, "source", str(self.source or "").strip())
        object.__setattr__(self, "data", dict(self.data or {}))


@dataclass(frozen=True, slots=True)
class ActionVerification:
    status: VerificationStatus
    reason: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    observed_at: str = field(default_factory=utc_now)

    @property
    def verified(self) -> bool:
        return self.status == "verified"

    def __post_init__(self) -> None:
        if self.status not in {"verified", "pending", "failed", "uncertain"}:
            raise ValueError(f"invalid action verification status: {self.status}")
        object.__setattr__(self, "reason", " ".join(str(self.reason or "").split()))
        object.__setattr__(self, "evidence", dict(self.evidence or {}))


@dataclass(frozen=True, slots=True)
class ActionExecution:
    execution_id: str
    request: ActionRequest
    descriptor: ActionDescriptor
    status: ExecutionStatus
    verification: ActionVerification
    observations: tuple[ActionObservation, ...] = ()
    body_result: BodyActionResult | None = None
    authority_mode: str = "resident"
    error: str | None = None
    started_at: str = field(default_factory=utc_now)
    completed_at: str = field(default_factory=utc_now)

    @property
    def success(self) -> bool:
        return self.status == "verified" and self.verification.verified


ObservationReader = Callable[
    [ActionRequest, BodyActionResult | None],
    ActionObservation,
]
ObservationVerifier = Callable[
    [ActionRequest, ActionObservation, BodyActionResult | None],
    ActionVerification,
]


class ActionExecutionRuntime:
    """Resolve semantic actions through the one existing Body."""

    def __init__(self, fabric: ActionFabricRegistry, body: Any) -> None:
        self.fabric = fabric
        self.body = body
        self._observers: dict[str, ObservationReader] = {}
        self._verifiers: dict[str, ObservationVerifier] = {}

    def register_verification(
        self,
        action_id: str,
        *,
        observe: ObservationReader,
        verify: ObservationVerifier,
    ) -> None:
        normalized = str(action_id or "").strip()
        if self.fabric.descriptor(normalized) is None:
            raise KeyError(normalized)
        self._observers[normalized] = observe
        self._verifiers[normalized] = verify

    def execute(self, request: ActionRequest) -> ActionExecution:
        started = utc_now()
        descriptor = self.fabric.descriptor(request.action_id)
        if descriptor is None:
            raise KeyError(request.action_id)

        availability = self.fabric.availability(request.action_id)
        if not availability.available:
            return self._failure(
                request,
                descriptor,
                started,
                "action is not currently available: "
                f"{availability.state}: {availability.reason}",
            )

        validation_error = _validate_request_args(descriptor, request.args)
        if validation_error:
            return self._failure(request, descriptor, started, validation_error)

        if descriptor.effect_class != "read_only" and not request.event_id:
            return self._failure(
                request,
                descriptor,
                started,
                "side-effect action requires a stable event_id before dispatch",
            )
        if not descriptor.body_action_kind:
            return self._failure(
                request,
                descriptor,
                started,
                "action has no existing Body action binding",
            )

        body_args = dict(request.args)
        authority_mode = "resident"
        if request.authority_context is not None:
            body_args = bind_worker_authority_arg(
                body_args,
                request.authority_context,
            )
            authority_mode = "worker_run"

        body_result = self.body.act(
            descriptor.body_action_kind,
            event_id=request.event_id,
            **body_args,
        )

        if descriptor.effect_class == "read_only":
            observation = ActionObservation(
                request.action_id,
                "body_result",
                data=dict(body_result.data or {}),
                observed_at=body_result.completed_at or utc_now(),
            )
            verification = ActionVerification(
                "verified" if body_result.success else "failed",
                (
                    "read-only Body result is current action evidence"
                    if body_result.success
                    else body_result.error or "read-only Body action failed"
                ),
                evidence={"body_action_id": body_result.action_id},
                observed_at=observation.observed_at,
            )
            return self._execution(
                request,
                descriptor,
                started,
                body_result=body_result,
                observations=(observation,),
                verification=verification,
                authority_mode=authority_mode,
                error=None if body_result.success else body_result.error,
            )

        may_have_effect = bool(
            body_result.success
            or (body_result.data or {}).get("dispatch_sent")
            or (body_result.data or {}).get("side_effect_uncertain")
        )
        if not may_have_effect:
            return self._failure(
                request,
                descriptor,
                started,
                body_result.error or "Body rejected the side-effect before dispatch",
                body_result=body_result,
                authority_mode=authority_mode,
            )

        return self._observe_effect(
            request,
            descriptor,
            started,
            body_result=body_result,
            observations=(),
            authority_mode=authority_mode,
        )

    def verify(self, execution: ActionExecution) -> ActionExecution:
        """Re-observe a prior side effect without redispatching it."""

        if execution.descriptor.effect_class == "read_only":
            return execution
        if execution.request.action_id not in self._observers:
            return execution
        return self._observe_effect(
            execution.request,
            execution.descriptor,
            execution.started_at,
            body_result=execution.body_result,
            observations=execution.observations,
            authority_mode=execution.authority_mode,
            execution_id=execution.execution_id,
        )

    def reverification_checkpoint(self, execution: ActionExecution) -> dict[str, Any]:
        """Persist only the safe evidence needed to re-observe an async effect."""

        if execution.status != "pending":
            raise ValueError("reverification checkpoint requires a pending execution")
        action_id = execution.request.action_id
        if action_id not in {
            "windows.application.launch",
            "windows.application.activate",
        }:
            raise ValueError(
                f"pending reverification is not durable-safe for action: {action_id}"
            )
        if execution.authority_mode != "resident":
            raise ValueError("generic durable reverification supports resident authority only")

        body_evidence: dict[str, Any] = {}
        body_action_id = None
        body_kind = None
        body_success = None
        if execution.body_result is not None:
            body_action_id = execution.body_result.action_id
            body_kind = execution.body_result.kind
            body_success = bool(execution.body_result.success)
            data = dict(execution.body_result.data or {})
            if action_id == "windows.application.activate":
                body_evidence = {
                    "window_handle": int(data.get("window_handle") or 0),
                    "process_id": int(data.get("process_id") or 0),
                }

        return {
            "version": 1,
            "execution_id": execution.execution_id,
            "action_id": action_id,
            "args": dict(execution.request.args),
            "event_id": execution.request.event_id,
            "started_at": execution.started_at,
            "authority_mode": execution.authority_mode,
            "observations": [
                {
                    "source": observation.source,
                    "data": dict(observation.data or {}),
                    "observed_at": observation.observed_at,
                }
                for observation in execution.observations[-4:]
            ],
            "body": {
                "action_id": body_action_id,
                "kind": body_kind,
                "success": body_success,
                "data": body_evidence,
            } if execution.body_result is not None else None,
        }

    def verify_checkpoint(self, checkpoint: Mapping[str, Any]) -> ActionExecution:
        """Restore one safe pending checkpoint and re-observe without dispatch."""

        raw = dict(checkpoint or {})
        if int(raw.get("version") or 0) != 1:
            raise ValueError("unsupported action reverification checkpoint version")
        action_id = str(raw.get("action_id") or "").strip()
        if action_id not in {
            "windows.application.launch",
            "windows.application.activate",
        }:
            raise ValueError("action reverification checkpoint action is unsupported")
        descriptor = self.fabric.descriptor(action_id)
        if descriptor is None:
            raise KeyError(action_id)
        if action_id not in self._observers:
            raise ValueError(f"action has no independent reverification observer: {action_id}")

        args = raw.get("args")
        if not isinstance(args, Mapping):
            raise ValueError("action reverification checkpoint args are malformed")
        request = ActionRequest(
            action_id,
            dict(args),
            event_id=str(raw.get("event_id") or "").strip() or None,
        )
        execution_id = str(raw.get("execution_id") or "").strip()
        started_at = str(raw.get("started_at") or "").strip()
        if not execution_id or not started_at:
            raise ValueError("action reverification checkpoint identity is incomplete")

        body_result = None
        body = raw.get("body")
        if body is not None:
            if not isinstance(body, Mapping):
                raise ValueError("action reverification checkpoint Body evidence is malformed")
            body_data = body.get("data")
            if not isinstance(body_data, Mapping):
                raise ValueError("action reverification checkpoint Body data is malformed")
            body_result = BodyActionResult(
                action_id=str(body.get("action_id") or "recovered-body-evidence"),
                kind=str(body.get("kind") or descriptor.body_action_kind or action_id),
                success=bool(body.get("success")),
                data=dict(body_data),
                event_id=request.event_id,
            )

        raw_observations = raw.get("observations") or []
        if not isinstance(raw_observations, list):
            raise ValueError("action reverification checkpoint observations are malformed")
        observations: list[ActionObservation] = []
        for item in raw_observations[-4:]:
            if not isinstance(item, Mapping):
                raise ValueError("action reverification checkpoint observation is malformed")
            data = item.get("data")
            if not isinstance(data, Mapping):
                raise ValueError("action reverification checkpoint observation data is malformed")
            observations.append(
                ActionObservation(
                    action_id,
                    str(item.get("source") or "durable_reverification"),
                    data=dict(data),
                    observed_at=str(item.get("observed_at") or utc_now()),
                )
            )

        restored = ActionExecution(
            execution_id=execution_id,
            request=request,
            descriptor=descriptor,
            status="pending",
            verification=ActionVerification(
                "pending",
                "restored durable pending action for fresh reverification",
            ),
            observations=tuple(observations),
            body_result=body_result,
            authority_mode="resident",
            started_at=started_at,
        )
        return self.verify(restored)

    def _observe_effect(
        self,
        request: ActionRequest,
        descriptor: ActionDescriptor,
        started: str,
        *,
        body_result: BodyActionResult,
        observations: tuple[ActionObservation, ...],
        authority_mode: str,
        execution_id: str | None = None,
    ) -> ActionExecution:
        observer = self._observers.get(request.action_id)
        verifier = self._verifiers.get(request.action_id)
        if observer is None or verifier is None:
            verification = ActionVerification(
                "failed",
                "side-effect action has no independent postcondition verifier",
            )
            return self._execution(
                request,
                descriptor,
                started,
                body_result=body_result,
                observations=observations,
                verification=verification,
                authority_mode=authority_mode,
                execution_id=execution_id,
                error=verification.reason,
            )

        try:
            observation = observer(request, body_result)
            verification = verifier(request, observation, body_result)
        except Exception as exc:
            verification = ActionVerification(
                "uncertain",
                f"fresh postcondition observation failed: {type(exc).__name__}: {exc}",
            )
            return self._execution(
                request,
                descriptor,
                started,
                body_result=body_result,
                observations=observations,
                verification=verification,
                authority_mode=authority_mode,
                execution_id=execution_id,
                error=verification.reason,
            )

        next_observations = (*observations, observation)

        error = None
        if not verification.verified:
            error = verification.reason
            if verification.status == "pending":
                error = None
        return self._execution(
            request,
            descriptor,
            started,
            body_result=body_result,
            observations=next_observations,
            verification=verification,
            authority_mode=authority_mode,
            execution_id=execution_id,
            error=error,
        )

    def _failure(
        self,
        request: ActionRequest,
        descriptor: ActionDescriptor,
        started: str,
        error: str,
        *,
        body_result: BodyActionResult | None = None,
        authority_mode: str = "resident",
    ) -> ActionExecution:
        verification = ActionVerification("failed", error)
        return self._execution(
            request,
            descriptor,
            started,
            body_result=body_result,
            observations=(),
            verification=verification,
            authority_mode=authority_mode,
            error=error,
        )

    @staticmethod
    def _execution(
        request: ActionRequest,
        descriptor: ActionDescriptor,
        started: str,
        *,
        body_result: BodyActionResult | None,
        observations: tuple[ActionObservation, ...],
        verification: ActionVerification,
        authority_mode: str,
        error: str | None,
        execution_id: str | None = None,
    ) -> ActionExecution:
        status: ExecutionStatus = verification.status
        return ActionExecution(
            execution_id=execution_id or f"action-{uuid.uuid4().hex[:12]}",
            request=request,
            descriptor=descriptor,
            status=status,
            verification=verification,
            observations=observations,
            body_result=body_result,
            authority_mode=authority_mode,
            error=error,
            started_at=started,
            completed_at=utc_now(),
        )


def build_machine_action_execution_runtime(
    fabric: ActionFabricRegistry,
    body: Any,
    *,
    device_capabilities: Any | None,
) -> ActionExecutionRuntime:
    runtime = ActionExecutionRuntime(fabric, body)

    if fabric.descriptor("windows.screen.capture") is not None:
        runtime.register_verification(
            "windows.screen.capture",
            observe=_observe_screen_capture,
            verify=_verify_screen_capture,
        )

    if fabric.descriptor("windows.desktop.scene.capture") is not None:
        runtime.register_verification(
            "windows.desktop.scene.capture",
            observe=_observe_desktop_scene,
            verify=_verify_desktop_scene,
        )

    if fabric.descriptor("windows.audio.volume.set") is not None:
        runtime.register_verification(
            "windows.audio.volume.set",
            observe=lambda request, result: _observe_volume(body, request),
            verify=_verify_volume,
        )

    if fabric.descriptor("windows.display.brightness.set") is not None:
        runtime.register_verification(
            "windows.display.brightness.set",
            observe=lambda request, result: _observe_brightness(body, request),
            verify=_verify_brightness,
        )

    if device_capabilities is not None:
        if fabric.descriptor("windows.application.launch") is not None:
            runtime.register_verification(
                "windows.application.launch",
                observe=lambda request, result: _observe_application_launch(
                    device_capabilities,
                    request,
                ),
                verify=_verify_application_launch,
            )
        if fabric.descriptor("windows.application.activate") is not None:
            runtime.register_verification(
                "windows.application.activate",
                observe=lambda request, result: _observe_application_activation(
                    device_capabilities,
                    request,
                ),
                verify=_verify_application_activation,
            )
    if fabric.descriptor("windows.ui.control.type_text") is not None:
        runtime.register_verification(
            "windows.ui.control.type_text",
            observe=lambda request, result: _observe_ui_control(
                body,
                request,
                _semantic_text_pattern(request),
            ),
            verify=lambda request, observation, result: _verify_ui_control(
                request,
                observation,
                result,
                _semantic_text_pattern(request),
            ),
        )

    for action_id, pattern in (
        ("windows.ui.control.set_value", "value"),
        ("windows.ui.control.toggle", "toggle"),
        ("windows.ui.control.expand_collapse", "expand_collapse"),
        ("windows.ui.control.select", "selection_item"),
    ):
        if fabric.descriptor(action_id) is None:
            continue
        runtime.register_verification(
            action_id,
            observe=lambda request, result, pattern=pattern: _observe_ui_control(
                body, request, pattern
            ),
            verify=lambda request, observation, result, pattern=pattern: _verify_ui_control(
                request, observation, result, pattern
            ),
        )

    if fabric.descriptor("windows.office.excel.cell.set") is not None:
        runtime.register_verification(
            "windows.office.excel.cell.set",
            observe=lambda request, result: _observe_office_excel_cell(body, request),
            verify=_verify_office_excel_cell,
        )
    if fabric.descriptor("windows.office.word.selection.set_text") is not None:
        runtime.register_verification(
            "windows.office.word.selection.set_text",
            observe=lambda request, result: _observe_office_word_selection(body, request),
            verify=_verify_office_word_selection,
        )

    return runtime


def _observe_screen_capture(
    request: ActionRequest,
    body_result: BodyActionResult | None,
) -> ActionObservation:
    result_data = dict((body_result.data if body_result is not None else {}) or {})
    local_path = str(result_data.get("local_path") or "").strip()
    if not local_path:
        local_path = str(screen_capture_artifact_path(str(request.event_id or "")))
    observed = inspect_screen_capture_artifact(local_path)
    return ActionObservation(
        request.action_id,
        "zn_screen_capture_artifact_readback",
        data=observed,
    )


def _verify_screen_capture(
    request: ActionRequest,
    observation: ActionObservation,
    body_result: BodyActionResult | None,
) -> ActionVerification:
    expected = dict((body_result.data if body_result is not None else {}) or {})
    observed = dict(observation.data or {})
    mismatches: list[str] = []

    for key in ("local_path", "sha256", "width", "height", "size_bytes"):
        value = expected.get(key)
        if value in (None, ""):
            continue
        if str(observed.get(key)) != str(value):
            mismatches.append(key)

    if mismatches:
        return ActionVerification(
            "failed",
            "fresh screenshot artifact readback does not match Body result",
            evidence={
                "mismatched_fields": mismatches,
                **observed,
            },
            observed_at=observation.observed_at,
        )

    return ActionVerification(
        "verified",
        (
            "fresh ZN-owned screenshot artifact exists and matches recorded evidence"
            if not expected.get("replay_blocked")
            else "recovered prior screenshot effect from deterministic artifact evidence"
        ),
        evidence={
            **observed,
            "replay_recovered": bool(expected.get("replay_blocked")),
        },
        observed_at=observation.observed_at,
    )


def _observe_office_excel_cell(
    body: Any,
    request: ActionRequest,
) -> ActionObservation:
    observer = getattr(body, "observe_excel_cell", None)
    if not callable(observer):
        raise RuntimeError("current Body does not expose Excel NativeOM observation")
    observed = observer(
        application_id=str(request.args.get("application_id") or ""),
        worksheet_name=str(request.args.get("worksheet_name") or ""),
        cell_address=str(request.args.get("cell_address") or ""),
    )
    data = dict(observed.audit())
    data["application_id"] = str(request.args.get("application_id") or "").strip()
    return ActionObservation(
        request.action_id,
        "office_excel_nativeom_readback",
        data=data,
        observed_at=observed.captured_at or utc_now(),
    )


def _verify_office_excel_cell(
    request: ActionRequest,
    observation: ActionObservation,
    _body_result: BodyActionResult | None,
) -> ActionVerification:
    data = dict(observation.data or {})
    target = dict(data.get("target") or {})
    state = dict(data.get("state") or {})
    try:
        expected = scalar_digest(request.args.get("value"))
    except ValueError as exc:
        return ActionVerification(
            "failed",
            str(exc),
            evidence={"application_id": data.get("application_id")},
            observed_at=observation.observed_at,
        )
    selector_matches = bool(
        data.get("application_id") == str(request.args.get("application_id") or "").strip()
        and target.get("worksheet_name") == str(request.args.get("worksheet_name") or "").strip()
        and target.get("cell_address") == str(request.args.get("cell_address") or "").strip().replace("$", "").upper()
    )
    verified = selector_matches and state == expected
    return ActionVerification(
        "verified" if verified else "failed",
        (
            "fresh Excel NativeOM cell digest matches requested value"
            if verified
            else "fresh Excel NativeOM cell digest does not match requested value"
        ),
        evidence={
            "application_id": data.get("application_id"),
            "target": target,
            "selector_matches": selector_matches,
            "expected": expected,
            "observed": state,
        },
        observed_at=observation.observed_at,
    )


def _observe_office_word_selection(
    body: Any,
    request: ActionRequest,
) -> ActionObservation:
    observer = getattr(body, "observe_word_selection", None)
    if not callable(observer):
        raise RuntimeError("current Body does not expose Word NativeOM selection observation")
    observed = observer(
        application_id=str(request.args.get("application_id") or ""),
    )
    data = dict(observed.audit())
    data["application_id"] = str(request.args.get("application_id") or "").strip()
    return ActionObservation(
        request.action_id,
        "office_word_nativeom_readback",
        data=data,
        observed_at=observed.captured_at or utc_now(),
    )


def _verify_office_word_selection(
    request: ActionRequest,
    observation: ActionObservation,
    _body_result: BodyActionResult | None,
) -> ActionVerification:
    data = dict(observation.data or {})
    state = dict(data.get("state") or {})
    text = request.args.get("text")
    if not isinstance(text, str):
        return ActionVerification(
            "failed",
            "Word replacement text is not a string",
            evidence={"application_id": data.get("application_id")},
            observed_at=observation.observed_at,
        )
    expected = {
        "selection_chars": len(text),
        "selection_sha256": text_sha256(text),
    }
    application_matches = (
        data.get("application_id") == str(request.args.get("application_id") or "").strip()
    )
    verified = bool(
        application_matches
        and state.get("selection_chars") == expected["selection_chars"]
        and state.get("selection_sha256") == expected["selection_sha256"]
    )
    return ActionVerification(
        "verified" if verified else "failed",
        (
            "fresh Word NativeOM selection digest matches requested text"
            if verified
            else "fresh Word NativeOM selection digest does not match requested text"
        ),
        evidence={
            "application_id": data.get("application_id"),
            "application_matches": application_matches,
            "expected": expected,
            "observed": {
                "selection_chars": state.get("selection_chars"),
                "selection_sha256": state.get("selection_sha256"),
            },
        },
        observed_at=observation.observed_at,
    )


def _semantic_text_pattern(request: ActionRequest) -> str:
    control_type = normalize_control_type(request.args.get("control_type"))
    if control_type == "document":
        return "text"
    if control_type == "edit":
        return "value"
    raise ValueError(
        "semantic text input is limited to UI Automation edit/document controls"
    )


def _observe_ui_control(
    body: Any,
    request: ActionRequest,
    pattern: str,
) -> ActionObservation:
    observer = getattr(body, "observe_automation_control", None)
    if not callable(observer):
        raise RuntimeError("current Body does not expose semantic UI Automation observation")
    observed = observer(
        application_id=str(request.args.get("application_id") or ""),
        control_type=str(request.args.get("control_type") or ""),
        control_name=str(request.args.get("control_name") or ""),
        automation_id=str(request.args.get("automation_id") or ""),
        pattern=pattern,
    )
    data = dict(observed.audit())
    data["application_id"] = str(request.args.get("application_id") or "").strip()
    return ActionObservation(
        request.action_id,
        "windows_uia_control_readback",
        data=data,
        observed_at=observed.captured_at or utc_now(),
    )


def _verify_ui_control(
    request: ActionRequest,
    observation: ActionObservation,
    _body_result: BodyActionResult | None,
    pattern: str,
) -> ActionVerification:
    data = dict(observation.data or {})
    selector = dict(data.get("selector") or {})
    state = dict(data.get("state") or {})
    try:
        expected_type = normalize_control_type(request.args.get("control_type"))
    except ValueError as exc:
        return ActionVerification(
            "failed",
            str(exc),
            evidence=data,
            observed_at=observation.observed_at,
        )
    expected_name = " ".join(str(request.args.get("control_name") or "").strip().split())
    expected_automation_id = str(request.args.get("automation_id") or "").strip()
    selector_matches = bool(
        data.get("application_id") == str(request.args.get("application_id") or "").strip()
        and selector.get("control_type") == expected_type
        and selector.get("name") == expected_name
        and selector.get("automation_id") == expected_automation_id
        and data.get("pattern") == pattern
    )
    verified = False
    target_evidence: dict[str, Any] = {}
    if selector_matches and pattern in {"value", "text"}:
        argument_name = "text" if request.action_id == "windows.ui.control.type_text" else "value"
        target = request.args.get(argument_name)
        if isinstance(target, str):
            chars_key = "text_chars" if pattern == "text" else "value_chars"
            hash_key = "text_sha256" if pattern == "text" else "value_sha256"
            chars = state.get(chars_key)
            expected_hash = text_sha256(target)
            verified = bool(
                isinstance(chars, int)
                and chars == len(target)
                and state.get(hash_key) == expected_hash
            )
            evidence_prefix = (
                "text"
                if request.action_id == "windows.ui.control.type_text"
                else "value"
            )
            target_evidence = {
                f"expected_{evidence_prefix}_chars": len(target),
                f"expected_{evidence_prefix}_sha256": expected_hash,
                f"observed_{evidence_prefix}_chars": chars,
                f"observed_{evidence_prefix}_sha256": state.get(hash_key),
            }
    elif selector_matches and pattern == "toggle":
        target = str(request.args.get("state") or "").strip().lower()
        verified = target in {"on", "off"} and state.get("toggle_state") == target
        target_evidence = {
            "expected_toggle_state": target,
            "observed_toggle_state": state.get("toggle_state"),
        }
    elif selector_matches and pattern == "expand_collapse":
        target = str(request.args.get("state") or "").strip().lower().replace("-", "_")
        verified = (
            target in {"expanded", "collapsed"}
            and state.get("expand_collapse_state") == target
        )
        target_evidence = {
            "expected_expand_collapse_state": target,
            "observed_expand_collapse_state": state.get("expand_collapse_state"),
        }
    elif selector_matches and pattern == "selection_item":
        verified = state.get("selected") is True
        target_evidence = {"observed_selected": state.get("selected")}

    evidence = {
        "application_id": data.get("application_id"),
        "selector": selector,
        "runtime_id": data.get("runtime_id"),
        "pattern": data.get("pattern"),
        "selector_matches": selector_matches,
        **target_evidence,
    }
    return ActionVerification(
        "verified" if verified else "failed",
        (
            "fresh UI Automation control readback matches requested target state"
            if verified
            else "fresh UI Automation control readback does not match requested target state"
        ),
        evidence=evidence,
        observed_at=observation.observed_at,
    )


def _observe_desktop_scene(
    request: ActionRequest,
    body_result: BodyActionResult | None,
) -> ActionObservation:
    event_id = str(request.event_id or "").strip()
    if not event_id:
        raise RuntimeError("desktop scene verification requires the stable event_id")
    observed = inspect_desktop_scene_artifact(event_id)
    return ActionObservation(
        request.action_id,
        "zn_desktop_scene_artifact_readback",
        data=observed,
    )


def _verify_desktop_scene(
    request: ActionRequest,
    observation: ActionObservation,
    body_result: BodyActionResult | None,
) -> ActionVerification:
    expected = dict((body_result.data if body_result is not None else {}) or {})
    observed = dict(observation.data or {})
    mismatches: list[str] = []
    for key in (
        "scene_artifact_path",
        "scene_id",
        "grounding_mode",
        "target_count",
        "uia_target_count",
        "visual_target_count",
        "truncated",
    ):
        value = expected.get(key)
        if value in (None, ""):
            continue
        if str(observed.get(key)) != str(value):
            mismatches.append(key)

    expected_scene = expected.get("scene")
    if isinstance(expected_scene, Mapping):
        expected_screenshot = expected_scene.get("screenshot")
        observed_screenshot = observed.get("screenshot")
        if isinstance(expected_screenshot, Mapping) and isinstance(
            observed_screenshot, Mapping
        ):
            for key in ("local_path", "sha256", "width", "height", "size_bytes"):
                value = expected_screenshot.get(key)
                if value in (None, ""):
                    continue
                if str(observed_screenshot.get(key)) != str(value):
                    mismatches.append(f"screenshot.{key}")

    if mismatches:
        return ActionVerification(
            "failed",
            "fresh desktop scene artifact readback does not match Body result",
            evidence={
                "mismatched_fields": tuple(mismatches),
                "scene_id": observed.get("scene_id"),
                "scene_artifact_path": observed.get("scene_artifact_path"),
            },
            observed_at=observation.observed_at,
        )

    return ActionVerification(
        "verified",
        (
            "fresh desktop scene sidecar and screenshot artifact match recorded evidence"
            if not expected.get("replay_blocked")
            else "recovered prior desktop scene effect from deterministic artifacts"
        ),
        evidence={
            "scene_id": observed.get("scene_id"),
            "scene_artifact_path": observed.get("scene_artifact_path"),
            "grounding_mode": observed.get("grounding_mode"),
            "target_count": observed.get("target_count"),
            "uia_target_count": observed.get("uia_target_count"),
            "visual_target_count": observed.get("visual_target_count"),
            "truncated": observed.get("truncated"),
            "screenshot_sha256": dict(observed.get("screenshot") or {}).get("sha256"),
            "replay_recovered": bool(expected.get("replay_blocked")),
        },
        observed_at=observation.observed_at,
    )


def _observe_volume(body: Any, request: ActionRequest) -> ActionObservation:
    result = body.act(
        "windows_audio_volume_read",
        event_id=request.event_id,
    )
    if not result.success:
        raise RuntimeError(result.error or "Windows volume readback failed")
    return ActionObservation(
        request.action_id,
        "windows_core_audio_readback",
        data=dict(result.data or {}),
        observed_at=result.completed_at or utc_now(),
    )


def _verify_volume(
    request: ActionRequest,
    observation: ActionObservation,
    _body_result: BodyActionResult | None,
) -> ActionVerification:
    requested = _finite_number(request.args.get("level_percent"))
    observed = _finite_number(observation.data.get("level_percent"))
    if requested is None or observed is None:
        return ActionVerification(
            "failed",
            "volume verification lacks numeric requested/readback evidence",
            evidence=dict(observation.data),
            observed_at=observation.observed_at,
        )
    delta = abs(observed - requested)
    verified = delta <= 0.5
    return ActionVerification(
        "verified" if verified else "failed",
        (
            "fresh Core Audio readback matches requested volume"
            if verified
            else "fresh Core Audio readback does not match requested volume"
        ),
        evidence={
            "requested_level_percent": requested,
            "observed_level_percent": observed,
            "delta_percent": delta,
            "tolerance_percent": 0.5,
        },
        observed_at=observation.observed_at,
    )


def _observe_brightness(body: Any, request: ActionRequest) -> ActionObservation:
    result = body.act(
        "windows_display_brightness_read",
        event_id=request.event_id,
    )
    if not result.success:
        raise RuntimeError(result.error or "Windows brightness readback failed")
    return ActionObservation(
        request.action_id,
        "windows_wmi_brightness_readback",
        data=dict(result.data or {}),
        observed_at=result.completed_at or utc_now(),
    )


def _verify_brightness(
    request: ActionRequest,
    observation: ActionObservation,
    body_result: BodyActionResult | None,
) -> ActionVerification:
    requested = _finite_number(request.args.get("level_percent"))
    observed = _finite_number(observation.data.get("level_percent"))
    observed_instance = str(observation.data.get("instance_name") or "").strip()
    expected_instance = str(
        ((body_result.data or {}).get("instance_name") if body_result is not None else "")
        or ""
    ).strip()
    if (
        requested is None
        or observed is None
        or not observed_instance
        or not expected_instance
    ):
        return ActionVerification(
            "failed",
            "brightness verification lacks numeric requested/readback evidence or the original monitor identity",
            evidence={
                **dict(observation.data),
                "expected_instance_name": expected_instance,
            },
            observed_at=observation.observed_at,
        )
    if observed_instance != expected_instance:
        return ActionVerification(
            "failed",
            "fresh brightness readback belongs to a different monitor identity",
            evidence={
                "expected_instance_name": expected_instance,
                "observed_instance_name": observed_instance,
                "requested_level_percent": requested,
                "observed_level_percent": observed,
            },
            observed_at=observation.observed_at,
        )
    delta = abs(observed - requested)
    verified = delta <= 0.5
    return ActionVerification(
        "verified" if verified else "failed",
        (
            "fresh WMI readback matches requested brightness on the same monitor"
            if verified
            else "fresh WMI readback does not match requested brightness"
        ),
        evidence={
            "instance_name": observed_instance,
            "requested_level_percent": requested,
            "observed_level_percent": observed,
            "delta_percent": delta,
            "tolerance_percent": 0.5,
        },
        observed_at=observation.observed_at,
    )


def _observe_application_launch(
    device_capabilities: Any,
    request: ActionRequest,
) -> ActionObservation:
    app_id = str(request.args.get("application_id") or "").strip()
    application = device_capabilities.application_by_id(app_id)
    processes = ()
    visible = ()
    if application is not None:
        processes, windows = device_capabilities.application_runtime(application)
        processes = tuple(
            row
            for row in processes
            if getattr(row, "resolved_app_id", app_id) == app_id
        )
        visible = tuple(
            row
            for row in windows
            if bool(getattr(row, "visible", False))
            and getattr(row, "resolved_app_id", app_id) == app_id
        )
    return ActionObservation(
        request.action_id,
        "device_capability_graph",
        data={
            "application_id": app_id,
            "application_present": application is not None,
            "process_ids": [int(getattr(row, "process_id", 0)) for row in processes],
            "visible_window_handles": [int(getattr(row, "hwnd", 0)) for row in visible],
        },
    )


def _verify_application_launch(
    request: ActionRequest,
    observation: ActionObservation,
    _body_result: BodyActionResult | None,
) -> ActionVerification:
    data = dict(observation.data)
    verified = bool(
        data.get("application_present")
        and data.get("process_ids")
        and data.get("visible_window_handles")
    )
    return ActionVerification(
        "verified" if verified else "pending",
        (
            "fresh process and visible-window evidence proves application launch"
            if verified
            else "launch dispatch is not yet proven by fresh process/window evidence"
        ),
        evidence=data,
        observed_at=observation.observed_at,
    )


def _observe_application_activation(
    device_capabilities: Any,
    request: ActionRequest,
) -> ActionObservation:
    app_id = str(request.args.get("application_id") or "").strip()
    application = device_capabilities.application_by_id(app_id)
    foreground = []
    if application is not None:
        processes, windows = device_capabilities.application_runtime(application)
        process_ids = {
            int(getattr(row, "process_id", 0))
            for row in processes
            if getattr(row, "resolved_app_id", app_id) == app_id
        }
        foreground = [
            {
                "window_handle": int(getattr(row, "hwnd", 0)),
                "process_id": int(getattr(row, "process_id", 0)),
            }
            for row in windows
            if bool(getattr(row, "visible", False))
            and bool(getattr(row, "foreground", False))
            and getattr(row, "resolved_app_id", app_id) == app_id
            and int(getattr(row, "process_id", 0)) in process_ids
        ]
    return ActionObservation(
        request.action_id,
        "device_capability_graph",
        data={
            "application_id": app_id,
            "application_present": application is not None,
            "foreground_windows": foreground,
        },
    )


def _verify_application_activation(
    request: ActionRequest,
    observation: ActionObservation,
    body_result: BodyActionResult | None,
) -> ActionVerification:
    expected = dict((body_result.data if body_result is not None else {}) or {})
    expected_hwnd = int(expected.get("window_handle") or 0)
    expected_pid = int(expected.get("process_id") or 0)
    observed = dict(observation.data or {})
    foreground = [
        row for row in observed.get("foreground_windows") or ()
        if isinstance(row, dict)
    ]
    exact = any(
        int(row.get("window_handle") or 0) == expected_hwnd
        and int(row.get("process_id") or 0) == expected_pid
        for row in foreground
    )
    if not expected_hwnd or not expected_pid:
        status: VerificationStatus = "failed"
        reason = "activation verification lacks the Body-admitted exact window/process identity"
    elif exact:
        status = "verified"
        reason = "fresh foreground evidence proves the exact admitted application window is active"
    else:
        status = "pending"
        reason = "the exact admitted application window is not yet proven foreground by fresh evidence"
    return ActionVerification(
        status,
        reason,
        evidence={
            "application_id": str(request.args.get("application_id") or ""),
            "expected_window_handle": expected_hwnd,
            "expected_process_id": expected_pid,
            "foreground_windows": foreground,
        },
        observed_at=observation.observed_at,
    )


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _validate_request_args(
    descriptor: ActionDescriptor,
    args: Mapping[str, Any],
) -> str | None:
    schema = dict(descriptor.input_schema or {})
    if not schema:
        return None
    if schema.get("type") not in {None, "object"}:
        return "Action Fabric v1 supports object input schemas only"

    values = dict(args or {})
    required = tuple(str(item) for item in (schema.get("required") or ()))
    missing = [name for name in required if name not in values]
    if missing:
        return "missing required action arguments: " + ", ".join(missing)

    properties = schema.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    if schema.get("additionalProperties") is False:
        extra = sorted(key for key in values if key not in properties)
        if extra:
            return "unexpected action arguments: " + ", ".join(extra)

    for name, rule in properties.items():
        if name not in values or not isinstance(rule, dict):
            continue
        value = values[name]
        expected = rule.get("type")
        if expected == "string" and not isinstance(value, str):
            return f"action argument {name} must be a string"
        if expected == "number":
            number = _finite_number(value)
            if number is None:
                return f"action argument {name} must be a finite number"
            minimum = rule.get("minimum")
            maximum = rule.get("maximum")
            if minimum is not None and number < float(minimum):
                return f"action argument {name} is below minimum {minimum}"
            if maximum is not None and number > float(maximum):
                return f"action argument {name} exceeds maximum {maximum}"
    return None
