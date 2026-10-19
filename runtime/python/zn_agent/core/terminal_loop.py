from __future__ import annotations

"""Model-led Work loop proposals for terminal commands.

The generic Action Fabric loop owns the proposal/completion envelopes, the
bounded step budget and the completion-evidence rules. This module adds the
terminal half of that loop without touching the terminal itself: every step
runs through the existing Body ``command`` action
(:meth:`Body.act("command", ...) <zn_agent.core.body.NativeBody.act>`), which
is the same authority ``ZNLocalTerminal`` dispatch the rest of ZN already
uses. No new execution path is opened: this module never spawns a process,
PTY, or shell of its own.

Permission is never model-supplied. The caller (event payload or a
resident-owned attribute) provides one
:class:`TerminalPermissionContext`; the model only proposes the command, its
working directory, and its timeout. Every dispatch re-checks that context,
including the caller-owned :class:`PermissionPolicy` when one is supplied:
a denylisted command is rejected outright, and a command the policy marks
``ASK`` fails with an ``approval_required:`` reason instead of executing --
the loop never runs a command that needs user approval.

Verification semantics: a synchronous command that runs to completion has
its real output and exit code as its observation evidence. ``verified``
means "this is the real output of exactly the proposed command", not "the
command exited 0": a completed command with a non-zero exit code is a
*failed* step whose output is still real evidence (the resident loop hands
it back to model-led cognition through ``completed_with_output`` so the
model can decide from it), while a timeout or transport failure carries no
trustworthy output. A dispatched command is never re-run to "verify" it:
re-running would execute the side effect twice.
"""

import math
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .action_execution import (
    ActionDescriptor,
    ActionExecution,
    ActionObservation,
    ActionRequest,
    ActionVerification,
)
from .action_fabric import ActionEffectClass
from .models import utc_now
from .permission_model import PermissionPolicy, PermissionVerdict


@dataclass(frozen=True, slots=True)
class TerminalLoopActionSpec:
    action_id: str
    effect_class: ActionEffectClass
    description: str
    required_args: tuple[str, ...] = ()
    optional_args: tuple[str, ...] = ()


TERMINAL_LOOP_ACTIONS: tuple[TerminalLoopActionSpec, ...] = (
    TerminalLoopActionSpec(
        action_id="terminal.run",
        effect_class="potential_side_effect",
        description=(
            "Run one non-interactive shell command in an explicit working "
            "directory and return its real output and exit code. "
            "Non-interactive only: no background, PTY, or stdin sessions."
        ),
        required_args=("command", "workdir"),
        optional_args=("timeout",),
    ),
)

_TERMINAL_LOOP_SPECS = {spec.action_id: spec for spec in TERMINAL_LOOP_ACTIONS}

_MAX_COMMAND_CHARS = 8000
_MAX_TIMEOUT_SECONDS = 600.0
_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_MAX_OUTPUT_CHARS = 50_000


def terminal_loop_spec(action_id: str) -> TerminalLoopActionSpec | None:
    return _TERMINAL_LOOP_SPECS.get(str(action_id or "").strip())


def terminal_loop_catalog() -> list[dict[str, Any]]:
    """Cognition-context rows in the same shape as Action Fabric rows."""
    rows: list[dict[str, Any]] = []
    for spec in TERMINAL_LOOP_ACTIONS:
        properties: dict[str, Any] = {
            "command": {"type": "string"},
            "workdir": {"type": "string"},
            "timeout": {"type": "number"},
        }
        rows.append(
            {
                "action_id": spec.action_id,
                "provider": "zn.terminal",
                "description": spec.description,
                "arguments_schema": {
                    "type": "object",
                    "required": list(spec.required_args),
                    "properties": properties,
                    "additionalProperties": False,
                },
                "effect_class": spec.effect_class,
                "preconditions": [
                    "caller-supplied terminal permission allows terminal commands",
                    "workdir resolves inside a permitted root (when roots are set)",
                    "timeout is within the caller permission cap",
                ],
                "verification": [
                    "synchronous Body terminal result: exit code + output are the observation",
                    "non-zero exit is evidence to decide from, not a replay",
                ],
            }
        )
    return rows


