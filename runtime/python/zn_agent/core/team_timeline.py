from __future__ import annotations

"""Team group-chat timeline: a read-only view derived from the Work log.

P2-5 (Grok Bot alignment): while a team runs, the workbench shows a
group-chat timeline -- every specialist message carries its author,
handoff events show who -> who, what was handed over, and evidence links,
and the user can ``@specialist`` to assign the next step.

Consistency rule: the timeline is *derived*, never a second source of
truth. Every entry maps 1:1 to a Work log message (same id, same text,
same timestamp) written through the normal journal path
(``ResidentWorkLedger.append_message``). This module only reads; it never
writes, mutates, or reorders history. The UI renders it read-only.

Event sources (all already durable Work journal entries):

- specialist/coordinator journal messages: role ``team:{team_id}:{author}``,
  detail ``kind`` in note/progress/handoff/blocker/decision.
- user assignment: role ``user`` (or ``team:{team_id}:user``) with
  detail ``kind == "assignment"`` -- written by the ``team_assign`` RPC.
- handoff evidence: verification journal entries carry detail
  ``evidence`` (``[{label, ref}]``) produced by the runner from the
  verifier's ``artifact_refs``; the builder links a ref to a thread
  artifact when the ref matches the artifact's id/path/name.

``@`` assignment semantics: ``team_assign`` reassigns the next
not-yet-dispatched plan item to the named specialist. The override is
stored in team shared memory and applied by ``TeamWorkOwner`` on every
pulse, so it survives restarts. Plan order, dependencies and the
verification gate are untouched -- assignment only changes *who* does the
next pending item, never *whether* it must be verified.
"""

import re
from dataclasses import replace
from typing import Any, Mapping, Sequence

from .privacy_choke import strip_tags
from .team_memory import team_shared_memory

#: Team shared-memory key holding plan-item assignee overrides:
#: ``{plan_item_id: specialist_name}``.
ASSIGNEE_OVERRIDES_KEY = "assignee_overrides"

#: Journal detail kinds that become timeline entries, in display order.
TIMELINE_KINDS = ("message", "progress", "handoff", "blocker", "decision", "assignment")

_MAX_ENTRIES = 500

_MENTION_RE = re.compile(r"^\s*[＠@]\s*([^\s＠@]+)\s*([\s\S]*)$")


def parse_team_role(role: Any) -> tuple[str, str] | None:
    """Split a journal role ``team:{team_id}:{author}`` or return None."""
    if not isinstance(role, str):
        return None
    parts = role.split(":")
    if len(parts) != 3 or parts[0] != "team":
        return None
    team_id, author = parts[1].strip(), parts[2].strip()
    if not team_id or not author:
        return None
    return team_id, author


def parse_mention(text: Any) -> tuple[str, str] | None:
    """Parse a leading ``@specialist [instruction]`` mention.

    Returns ``(specialist_name, instruction)`` or None when the text does
    not start with a mention. Both half-width ``@`` and full-width ``＠``
    are accepted (CJK keyboards emit the latter).
    """
    if not isinstance(text, str):
        return None
    match = _MENTION_RE.match(text)
    if match is None:
        return None
    name = match.group(1).strip()
    if not name:
        return None
    return name, match.group(2).strip()


def assignee_overrides(memory: Any, team_id: str) -> dict[str, str]:
    """Current plan-item assignee overrides for a team (may be empty)."""
    shared = team_shared_memory(memory, team_id)
    match = shared.recall(ASSIGNEE_OVERRIDES_KEY)
    if match is None or not isinstance(match.value, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in match.value.items()
        if str(key).strip() and str(value).strip()
    }


