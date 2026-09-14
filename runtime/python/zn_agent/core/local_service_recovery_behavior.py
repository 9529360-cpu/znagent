from __future__ import annotations

"""E2E-21 bounded natural-language local-service diagnosis and repair.

This behavior composes the existing Product Resident, Work ledger, read-only
``local_service_state`` Body movement, and guarded ``command`` side-effect path.
It does not add a service manager or a second execution authority.

The representative slice requires an exact current-service context from the Work
caller for observation (loopback host/port, process name, health path and a log
path relative to the attached workspace). Mutation authority is narrower: the
user task itself must name exactly one project-local Python repair script in an
inline code span. The Resident resolves that script inside the attached workspace
and executes it at most once through the existing command side-effect guard.

A command result never proves recovery. Completion requires a fresh service
observation after the mutation that independently proves a healthy listener and
health endpoint. If a crash makes the command dispatch uncertain, later steps may
only re-observe current reality; the command is never replayed blindly.
"""

import hashlib
import json
import re
import shlex
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .file_identity import observe_file_identity
from .models import ExecutionPath, ResidentRunResult, utc_now


_STATE_KEY = "e2e21_local_service_recovery"
_INSTALL_MARKER = "_e2e21_local_service_recovery_installed"
_ACCEPTANCE = "local_service_recovery:v1"
_VERIFY_ATTEMPTS = 40
_VERIFY_INTERVAL_SECONDS = 0.1
_MAX_SCRIPT_CHARS = 260
_MAX_REPAIR_SCRIPT_BYTES = 2 * 1024 * 1024
_INLINE_CODE = re.compile(r"(?<!`)`([^`\r\n]{1,260})`(?!`)")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_SERVICE_MARKERS = (
    "这个服务",
    "服务为什么挂",
    "服务挂了",
    "local service",
    "service is down",
    "service went down",
)
_REPAIR_MARKERS = (
    "能安全修就修",
    "安全修",
    "修好",
    "safe to fix",
    "repair it",
    "fix it",
)
_VERIFY_MARKERS = (
    "确认它真的恢复",
    "确认恢复",
    "确认真的恢复",
    "verify it recovered",
    "confirm it recovered",
    "make sure it recovered",
)


