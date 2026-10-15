from __future__ import annotations

"""CUR-2 Plan Mode: plan first, execute only after user approval.

Offense to P2b ``gap_report``'s defense: a gap report stops the team when
required information is missing. Plan Mode is the mirror image -- when a
task touches multiple files or needs a design decision, the specialist
proposes a plan FIRST instead of writing files. The plan is rendered as
a reviewable, editable markdown file; work starts only after the user
approves the (possibly edited) plan.

Shape (mirrors ``gap_report`` / ``completion_report`` -- one exact JSON
object, nothing else)::

    {"plan_proposal": {"title": "...", "goal": "...",
      "files": ["relative/path", ...],
      "steps": ["...", ...],
      "decisions": [{"question": "...", "options": ["...", "..."],
                     "recommendation": "..."}],
      "risks": ["...", ...],
      "acceptance": ["...", ...]}}

Gate state machine (durable, stored in working-state data under
``PLAN_GATE_STATE_KEY``)::

    pending -> approved   (user edited + approved the plan file)
    pending -> rejected   (user refused the plan; the team stops)

The gate functions here are pure state transitions over a dict, so the
daemon/workbench approval entry point can call the same functions later
without touching the resident. Until approval lands, the resident blocks
(never executes a work step for the planned item); a rejected plan fails
the team closed with the rejection reason.
"""

import re
from dataclasses import dataclass, field

from .structured_proposal import parse_exact_json_payload

#: Working-state data key holding the pending/approved/rejected plan gate.
PLAN_GATE_STATE_KEY = "team_plan_gate"
#: Directory (workspace-relative) holding reviewable plan files.
PLAN_FILE_DIR = "plans"
#: Caps keep a hostile/rambling proposal from bloating state or disk.
MAX_PLAN_TEXT = 20000
_MAX_TITLE = 200
_MAX_GOAL = 2000
_MAX_FILES = 30
_MAX_FILE_LEN = 300
_MAX_STEPS = 20
_MAX_STEP_LEN = 600
_MAX_DECISIONS = 10
_MAX_DECISION_LEN = 600
_MAX_OPTIONS = 6
_MAX_RISKS = 20
_MAX_RISK_LEN = 600
_MAX_ACCEPTANCE = 20
_MAX_ACCEPTANCE_LEN = 300


@dataclass(slots=True)
class PlanDecision:
    """One design decision the user should see and can overrule."""

    question: str
    options: tuple[str, ...] = ()
    recommendation: str = ""


@dataclass(slots=True)
class PlanProposal:
    """A validated, size-capped plan proposal from a specialist."""

    title: str
    goal: str
    files: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    decisions: tuple[PlanDecision, ...] = ()
    risks: tuple[str, ...] = ()
    acceptance: tuple[str, ...] = ()


def _clean_str(value: object, *, cap: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:cap]


