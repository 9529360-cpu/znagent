from __future__ import annotations

"""Bounded execution of versioned application competence recipes.

This is intentionally a thin coordinator over the existing AppCompetenceRegistry
and ActionExecutionRuntime. It does not own authority, Body, Work, persistence,
routing, or another agent loop.

Recovery is reality-first: before every side-effect stage the declared read-only
completion proof is evaluated. If current reality already satisfies that proof,
the mutation is skipped. If a prior dispatch is replay-blocked or uncertain, the
executor observes completion until the bounded stage deadline and never blindly
redispatches the effect.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping

from .action_authority import ActionAuthorityContext
from .action_execution import ActionExecution, ActionExecutionRuntime, ActionRequest
from .action_fabric import ActionDescriptor
from .app_competence import (
    AppCompetenceBinding,
    AppCompetenceCompletion,
    AppCompetencePack,
    AppCompetenceRegistry,
    AppCompetenceStage,
)
from .models import utc_now


RecipeStatus = Literal["verified", "failed", "uncertain"]
StageStatus = Literal["already_verified", "verified", "failed", "uncertain"]


@dataclass(frozen=True, slots=True)
class AppCompetenceCompletionCheck:
    matched: bool
    expected: Mapping[str, Any]
    observed: Mapping[str, Any]
    execution: ActionExecution
    checked_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "expected", dict(self.expected or {}))
        object.__setattr__(self, "observed", dict(self.observed or {}))


@dataclass(frozen=True, slots=True)
class AppCompetenceStageExecution:
    index: int
    stage: AppCompetenceStage
    status: StageStatus
    preflight: AppCompetenceCompletionCheck | None = None
    action: ActionExecution | None = None
    completion_checks: tuple[AppCompetenceCompletionCheck, ...] = ()
    error: str | None = None
    started_at: str = field(default_factory=utc_now)
    completed_at: str = field(default_factory=utc_now)

    @property
    def success(self) -> bool:
        return self.status in {"already_verified", "verified"}


@dataclass(frozen=True, slots=True)
class AppCompetenceRecipeExecution:
    pack_id: str
    app_id: str
    app_version: str
    capability: str
    event_id: str
    status: RecipeStatus
    stages: tuple[AppCompetenceStageExecution, ...] = ()
    error: str | None = None
    started_at: str = field(default_factory=utc_now)
    completed_at: str = field(default_factory=utc_now)

    @property
    def success(self) -> bool:
        return self.status == "verified"


SleepFn = Callable[[float], None]
MonotonicFn = Callable[[], float]


class AppCompetenceRecipeExecutor:
    """Execute one exact app/version competence through Action Fabric only."""

    def __init__(
        self,
        registry: AppCompetenceRegistry,
        action_runtime: ActionExecutionRuntime,
        *,
        poll_interval_ms: int = 150,
        sleep_fn: SleepFn = time.sleep,
        monotonic_fn: MonotonicFn = time.monotonic,
    ) -> None:
        poll_interval_ms = int(poll_interval_ms)
        if not 25 <= poll_interval_ms <= 2_000:
            raise ValueError("competence poll_interval_ms must be within 25..2000")
        self.registry = registry
        self.action_runtime = action_runtime
        self.poll_interval_ms = poll_interval_ms
        self._sleep = sleep_fn
        self._monotonic = monotonic_fn

    def execute(
        self,
        *,
        app: str,
        version: str,
        capability: str,
        event_id: str,
        application_id: str | None = None,
        authority_context: ActionAuthorityContext | None = None,
    ) -> AppCompetenceRecipeExecution:
        started = utc_now()
        normalized_event = str(event_id or "").strip()
        if not normalized_event:
            return self._recipe_failure(
                app=app,
                version=version,
                capability=capability,
                event_id="",
                started=started,
                error="competence recipe requires a stable event_id",
            )

        pack = self.registry.resolve(app, version)
        if pack is None:
            return self._recipe_failure(
                app=app,
                version=version,
                capability=capability,
                event_id=normalized_event,
                started=started,
                error="no exact app/version competence pack is registered",
            )
        binding = pack.binding(capability)
        if binding is None:
            return self._recipe_failure(
                app=pack.app_id,
                version=pack.app_version,
                capability=capability,
                event_id=normalized_event,
                started=started,
                pack_id=pack.pack_id,
                error="competence pack does not expose the requested capability",
            )

        validation_error = self._validate_executable_plan(binding)
        if validation_error is not None:
            return self._recipe_failure(
                app=pack.app_id,
                version=pack.app_version,
                capability=binding.capability,
                event_id=normalized_event,
                started=started,
                pack_id=pack.pack_id,
                error=validation_error,
            )

        completed: list[AppCompetenceStageExecution] = []
        for index, stage in enumerate(binding.stage_plan()):
            stage_result = self._execute_stage(
                index=index,
                stage=stage,
                event_id=normalized_event,
                application_id=application_id,
                authority_context=authority_context,
            )
            completed.append(stage_result)
            if not stage_result.success:
                status: RecipeStatus = (
                    "uncertain" if stage_result.status == "uncertain" else "failed"
                )
                return AppCompetenceRecipeExecution(
                    pack_id=pack.pack_id,
                    app_id=pack.app_id,
                    app_version=pack.app_version,
                    capability=binding.capability,
                    event_id=normalized_event,
                    status=status,
                    stages=tuple(completed),
                    error=stage_result.error,
                    started_at=started,
                    completed_at=utc_now(),
                )

        return AppCompetenceRecipeExecution(
            pack_id=pack.pack_id,
            app_id=pack.app_id,
            app_version=pack.app_version,
            capability=binding.capability,
            event_id=normalized_event,
            status="verified",
            stages=tuple(completed),
            started_at=started,
            completed_at=utc_now(),
        )

    def _execute_stage(
        self,
        *,
        index: int,
        stage: AppCompetenceStage,
        event_id: str,
        application_id: str | None,
        authority_context: ActionAuthorityContext | None,
    ) -> AppCompetenceStageExecution:
        started = utc_now()
        deadline = self._monotonic() + (stage.timeout_ms / 1000.0)
        descriptor = self.action_runtime.fabric.descriptor(stage.action_id)
        assert descriptor is not None  # validated by _validate_executable_plan

        request_args, error = self._request_args(
            descriptor,
            stage.arguments,
            application_id=application_id,
        )
        if error is not None:
            return AppCompetenceStageExecution(
                index=index,
                stage=stage,
                status="failed",
                error=error,
                started_at=started,
                completed_at=utc_now(),
            )

        preflight: AppCompetenceCompletionCheck | None = None
        completion = stage.completion
        completion_args: dict[str, Any] | None = None
        if completion is not None:
            completion_descriptor = self.action_runtime.fabric.descriptor(
                completion.action_id
            )
            assert completion_descriptor is not None
            completion_args, error = self._request_args(
                completion_descriptor,
                completion.arguments,
                application_id=application_id,
            )
            if error is not None:
                return AppCompetenceStageExecution(
                    index=index,
                    stage=stage,
                    status="failed",
                    error=error,
                    started_at=started,
                    completed_at=utc_now(),
                )
            preflight = self._check_completion(
                completion,
                arguments=completion_args,
                event_id=event_id,
            )
            if preflight.matched:
                return AppCompetenceStageExecution(
                    index=index,
                    stage=stage,
                    status="already_verified",
                    preflight=preflight,
                    completed_at=utc_now(),
                    started_at=started,
                )
            if self._monotonic() >= deadline:
                return AppCompetenceStageExecution(
                    index=index,
                    stage=stage,
                    status="failed",
                    preflight=preflight,
                    error=(
                        "competence stage deadline elapsed during completion preflight; "
                        "no side effect was dispatched"
                    ),
                    started_at=started,
                    completed_at=utc_now(),
                )

        action = self.action_runtime.execute(
            ActionRequest(
                stage.action_id,
                request_args,
                event_id=event_id,
                authority_context=authority_context,
            )
        )

        if descriptor.effect_class == "read_only":
            if not action.success:
                return AppCompetenceStageExecution(
                    index=index,
                    stage=stage,
                    status="failed",
                    preflight=preflight,
                    action=action,
                    error=action.error or action.verification.reason,
                    started_at=started,
                    completed_at=utc_now(),
                )
            if completion is None:
                return AppCompetenceStageExecution(
                    index=index,
                    stage=stage,
                    status="verified",
                    preflight=preflight,
                    action=action,
                    started_at=started,
                    completed_at=utc_now(),
                )

        if completion is None:
            # _validate_executable_plan prevents this for side effects.
            return AppCompetenceStageExecution(
                index=index,
                stage=stage,
                status="failed",
                preflight=preflight,
                action=action,
                error="side-effect competence stage has no read-only completion proof",
                started_at=started,
                completed_at=utc_now(),
            )

        may_have_effect = descriptor.effect_class != "read_only" and self._may_have_effect(action)
        if descriptor.effect_class != "read_only" and not may_have_effect:
            return AppCompetenceStageExecution(
                index=index,
                stage=stage,
                status="failed",
                preflight=preflight,
                action=action,
                error=action.error or action.verification.reason,
                started_at=started,
                completed_at=utc_now(),
            )

        checks: list[AppCompetenceCompletionCheck] = []
        while True:
            assert completion_args is not None
            check = self._check_completion(
                completion,
                arguments=completion_args,
                event_id=event_id,
            )
            checks.append(check)
            if check.matched:
                return AppCompetenceStageExecution(
                    index=index,
                    stage=stage,
                    status="verified",
                    preflight=preflight,
                    action=action,
                    completion_checks=tuple(checks),
                    started_at=started,
                    completed_at=utc_now(),
                )

            now = self._monotonic()
            if now >= deadline:
                if descriptor.effect_class == "read_only":
                    status: StageStatus = "failed"
                    reason = "read-only competence stage completion condition timed out"
                else:
                    status = "uncertain"
                    reason = (
                        "side-effect competence stage was dispatched or replay-blocked but "
                        "its completion condition was not proven before timeout; refusing "
                        "blind redispatch"
                    )
                return AppCompetenceStageExecution(
                    index=index,
                    stage=stage,
                    status=status,
                    preflight=preflight,
                    action=action,
                    completion_checks=tuple(checks),
                    error=reason,
                    started_at=started,
                    completed_at=utc_now(),
                )

            remaining = max(0.0, deadline - now)
            self._sleep(min(self.poll_interval_ms / 1000.0, remaining))

    def _validate_executable_plan(self, binding: AppCompetenceBinding) -> str | None:
        seen_side_effects: set[str] = set()
        for index, stage in enumerate(binding.stage_plan()):
            descriptor = self.action_runtime.fabric.descriptor(stage.action_id)
            if descriptor is None:
                return f"competence stage {index} references unknown action {stage.action_id}"

            completion = stage.completion
            if completion is not None:
                completion_descriptor = self.action_runtime.fabric.descriptor(
                    completion.action_id
                )
                if completion_descriptor is None:
                    return (
                        f"competence stage {index} completion references unknown action "
                        f"{completion.action_id}"
                    )
                if completion_descriptor.effect_class != "read_only":
                    return (
                        f"competence stage {index} completion action "
                        f"{completion.action_id} must be read_only"
                    )

            if descriptor.effect_class == "read_only":
                continue
            if completion is None:
                return (
                    f"competence side-effect stage {index} ({stage.action_id}) requires "
                    "a read-only completion proof for recovery"
                )
            identity = self._stage_identity(stage)
            if identity in seen_side_effects:
                return (
                    "competence recipe contains duplicate side-effect stage identity; "
                    "schema v1 cannot safely distinguish replay of repeated identical effects"
                )
            seen_side_effects.add(identity)
        return None

    @staticmethod
    def _stage_identity(stage: AppCompetenceStage) -> str:
        return json.dumps(
            {
                "action_id": stage.action_id,
                "arguments": dict(stage.arguments or {}),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    def _check_completion(
        self,
        completion: AppCompetenceCompletion,
        *,
        arguments: Mapping[str, Any],
        event_id: str,
    ) -> AppCompetenceCompletionCheck:
        execution = self.action_runtime.execute(
            ActionRequest(
                completion.action_id,
                dict(arguments or {}),
                event_id=event_id,
            )
        )
        observed = self._observed_data(execution)
        matched = execution.success and completion_expected_matches(
            observed,
            completion.expected,
        )
        return AppCompetenceCompletionCheck(
            matched=matched,
            expected=completion.expected,
            observed=observed,
            execution=execution,
        )

    @staticmethod
    def _observed_data(execution: ActionExecution) -> dict[str, Any]:
        if execution.observations:
            return dict(execution.observations[-1].data or {})
        if execution.body_result is not None:
            return dict(execution.body_result.data or {})
        return {}

    @staticmethod
    def _may_have_effect(execution: ActionExecution) -> bool:
        body_result = execution.body_result
        if body_result is None:
            return False
        data = dict(body_result.data or {})
        return bool(
            body_result.success
            or data.get("dispatch_sent")
            or data.get("side_effect_uncertain")
            or data.get("replay_blocked")
        )

    @staticmethod
    def _request_args(
        descriptor: ActionDescriptor,
        persisted: Mapping[str, Any],
        *,
        application_id: str | None,
    ) -> tuple[dict[str, Any], str | None]:
        args = dict(persisted or {})
        schema = dict(descriptor.input_schema or {})
        properties = schema.get("properties")
        supports_application = (
            isinstance(properties, Mapping) and "application_id" in properties
        )
        required = schema.get("required")
        requires_application = (
            isinstance(required, (list, tuple))
            and "application_id" in required
        )
        normalized_application = str(application_id or "").strip()
        if requires_application and not normalized_application:
            return args, (
                f"action {descriptor.action_id} requires current runtime application_id"
            )
        if supports_application and normalized_application:
            args["application_id"] = normalized_application
        return args, None

    @staticmethod
    def _recipe_failure(
        *,
        app: str,
        version: str,
        capability: str,
        event_id: str,
        started: str,
        error: str,
        pack_id: str = "",
    ) -> AppCompetenceRecipeExecution:
        return AppCompetenceRecipeExecution(
            pack_id=pack_id,
            app_id=str(app or "").strip().casefold(),
            app_version=str(version or "").strip(),
            capability=str(capability or "").strip().casefold(),
            event_id=event_id,
            status="failed",
            error=error,
            started_at=started,
            completed_at=utc_now(),
        )


def completion_expected_matches(
    observed: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> bool:
    """Exact bounded matcher for read-only competence completion evidence."""

    if not expected:
        return False
    rows = _flatten_expected(expected)
    if not rows:
        return False
    for path, wanted in rows:
        found, actual = _read_path(observed, path)
        if not found or actual != wanted:
            return False
    return True


def _flatten_expected(
    value: Mapping[str, Any],
    prefix: tuple[str, ...] = (),
) -> tuple[tuple[tuple[str, ...], Any], ...]:
    rows: list[tuple[tuple[str, ...], Any]] = []
    for raw_key, nested in value.items():
        key_parts = tuple(
            part for part in str(raw_key).strip().split(".") if part
        )
        if not key_parts:
            continue
        path = (*prefix, *key_parts)
        if isinstance(nested, Mapping):
            rows.extend(_flatten_expected(nested, path))
        else:
            rows.append((path, nested))
    return tuple(rows)


def _read_path(
    value: Mapping[str, Any],
    path: tuple[str, ...],
) -> tuple[bool, Any]:
    current: Any = value
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current
