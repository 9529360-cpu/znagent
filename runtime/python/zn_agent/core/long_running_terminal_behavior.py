from __future__ import annotations

"""E2E-22 bounded long-running terminal Work on the existing Product Resident.

This path deliberately reuses the one durable Work ledger and one existing Body.
The user must provide one explicit inline command and the current Work must already
own one exact workspace. The command is dispatched once as an existing background
terminal session; every later step is a read-only ``terminal_poll`` observation.

The representative slice is intentionally not a durable job scheduler. If the
in-memory terminal session is lost (for example after a process restart), ZN fails
closed instead of replaying the command.
"""

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .models import ExecutionPath, ResidentRunResult, utc_now


_STATE_KEY = "e2e22_long_running_terminal"
_INSTALL_MARKER = "_e2e22_long_running_terminal_installed"
_ACCEPTANCE = "long_running_terminal:v1"
_MAX_COMMAND_CHARS = 2_000
_MAX_OUTPUT_CHARS = 8_000
_MONITOR_SECONDS = 120.0
_POLL_INTERVAL_SECONDS = 0.2
_INLINE_COMMAND = re.compile(r"(?<!`)`([^`\r\n]{1,2000})`(?!`)")
_WAIT_MARKERS = (
    "等它结束",
    "等它跑完",
    "等命令结束",
    "等运行结束",
    "运行完成后",
    "跑完以后",
    "跑完后",
    "结束后把结果",
    "完成后把结果",
    "wait until it finishes",
    "wait for it to finish",
    "when it finishes",
    "after it finishes",
    "after the command finishes",
)


def _request(event) -> dict[str, str] | None:
    if str(getattr(event, "kind", "") or "").strip().lower() != "desktop_user_event":
        return None
    payload = getattr(event, "payload", {}) or {}
    if payload.get("body_action") or payload.get("native_action"):
        return None

    task = str(getattr(event, "task", "") or "")
    lowered = " ".join(task.split()).casefold()
    if not any(marker.casefold() in lowered for marker in _WAIT_MARKERS):
        return None

    commands = [match.strip() for match in _INLINE_COMMAND.findall(task) if match.strip()]
    if len(commands) != 1:
        return None
    command = commands[0]
    if len(command) > _MAX_COMMAND_CHARS or "\x00" in command:
        return None

    workspace = str(payload.get("workspace_path") or "").strip()
    if not workspace:
        return None
    return {"command": command, "workspace_path": workspace}


def _authorized_workspace(resident, event, thread_id: str) -> tuple[Path | None, str | None]:
    explicit = str((getattr(event, "payload", {}) or {}).get("workspace_path") or "").strip()
    if not explicit or not thread_id:
        return None, "long-running terminal work requires one exact attached Work workspace"
    thread = resident.work_ledger.get_thread(thread_id)
    association = resident.work_ledger.workspace_for(thread) if thread is not None else None
    if association is None:
        return None, "current Work has no attached workspace"
    try:
        requested = Path(explicit).resolve(strict=True)
        attached = Path(association.path).resolve(strict=True)
    except (OSError, RuntimeError):
        return None, "attached workspace is unavailable"
    if requested != attached or not requested.is_dir():
        return None, "terminal workdir does not match the current Work workspace"
    return requested, None


def _safe_process_evidence(meta: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "command_sha256": meta.get("command_sha256"),
        "command_chars": meta.get("command_chars"),
        "workspace": meta.get("workspace"),
        "session_id": meta.get("session_id"),
        "pid": meta.get("pid"),
        "status": meta.get("status"),
        "exit_code": meta.get("exit_code"),
        "poll_count": meta.get("poll_count", 0),
        "started_at": meta.get("started_at"),
        "last_observed_at": meta.get("last_observed_at"),
        "completed_at": meta.get("completed_at"),
        "output_chars": meta.get("output_chars", 0),
        "output_sha256": meta.get("output_sha256"),
        "output_truncated": bool(meta.get("output_truncated", False)),
        "blocker": meta.get("blocker"),
    }