@dataclass(frozen=True, slots=True)
class TerminalPermissionContext:
    """Caller-owned terminal permission. The model cannot grant or widen it."""

    allow_terminal: bool = False
    allowed_workdirs: tuple[str, ...] = ()
    max_timeout_seconds: float = 120.0
    max_command_chars: int = _MAX_COMMAND_CHARS
    max_output_chars: int = _DEFAULT_MAX_OUTPUT_CHARS
    denylist: tuple[str, ...] = ()
    permission_policy: PermissionPolicy | None = None

    def __post_init__(self) -> None:
        if type(self.allow_terminal) is not bool:
            raise ValueError("terminal permission allow_terminal must be a boolean")
        roots = tuple(
            dict.fromkeys(
                str(item) for item in (self.allowed_workdirs or ()) if str(item).strip()
            )
        )
        object.__setattr__(self, "allowed_workdirs", roots)
        timeout_cap = self.max_timeout_seconds
        if (
            isinstance(timeout_cap, bool)
            or not isinstance(timeout_cap, (int, float))
            or not math.isfinite(float(timeout_cap))
            or float(timeout_cap) <= 0
        ):
            raise ValueError("terminal permission max_timeout_seconds must be a positive number")
        object.__setattr__(self, "max_timeout_seconds", float(timeout_cap))
        if (
            isinstance(self.max_command_chars, bool)
            or not isinstance(self.max_command_chars, int)
            or int(self.max_command_chars) <= 0
        ):
            raise ValueError("terminal permission max_command_chars must be a positive integer")
        if (
            isinstance(self.max_output_chars, bool)
            or not isinstance(self.max_output_chars, int)
            or int(self.max_output_chars) <= 0
        ):
            raise ValueError("terminal permission max_output_chars must be a positive integer")
        for pattern in self.denylist or ():
            try:
                re.compile(str(pattern))
            except re.error as exc:
                raise ValueError(f"terminal permission denylist pattern is invalid: {exc}") from exc
        if self.permission_policy is not None and not isinstance(
            self.permission_policy, PermissionPolicy
        ):
            raise ValueError("terminal permission permission_policy must be a PermissionPolicy")

    def denies_command(self, command: str) -> bool:
        """Absolute denylist: True when the command must never execute."""
        for pattern in self.denylist or ():
            if re.search(str(pattern), command):
                return True
        return False

    def allows_workdir(self, workdir: str) -> bool:
        """Empty roots mean no workdir restriction; otherwise containment."""
        if not self.allowed_workdirs:
            return True
        try:
            resolved = Path(str(workdir)).expanduser().resolve()
        except (OSError, RuntimeError):
            return False
        for root in self.allowed_workdirs:
            try:
                root_path = Path(root).expanduser().resolve()
            except (OSError, RuntimeError):
                continue
            if resolved == root_path or root_path in resolved.parents:
                return True
        return False


def check_terminal_permission(
    permission: TerminalPermissionContext,
    *,
    command: str,
    workdir: str,
    timeout: float,
) -> str | None:
    """Return the rejection reason, or None when the command may execute.

    This is the single gate used both when admitting a proposal (fail fast,
    so the model can repair) and immediately before dispatch (authoritative
    re-check). A rejected command is never executed.
    """
    if not permission.allow_terminal:
        return "terminal loop permission does not allow terminal commands"
    if not str(command or "").strip():
        return "terminal loop command must not be empty"
    if len(str(command)) > int(permission.max_command_chars):
        return (
            "terminal loop command exceeds the caller permission length cap "
            f"({permission.max_command_chars} chars)"
        )
    if not str(workdir or "").strip():
        return "terminal loop workdir must not be empty"
    if not permission.allows_workdir(str(workdir)):
        return "terminal loop workdir is outside the caller-permitted roots"
    if timeout <= 0 or timeout > float(permission.max_timeout_seconds):
        return (
            "terminal loop timeout is outside the caller permission cap "
            f"(max {permission.max_timeout_seconds:g}s)"
        )
    if permission.denies_command(str(command)):
        return "terminal command is denied by the terminal permission denylist"
    policy = permission.permission_policy
    if policy is not None:
        verdict = policy.evaluate("terminal_command", str(command))
        if verdict is PermissionVerdict.DENY:
            return "terminal command is denied by the caller permission policy"
        if verdict is PermissionVerdict.ASK:
            return (
                "approval_required: terminal command needs user approval "
                "under the caller permission policy"
            )
    return None