def record_assignee_override(
    memory: Any, team_id: str, plan_item_id: str, specialist_name: str
) -> dict[str, str]:
    """Durably reassign one plan item. Returns the full override map."""
    # CM-3 privacy choke: timeline capture (assignee overrides are
    # team memory writes) sanitizes identifiers before storing.
    # The shared-memory write chokes again at the write boundary.
    plan_item_id = strip_tags(plan_item_id)
    specialist_name = strip_tags(specialist_name)
    if not str(plan_item_id or "").strip():
        raise ValueError("plan_item_id must not be empty")
    if not str(specialist_name or "").strip():
        raise ValueError("specialist_name must not be empty")
    shared = team_shared_memory(memory, team_id)
    overrides = assignee_overrides(memory, team_id)
    overrides[str(plan_item_id)] = str(specialist_name)
    shared.remember(ASSIGNEE_OVERRIDES_KEY, dict(overrides))
    return overrides


def apply_assignee_overrides(team: Any, overrides: Mapping[str, str]) -> Any:
    """Return a team copy with assignee overrides applied to the plan.

    Unknown plan items and names that are not team members are ignored --
    the stored override is never allowed to corrupt the plan. The input
    team is never mutated.
    """
    if not overrides:
        return team
    members = {member.name for member in team.members}
    plan: list[Any] = []
    changed = False
    for item in team.plan:
        replacement = overrides.get(item.item_id)
        if (
            replacement is not None
            and replacement in members
            and replacement != item.assignee
        ):
            plan.append(replace(item, assignee=replacement))
            changed = True
        else:
            plan.append(item)
    if not changed:
        return team
    return replace(team, plan=tuple(plan))


def evidence_from_refs(refs: Any) -> list[dict[str, str]]:
    """Normalize verifier ``artifact_refs`` into timeline evidence links.

    Each ref dict may carry ``path`` / ``name`` / ``id`` / ``url``; the
    first present value becomes the link ``ref``, with a human ``label``.
    Non-dict and empty refs are dropped -- evidence must be a real
    reference, never an invented one.
    """
    if not isinstance(refs, (list, tuple)):
        return []
    evidence: list[dict[str, str]] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        target = (
            str(ref.get("path") or "").strip()
            or str(ref.get("url") or "").strip()
            or str(ref.get("ref") or "").strip()
            or str(ref.get("id") or "").strip()
            or str(ref.get("name") or "").strip()
        )
        if not target:
            continue
        label = str(ref.get("label") or ref.get("name") or "").strip() or target
        evidence.append({"label": label[:300], "ref": target[:2000]})
    return evidence[:32]


def _field(message: Any, name: str, default: Any = "") -> Any:
    if isinstance(message, Mapping):
        return message.get(name, default)
    return getattr(message, name, default)


def _message_id(message: Any) -> str:
    for key in ("message_id", "id"):
        value = _field(message, key, "")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _message_detail(message: Any) -> dict[str, Any]:
    detail = _field(message, "detail", {})
    return dict(detail) if isinstance(detail, dict) else {}


def _artifact_fields(artifact: Any) -> tuple[str, str, str]:
    artifact_id = _field(artifact, "artifact_id", "") or _field(artifact, "id", "")
    path = _field(artifact, "path", "") or ""
    name = _field(artifact, "name", "") or ""
    return str(artifact_id or ""), str(path or ""), str(name or "")


def _link_evidence(
    evidence: list[dict[str, str]], artifacts: Sequence[Any]
) -> list[dict[str, str]]:
    """Attach ``artifact_id`` when an evidence ref matches a thread artifact."""
    by_ref: dict[str, str] = {}
    for artifact in artifacts:
        artifact_id, path, name = _artifact_fields(artifact)
        if not artifact_id:
            continue
        for key in (artifact_id, path, name):
            if key:
                by_ref.setdefault(key, artifact_id)
    linked: list[dict[str, str]] = []
    for item in evidence:
        entry = dict(item)
        match = by_ref.get(item["ref"])
        if match:
            entry["artifact_id"] = match
        linked.append(entry)
    return linked


def _parse_handoff_text(text: str) -> tuple[str, str]:
    """Fallback parse for ``派活：{what} → {to}`` when detail lacks fields."""
    if "→" not in text:
        return "", ""
    left, right = text.split("→", 1)
    to_author = right.strip().split()[0] if right.strip() else ""
    what = left
    if "：" in what:
        what = what.split("：", 1)[1]
    elif ":" in what:
        what = what.split(":", 1)[1]
    return what.strip(), to_author