def _persist(
    resident,
    event,
    meta: Mapping[str, Any],
    *,
    status: str,
    blocker: str | None = None,
) -> None:
    root = resident.work_ledger.work_item_for_event(event.event_id)
    if root is None:
        return
    current = next(
        (
            item
            for item in resident.work_ledger.list_work_items(root.work_thread_id, limit=256)
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
            and _ACCEPTANCE in item.acceptance_criteria
        ),
        None,
    )
    if current is None:
        current = resident.work_ledger.create_child_item(
            root_work_item_id=root.work_item_id,
            objective=(
                "Run one explicit user command once and monitor the same terminal session "
                "until real process completion without model cognition for waiting"
            ),
            acceptance_criteria=[_ACCEPTANCE],
            title="Long-running command",
        )
    now = utc_now()
    current.status = (
        "completed" if status == "complete" else "blocked" if status == "blocked" else "running"
    )
    evidence = _safe_process_evidence(meta)
    if blocker:
        evidence["blocker"] = str(blocker)[:2000]
    current.result = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
    current.blocker = str(blocker)[:4000] if blocker else None
    current.updated_at = now
    if status == "complete":
        current.completed_at = now
    resident.work_ledger._save_item(current)


def _blocked(
    resident,
    event,
    state,
    meta: dict[str, Any],
    code: str,
    detail: str,
    response: str,
) -> ResidentRunResult:
    reason = f"{code}: {detail}"[:4000]
    meta["status"] = "blocked"
    meta["blocker"] = {"code": code, "detail": str(detail)[:2000]}
    meta["last_observed_at"] = utc_now()
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
        response=str(response)[:8000],
        model_invocations=0,
        reason=reason,
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
            "E2E-22 requires one durable Root Work created by normal product ingress",
            "当前任务没有绑定到可持续的 Root Work，因此没有启动命令。",
        )

    workspace, error = _authorized_workspace(resident, event, root.work_thread_id)
    command = str(request.get("command") or "")
    meta: dict[str, Any] = {
        "version": 1,
        "work_thread_id": root.work_thread_id,
        "root_work_item_id": root.work_item_id,
        "plan_version": root.plan_version,
        "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
        "command_chars": len(command),
        "workspace": str(workspace) if workspace is not None else None,
        "status": "preflight",
        "poll_count": 0,
        "model_invocations": 0,
    }
    if error or workspace is None:
        return _blocked(
            resident,
            event,
            state,
            meta,
            "workspace_authority_missing",
            error or "workspace unavailable",
            "当前 Work 没有唯一、匹配的项目目录权限，因此没有启动命令。",
        )

    try:
        started = resident.body.act(
            "command",
            event_id=event.event_id,
            command=command,
            workdir=str(workspace),
            background=True,
            task_id=root.work_item_id,
            max_output_chars=_MAX_OUTPUT_CHARS,
        )
    except Exception as exc:
        return _blocked(
            resident,
            event,
            state,
            meta,
            "command_start_failed",
            f"{type(exc).__name__}: {exc}",
            "命令没有建立可监控的后台进程；ZN 不会自动重试这个有副作用的启动动作。",
        )

    data = started.data if isinstance(started.data, dict) else {}
    session_id = str(data.get("session_id") or "").strip()
    status = str(data.get("status") or "").strip().lower()
    try:
        pid = int(data.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if not started.success or status != "running" or not session_id or pid <= 0:
        return _blocked(
            resident,
            event,
            state,
            meta,
            "background_session_not_established",
            started.error or f"unexpected terminal start status: {status or '<empty>'}",
            "命令启动结果没有证明唯一的 running terminal session；为避免重复执行，ZN 不会重新启动它。",
        )

    now = utc_now()
    meta.update(
        {
            "session_id": session_id,
            "pid": pid,
            "status": "running",
            "started_at": now,
            "last_observed_at": now,
        }
    )
    state.data[_STATE_KEY] = meta
    state.stage = "e2e22_wait"
    state.next_action = "poll the same terminal session for real process completion"
    state.blocked_by = None
    resident.store.save_working_state(state)
    _persist(resident, event, meta, status="running")
    return None


def _elapsed_seconds(started_at: str) -> float:
    try:
        started = datetime.fromisoformat(str(started_at))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return _MONITOR_SECONDS + 1.0


def _record_output_evidence(meta: dict[str, Any], output: str, *, truncated: bool) -> None:
    encoded = str(output or "").encode("utf-8")
    meta["output_chars"] = len(str(output or ""))
    meta["output_sha256"] = hashlib.sha256(encoded).hexdigest()
    meta["output_truncated"] = bool(truncated)


def _poll(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    session_id = str(meta.get("session_id") or "").strip()
    expected_pid = int(meta.get("pid") or 0)
    if not session_id or expected_pid <= 0:
        return _blocked(
            resident,
            event,
            state,
            meta,
            "terminal_session_identity_missing",
            "durable wait state lost its session or process identity",
            "等待状态缺少可验证的 terminal session 身份；ZN 不会重跑命令。",
        )

    elapsed = _elapsed_seconds(str(meta.get("started_at") or ""))
    if elapsed > _MONITOR_SECONDS:
        return _blocked(
            resident,
            event,
            state,
            meta,
            "monitor_window_exceeded",
            f"process remained unverified after {_MONITOR_SECONDS:g}s bounded monitor window",
            "命令仍未在第一版 bounded 观察窗口内完成。ZN 没有重跑、停止或替换这个进程。",
        )

    time.sleep(min(_POLL_INTERVAL_SECONDS, max(0.0, _MONITOR_SECONDS - elapsed)))
    try:
        observed = resident.body.act(
            "terminal_poll",
            event_id=event.event_id,
            session_id=session_id,
        )
    except Exception as exc:
        return _blocked(
            resident,
            event,
            state,
            meta,
            "terminal_session_lost",
            f"{type(exc).__name__}: {exc}",
            "原来的 terminal session 已无法继续观测。为避免重复副作用，ZN 不会重新执行命令。",
        )

    data = observed.data if isinstance(observed.data, dict) else {}
    status = str(data.get("status") or "").strip().lower()
    observed_session = str(data.get("session_id") or "").strip()
    try:
        observed_pid = int(data.get("pid") or 0)
    except (TypeError, ValueError):
        observed_pid = 0
    if observed_session != session_id or observed_pid != expected_pid:
        return _blocked(
            resident,
            event,
            state,
            meta,
            "terminal_session_identity_drift",
            "terminal poll no longer matches the admitted session/process identity",
            "terminal poll 返回了不同的 session/process 身份；ZN 不会把它当成原命令完成。",
        )

    output = str(observed.output or "")
    meta["poll_count"] = int(meta.get("poll_count") or 0) + 1
    meta["last_observed_at"] = utc_now()
    meta["status"] = status or "unknown"
    _record_output_evidence(meta, output, truncated=bool(data.get("truncated", False)))

    if status == "running":
        if not observed.success:
            return _blocked(
                resident,
                event,
                state,
                meta,
                "running_poll_failed",
                observed.error or "running terminal poll was unsuccessful",
                "进程仍显示 running，但状态观测失败；ZN 不会重跑命令。",
            )
        state.data[_STATE_KEY] = meta
        state.stage = "e2e22_wait"
        state.next_action = "poll the same terminal session for real process completion"
        resident.store.save_working_state(state)
        _persist(resident, event, meta, status="running")
        return None

    if status != "completed":
        return _blocked(
            resident,
            event,
            state,
            meta,
            "unexpected_terminal_status",
            observed.error or f"unexpected terminal status: {status or '<empty>'}",
            "terminal session 没有给出可接受的 completed 状态；ZN 不会重跑命令。",
        )

    try:
        exit_code = int(data.get("exit_code"))
    except (TypeError, ValueError):
        exit_code = None
    meta["exit_code"] = exit_code
    meta["completed_at"] = utc_now()
    meta["status"] = "completed"
    state.data[_STATE_KEY] = meta

    if not observed.success or exit_code != 0:
        detail = observed.error or f"command exited with code {exit_code}"
        return _blocked(
            resident,
            event,
            state,
            meta,
            "command_completed_nonzero",
            detail,
            ("命令已经真实结束，但退出码不是 0。ZN 没有重跑命令。\n" + output.strip())[:8000],
        )

    state.stage = "complete"
    state.next_action = None
    state.blocked_by = None
    resident.store.save_working_state(state)
    _persist(resident, event, meta, status="complete")
    rendered = output.strip()
    response = "命令已真实结束，退出码 0。"
    if rendered:
        response += "\n" + rendered[:6000]
    return ResidentRunResult(
        event=event,
        execution_path=ExecutionPath.BODY,
        success=True,
        response=response,
        model_invocations=0,
        reason=(
            "E2E-22 VERIFIED NARROW only after one guarded background command dispatch and "
            "read-only polling of the same terminal session/process to observed exit code 0; "
            "waiting consumed zero model invocations"
        ),
    )


def install_long_running_terminal_behavior(resident) -> None:
    """Attach the bounded E2E-22 path to the one existing Product Resident."""
    if getattr(resident, _INSTALL_MARKER, False):
        return
    original_advance = resident._advance_event_step

    def advance_event_step(event, state, *, readiness, learning_evidence, thought=None):
        stage = str(state.stage or "")
        request = _request(event)
        if stage == "orient" and request is not None:
            return _begin(resident, event, state, request)
        if stage == "e2e22_wait":
            return _poll(resident, event, state)
        return original_advance(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    resident._advance_event_step = advance_event_step
    setattr(resident, _INSTALL_MARKER, True)
