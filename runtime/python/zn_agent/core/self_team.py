from __future__ import annotations

"""ZN's own judgment to split a task into a parallel specialist team (M-12).

Today a team is only assembled when the *user* asks for one
(``parse_team_request`` -> ``assemble_team``). This module gives ZN the
self-drive to make that call itself, inside a normal Work:

  task looks decomposable with clear parallel benefit
      -> decompose (one bounded cognition call)
      -> check the approval/budget envelope
      -> inside the envelope: assemble + parallel dispatch
      -> outside the envelope (sensitive / over budget): an approval card

Reuse, not a new control plane: a positive decision becomes the same
``team_request`` payload the user-triggered path uses, so the existing
``TeamWorkOwner`` / ``TeamRunner`` / CP-3 machinery drives it unchanged.
The team state machine is untouched; ``SelfTeamWorkOwner`` only reshapes
the assembled plan (model-provided subtasks, parallel dependencies).

The decision itself is a pure function of (task text, one bounded
cognition call). Deterministic pre-screening keeps tiny / indivisible /
opted-out tasks off the model entirely; the model only judges the
ambiguous middle. The cognition answer is validated, never trusted:
unknown roles, bad shapes, or oversized teams fail closed to solo work.
"""

import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable

from .privacy_choke import strip_tags
from .project_team import ROLE_TEMPLATES, ProjectTeam
from .sensitive_handover import detect_sensitive_step
from .team_disband import handles_disband
from .team_request import parse_team_request
from .team_work_owner import TeamWorkOwner

#: Durable working-state key: one self-team decision per event.
SELF_TEAM_STATE_KEY = "self_team_decision"

#: Decision values recorded in working state / returned by the driver.
DECIDE_ASSEMBLE = "assemble"
DECIDE_NO_TEAM = "no_team"
DECIDE_NEEDS_APPROVAL = "needs_approval"  # transient; becomes pending_approval
DECIDE_PENDING_APPROVAL = "pending_approval"
DECIDE_NOT_APPLICABLE = "not_applicable"

#: Approval kind for the team-assembly card (see approval_cards.APPROVAL_KINDS).
APPROVAL_KIND_TEAM_ASSEMBLY = "team_assembly"

#: Marker key on the injected team_request payload: assembled by ZN itself.
SELF_TEAM_MARKER = "self_team"

#: Hard cap on parallel specialists; beyond this the envelope demands approval.
DEFAULT_MAX_SPECIALISTS = 4
#: Absolute ceiling the cognition answer may propose; proposals above the
#: envelope (but within this ceiling) become needs_approval, not rejections.
_MAX_PROPOSABLE_ROLES = 6
#: Tasks shorter than this with no parallel signals never reach cognition.
_SMALL_TASK_CHARS = 24
#: Caps so a model answer cannot bloat durable state.
_MAX_REASON_CHARS = 200
_MAX_SUBTASK_CHARS = 200
_MAX_TITLE_CHARS = 40

#: Explicit opt-outs: the user said no team / solo.
_OPTOUT_RES = (
    r"不要组队",
    r"别组队",
    r"不组队",
    r"不要建队",
    r"别建队",
    r"一个人做",
    r"我自己做",
    r"不用组队",
    r"无需组队",
    r"\bno team\b",
    r"\bwithout a team\b",
    r"\bnot a team\b",
    r"\bsolo\b",
    r"\bdo it myself\b",
)

#: Deterministic signals that a task *might* have parallel structure.
#: A signal only routes the task to the cognition judgment -- never to
#: assembly by itself.
_PARALLEL_SIGNAL_RES = (
    r"[1-9]\s*[.、)]",  # "1. ... 2. ..." / "1、... 2、..."
    r"第[一二三四五六七八九十]+",  # 第一、第二...
    r"首先.+其次",
    r"一方面.+另一方面",
    r"同时",
    r"分别",
    r"各自",
    r"并行",
    r"一并",
    r"分头",
    r"一边.+一边",
)

#: Phase words; two or more distinct ones in a single task hint at a
#: decomposable multi-phase job.
_PHASE_WORDS = ("调研", "研究", "设计", "架构", "开发", "实现", "编码", "测试")