def _clean_str_list(value: object, *, cap: int, max_items: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    for item in value[:max_items]:
        cleaned = _clean_str(item, cap=cap)
        if cleaned:
            out.append(cleaned)
    return tuple(out)


def plan_mode_enabled(event: object) -> bool:
    """Plan Mode is a team-level opt-in: ``team_request.plan_mode == True``."""
    payload = getattr(event, "payload", None)
    if not isinstance(payload, dict):
        return False
    request = payload.get("team_request")
    if not isinstance(request, dict):
        return False
    return request.get("plan_mode") is True


def plan_file_rel_path(work_item_id: str) -> str:
    """Workspace-relative path of the reviewable plan file for one item."""
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", str(work_item_id or "").strip())
    safe = safe.strip("-")[:64] or "item"
    return f"{PLAN_FILE_DIR}/plan-{safe}.md"


def parse_plan_proposal(content: object) -> tuple[PlanProposal | None, str]:
    """Parse one exact ``{"plan_proposal": {...}}`` payload.

    Returns (proposal, "") on success, (None, reason) on any failure.
    A plan must name its goal, at least one file, and at least one step --
    otherwise it is not a reviewable plan, it is a wish.
    """
    if not isinstance(content, str) or not content.strip():
        return None, "plan_proposal 为空"
    shape = parse_exact_json_payload(content)
    if not isinstance(shape, dict) or "plan_proposal" not in shape:
        return None, (
            "plan_proposal 格式错误：需为单个 JSON 对象且含 plan_proposal 键"
        )
    raw = shape.get("plan_proposal")
    if not isinstance(raw, dict):
        return None, "plan_proposal 需为 JSON 对象"
    title = _clean_str(raw.get("title"), cap=_MAX_TITLE)
    goal = _clean_str(raw.get("goal"), cap=_MAX_GOAL)
    files = _clean_str_list(
        raw.get("files"), cap=_MAX_FILE_LEN, max_items=_MAX_FILES
    )
    steps = _clean_str_list(
        raw.get("steps"), cap=_MAX_STEP_LEN, max_items=_MAX_STEPS
    )
    risks = _clean_str_list(
        raw.get("risks"), cap=_MAX_RISK_LEN, max_items=_MAX_RISKS
    )
    acceptance = _clean_str_list(
        raw.get("acceptance"),
        cap=_MAX_ACCEPTANCE_LEN,
        max_items=_MAX_ACCEPTANCE,
    )
    decisions: list[PlanDecision] = []
    raw_decisions = raw.get("decisions")
    if isinstance(raw_decisions, list):
        for item in raw_decisions[:_MAX_DECISIONS]:
            if not isinstance(item, dict):
                return None, "plan_proposal.decisions 每一项需为对象"
            question = _clean_str(item.get("question"), cap=_MAX_DECISION_LEN)
            options = _clean_str_list(
                item.get("options"), cap=_MAX_DECISION_LEN, max_items=_MAX_OPTIONS
            )
            recommendation = _clean_str(
                item.get("recommendation"), cap=_MAX_DECISION_LEN
            )
            if not question:
                return None, "plan_proposal.decisions 每一项需含非空 question"
            if len(options) < 2:
                return None, (
                    "plan_proposal.decisions 每一项需至少 2 个 options"
                )
            decisions.append(
                PlanDecision(
                    question=question,
                    options=options,
                    recommendation=recommendation,
                )
            )
    if not title:
        return None, "plan_proposal 需含非空 title"
    if not goal:
        return None, "plan_proposal 需含非空 goal"
    if not files:
        return None, "plan_proposal 需至少列 1 个 files"
    if not steps:
        return None, "plan_proposal 需至少列 1 个 steps"
    return (
        PlanProposal(
            title=title,
            goal=goal,
            files=files,
            steps=steps,
            decisions=tuple(decisions),
            risks=risks,
            acceptance=acceptance,
        ),
        "",
    )


def render_plan_markdown(
    proposal: PlanProposal,
    *,
    work_item_id: str,
    specialist_name: str,
) -> str:
    """Render a proposal as reviewable, editable markdown.

    Plain markdown, no JSON blobs: the user reads it, edits it in place,
    and approves it. The ``PLAN STATUS`` marker is the machine-readable
    part; everything else is for the human.
    """
    lines = [
        f"# 计划：{proposal.title}",
        "",
        f"> 专员：{specialist_name or 'specialist'} · "
        f"工作项：{work_item_id} · 状态：待审批",
        "> 审批方式：直接编辑本文件，然后由用户批准；批准前不执行任何步骤。",
        "",
        "## 目标",
        "",
        proposal.goal,
        "",
        f"## 文件（{len(proposal.files)} 个）",
        "",
    ]
    for path in proposal.files:
        lines.append(f"- `{path}`")
    lines += ["", "## 步骤", ""]
    for index, step in enumerate(proposal.steps, start=1):
        lines.append(f"{index}. {step}")
    lines += ["", "## 设计抉择", ""]
    if proposal.decisions:
        for index, decision in enumerate(proposal.decisions, start=1):
            lines.append(f"### 抉择 {index}：{decision.question}")
            lines.append("")
            for option in decision.options:
                lines.append(f"- 选项：{option}")
            if decision.recommendation:
                lines.append(f"- 建议：{decision.recommendation}")
            lines.append("")
    else:
        lines.append("无")
        lines.append("")
    lines += ["## 风险", ""]
    if proposal.risks:
        for risk in proposal.risks:
            lines.append(f"- {risk}")
    else:
        lines.append("无")
    lines += ["", "## 验收", ""]
    if proposal.acceptance:
        for criterion in proposal.acceptance:
            lines.append(f"- {criterion}")
    else:
        lines.append("无")
    lines += ["", "<!-- PLAN STATUS: pending -->", ""]
    return "\n".join(lines)


# -- gate: pure state transitions over a working-state data dict ---------


def plan_gate(data: dict) -> dict | None:
    """The current plan gate, or None when no plan was ever proposed."""
    gate = data.get(PLAN_GATE_STATE_KEY)
    return dict(gate) if isinstance(gate, dict) else None


def plan_pending(data: dict) -> bool:
    """True while a proposed plan waits for user approval."""
    gate = plan_gate(data)
    return gate is not None and gate.get("status") == "pending"


def request_plan(
    data: dict,
    *,
    work_item_id: str,
    run_id: str,
    proposal: PlanProposal,
    plan_file: str,
) -> tuple[dict, bool]:
    """Record a proposed plan as pending approval.

    Returns (gate, replaced). When a plan is already pending for the same
    work item the existing gate is kept -- the user may be mid-review, and
    a re-plan must not clobber it. The specialist gets told a plan is
    already pending instead.
    """
    existing = plan_gate(data)
    if (
        existing is not None
        and existing.get("status") == "pending"
        and str(existing.get("work_item_id") or "") == str(work_item_id)
    ):
        return existing, False
    gate = {
        "status": "pending",
        "work_item_id": str(work_item_id),
        "run_id": str(run_id),
        "title": proposal.title,
        "plan_file": str(plan_file),
    }
    data[PLAN_GATE_STATE_KEY] = gate
    return dict(gate), True


def approve_plan(data: dict, *, edited_markdown: str) -> tuple[dict | None, str]:
    """Approve the pending plan with the user's (possibly edited) text.

    Returns (gate, "") on success, (None, reason) when there is nothing
    pending to approve or the approved text is empty. The edited text is
    what the specialist follows -- the original proposal is superseded.
    """
    gate = plan_gate(data)
    if gate is None or gate.get("status") != "pending":
        return None, "没有待审批的计划"
    text = _clean_str(edited_markdown, cap=MAX_PLAN_TEXT)
    if not text:
        return None, "批准的计划内容为空"
    gate["status"] = "approved"
    gate["approved_text"] = text
    data[PLAN_GATE_STATE_KEY] = gate
    return dict(gate), ""


def reject_plan(data: dict, *, reason: str) -> tuple[dict | None, str]:
    """Reject the pending plan. The team stops with the rejection reason."""
    gate = plan_gate(data)
    if gate is None or gate.get("status") != "pending":
        return None, "没有待审批的计划"
    gate["status"] = "rejected"
    gate["reject_reason"] = _clean_str(reason, cap=600) or "计划被拒绝"
    data[PLAN_GATE_STATE_KEY] = gate
    return dict(gate), ""


def approved_plan_text(data: dict, *, work_item_id: str) -> str | None:
    """The approved (possibly edited) plan text for one work item."""
    gate = plan_gate(data)
    if gate is None or gate.get("status") != "approved":
        return None
    if str(gate.get("work_item_id") or "") != str(work_item_id):
        return None
    text = gate.get("approved_text")
    return str(text) if isinstance(text, str) and text.strip() else None


__all__ = [
    "MAX_PLAN_TEXT",
    "PLAN_FILE_DIR",
    "PLAN_GATE_STATE_KEY",
    "PlanDecision",
    "PlanProposal",
    "approve_plan",
    "approved_plan_text",
    "parse_plan_proposal",
    "plan_file_rel_path",
    "plan_gate",
    "plan_mode_enabled",
    "plan_pending",
    "reject_plan",
    "render_plan_markdown",
    "request_plan",
]
