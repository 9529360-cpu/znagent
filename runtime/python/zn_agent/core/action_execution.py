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
from .body import BodyActionResult
from .models import utc_now


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

    if fabric.descriptor("windows.audio.volume.set") is not None:
        runtime.register_verification(
            "windows.audio.volume.set",
            observe=lambda request, result: _observe_volume(body, request),
            verify=_verify_volume,
        )

    if (
        device_capabilities is not None
        and fabric.descriptor("windows.application.launch") is not None
    ):
        runtime.register_verification(
            "windows.application.launch",
            observe=lambda request, result: _observe_application_launch(
                device_capabilities,
                request,
            ),
            verify=_verify_application_launch,
        )
    return runtime


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


def _observe_application_launch(
    device_capabilities: Any,
    request: ActionRequest,
) -> ActionObservation:
    app_id = str(request.args.get("application_id") or "").strip()
    application = device_capabilities.application_by_id(
        app_id,
        force_refresh=True,
    )
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
