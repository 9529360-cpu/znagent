from __future__ import annotations

"""Action-level authority for transient Work/WorkerRun execution.

Authority belongs to the current Work/WorkerRun/action, never to a model or a
permanent agent identity. The active Resident installs this gate on the existing
Body instance, preserving the one Body object's class/store/recovery semantics.
"""

import hashlib
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .body import BodyAction, BodyActionResult
from .models import utc_now


_AUTHORITY_ARG = "__zn_authority_context"


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


class WorkerActionAuthorityEnforcer:
    """Fail-closed checks for Body actions that declare WorkerRun authority."""

    _READ_KINDS = {"inspect_path", "path", "read_text", "read_file", "list_directory", "list_dir"}
    _WRITE_KINDS = {"write_text", "write_file"}
    _COMMAND_KINDS = {"command", "terminal", "shell"}
    _GIT_READ_KINDS = {"git_state", "git", "git_diff"}

    @classmethod
    def authorize(cls, kind: str, args: dict[str, Any], context: ActionAuthorityContext) -> None:
        if not context.worker_run_id or not context.work_item_id or not context.work_thread_id:
            raise WorkerActionAuthorityError("worker action authority identity is incomplete")
        if context.plan_version < 1:
            raise WorkerActionAuthorityError("worker action authority plan_version is invalid")

        normalized = str(kind or "").strip().lower()
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

    def __init__(self, body, *, resident=None) -> None:
        self._body = body
        self._original_act = body.act
        self._resident = resident

    def act(self, kind: str, *, event_id: str | None = None, **args: Any) -> BodyActionResult:
        raw_context = args.pop(_AUTHORITY_ARG, None)
        if raw_context is not None:
            try:
                if not isinstance(raw_context, dict):
                    raise WorkerActionAuthorityError("worker action authority context is malformed")
                context = ActionAuthorityContext.from_dict(raw_context)
                self._revalidate_durable_authority(context)
                WorkerActionAuthorityEnforcer.authorize(kind, args, context)
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


def install_worker_authority_gate(body, *, resident) -> AuthorityEnforcedBody:
    """Install once without replacing the existing Body object or its class."""

    existing = getattr(body, "_zn_worker_authority_gate", None)
    if isinstance(existing, AuthorityEnforcedBody):
        return existing
    gate = AuthorityEnforcedBody(body, resident=resident)
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