@dataclass(frozen=True, slots=True)
class SelfTeamDecision:
    """The outcome of ZN's self-team judgment for one task."""

    decision: str  # assemble | no_team | needs_approval | pending_approval
    reason: str
    project_title: str = ""
    role_keys: tuple[str, ...] = ()
    subtasks: tuple[str, ...] = ()
    parallel: bool = False
    approval_request_id: str | None = None
    needs_approval_reason: str = ""

    def to_record(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "project_title": self.project_title,
            "role_keys": list(self.role_keys),
            "subtasks": list(self.subtasks),
            "parallel": self.parallel,
            "approval_request_id": self.approval_request_id,
            "needs_approval_reason": self.needs_approval_reason,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def from_record(raw: Any) -> "SelfTeamDecision | None":
        if not isinstance(raw, dict):
            return None
        decision = str(raw.get("decision") or "")
        if decision not in (
            DECIDE_ASSEMBLE,
            DECIDE_NO_TEAM,
            DECIDE_PENDING_APPROVAL,
        ):
            return None
        role_keys = tuple(
            str(key) for key in (raw.get("role_keys") or []) if str(key).strip()
        )
        subtasks = tuple(
            str(item) for item in (raw.get("subtasks") or []) if str(item).strip()
        )
        request_id = raw.get("approval_request_id")
        return SelfTeamDecision(
            decision=decision,
            reason=str(raw.get("reason") or "")[:_MAX_REASON_CHARS],
            project_title=str(raw.get("project_title") or "")[:_MAX_TITLE_CHARS],
            role_keys=role_keys,
            subtasks=subtasks,
            parallel=bool(raw.get("parallel")),
            approval_request_id=(
                str(request_id).strip() or None
                if request_id is not None
                else None
            ),
            needs_approval_reason=str(raw.get("needs_approval_reason") or "")[
                :_MAX_REASON_CHARS
            ],
        )


@dataclass(frozen=True, slots=True)
class SelfTeamEnvelope:
    """Approval/budget envelope for self-assembled teams.

    Inside the envelope ZN assembles on its own judgment; outside it
    (sensitive task or over budget) an approval card goes to the user and
    nothing is assembled until approved.
    """

    max_specialists: int = DEFAULT_MAX_SPECIALISTS


def _has_parallel_signals(task: str) -> bool:
    for pattern in _PARALLEL_SIGNAL_RES:
        if re.search(pattern, task):
            return True
    hits = {word for word in _PHASE_WORDS if word in task}
    return len(hits) >= 2


def prescreen_self_team(task: str) -> SelfTeamDecision | None:
    """Deterministic pre-screen; None means "needs the cognition judgment".

    Returns a final no_team decision for the clear-cut cases so they never
    burn a model call: empty tasks, explicit opt-outs, explicit team asks
    (owned by the user-triggered path), and tiny tasks with no parallel
    structure.
    """
    text = str(task or "").strip()
    if not text:
        return SelfTeamDecision(
            decision=DECIDE_NO_TEAM, reason="空任务，不组队"
        )
    lowered = text.lower()
    for pattern in _OPTOUT_RES:
        if re.search(pattern, lowered):
            return SelfTeamDecision(
                decision=DECIDE_NO_TEAM, reason="用户明确不组队，单人继续"
            )
    if parse_team_request(text) is not None:
        # The user asked for a team explicitly: the user-triggered ingress
        # path owns it; the self-team judgment stays out.
        return SelfTeamDecision(
            decision=DECIDE_NO_TEAM, reason="用户已明确要求组队，走用户触发路径"
        )
    if len(text) < _SMALL_TASK_CHARS and not _has_parallel_signals(text):
        return SelfTeamDecision(
            decision=DECIDE_NO_TEAM, reason="任务小、无并行结构，不组队"
        )
    return None


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if raw.startswith("```") and raw.endswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3:
            raw = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


#: Markup the model might emit in titles/subtasks; stripped before the
#: text lands in team payloads / journal (strip_tags is privacy scrubbing,
#: not markup removal).
_MARKUP_RE = re.compile(r"<[^>]{0,200}>")


def _clean_text(value: Any, cap: int) -> str:
    text = _MARKUP_RE.sub("", str(value or ""))
    scrubbed = strip_tags(text)
    return " ".join(str(scrubbed).split())[:cap]


def quiet_save_working_state(store: Any, state: Any) -> bool:
    """Best-effort working-state save; False when the save itself failed.

    Used where a save failure must never break the Work path (the
    in-memory record is already set for this pulse).
    """
    saver = getattr(store, "save_working_state", None)
    if not callable(saver):
        return False
    try:
        saver(state)
    except Exception:
        return False
    return True


def _try_consume_card(store: Any, request_id: str) -> bool:
    """Best-effort consume of an approved card; never raises."""
    consumer = getattr(store, "consume", None)
    if not callable(consumer):
        return False
    try:
        return bool(consumer(request_id))
    except Exception:
        return False


def build_self_team_question(task: str) -> str:
    """The bounded cognition contract: assemble only on clear parallel benefit."""
    allowed = ", ".join(
        f"{key}（{ROLE_TEMPLATES[key].title}）" for key in ROLE_TEMPLATES
    )
    return (
        "你是 ZN 的任务分解判断器：判断下面的用户任务是否值得拆成一个并行专员团队来做。"
        "只有同时满足以下两点才建议组队："
        "1) 任务可拆成 2 个或更多相互独立、可并行的子任务；"
        "2) 并行收益明确（子任务互不阻塞、耗时相当，串行做会明显更慢）。"
        "以下情况一律不建议组队：任务本身很小、一步就能做完；子任务严格串行依赖；"
        "任务含敏感操作（密码/凭证/支付/个人隐私/对外发布）——敏感任务走审批，不由你直接组队。"
        f"可选角色限定为：{allowed}。"
        "只返回一个 JSON 对象，不要任何解释文字："
        '{"assemble": true/false, "reason": "一句话原因", '
        '"project_title": "项目名（20字内）", '
        '"role_keys": ["researcher", ...], "subtasks": ["子任务1", ...], '
        '"parallel": true/false}。'
        "parallel=true 表示子任务相互独立可并行；false 表示有先后依赖。"
        "role_keys 与 subtasks 一一对应、数量相等、2 到 6 个"
        "（超过 4 个需主人审批，不要为了凑数硬拆）。"
        f"用户任务：{task}"
    )


def _validate_cognition_answer(
    raw: dict[str, Any] | None, task: str
) -> SelfTeamDecision | None:
    """Validate the model's answer; None when it cannot be trusted."""
    if raw is None:
        return None
    assemble = raw.get("assemble")
    if not isinstance(assemble, bool):
        return None
    reason = _clean_text(raw.get("reason"), _MAX_REASON_CHARS)
    if not reason:
        return None
    if not assemble:
        return SelfTeamDecision(decision=DECIDE_NO_TEAM, reason=f"认知判断不组队：{reason}")
    role_keys = raw.get("role_keys")
    subtasks = raw.get("subtasks")
    if not isinstance(role_keys, list) or not isinstance(subtasks, list):
        return None
    keys = [str(key).strip() for key in role_keys]
    if not (2 <= len(keys) <= _MAX_PROPOSABLE_ROLES):
        return None
    if any(key not in ROLE_TEMPLATES for key in keys):
        return None
    if len(set(keys)) != len(keys):
        return None
    if len(subtasks) != len(keys):
        return None
    cleaned_subtasks = [_clean_text(item, _MAX_SUBTASK_CHARS) for item in subtasks]
    if any(not item for item in cleaned_subtasks):
        return None
    parallel = raw.get("parallel")
    if parallel is None:
        # Missing flag: chain (safe) beats parallel (fast) when unsure.
        parallel = False
    if not isinstance(parallel, bool):
        return None
    title = _clean_text(raw.get("project_title"), _MAX_TITLE_CHARS)
    if not title:
        title = _clean_text(task, _MAX_TITLE_CHARS)
    return SelfTeamDecision(
        decision=DECIDE_ASSEMBLE,
        reason=f"认知判断组队：{reason}",
        project_title=title,
        role_keys=tuple(keys),
        subtasks=tuple(cleaned_subtasks),
        parallel=parallel,
    )


def check_self_team_envelope(
    decision: SelfTeamDecision,
    task: str,
    *,
    envelope: SelfTeamEnvelope | None = None,
) -> SelfTeamDecision:
    """Apply the approval/budget envelope to a positive assembly decision.

    Non-assemble decisions pass through untouched. Sensitive tasks and
    over-budget teams become needs_approval -- nothing is assembled until
    the user approves the card.
    """
    envelope = envelope or SelfTeamEnvelope()
    if decision.decision != DECIDE_ASSEMBLE:
        return decision
    sensitive = detect_sensitive_step(str(task or ""))
    if sensitive is not None:
        return replace(
            decision,
            decision=DECIDE_NEEDS_APPROVAL,
            needs_approval_reason=f"任务含敏感内容（{sensitive.kind}），组队需主人审批",
        )
    if len(decision.role_keys) > envelope.max_specialists:
        return replace(
            decision,
            decision=DECIDE_NEEDS_APPROVAL,
            needs_approval_reason=(
                f"团队规模 {len(decision.role_keys)} 超出自主包络"
                f"（{envelope.max_specialists} 人），需主人审批"
            ),
        )
    return decision


def decide_self_team(
    task: str,
    *,
    allow_cognition: bool = True,
    cognitive_invoke: Callable[[str, str], str] | None = None,
    envelope: SelfTeamEnvelope | None = None,
) -> SelfTeamDecision:
    """ZN's self-team judgment for one task: pure function of (task, one call).

    ``cognitive_invoke`` is ``(question, context) -> model text``; tests pass
    a mock, the resident wires one bounded ``kernel.run_goal`` call. Any
    failure -- disabled/unavailable cognition, broken JSON, untrusted answer,
    envelope breach -- fails closed to solo work or an approval card, never
    to an unreviewed team.
    """
    prescreened = prescreen_self_team(task)
    if prescreened is not None:
        return prescreened
    if not allow_cognition or cognitive_invoke is None:
        return SelfTeamDecision(
            decision=DECIDE_NO_TEAM, reason="认知不可用/被禁用，不组队、单人继续"
        )
    try:
        raw_text = cognitive_invoke(build_self_team_question(str(task)), "")
    except Exception as exc:
        return SelfTeamDecision(
            decision=DECIDE_NO_TEAM,
            reason=f"认知调用失败（{type(exc).__name__}），不组队、单人继续",
        )
    validated = _validate_cognition_answer(_extract_json_object(raw_text), str(task))
    if validated is None:
        return SelfTeamDecision(
            decision=DECIDE_NO_TEAM, reason="认知回答不可信（格式/角色非法），不组队"
        )
    return check_self_team_envelope(validated, task, envelope=envelope)


def inject_self_team_request(event: Any, decision: SelfTeamDecision) -> bool:
    """Inject the user-path ``team_request`` payload for a self-team decision.

    Idempotent and defensive: never overrides an existing (user-triggered)
    team request. Returns True when the event now routes into the existing
    team branch.
    """
    payload = getattr(event, "payload", None)
    if not isinstance(payload, dict):
        return False
    if TeamWorkOwner.handles(event):
        return False
    if decision.decision != DECIDE_ASSEMBLE:
        return False
    payload["team_request"] = {
        "project_title": decision.project_title,
        "role_keys": list(decision.role_keys),
        "workspace_root": None,
        SELF_TEAM_MARKER: True,
        "self_team_subtasks": list(decision.subtasks),
        "self_team_parallel": bool(decision.parallel),
    }
    return True


def apply_self_team_plan(team: ProjectTeam, request: dict[str, Any]) -> ProjectTeam:
    """Reshape an assembled team's plan from the self-team decomposition.

    The model's subtasks become the plan items' objectives; when the model
    judged them independent, inter-item dependencies are dropped so the
    runner dispatches them in parallel in one pulse. Anything unexpected
    (length mismatch, blank subtask) keeps the safely assembled plan.
    """
    subtasks = [
        _clean_text(item, _MAX_SUBTASK_CHARS)
        for item in (request.get("self_team_subtasks") or [])
    ]
    if len(subtasks) != len(team.plan) or any(not item for item in subtasks):
        return team
    parallel = bool(request.get("self_team_parallel"))
    for item, subtask in zip(team.plan, subtasks):
        item.objective = subtask
        if parallel:
            item.dependency_ids = ()
    return team


class SelfTeamWorkOwner(TeamWorkOwner):
    """TeamWorkOwner for ZN-assembled teams: same runner, coordination and
    CP-3 adjudication; only the plan reflects ZN's own decomposition.

    No team state machine change: ``resolve_team`` reuses the full parent
    flow (durable spec, overrides, workspace materialization) and then
    applies the self-team plan shaping deterministically from the payload,
    so every pulse reconstructs the identical team.
    """

    def resolve_team(self, *, event: Any, state: Any, thread_id: str) -> ProjectTeam:
        team = super().resolve_team(event=event, state=state, thread_id=thread_id)
        payload = getattr(event, "payload", None)
        request = payload.get("team_request") if isinstance(payload, dict) else None
        if not isinstance(request, dict) or not request.get(SELF_TEAM_MARKER):
            return team
        return apply_self_team_plan(team, request)


class _CognitionNotAllowed(Exception):
    pass


class SelfTeamDriver:
    """Resident-facing driver: one durable self-team decision per event.

    ``step`` returns the recorded decision for the event
    (assemble | no_team | pending_approval | not_applicable) and, on
    assemble, injects the team_request payload so the existing team branch
    drives the event. The cognition call happens at most once per event;
    approval cards are polled on later pulses until decided.
    """

    def __init__(
        self,
        *,
        kernel: Any = None,
        budget: Any = None,
        store: Any = None,
        envelope: SelfTeamEnvelope | None = None,
    ) -> None:
        self._kernel = kernel
        self._budget = budget
        self._store = store
        self._envelope = envelope or SelfTeamEnvelope()

    # -- eligibility --------------------------------------------------------

    @staticmethod
    def consider(event: Any, state: Any = None) -> bool:
        """Whether this event is even eligible for a self-team judgment."""
        if TeamWorkOwner.handles(event):
            return False
        if handles_disband(event):
            return False
        task = str(getattr(event, "task", "") or "").strip()
        if not task:
            return False
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            return False
        if not str(payload.get("work_thread_id") or "").strip():
            return False
        # The team branch fail-closes without an attached workspace; a
        # self-directed decision must never manufacture that failure.
        if not str(payload.get("workspace_path") or "").strip():
            return False
        return True

    # -- one durable step per event ------------------------------------------

    def step(self, event: Any, state: Any) -> str:
        if not self.consider(event):
            return DECIDE_NOT_APPLICABLE
        data = self._state_data(state)
        decision = SelfTeamDecision.from_record(data.get(SELF_TEAM_STATE_KEY))
        if decision is None:
            decision = self._decide_fresh(event)
            if decision.decision == DECIDE_NEEDS_APPROVAL:
                decision = self._open_approval(event, decision)
            self._record(state, data, decision)
        elif decision.decision == DECIDE_PENDING_APPROVAL:
            updated = self._poll_approval(decision)
            if updated.decision != decision.decision:
                decision = updated
                self._record(state, data, decision)
        if decision.decision == DECIDE_ASSEMBLE:
            inject_self_team_request(event, decision)
        self._save(state)
        return decision.decision

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _state_data(state: Any) -> dict[str, Any]:
        data = getattr(state, "data", None)
        if isinstance(data, dict):
            return data
        fresh: dict[str, Any] = {}
        try:
            state.data = fresh
        except Exception:
            # Exotic state object: decide for this pulse anyway; the
            # record just won't be durable.
            return {}
        return fresh

    def _record(self, state: Any, data: dict[str, Any], decision: SelfTeamDecision) -> None:
        data[SELF_TEAM_STATE_KEY] = decision.to_record()
        self._save(state)

    def _save(self, state: Any) -> None:
        quiet_save_working_state(self._store, state)

    def _cognition_allowed(self, event: Any) -> tuple[bool, str]:
        budget = self._budget
        if budget is None:
            return True, ""
        try:
            made = budget.decide(
                event, memory_hit=False, local_capability_available=False
            )
        except Exception:
            return False, "budget check failed"
        return bool(made.use_model), str(getattr(made, "reason", "") or "")

    def _decide_fresh(self, event: Any) -> SelfTeamDecision:
        task = str(getattr(event, "task", "") or "")
        allow, _reason = self._cognition_allowed(event)
        invoke = self._cognitive_invoke(event) if allow else None
        return decide_self_team(
            task,
            allow_cognition=allow,
            cognitive_invoke=invoke,
            envelope=self._envelope,
        )

    def _cognitive_invoke(self, event: Any) -> Callable[[str, str], str]:
        kernel = self._kernel

        def invoke(question: str, context: str) -> str:
            if kernel is None:
                raise _CognitionNotAllowed("no kernel for cognition call")
            result = kernel.run_goal(
                question,
                required_capabilities=("language_understanding",),
                priority=getattr(event, "priority", 0),
                metadata={
                    "resident_event_id": getattr(event, "event_id", ""),
                    "purpose": "self_team_decision",
                },
                max_attempts_override=1,
            )
            worker_result = getattr(result, "worker_result", None)
            if worker_result is None or not getattr(worker_result, "success", False):
                raise RuntimeError("self-team cognition worker failed")
            assessment = getattr(result, "assessment", None)
            if assessment is not None and not getattr(assessment, "success", True):
                raise RuntimeError("self-team cognition assessment failed")
            return str(getattr(worker_result, "response", "") or "")

        return invoke

    def _open_approval(
        self, event: Any, decision: SelfTeamDecision
    ) -> SelfTeamDecision:
        store = self._store
        requester = getattr(store, "request_approval", None)
        if not callable(requester):
            # No approval path: fail closed -- never assemble without the card.
            return replace(
                decision,
                decision=DECIDE_NO_TEAM,
                reason="需审批但审批存储不可用，不组队、单人继续",
            )
        payload = getattr(event, "payload", None)
        thread_id = ""
        if isinstance(payload, dict):
            thread_id = str(payload.get("work_thread_id") or "").strip()
        role_titles = ", ".join(
            ROLE_TEMPLATES[key].title for key in decision.role_keys
        )
        subtask_text = "；".join(decision.subtasks)[:600]
        try:
            request = requester(
                action_kind=APPROVAL_KIND_TEAM_ASSEMBLY,
                target=decision.project_title or "自主组队",
                scope=f"self-team-assembly:{thread_id or 'unknown'}",
                value_text=(
                    f"{decision.needs_approval_reason}。"
                    f"拟组专员：{role_titles}。子任务：{subtask_text}。"
                ),
                source="resident",
                event_id=str(getattr(event, "event_id", "") or ""),
            )
        except Exception as exc:
            return replace(
                decision,
                decision=DECIDE_NO_TEAM,
                reason=f"审批卡创建失败（{type(exc).__name__}），不组队、单人继续",
            )
        return replace(
            decision,
            decision=DECIDE_PENDING_APPROVAL,
            approval_request_id=str(
                getattr(request, "request_id", "") or ""
            ).strip()
            or None,
            reason=f"已发起组队审批（{decision.needs_approval_reason}），等主人拍板",
        )

    def _poll_approval(self, decision: SelfTeamDecision) -> SelfTeamDecision:
        store = self._store
        request_id = decision.approval_request_id or ""
        getter = getattr(store, "get_request", None)
        if not request_id or not callable(getter):
            return decision
        try:
            expirer = getattr(store, "expire_overdue", None)
            if callable(expirer):
                expirer()
            request = getter(request_id)
        except Exception:
            return decision
        if request is None:
            return decision
        status = str(getattr(request, "status", "") or "")
        if status in ("approved", "approved_once"):
            # Consume is bookkeeping: the approval itself stands even if
            # the consume write fails, so the team still assembles.
            _try_consume_card(store, request_id)
            return replace(
                decision,
                decision=DECIDE_ASSEMBLE,
                approval_request_id=None,
                reason="主人已批准组队，建队并行推进",
            )
        if status in ("denied", "expired"):
            return replace(
                decision,
                decision=DECIDE_NO_TEAM,
                approval_request_id=None,
                reason=f"组队审批{status}，单人继续",
            )
        return decision


__all__ = [
    "APPROVAL_KIND_TEAM_ASSEMBLY",
    "DECIDE_ASSEMBLE",
    "DECIDE_NEEDS_APPROVAL",
    "DECIDE_NOT_APPLICABLE",
    "DECIDE_NO_TEAM",
    "DECIDE_PENDING_APPROVAL",
    "DEFAULT_MAX_SPECIALISTS",
    "SELF_TEAM_MARKER",
    "SELF_TEAM_STATE_KEY",
    "SelfTeamDecision",
    "SelfTeamDriver",
    "SelfTeamEnvelope",
    "SelfTeamWorkOwner",
    "apply_self_team_plan",
    "build_self_team_question",
    "check_self_team_envelope",
    "decide_self_team",
    "inject_self_team_request",
    "prescreen_self_team",
    "quiet_save_working_state",
]
