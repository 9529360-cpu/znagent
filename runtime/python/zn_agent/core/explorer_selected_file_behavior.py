from __future__ import annotations

"""Bounded Product Resident behavior for current File Explorer selection metadata.

This is deliberately a read-only representative path. The user explicitly refers
to the file selected in Windows File Explorer; ZN resolves that current reference
through the existing DeviceCapabilityGraph, reads it twice, and completes only if
the exact Explorer HWND and file identity remain stable. No selected path or file
name is persisted in WorkingState/Work evidence.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

from .models import ExecutionPath, ResidentRunResult, utc_now
from .windows_explorer_selection import (
    WindowsExplorerSelectionObservation,
    same_explorer_file_selection,
)


_STATE_KEY = "explorer_selected_file_metadata"
_INSTALL_MARKER = "_explorer_selected_file_metadata_installed"
_ACCEPTANCE = "explorer_selected_file_metadata:v1"

_EXPLORER_MARKERS = (
    "资源管理器",
    "文件资源管理器",
    "file explorer",
    "windows explorer",
)
_SELECTED_MARKERS = (
    "选中的",
    "选中这个",
    "当前选中",
    "selected file",
    "selected item",
    "currently selected",
)
_INFO_MARKERS = (
    "是什么",
    "哪个文件",
    "文件名",
    "大小",
    "修改时间",
    "文件信息",
    "what file",
    "which file",
    "file name",
    "filename",
    "size",
    "modified",
    "details",
    "metadata",
)


def _request(event: Any) -> bool:
    if str(getattr(event, "kind", "") or "").strip().lower() != "desktop_user_event":
        return False
    payload = getattr(event, "payload", {}) or {}
    if payload.get("body_action") or payload.get("native_action"):
        return False
    task = " ".join(str(getattr(event, "task", "") or "").split()).casefold()
    if not task:
        return False
    return (
        any(marker.casefold() in task for marker in _EXPLORER_MARKERS)
        and any(marker.casefold() in task for marker in _SELECTED_MARKERS)
        and any(marker.casefold() in task for marker in _INFO_MARKERS)
    )


def _english(event: Any) -> bool:
    text = str(getattr(event, "task", "") or "")
    return not any("\u4e00" <= char <= "\u9fff" for char in text)


def _safe_evidence(
    observation: WindowsExplorerSelectionObservation | None,
    *,
    status: str,
    blocker: str | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "version": 1,
        "status": status,
        "fresh_revalidated": status == "complete",
    }
    if observation is not None:
        evidence.update(
            {
                "platform_supported": observation.platform_supported,
                "explorer_foreground": observation.explorer_foreground,
                "selected_count": observation.selected_count,
                "disposition": observation.disposition,
                "size_bytes": observation.size_bytes,
                "mtime_ns": observation.mtime_ns,
            }
        )
        if observation.name:
            evidence["name_chars"] = len(observation.name)
            evidence["name_sha256"] = hashlib.sha256(
                observation.name.encode("utf-8", errors="replace")
            ).hexdigest()
    if blocker:
        evidence["blocker"] = str(blocker)[:800]
    return evidence


def _persist(
    resident: Any,
    event: Any,
    observation: WindowsExplorerSelectionObservation | None,
    *,
    status: str,
    blocker: str | None = None,
) -> None:
    root = resident.work_ledger.work_item_for_event(event.event_id)
    if root is None or root.parent_work_item_id is not None:
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
                "Resolve the exact file currently selected in foreground Windows File Explorer "
                "and report bounded metadata only after fresh selection revalidation"
            ),
            acceptance_criteria=[_ACCEPTANCE],
            title="Inspect selected Explorer file",
        )
    now = utc_now()
    item.status = "completed" if status == "complete" else "blocked"
    item.result = json.dumps(
        _safe_evidence(observation, status=status, blocker=blocker),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    item.blocker = str(blocker)[:2000] if blocker else None
    item.updated_at = now
    if status == "complete":
        item.completed_at = now
    resident.work_ledger._save_item(item)


def _blocked_response(event: Any, disposition: str) -> str:
    english = _english(event)
    messages = {
        "foreground_not_explorer": (
            "File Explorer is not the current foreground app, so I did not guess which file you meant."
            if english
            else "当前前台不是 Windows 文件资源管理器，所以我没有猜测你指的是哪个文件。"
        ),
        "no_selection": (
            "No file is currently selected in the foreground File Explorer window."
            if english
            else "当前前台资源管理器窗口里没有选中文件。"
        ),
        "multiple_selection": (
            "More than one item is selected. This path requires exactly one selected local file."
            if english
            else "当前选中了多个项目；这个能力只接受一个明确选中的本地文件。"
        ),
        "selection_not_local_file_path": (
            "The selected item is not a supported local file path. Network/UNC selections are not accepted."
            if english
            else "当前选中项不是受支持的本地文件路径；网络/UNC 选中项不会被接受。"
        ),
        "selection_not_regular_file": (
            "The selected item is not a regular file, so I did not treat it as one."
            if english
            else "当前选中项不是普通文件，所以我没有把它当作文件处理。"
        ),
        "selection_changed": (
            "The Explorer selection changed while I was verifying it, so I did not report stale metadata."
            if english
            else "验证期间资源管理器的选中项发生了变化，所以我没有返回可能已经过期的文件信息。"
        ),
    }
    return messages.get(
        disposition,
        "I could not reliably read the current File Explorer selection."
        if english
        else "我无法可靠读取当前资源管理器的选中项。",
    )


def _blocked(
    resident: Any,
    event: Any,
    state: Any,
    observation: WindowsExplorerSelectionObservation | None,
    disposition: str,
) -> ResidentRunResult:
    reason = f"explorer_selected_file_blocked:{disposition}"
    safe_state = _safe_evidence(observation, status="blocked", blocker=disposition)
    state.data[_STATE_KEY] = safe_state
    state.stage = "failed"
    state.next_action = None
    state.blocked_by = disposition
    resident.store.save_working_state(state)
    _persist(resident, event, observation, status="blocked", blocker=reason)
    return ResidentRunResult(
        event=event,
        execution_path=ExecutionPath.INVESTIGATION,
        success=False,
        response=_blocked_response(event, disposition),
        model_invocations=0,
        reason=reason,
    )


def _modified_iso(mtime_ns: int) -> str:
    return datetime.fromtimestamp(mtime_ns / 1_000_000_000, tz=timezone.utc).isoformat(
        timespec="seconds"
    )


def _complete(
    resident: Any,
    event: Any,
    state: Any,
    observation: WindowsExplorerSelectionObservation,
) -> ResidentRunResult:
    safe_state = _safe_evidence(observation, status="complete")
    state.data[_STATE_KEY] = safe_state
    state.stage = "complete"
    state.next_action = None
    state.blocked_by = None
    resident.store.save_working_state(state)
    _persist(resident, event, observation, status="complete")

    name = str(observation.name or "")
    size = int(observation.size_bytes or 0)
    modified = _modified_iso(int(observation.mtime_ns or 0))
    if _english(event):
        response = f'The selected File Explorer file is "{name}". Size: {size} bytes. Modified (UTC): {modified}.'
    else:
        response = f'当前资源管理器里选中的是“{name}”。大小：{size} 字节；修改时间（UTC）：{modified}。'
    return ResidentRunResult(
        event=event,
        execution_path=ExecutionPath.BODY,
        success=True,
        response=response,
        model_invocations=0,
        reason=(
            "Explorer selected-file metadata VERIFIED NARROW after two fresh exact-foreground "
            "Shell selection reads and stable local-file metadata"
        ),
    )


def _inspect(resident: Any, event: Any, state: Any) -> ResidentRunResult:
    reader = getattr(resident.device_capabilities, "explorer_selection", None)
    if not callable(reader):
        return _blocked(resident, event, state, None, "selection_capability_unavailable")

    try:
        first = reader()
    except Exception:
        return _blocked(resident, event, state, None, "selection_unavailable")
    if not isinstance(first, WindowsExplorerSelectionObservation) or not first.available:
        disposition = (
            str(getattr(first, "disposition", "") or "selection_unavailable")
            if first is not None
            else "selection_unavailable"
        )
        return _blocked(resident, event, state, first if isinstance(first, WindowsExplorerSelectionObservation) else None, disposition)

    try:
        second = reader()
    except Exception:
        return _blocked(resident, event, state, first, "selection_changed")
    if not isinstance(second, WindowsExplorerSelectionObservation) or not same_explorer_file_selection(first, second):
        return _blocked(resident, event, state, first, "selection_changed")
    return _complete(resident, event, state, second)


def install_explorer_selected_file_behavior(resident: Any) -> None:
    """Attach the read-only Explorer-current-selection path to the existing Resident."""

    if getattr(resident, _INSTALL_MARKER, False):
        return
    original_advance = resident._advance_event_step

    def advance_event_step(event, state, *, readiness, learning_evidence, thought=None):
        if str(state.stage or "") == "orient" and _request(event):
            return _inspect(resident, event, state)
        return original_advance(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    resident._advance_event_step = advance_event_step
    setattr(resident, _INSTALL_MARKER, True)
