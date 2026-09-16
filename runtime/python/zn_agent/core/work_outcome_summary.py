from __future__ import annotations

"""Privacy-bounded, user-readable observations over durable Work truth.

This module does not own Work state or execution. It derives one bounded current-plan
observation from WorkItem facts after execution/final acceptance has already settled.
"""

import re
from typing import Any


_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_ -]?key|access[_ -]?token|auth[_ -]?token|password|secret|authorization)\b\s*[:=]\s*[^\s,;]+"
)
_SECRET_TOKEN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|eyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})\b"
)
_ITEM_LIMIT = 12
_CRITERIA_LIMIT = 4


def public_work_text(value: Any, *, limit: int = 600) -> str:
    text = " ".join(str(value or "").strip().split())
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=<redacted>", text)
    text = _SECRET_TOKEN.sub("<redacted>", text)
    return text[: max(0, int(limit))]


def _criteria(item: Any) -> list[str]:
    values: list[str] = []
    for raw in list(getattr(item, "acceptance_criteria", ()) or ())[:_CRITERIA_LIMIT]:
        text = public_work_text(raw, limit=300)
        if text:
            values.append(text)
    return values


def _completed_view(item: Any) -> dict[str, Any]:
    view: dict[str, Any] = {
        "title": public_work_text(getattr(item, "title", None), limit=240) or "Completed work",
        "status": "completed",
    }
    criteria = _criteria(item)
    if criteria:
        view["criteria"] = criteria
    completed_at = str(getattr(item, "completed_at", None) or "").strip()
    if completed_at:
        view["completed_at"] = completed_at
    return view


def _blocked_view(item: Any) -> dict[str, Any]:
    reason = public_work_text(getattr(item, "blocker", None), limit=600)
    view: dict[str, Any] = {
        "title": public_work_text(getattr(item, "title", None), limit=240) or "Blocked work",
        "status": "blocked",
        "reason": reason or "blocked in durable Work truth",
    }
    criteria = _criteria(item)
    if criteria:
        view["criteria"] = criteria
    return view


def project_work_outcome(ledger: Any, event_id: str) -> dict[str, Any] | None:
    """Project only the exact current plan; stale plans never get a fresh conclusion."""

    root = ledger.work_item_for_event(event_id)
    work_run = ledger.get_run(event_id)
    if root is None or work_run is None or getattr(root, "parent_work_item_id", None) is not None:
        return None
    if str(getattr(work_run, "thread_id", "")) != str(getattr(root, "work_thread_id", "")):
        return None
    if str(getattr(work_run, "ledger_state", "")).startswith("stale"):
        return None

    try:
        current_version = int(ledger.plan_version(root.work_thread_id))
        root_version = int(root.plan_version)
    except (TypeError, ValueError):
        return None
    if current_version < 1 or root_version != current_version:
        return None

    children = [
        item
        for item in ledger.list_work_items(root.work_thread_id, limit=256)
        if item.plan_version == current_version
        and item.parent_work_item_id == root.work_item_id
    ]
    all_completed = [item for item in children if item.status == "completed"]
    all_blocked = [item for item in children if item.status == "blocked"]
    all_active = [
        item
        for item in children
        if item.status in {"proposed", "ready", "running"}
    ]
    completed_items = all_completed[:_ITEM_LIMIT]
    blocked_items = all_blocked[:_ITEM_LIMIT]
    active_items = all_active[:_ITEM_LIMIT]

    root_status = str(root.status or "").strip().lower() or "running"
    if root_status == "completed":
        status = "completed"
        reason = "Completed"
    elif root_status == "blocked" and all_completed:
        status = "partial"
        reason = "PartiallyCompleted"
    elif root_status == "blocked" or all_blocked:
        status = "blocked"
        reason = "Blocked"
    else:
        status = "in_progress"
        reason = "InProgress"

    root_blocker = public_work_text(getattr(root, "blocker", None), limit=600)
    updated_values = [
        str(getattr(item, "updated_at", "") or "").strip()
        for item in [root, *children]
        if str(getattr(item, "updated_at", "") or "").strip()
    ]
    projection: dict[str, Any] = {
        "plan_version": current_version,
        "status": status,
        "reason": reason,
        "root_status": root_status,
        "counts": {
            "completed": len(all_completed),
            "blocked": len(all_blocked),
            "active": len(all_active),
        },
        "completed": [_completed_view(item) for item in completed_items],
        "blocked": [_blocked_view(item) for item in blocked_items],
        "active": [
            {
                "title": public_work_text(item.title, limit=240) or "Active work",
                "status": str(item.status),
            }
            for item in active_items
        ],
    }
    if root_blocker:
        projection["root_blocker"] = root_blocker
    if updated_values:
        projection["observed_at"] = max(updated_values)
    return projection


def render_work_outcome_summary(projection: dict[str, Any]) -> str | None:
    """Render terminal non-total outcomes without turning observations into authority."""

    status = str(projection.get("status") or "")
    if status not in {"partial", "blocked"}:
        return None

    lines = ["Partially completed." if status == "partial" else "Work is blocked."]
    completed = projection.get("completed")
    if isinstance(completed, list) and completed:
        lines.append("Completed:")
        for item in completed[:_ITEM_LIMIT]:
            if not isinstance(item, dict):
                continue
            title = public_work_text(item.get("title"), limit=240) or "Completed work"
            criteria = item.get("criteria")
            values = [public_work_text(value, limit=240) for value in criteria] if isinstance(criteria, list) else []
            values = [value for value in values if value]
            suffix = f" — Work truth: completed; criteria: {'; '.join(values)}" if values else " — Work truth: completed"
            lines.append(f"- {title}{suffix}")

    blocked = projection.get("blocked")
    if isinstance(blocked, list) and blocked:
        lines.append("Blocked:")
        for item in blocked[:_ITEM_LIMIT]:
            if not isinstance(item, dict):
                continue
            title = public_work_text(item.get("title"), limit=240) or "Blocked work"
            reason = public_work_text(item.get("reason"), limit=600) or "blocked in durable Work truth"
            lines.append(f"- {title} — {reason}")

    root_blocker = public_work_text(projection.get("root_blocker"), limit=600)
    if root_blocker:
        lines.append(f"Final acceptance: blocked — {root_blocker}")
    return "\n".join(lines)