def parse_terminal_permission(raw: Any) -> TerminalPermissionContext | None:
    """Build a caller-owned permission context from an event-payload dict.

    Returns None when no permission was supplied. Unknown keys are ignored;
    malformed values fail closed with ValueError instead of widening access.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("terminal_permission must be an object")
    kwargs: dict[str, Any] = {}
    if "allow_terminal" in raw:
        value = raw.get("allow_terminal")
        if type(value) is not bool:
            raise ValueError("terminal_permission.allow_terminal must be a boolean")
        kwargs["allow_terminal"] = value
    if "allowed_workdirs" in raw:
        roots = raw.get("allowed_workdirs")
        if not isinstance(roots, (list, tuple)) or not all(
            isinstance(item, str) for item in roots
        ):
            raise ValueError("terminal_permission.allowed_workdirs must be a list of strings")
        kwargs["allowed_workdirs"] = tuple(roots)
    if "max_timeout_seconds" in raw:
        value = raw.get("max_timeout_seconds")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0
        ):
            raise ValueError("terminal_permission.max_timeout_seconds must be a positive number")
        kwargs["max_timeout_seconds"] = float(value)
    if "max_command_chars" in raw:
        value = raw.get("max_command_chars")
        if isinstance(value, bool) or not isinstance(value, int) or int(value) <= 0:
            raise ValueError("terminal_permission.max_command_chars must be a positive integer")
        kwargs["max_command_chars"] = int(value)
    if "max_output_chars" in raw:
        value = raw.get("max_output_chars")
        if isinstance(value, bool) or not isinstance(value, int) or int(value) <= 0:
            raise ValueError("terminal_permission.max_output_chars must be a positive integer")
        kwargs["max_output_chars"] = int(value)
    if "denylist" in raw:
        patterns = raw.get("denylist")
        if not isinstance(patterns, (list, tuple)) or not all(
            isinstance(item, str) for item in patterns
        ):
            raise ValueError("terminal_permission.denylist must be a list of strings")
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(
                    f"terminal_permission.denylist pattern is invalid: {exc}"
                ) from exc
        kwargs["denylist"] = tuple(patterns)
    if "permission_policy" in raw:
        policy_raw = raw.get("permission_policy")
        if not isinstance(policy_raw, Mapping):
            raise ValueError("terminal_permission.permission_policy must be an object")
        try:
            kwargs["permission_policy"] = PermissionPolicy.from_dict(dict(policy_raw))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"terminal_permission.permission_policy is invalid: {exc}") from exc
    return TerminalPermissionContext(**kwargs)


def validate_terminal_loop_arguments(
    spec: TerminalLoopActionSpec,
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize one model proposal; unknown arguments are rejected."""
    if not isinstance(arguments, Mapping):
        raise ValueError("terminal loop arguments must be an object")
    allowed = set(spec.required_args) | set(spec.optional_args)
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise ValueError(
            f"terminal loop {spec.action_id} rejects unknown arguments: {', '.join(unknown)}"
        )
    for name in spec.required_args:
        if name not in arguments:
            raise ValueError(f"terminal loop {spec.action_id} requires {name}")
    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("terminal loop terminal.run requires a non-empty command")
    if "\x00" in command:
        raise ValueError("terminal loop command must not contain NUL bytes")
    if len(command) > _MAX_COMMAND_CHARS:
        raise ValueError(
            f"terminal loop command exceeds the absolute length cap ({_MAX_COMMAND_CHARS} chars)"
        )
    workdir = arguments.get("workdir")
    if not isinstance(workdir, str) or not workdir.strip():
        raise ValueError("terminal loop terminal.run requires a non-empty workdir")
    if "\x00" in workdir:
        raise ValueError("terminal loop workdir must not contain NUL bytes")
    normalized: dict[str, Any] = {
        "command": command.strip(),
        "workdir": workdir.strip(),
        "timeout": _DEFAULT_TIMEOUT_SECONDS,
    }
    if "timeout" in arguments:
        timeout = arguments.get("timeout")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(float(timeout))
            or float(timeout) <= 0
            or float(timeout) > _MAX_TIMEOUT_SECONDS
        ):
            raise ValueError(
                "terminal loop timeout must be a number in "
                f"(0, {_MAX_TIMEOUT_SECONDS:g}] seconds"
            )
        normalized["timeout"] = float(timeout)
    return normalized


@dataclass(frozen=True, slots=True)
class TerminalLoopStepResult:
    execution: ActionExecution
    completed_with_output: bool = False


def _build_execution(
    *,
    spec: TerminalLoopActionSpec,
    arguments: Mapping[str, Any],
    success: bool,
    reason: str,
    evidence: Mapping[str, Any],
    observation_data: Mapping[str, Any],
    error: str | None = None,
    body_result: Any | None = None,
) -> ActionExecution:
    verification = ActionVerification(
        status="verified" if success else "failed",
        reason=reason,
        evidence=dict(evidence),
    )
    request = ActionRequest(spec.action_id, dict(arguments))
    descriptor = ActionDescriptor(
        action_id=spec.action_id,
        provider="zn.terminal",
        description=spec.description,
        effect_class=spec.effect_class,
    )
    return ActionExecution(
        execution_id=f"terminal-{uuid.uuid4().hex[:12]}",
        request=request,
        descriptor=descriptor,
        status="verified" if success else "failed",
        verification=verification,
        observations=(
            ActionObservation(
                action_id=spec.action_id,
                source="terminal_body_result",
                data=dict(observation_data),
            ),
        ),
        body_result=body_result,
        error=None if success else (error or reason),
    )


