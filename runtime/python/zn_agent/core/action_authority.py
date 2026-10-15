from __future__ import annotations

"""Action-level authority for transient Work/WorkerRun execution.

Authority belongs to the current Work/WorkerRun/action, never to a model or a
permanent agent identity. The active Resident installs this gate on the existing
Body instance, preserving the one Body object's class/store/recovery semantics.
"""

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .body import BodyAction, BodyActionResult
from .models import utc_now
from .sandbox import SandboxDeniedError, SandboxGate, SandboxPolicy


_AUTHORITY_ARG = "__zn_authority_context"
_ESCALATION_TOKEN_ARG = "__zn_escalation_token"


@dataclass(frozen=True, slots=True)
class ActionAuthorityContext:
    work_thread_id: str
    work_item_id: str
    worker_run_id: str
    plan_version: int
    executor_kind: str
    expected_action: str
    tool_scope: tuple[str, ...]
    authority_scope: tuple[str, ...]
    workspace_root: str | None = None
    allowed_command_sha256: str | None = None
    side_effect_sensitivity: str = "bounded_worker_effect"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ActionAuthorityContext":
        return cls(
            work_thread_id=str(raw.get("work_thread_id") or ""),
            work_item_id=str(raw.get("work_item_id") or ""),
            worker_run_id=str(raw.get("worker_run_id") or ""),
            plan_version=int(raw.get("plan_version") or 0),
            executor_kind=str(raw.get("executor_kind") or ""),
            expected_action=str(raw.get("expected_action") or ""),
            tool_scope=tuple(str(item) for item in (raw.get("tool_scope") or ())),
            authority_scope=tuple(str(item) for item in (raw.get("authority_scope") or ())),
            workspace_root=str(raw.get("workspace_root") or "").strip() or None,
            allowed_command_sha256=(str(raw.get("allowed_command_sha256") or "").strip() or None),
            side_effect_sensitivity=str(raw.get("side_effect_sensitivity") or "bounded_worker_effect"),
        )

    @staticmethod
    def command_digest(command: str) -> str:
        return hashlib.sha256(str(command).encode("utf-8", errors="replace")).hexdigest()


class WorkerActionAuthorityError(PermissionError):
    pass


class ApprovalSnapshotMismatchError(PermissionError):
    """Raised when execution args no longer match the approved snapshot."""