class _Blocked(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _request(event) -> dict[str, str] | None:
    if str(getattr(event, "kind", "") or "").strip().lower() != "desktop_user_event":
        return None
    payload = getattr(event, "payload", {}) or {}
    if payload.get("body_action") or payload.get("native_action"):
        return None

    task = " ".join(str(getattr(event, "task", "") or "").split())
    lowered = task.casefold()
    if not any(marker.casefold() in lowered for marker in _SERVICE_MARKERS):
        return None
    if not any(marker.casefold() in lowered for marker in _REPAIR_MARKERS):
        return None
    if not any(marker.casefold() in lowered for marker in _VERIFY_MARKERS):
        return None

    code_spans = [value.strip() for value in _INLINE_CODE.findall(task) if value.strip()]
    python_scripts = [value for value in code_spans if value.casefold().endswith(".py")]
    repair_script = python_scripts[0] if len(python_scripts) == 1 and len(code_spans) == 1 else ""
    return {"repair_script": repair_script}


def _authorized_workspace(resident, event, root) -> Path:
    payload = getattr(event, "payload", {}) or {}
    explicit = str(payload.get("workspace_path") or "").strip()
    if not explicit:
        raise _Blocked(
            "workspace_authority_missing",
            "local-service recovery requires one exact attached Work workspace",
        )
    thread = resident.work_ledger.get_thread(root.work_thread_id)
    association = resident.work_ledger.workspace_for(thread) if thread is not None else None
    if association is None:
        raise _Blocked("workspace_authority_missing", "current Root Work has no attached workspace")
    try:
        requested = Path(explicit).resolve(strict=True)
        attached = Path(association.path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _Blocked("workspace_authority_missing", "attached workspace is unavailable") from exc
    if requested != attached or not requested.is_dir():
        raise _Blocked(
            "workspace_authority_missing",
            "event workspace does not exactly match the current Root Work workspace",
        )
    return requested


def _relative_file(workspace: Path, raw: str, *, code: str, suffix: str | None = None) -> Path:
    normalized = str(raw or "").strip().replace("\\", "/")
    if not normalized or len(normalized) > _MAX_SCRIPT_CHARS:
        raise _Blocked(code, "required project-local file identity is missing or too long")
    relative = PurePosixPath(normalized)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise _Blocked(code, "project-local file identity must be traversal-free and relative")
    if suffix and relative.suffix.casefold() != suffix.casefold():
        raise _Blocked(code, f"project-local file must use {suffix}")
    candidate = workspace.joinpath(*relative.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(workspace)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _Blocked(code, "project-local file is unavailable inside the attached workspace") from exc
    if not resolved.is_file():
        raise _Blocked(code, "project-local file is not a regular file")
    return resolved


def _observe_repair_script_identity(path: Path) -> dict[str, Any]:
    """Capture privacy-bounded exact repair-script identity for pre-mutation reuse."""

    observed = observe_file_identity(path, max_hash_bytes=_MAX_REPAIR_SCRIPT_BYTES)
    if not (
        observed.get("observable") is True
        and observed.get("stable") is True
        and observed.get("exists") is True
        and str(observed.get("type") or "") == "file"
        and observed.get("digest_complete") is True
        and str(observed.get("content_sha256") or "")
    ):
        raise _Blocked(
            "repair_script_identity_unavailable",
            "repair script does not have one stable complete file identity within the bounded hash limit",
        )
    resolved_path = str(observed.get("path") or "")
    return {
        "version": observed.get("version"),
        "resolved_path_sha256": hashlib.sha256(resolved_path.encode("utf-8")).hexdigest(),
        "size_bytes": observed.get("size_bytes"),
        "mtime_ns": observed.get("mtime_ns"),
        "ctime_ns": observed.get("ctime_ns"),
        "device": observed.get("device"),
        "inode": observed.get("inode"),
        "content_sha256": observed.get("content_sha256"),
    }


def _same_repair_script_identity(expected: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    keys = (
        "version",
        "resolved_path_sha256",
        "size_bytes",
        "mtime_ns",
        "ctime_ns",
        "device",
        "inode",
        "content_sha256",
    )
    return all(expected.get(key) == current.get(key) for key in keys)


def _service_context(event, workspace: Path) -> tuple[dict[str, Any], Path]:
    payload = getattr(event, "payload", {}) or {}
    raw = payload.get("local_service_context")
    if not isinstance(raw, Mapping):
        raise _Blocked(
            "service_context_missing",
            "the current Work has no exact local-service observation context",
        )

    try:
        port = int(raw.get("port") or 0)
    except (TypeError, ValueError) as exc:
        raise _Blocked("service_context_invalid", "local-service port is invalid") from exc
    if not 1 <= port <= 65535:
        raise _Blocked("service_context_invalid", "local-service port is outside 1..65535")

    host = str(raw.get("host") or "127.0.0.1").strip().casefold().strip("[]")
    if host not in _LOOPBACK_HOSTS:
        raise _Blocked(
            "service_context_invalid",
            "representative local-service recovery accepts loopback targets only",
        )

    expected_process_name = str(raw.get("expected_process_name") or "").strip()
    if not expected_process_name or len(expected_process_name) > 260:
        raise _Blocked(
            "service_context_invalid",
            "an exact expected process name is required for repair admission",
        )

    health_path = str(raw.get("health_path") or "/health").strip()
    if (
        not health_path.startswith("/")
        or "//" in health_path
        or "://" in health_path
        or "#" in health_path
        or len(health_path) > 512
    ):
        raise _Blocked("service_context_invalid", "local health path is invalid")

    log_path = _relative_file(
        workspace,
        str(raw.get("log_relative_path") or ""),
        code="service_log_authority_missing",
    )
    url_host = "127.0.0.1" if host == "localhost" else f"[{host}]" if ":" in host else host
    return (
        {
            "port": port,
            "host": host,
            "expected_process_name": expected_process_name,
            "health_url": f"http://{url_host}:{port}{health_path}",
            "log_path": str(log_path),
            "log_root": str(workspace),
            "health_timeout": 1.0,
        },
        log_path,
    )


def _listener_identity(data: Mapping[str, Any]) -> dict[str, Any] | None:
    rows = data.get("listeners")
    if not isinstance(rows, (list, tuple)):
        return None
    identities: dict[tuple[int, float], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            pid = int(row.get("pid") or 0)
            created = float(row.get("created_at_epoch"))
        except (TypeError, ValueError):
            continue
        if pid <= 0 or created <= 0:
            continue
        identities[(pid, created)] = {
            "pid": pid,
            "created_at_epoch": created,
            "process_name": str(row.get("process_name") or "").strip() or None,
        }
    return next(iter(identities.values())) if len(identities) == 1 else None


def _same_identity(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    try:
        return (
            int(left.get("pid") or 0) == int(right.get("pid") or 0)
            and abs(
                float(left.get("created_at_epoch") or 0.0)
                - float(right.get("created_at_epoch") or 0.0)
            )
            <= 0.001
        )
    except (TypeError, ValueError):
        return False


def _health_status(data: Mapping[str, Any]) -> int | None:
    health = data.get("health")
    if not isinstance(health, Mapping):
        return None
    try:
        return int(health.get("status_code")) if health.get("status_code") is not None else None
    except (TypeError, ValueError):
        return None


def _safe_evidence(meta: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "status": meta.get("status"),
        "port": meta.get("port"),
        "host": meta.get("host"),
        "expected_process_name": meta.get("expected_process_name"),
        "repair_script_chars": meta.get("repair_script_chars"),
        "repair_script_sha256": meta.get("repair_script_sha256"),
        "initial_pid": meta.get("initial_pid"),
        "initial_created_at_epoch": meta.get("initial_created_at_epoch"),
        "pre_repair_health_status": meta.get("pre_repair_health_status"),
        "side_effect_attempt_id": meta.get("side_effect_attempt_id"),
        "command_dispatch_observed": meta.get("command_dispatch_observed"),
        "command_success": meta.get("command_success"),
        "verification_attempts": meta.get("verification_attempts", 0),
        "final_pid": meta.get("final_pid"),
        "final_created_at_epoch": meta.get("final_created_at_epoch"),
        "final_health_status": meta.get("final_health_status"),
        "blocker": meta.get("blocker"),
    }


def _persist(resident, event, meta: Mapping[str, Any], *, status: str, blocker: str | None = None) -> None:
    root = resident.work_ledger.work_item_for_event(event.event_id)
    if root is None:
        return
    item = next(
        (
            candidate
            for candidate in resident.work_ledger.list_work_items(root.work_thread_id, limit=256)
            if candidate.parent_work_item_id == root.work_item_id
            and candidate.plan_version == root.plan_version
            and _ACCEPTANCE in candidate.acceptance_criteria
        ),
        None,
    )
    if item is None:
        item = resident.work_ledger.create_child_item(
            root_work_item_id=root.work_item_id,
            objective=(
                "Diagnose one exact local service, admit at most one project-local repair, "
                "and independently verify restored service health"
            ),
            acceptance_criteria=[_ACCEPTANCE],
            title="Local service recovery",
        )
    now = utc_now()
    item.status = "completed" if status == "complete" else "blocked" if status == "blocked" else "running"
    evidence = _safe_evidence(meta)
    if blocker:
        evidence["blocker"] = str(blocker)[:2000]
    item.result = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
    item.blocker = str(blocker)[:4000] if blocker else None
    item.updated_at = now
    if status == "complete":
        item.completed_at = now
    resident.work_ledger._save_item(item)


def _blocked(resident, event, state, meta: dict[str, Any], code: str, detail: str, response: str) -> ResidentRunResult:
    reason = f"{code}: {detail}"[:4000]
    meta["status"] = "blocked"
    meta["blocker"] = {"code": code, "detail": str(detail)[:1200]}
    state.data[_STATE_KEY] = meta
    state.stage = "failed"
    state.next_action = None
    state.blocked_by = code
    resident.store.save_working_state(state)
    _persist(resident, event, meta, status="blocked", blocker=reason)
    return ResidentRunResult(
        event=event,
        execution_path=ExecutionPath.INVESTIGATION,
        success=False,
        response=response[:8000],
        model_invocations=0,
        reason=reason,
    )


def _complete(resident, event, state, meta: dict[str, Any], *, repaired: bool) -> ResidentRunResult:
    meta["status"] = "complete"
    state.data[_STATE_KEY] = meta
    state.stage = "complete"
    state.next_action = None
    state.blocked_by = None
    resident.store.save_working_state(state)
    _persist(resident, event, meta, status="complete")
    response = (
        "服务已重新观测为健康；修复后 listener/process 与 HTTP health 都通过了 fresh verification。"
        if repaired
        else "服务当前已经是健康状态；ZN 没有执行修复命令。"
    )
    return ResidentRunResult(
        event=event,
        execution_path=ExecutionPath.BODY,
        success=True,
        response=response,
        model_invocations=0,
        reason=(
            "E2E-21 VERIFIED NARROW only after fresh local listener/process/health evidence; "
            + (
                "one guarded project-local repair dispatch was independently followed by fresh health verification"
                if repaired
                else "no mutation was needed because the initial fresh observation was already healthy"
            )
        ),
    )


def _begin(resident, event, state, request: Mapping[str, str]):
    root = resident.work_ledger.work_item_for_event(event.event_id)
    if root is None or root.parent_work_item_id is not None:
        return _blocked(
            resident,
            event,
            state,
            {},
            "missing_root_work",
            "E2E-21 requires one durable Root Work",
            "当前任务没有绑定到可持续的 Root Work，因此没有诊断或修复服务。",
        )

    try:
        workspace = _authorized_workspace(resident, event, root)
        repair_script_raw = str(request.get("repair_script") or "").strip()
        if not repair_script_raw:
            raise _Blocked(
                "repair_authority_missing",
                "user task must identify exactly one project-local .py repair script in an inline code span",
            )
        repair_script = _relative_file(
            workspace,
            repair_script_raw,
            code="repair_authority_missing",
            suffix=".py",
        )
        repair_script_identity = _observe_repair_script_identity(repair_script)
        service_args, _ = _service_context(event, workspace)
    except _Blocked as exc:
        return _blocked(
            resident,
            event,
            state,
            {},
            exc.code,
            exc.detail,
            "当前服务上下文或项目内修复权限不够明确；ZN 没有执行任何修复命令。",
        )

    script_identity = repair_script.relative_to(workspace).as_posix()
    meta: dict[str, Any] = {
        "version": 1,
        "status": "diagnosing",
        "work_thread_id": root.work_thread_id,
        "root_work_item_id": root.work_item_id,
        "plan_version": root.plan_version,
        "port": service_args["port"],
        "host": service_args["host"],
        "expected_process_name": service_args["expected_process_name"],
        "repair_script_chars": len(script_identity),
        "repair_script_sha256": hashlib.sha256(script_identity.encode("utf-8")).hexdigest(),
        "repair_script_identity": repair_script_identity,
        "verification_attempts": 0,
    }

    observed = resident.body.act("local_service_state", event_id=event.event_id, **service_args)
    if not observed.success:
        return _blocked(
            resident,
            event,
            state,
            meta,
            "service_observation_failed",
            observed.error or "initial local-service observation failed",
            "服务当前状态无法可靠观测，因此没有执行修复。",
        )
    data = observed.data if isinstance(observed.data, dict) else {}
    if bool(data.get("healthy")):
        identity = _listener_identity(data)
        if identity is not None:
            meta["final_pid"] = identity["pid"]
            meta["final_created_at_epoch"] = identity["created_at_epoch"]
        meta["final_health_status"] = _health_status(data)
        return _complete(resident, event, state, meta, repaired=False)

    blocked_reason = str(data.get("repair_blocked_reason") or "").strip()
    if blocked_reason:
        return _blocked(
            resident,
            event,
            state,
            meta,
            "repair_not_admitted",
            blocked_reason,
            "服务当前的 listener/process 证据不允许安全修复；ZN 没有执行修复命令。",
        )
    identity = _listener_identity(data)
    if identity is None:
        return _blocked(
            resident,
            event,
            state,
            meta,
            "service_identity_ambiguous",
            "one exact listener PID + creation-time identity could not be proven",
            "服务进程身份不唯一或不完整；ZN 没有执行修复命令。",
        )

    meta.update(
        {
            "status": "pre_repair_revalidation",
            "initial_pid": identity["pid"],
            "initial_created_at_epoch": identity["created_at_epoch"],
            "pre_repair_health_status": _health_status(data),
        }
    )
    state.data[_STATE_KEY] = meta
    state.stage = "e2e21_pre_repair"
    state.next_action = "freshly revalidate the exact listener and repair-script identities before one guarded repair"
    state.blocked_by = None
    resident.store.save_working_state(state)
    _persist(resident, event, meta, status="running")
    return None


def _repair(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    root = resident.work_ledger.work_item_for_event(event.event_id)
    if root is None:
        return _blocked(
            resident,
            event,
            state,
            meta,
            "missing_root_work",
            "Root Work disappeared before repair",
            "Root Work 已不可用；ZN 没有重放修复命令。",
        )
    try:
        workspace = _authorized_workspace(resident, event, root)
        request = _request(event) or {}
        repair_script = _relative_file(
            workspace,
            str(request.get("repair_script") or ""),
            code="repair_authority_missing",
            suffix=".py",
        )
        service_args, _ = _service_context(event, workspace)
    except _Blocked as exc:
        return _blocked(
            resident,
            event,
            state,
            meta,
            exc.code,
            exc.detail,
            "修复前权限或服务上下文已变化；ZN 没有执行或重放修复命令。",
        )

    fresh = resident.body.act("local_service_state", event_id=event.event_id, **service_args)
    if not fresh.success:
        return _blocked(
            resident,
            event,
            state,
            meta,
            "service_revalidation_failed",
            fresh.error or "fresh pre-repair service observation failed",
            "修复前无法重新确认服务状态；ZN 没有执行修复命令。",
        )
    data = fresh.data if isinstance(fresh.data, dict) else {}
    if bool(data.get("healthy")):
        identity = _listener_identity(data)
        if identity is not None:
            meta["final_pid"] = identity["pid"]
            meta["final_created_at_epoch"] = identity["created_at_epoch"]
        meta["final_health_status"] = _health_status(data)
        return _complete(resident, event, state, meta, repaired=False)
    if str(data.get("repair_blocked_reason") or "").strip():
        return _blocked(
            resident,
            event,
            state,
            meta,
            "repair_not_admitted",
            "fresh listener ownership now blocks repair",
            "服务 listener/process 状态已变化，当前不再允许安全修复。",
        )

    fresh_identity = _listener_identity(data)
    expected_identity = {
        "pid": meta.get("initial_pid"),
        "created_at_epoch": meta.get("initial_created_at_epoch"),
    }
    if fresh_identity is None or not _same_identity(fresh_identity, expected_identity):
        return _blocked(
            resident,
            event,
            state,
            meta,
            "service_identity_drift",
            "listener PID/creation-time identity changed before mutation",
            "服务进程身份在修复前发生变化；ZN 没有执行修复命令。",
        )

    try:
        fresh_script_identity = _observe_repair_script_identity(repair_script)
    except _Blocked as exc:
        return _blocked(
            resident,
            event,
            state,
            meta,
            exc.code,
            exc.detail,
            "修复脚本在执行前已无法证明为同一个稳定文件；ZN 没有执行修复命令。",
        )
    expected_script_identity = meta.get("repair_script_identity")
    if not isinstance(expected_script_identity, Mapping) or not _same_repair_script_identity(
        expected_script_identity,
        fresh_script_identity,
    ):
        return _blocked(
            resident,
            event,
            state,
            meta,
            "repair_script_identity_drift",
            "repair script path/content identity changed between authorization and mutation",
            "修复脚本在诊断后发生变化；ZN 没有执行修复命令。",
        )

    executable = str(Path(sys.executable).resolve()).replace("\\", "/")
    script_rel = repair_script.relative_to(workspace).as_posix()
    command = f"{shlex.quote(executable)} {shlex.quote(script_rel)}"
    repaired = resident.body.act(
        "command",
        event_id=event.event_id,
        command=command,
        workdir=str(workspace),
        timeout=10.0,
        max_output_chars=4_000,
        local_service_repair=True,
    )
    result_data = repaired.data if isinstance(repaired.data, dict) else {}
    attempt_id = str(result_data.get("side_effect_attempt_id") or "").strip()
    if attempt_id:
        meta["side_effect_attempt_id"] = attempt_id
    uncertain = bool(result_data.get("side_effect_uncertain")) or bool(
        result_data.get("replay_blocked")
    )
    dispatch_observed = result_data.get("side_effect_dispatch_observed") is True
    meta["command_dispatch_observed"] = dispatch_observed
    meta["command_success"] = bool(repaired.success)

    if not uncertain and (not dispatch_observed or not attempt_id):
        return _blocked(
            resident,
            event,
            state,
            meta,
            "side_effect_guard_unconfirmed",
            "repair command returned without a durable observed side-effect attempt receipt",
            "修复命令没有返回 durable side-effect checkpoint；ZN 不会重放它。",
        )

    meta["status"] = "verify_after_uncertain_dispatch" if uncertain else "verify_after_repair"
    meta["verification_attempts"] = 0
    state.data[_STATE_KEY] = meta
    state.stage = "e2e21_verify"
    state.next_action = "freshly observe listener/process/health without replaying repair"
    state.blocked_by = None
    resident.store.save_working_state(state)
    _persist(resident, event, meta, status="running")
    return None


def _verify(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    root = resident.work_ledger.work_item_for_event(event.event_id)
    if root is None:
        return _blocked(
            resident,
            event,
            state,
            meta,
            "missing_root_work",
            "Root Work disappeared during verification",
            "修复后的 Work 已不可用；ZN 不会重放修复命令。",
        )
    try:
        workspace = _authorized_workspace(resident, event, root)
        service_args, _ = _service_context(event, workspace)
    except _Blocked as exc:
        return _blocked(
            resident,
            event,
            state,
            meta,
            exc.code,
            exc.detail,
            "修复后的服务上下文已不可验证；ZN 不会重放修复命令。",
        )

    time.sleep(_VERIFY_INTERVAL_SECONDS)
    observed = resident.body.act("local_service_state", event_id=event.event_id, **service_args)
    meta["verification_attempts"] = int(meta.get("verification_attempts") or 0) + 1
    if not observed.success:
        if meta["verification_attempts"] < _VERIFY_ATTEMPTS:
            state.data[_STATE_KEY] = meta
            resident.store.save_working_state(state)
            _persist(resident, event, meta, status="running")
            return None
        return _blocked(
            resident,
            event,
            state,
            meta,
            "service_verification_unavailable",
            observed.error or "fresh service verification remained unavailable",
            "修复后始终无法取得可靠的服务状态；ZN 没有重放修复命令。",
        )

    data = observed.data if isinstance(observed.data, dict) else {}
    identity = _listener_identity(data)
    if bool(data.get("healthy")) and identity is not None:
        meta["final_pid"] = identity["pid"]
        meta["final_created_at_epoch"] = identity["created_at_epoch"]
        meta["final_health_status"] = _health_status(data)
        return _complete(resident, event, state, meta, repaired=True)

    if meta["verification_attempts"] < _VERIFY_ATTEMPTS:
        meta["final_health_status"] = _health_status(data)
        state.data[_STATE_KEY] = meta
        resident.store.save_working_state(state)
        _persist(resident, event, meta, status="running")
        return None

    return _blocked(
        resident,
        event,
        state,
        meta,
        "service_not_recovered",
        "fresh listener/process/health evidence did not reach the healthy postcondition",
        "修复命令已处理过，但 fresh listener/process/health 仍未证明服务恢复；ZN 不会重复执行修复命令。",
    )


def install_local_service_recovery_behavior(resident) -> None:
    """Attach the bounded E2E-21 path to the one existing Product Resident."""

    if getattr(resident, _INSTALL_MARKER, False):
        return
    original_advance = resident._advance_event_step

    def advance_event_step(event, state, *, readiness, learning_evidence, thought=None):
        stage = str(state.stage or "")
        request = _request(event)
        if stage == "orient" and request is not None:
            return _begin(resident, event, state, request)
        if stage == "e2e21_pre_repair":
            return _repair(resident, event, state)
        if stage == "e2e21_verify":
            return _verify(resident, event, state)
        return original_advance(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    resident._advance_event_step = advance_event_step
    setattr(resident, _INSTALL_MARKER, True)