def _failed_step(
    *,
    spec: TerminalLoopActionSpec,
    arguments: Mapping[str, Any],
    reason: str,
    evidence: Mapping[str, Any] | None = None,
    observation_data: Mapping[str, Any] | None = None,
    body_result: Any | None = None,
    completed_with_output: bool = False,
) -> TerminalLoopStepResult:
    return TerminalLoopStepResult(
        execution=_build_execution(
            spec=spec,
            arguments=arguments,
            success=False,
            reason=reason,
            evidence=dict(evidence or {}),
            observation_data=dict(observation_data or {}),
            error=reason,
            body_result=body_result,
        ),
        completed_with_output=completed_with_output,
    )


def execute_terminal_loop_step(
    body: Any,
    *,
    permission: TerminalPermissionContext,
    action_id: str,
    arguments: Mapping[str, Any],
    event_id: str | None = None,
) -> TerminalLoopStepResult:
    """Execute one validated terminal proposal through the existing Body.

    Single-shot: a dispatched, timed-out, or failed command is never
    re-dispatched. The Body ``command`` action owns the actual shell
    execution (including killing the process tree on timeout); this step
    only gates, dispatches, and records the real result as evidence.
    """
    spec = terminal_loop_spec(action_id)
    if spec is None:
        raise ValueError(f"unknown terminal loop action: {action_id}")
    normalized = validate_terminal_loop_arguments(spec, arguments)
    command = str(normalized["command"])
    workdir = str(normalized["workdir"])
    timeout = float(normalized["timeout"])

    gate = check_terminal_permission(
        permission, command=command, workdir=workdir, timeout=timeout
    )
    if gate is not None:
        return _failed_step(
            spec=spec,
            arguments=normalized,
            reason=gate,
            observation_data={
                "command": command,
                "workdir": workdir,
                "timeout": timeout,
                "executed": False,
            },
        )

    if body is None or not callable(getattr(body, "act", None)):
        return _failed_step(
            spec=spec,
            arguments=normalized,
            reason="terminal loop has no Body to dispatch the command through",
            observation_data={
                "command": command,
                "workdir": workdir,
                "timeout": timeout,
                "executed": False,
            },
        )
    try:
        body_result = body.act(
            "command",
            event_id=event_id,
            command=command,
            workdir=workdir,
            timeout=timeout,
            max_output_chars=int(permission.max_output_chars),
        )
    except Exception as exc:
        return _failed_step(
            spec=spec,
            arguments=normalized,
            reason=f"terminal loop dispatch failed: {type(exc).__name__}: {exc}",
            observation_data={
                "command": command,
                "workdir": workdir,
                "timeout": timeout,
                "executed": False,
            },
        )

    data = dict(getattr(body_result, "data", {}) or {})
    output = str(getattr(body_result, "output", "") or "")
    body_success = bool(getattr(body_result, "success", False))
    timed_out = bool(data.get("timed_out", False))
    exit_code = data.get("exit_code")
    observation_data = {
        "command": command,
        "workdir": str(data.get("cwd") or workdir),
        "timeout": timeout,
        "executed": True,
        "exit_code": exit_code,
        "output": output,
        "timed_out": timed_out,
        "truncated": bool(data.get("truncated", False)),
    }
    evidence: dict[str, Any] = {"body_action_id": str(getattr(body_result, "action_id", "") or "")}

    if timed_out:
        return _failed_step(
            spec=spec,
            arguments=normalized,
            reason=f"terminal command timed out after {timeout:g}s; the process tree was killed",
            evidence=evidence,
            observation_data=observation_data,
            body_result=body_result,
        )
    if body_success:
        return TerminalLoopStepResult(
            execution=_build_execution(
                spec=spec,
                arguments=normalized,
                success=True,
                reason="terminal command completed with exit code 0",
                evidence=evidence,
                observation_data=observation_data,
                body_result=body_result,
            ),
            completed_with_output=True,
        )
    if str(data.get("status") or "") == "completed":
        # The command ran to completion and produced real output, but
        # exited non-zero. The output is real evidence, so the caller
        # may hand it back to cognition; the step itself stays failed
        # so a non-zero exit can never be cited as completion evidence.
        return _failed_step(
            spec=spec,
            arguments=normalized,
            reason=f"terminal command completed with exit code {exit_code}",
            evidence=evidence,
            observation_data=observation_data,
            body_result=body_result,
            completed_with_output=True,
        )
    return _failed_step(
        spec=spec,
        arguments=normalized,
        reason=str(getattr(body_result, "error", "") or "terminal command failed without completion evidence"),
        evidence=evidence,
        observation_data=observation_data,
        body_result=body_result,
    )