def canonical_args_digest(args: dict[str, Any]) -> str:
    """Deterministic digest of execution args for approval snapshots.

    Keys are sorted and values are JSON-normalized, so two equal arg dicts
    always produce the same digest regardless of insertion order.
    Non-JSON values fall back to their string form so the digest never
    fails on an unusual argument type.
    """
    canonical = json.dumps(dict(args or {}), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8", errors="replace")).hexdigest()


@dataclass(frozen=True, slots=True)
class ApprovalSnapshot:
    """Immutable snapshot of the exact args an approval was granted for.

    Captured at approval time, verified immediately before dispatch. Any
    approved key that changed or disappeared between approval and dispatch
    is a post-approval parameter swap and must refuse execution. Keys added
    after approval (resident-applied bindings such as a workspace root)
    are not part of the snapshot and are permitted; they are recorded in
    the execution audit trail instead of being treated as tampering.
    """

    action_id: str
    event_id: str | None
    approved_args: dict[str, Any] = field(default_factory=dict)
    args_digest: str = ""
    approved_command: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_id", str(self.action_id or "").strip())
        object.__setattr__(self, "approved_args", dict(self.approved_args or {}))
        if not self.args_digest:
            object.__setattr__(
                self, "args_digest", canonical_args_digest(self.approved_args)
            )

    @classmethod
    def capture(
        cls,
        action_id: str,
        args: dict[str, Any],
        event_id: str | None,
        *,
        approved_command: str | None = None,
    ) -> "ApprovalSnapshot":
        """Snapshot ``args`` with an approved edited command applied.

        When the approval card approved a user-edited command (W-1), the
        edited command is the approved value: the snapshot stores it, so
        a later substitution back to the pre-approval command is itself
        a mismatch.
        """
        approved_args = dict(args or {})
        if approved_command is not None and isinstance(approved_args.get("command"), str):
            approved_args = dict(approved_args)
            approved_args["command"] = approved_command
        return cls(
            action_id=action_id,
            event_id=str(event_id or "").strip() or None,
            approved_args=approved_args,
            args_digest=canonical_args_digest(approved_args),
            approved_command=approved_command,
        )

    def verify(
        self,
        action_id: str,
        args: dict[str, Any],
        event_id: str | None,
    ) -> list[str]:
        """Return human-readable mismatches between snapshot and dispatch args."""
        mismatches: list[str] = []
        if str(action_id or "").strip() != self.action_id:
            mismatches.append(
                f"action changed: approved {self.action_id!r}, dispatch {str(action_id or '').strip()!r}"
            )
        normalized_event = str(event_id or "").strip() or None
        if normalized_event != self.event_id:
            mismatches.append("event_id changed after approval")
        current = dict(args or {})
        for key, approved_value in self.approved_args.items():
            if key not in current:
                mismatches.append(f"approved parameter removed: {key}")
            elif current[key] != approved_value:
                mismatches.append(f"approved parameter changed: {key}")
        return mismatches

    def matches(self, action_id: str, args: dict[str, Any], event_id: str | None) -> bool:
        return not self.verify(action_id, args, event_id)


class WorkerActionAuthorityError(PermissionError):
    pass


class WorkerActionAuthorityEnforcer:
    """Fail-closed checks for Body actions that declare WorkerRun authority."""

    _READ_KINDS = {"inspect_path", "path", "read_text", "read_file", "list_directory", "list_dir"}
    _WRITE_KINDS = {"write_text", "write_file"}
    _COMMAND_KINDS = {"command", "terminal", "shell"}
    _GIT_READ_KINDS = {"git_state", "git", "git_diff"}

    @classmethod
    def authorize(
        cls,
        kind: str,
        args: dict[str, Any],
        context: ActionAuthorityContext,
        *,
        permission_policy=None,
        sandbox_gate: SandboxGate | None = None,
        sandbox_policy: SandboxPolicy | None = None,
        escalation_token: str | None = None,
    ) -> None:
        if not context.worker_run_id or not context.work_item_id or not context.work_thread_id:
            raise WorkerActionAuthorityError("worker action authority identity is incomplete")
        if context.plan_version < 1:
            raise WorkerActionAuthorityError("worker action authority plan_version is invalid")

        normalized = str(kind or "").strip().lower()

        # DSH-6: sandbox tier check -- what the call can touch. The W-1
        # permission policy (checked per kind below) decides whether the
        # action is allowed; the sandbox decides what it can touch. A gate
        # carries escalation state; a bare policy gets an ephemeral gate
        # (plain enforcement, no escalation flow).
        gate = sandbox_gate
        if gate is None and sandbox_policy is not None:
            gate = SandboxGate(sandbox_policy)
        if gate is not None:
            try:
                gate.require(kind, args, escalation_token)
            except SandboxDeniedError as exc:
                raise WorkerActionAuthorityError(str(exc)) from exc

        tools = set(context.tool_scope)
        authorities = set(context.authority_scope)

        if normalized in cls._WRITE_KINDS:
            if context.expected_action != "write_file":
                raise WorkerActionAuthorityError(
                    "workspace mutation is outside the admitted action contract"
                )
            if "workspace.write" not in tools or "workspace_write" not in authorities:
                raise WorkerActionAuthorityError(
                    "workspace write capability is outside WorkerRun scope"
                )
            cls._require_workspace_target(args.get("path"), context)
            return

        if normalized in cls._COMMAND_KINDS:
            command = str(args.get("command") or "")
            # W-1: the permission denylist is global -- it blocks a
            # WorkerRun command even when its digest matches the admitted
            # action. The digest still pins the exact command; the
            # denylist is an additional, absolute block.
            if permission_policy is not None and permission_policy.denies(
                "terminal_command", command
            ):
                raise WorkerActionAuthorityError(
                    "worker command is denied by the permission policy (denylist)"
                )
            if not command or not context.allowed_command_sha256:
                raise WorkerActionAuthorityError("worker command is not bound to the admitted action")
            if ActionAuthorityContext.command_digest(command) != context.allowed_command_sha256:
                raise WorkerActionAuthorityError("worker command differs from the admitted action")
            if context.expected_action != "run_python":
                raise WorkerActionAuthorityError(
                    "worker command is outside the admitted action contract"
                )
            can_execute = (
                "terminal.python" in tools and "terminal_execute" in authorities
            )
            can_verify = (
                "terminal.test" in tools and "terminal_verify" in authorities
            )
            if not (can_execute or can_verify):
                raise WorkerActionAuthorityError(
                    "terminal capability is outside WorkerRun scope"
                )
            workdir = args.get("workdir")
            if workdir is not None:
                cls._require_workspace_target(workdir, context, allow_root=True)
            return

        if normalized in cls._READ_KINDS:
            if "workspace.read" not in tools or "workspace_read" not in authorities:
                raise WorkerActionAuthorityError("workspace read capability is outside WorkerRun scope")
            cls._require_workspace_target(args.get("path"), context, allow_root=True)
            return

        if normalized in cls._GIT_READ_KINDS:
            if "git.status" not in tools and "git.diff" not in tools:
                raise WorkerActionAuthorityError("Git read capability is outside WorkerRun scope")
            root = args.get("root") or args.get("workdir") or context.workspace_root
            cls._require_workspace_target(root, context, allow_root=True)
            return

        raise WorkerActionAuthorityError(
            f"Body action {normalized or '<empty>'} is not admitted for a WorkerRun"
        )

    @staticmethod
    def _require_workspace_target(
        raw_target: object,
        context: ActionAuthorityContext,
        *,
        allow_root: bool = False,
    ) -> None:
        if not context.workspace_root:
            raise WorkerActionAuthorityError("WorkerRun has no workspace target scope")
        if raw_target is None or not str(raw_target).strip():
            if allow_root:
                return
            raise WorkerActionAuthorityError("worker action has no target path")
        root = Path(context.workspace_root).expanduser().resolve(strict=False)
        target = Path(str(raw_target)).expanduser().resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise WorkerActionAuthorityError("worker target is outside the attached workspace") from exc


class AuthorityEnforcedBody:
    """Admission gate that delegates to the original bound ``body.act`` method."""

    def __init__(
        self,
        body,
        *,
        resident=None,
        permission_policy=None,
        sandbox_gate: SandboxGate | None = None,
        sandbox_policy: SandboxPolicy | None = None,
    ) -> None:
        self._body = body
        self._original_act = body.act
        self._resident = resident
        self._permission_policy = permission_policy
        self._sandbox_gate = sandbox_gate
        if self._sandbox_gate is None and sandbox_policy is not None:
            self._sandbox_gate = SandboxGate(sandbox_policy)

    def act(self, kind: str, *, event_id: str | None = None, **args: Any) -> BodyActionResult:
        raw_context = args.pop(_AUTHORITY_ARG, None)
        escalation_token = args.pop(_ESCALATION_TOKEN_ARG, None)
        if raw_context is not None:
            try:
                if not isinstance(raw_context, dict):
                    raise WorkerActionAuthorityError("worker action authority context is malformed")
                context = ActionAuthorityContext.from_dict(raw_context)
                self._revalidate_durable_authority(context)
                WorkerActionAuthorityEnforcer.authorize(
                    kind,
                    args,
                    context,
                    permission_policy=self._permission_policy,
                    sandbox_gate=self._sandbox_gate,
                    escalation_token=escalation_token,
                )
            except (WorkerActionAuthorityError, TypeError, ValueError) as exc:
                return self._record_denial(kind, event_id=event_id, args=args, error=exc)
        return self._original_act(kind, event_id=event_id, **args)

    def _record_denial(
        self,
        kind: str,
        *,
        event_id: str | None,
        args: dict[str, Any],
        error: BaseException,
    ) -> BodyActionResult:
        action = BodyAction(
            action_id=f"body-{uuid.uuid4().hex[:12]}",
            kind=str(kind or "").strip().lower(),
            args=dict(args),
            event_id=event_id,
        )
        started = utc_now()
        result = BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=False,
            error=f"WorkerActionAuthorityError: {error}",
            event_id=event_id,
            started_at=started,
            completed_at=utc_now(),
        )
        try:
            self._body._record(action, result)
        except Exception:
            # The rejection itself remains fail-closed even if secondary audit
            # persistence is unavailable; never fall through to the real effect.
            pass
        return result

    def _revalidate_durable_authority(self, context: ActionAuthorityContext) -> None:
        resident = self._resident
        if resident is None:
            return
        ledger = resident.work_ledger
        current_plan = int(ledger.plan_version(context.work_thread_id))
        if current_plan != context.plan_version:
            raise WorkerActionAuthorityError("worker action belongs to a stale Work plan")
        worker = ledger.worker_run(context.worker_run_id)
        if worker is None:
            raise WorkerActionAuthorityError("worker action references a missing WorkerRun")
        if (
            worker.work_item_id != context.work_item_id
            or worker.plan_version != context.plan_version
            or worker.executor_kind != context.executor_kind
            or tuple(worker.tool_scope) != tuple(context.tool_scope)
            or tuple(worker.authority_scope) != tuple(context.authority_scope)
        ):
            raise WorkerActionAuthorityError("worker action authority no longer matches durable WorkerRun")
        if worker.state not in {"queued", "running", "completed"}:
            raise WorkerActionAuthorityError(
                f"worker action cannot execute from WorkerRun state {worker.state}"
            )


def install_worker_authority_gate(
    body, *, resident, permission_policy=None, sandbox_gate=None, sandbox_policy=None
) -> AuthorityEnforcedBody:
    """Install once without replacing the existing Body object or its class."""

    existing = getattr(body, "_zn_worker_authority_gate", None)
    if isinstance(existing, AuthorityEnforcedBody):
        return existing
    gate = AuthorityEnforcedBody(
        body,
        resident=resident,
        permission_policy=permission_policy,
        sandbox_gate=sandbox_gate,
        sandbox_policy=sandbox_policy,
    )
    body.act = gate.act
    body._zn_worker_authority_gate = gate
    return gate


def bind_worker_authority_arg(
    args: dict[str, Any],
    context: ActionAuthorityContext,
) -> dict[str, Any]:
    bound = dict(args)
    bound[_AUTHORITY_ARG] = context.to_dict()
    return bound