def build_team_timeline(
    messages: Sequence[Any], *, artifacts: Sequence[Any] = ()
) -> list[dict[str, Any]]:
    """Derive timeline entries from Work log messages, in log order.

    Only team journal messages and user assignment messages become
    entries. Every entry keeps the source message id so the UI (and any
    audit) can line it up against the Work log exactly.
    """
    entries: list[dict[str, Any]] = []
    for message in messages:
        if len(entries) >= _MAX_ENTRIES:
            break
        role = str(_field(message, "role", "") or "")
        text = str(_field(message, "text", "") or "")
        detail = _message_detail(message)
        parsed = parse_team_role(role)
        kind = str(detail.get("kind") or "").strip()
        if parsed is not None:
            team_id, author = parsed
            entry_kind = kind if kind in TIMELINE_KINDS else "message"
        elif role == "user" and kind == "assignment":
            team_id = str(detail.get("team_id") or "").strip()
            author = "user"
            entry_kind = "assignment"
            if not team_id:
                continue
        else:
            continue
        entry: dict[str, Any] = {
            "id": _message_id(message) or f"timeline-{len(entries)}",
            "kind": entry_kind,
            "author": author,
            "text": text,
            "at": str(_field(message, "created_at", "") or ""),
            "team_id": team_id,
            "from_author": str(detail.get("from_author") or author),
            "to_author": str(detail.get("to_author") or ""),
            "item_title": str(detail.get("item_title") or ""),
            "objective": str(detail.get("objective") or ""),
            "instruction": str(detail.get("instruction") or ""),
            "evidence": _link_evidence(
                evidence_from_refs(detail.get("evidence")), artifacts
            ),
        }
        if entry_kind == "handoff" and (not entry["to_author"] or not entry["item_title"]):
            what, to_author = _parse_handoff_text(text)
            if not entry["item_title"]:
                entry["item_title"] = what
            if not entry["to_author"]:
                entry["to_author"] = to_author
        entries.append(entry)
    return entries


def review_timeline_entry(
    review: Any, *, team_id: str, author: str = "coordinator"
) -> dict[str, Any]:
    """Convert an AF-3 plan review (see team_coordinator.PlanReview) to
    one timeline entry, in the same shape build_team_timeline produces.

    Reviews normally reach the timeline as journal ``decision`` messages
    (see team_coordinator.review_journal); this helper is for callers
    that already hold the review object and want its timeline form
    without round-tripping through the journal. It never reads or
    mutates history.
    """
    verdict = str(getattr(review, "verdict", "") or "")
    plan_id = str(getattr(review, "plan_id", "") or "")
    findings = list(getattr(review, "findings", ()) or ())
    recommendations = list(getattr(review, "recommendations", ()) or ())
    if verdict == "revise":
        text = f"计划评审：计划 {plan_id} 需修订（{len(findings)} 个发现）"
    elif verdict == "continue":
        text = f"计划评审：计划 {plan_id} 继续执行，无需修订"
    else:
        text = f"计划评审：计划 {plan_id}（未知结论 {verdict!r}）"
    return {
        "id": f"review-{plan_id}-{getattr(review, 'seq', 0)}",
        "kind": "decision",
        "author": author,
        "text": text,
        "at": "",
        "team_id": team_id,
        "from_author": author,
        "to_author": "",
        "item_title": "",
        "objective": "",
        "instruction": "",
        "evidence": [],
        "plan_id": plan_id,
        "review_verdict": verdict,
        "review_findings": findings,
        "review_recommendations": recommendations,
    }


__all__ = [
    "ASSIGNEE_OVERRIDES_KEY",
    "TIMELINE_KINDS",
    "apply_assignee_overrides",
    "assignee_overrides",
    "build_team_timeline",
    "evidence_from_refs",
    "parse_mention",
    "parse_team_role",
    "record_assignee_override",
    "review_timeline_entry",
]
