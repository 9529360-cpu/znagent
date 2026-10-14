from __future__ import annotations

"""ZN saved skills: tasks stored as reusable skills (P1-3).

A user says "存成技能" after a task completes and ZN builds a skill *draft*
from that completed Work: seven fields (when to use, inputs/permissions,
steps, verification method, return format, approval boundary, failure
handling). A draft is inert until a human confirms it; only confirmed
("active") skills are ever matched, injected into cognition, or referenced
by team specialists. Deleting a skill removes only the skill row -- Work
records (events / outcomes) are never touched.

Skills are DATA, not authority: they never grant tool permission, change
Work route policy, require an action, or prove task completion. Their
approval boundary still applies to every action taken while following one.

This is deliberately separate from the file-based skill bundles in
``skills.py`` (markdown knowledge under ``$ZN_HOME/skills/``): saved skills
are SQLite rows in the same DB as memory facts, with a draft -> confirmed
lifecycle and human confirmation as the activation gate.
"""

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Any

from .models import EventOutcome, EventStatus, utc_now

#: The seven draft fields. ``validate_for_activation`` requires every one
#: non-empty; the approval boundary is the field the design calls out
#: explicitly (missing -> refuse to store).
SKILL_FIELDS: tuple[str, ...] = (
    "when_to_use",
    "inputs_permissions",
    "steps",
    "verification_method",
    "return_format",
    "approval_boundary",
    "failure_handling",
)

STATUS_DRAFT = "draft"
STATUS_ACTIVE = "active"

_MAX_NAME_CHARS = 64
_MAX_FIELD_CHARS = 4000
_MAX_STEPS = 12
_MAX_RELEVANT_SKILLS = 3
_DEFAULT_APPROVAL_BOUNDARY = (
    "副作用动作（写文件、发送、发布、购买、删除、生产变更）需用户显式审批后执行；"
    "只读查询可直接执行。"
)
_DEFAULT_FAILURE_HANDLING = "首次失败即停止并报告原因，不自动重试副作用；用户确认后可重试一次。"


def clean_skill_name(value: object) -> str:
    """Normalize a skill name: collapse whitespace to '-', bounded length."""
    text = re.sub(r"\s+", "-", str(value or "").strip())
    text = text.strip("-/").strip()
    return text[:_MAX_NAME_CHARS]


def valid_skill_name(name: str) -> bool:
    """A usable skill name: non-empty, bounded, no '/' (slash-reference safe)."""
    if not name or len(name) > _MAX_NAME_CHARS:
        return False
    if "/" in name or "\n" in name or "\r" in name:
        return False
    return True


def _clean_text(value: object, *, limit: int = _MAX_FIELD_CHARS) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _clean_steps(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, (list, tuple)):
        candidates = [str(item) for item in value]
    else:
        candidates = []
    cleaned: list[str] = []
    for item in candidates:
        text = _clean_text(item, limit=1000)
        if text:
            cleaned.append(text)
    return tuple(cleaned[:_MAX_STEPS])


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[\W_]+", " ", text)
    return " ".join(text.split())


def _cue_occurs(query: str, cue: str) -> bool:
    if not query or not cue:
        return False
    if query == cue:
        return True
    if len(cue) < 2:
        return False
    if re.search(r"[\u4e00-\u9fff]", cue):
        return cue in query
    if re.search(r"[a-z0-9]", cue):
        if " " not in cue and len(cue) < 12:
            return False
        return re.search(rf"(?<![a-z0-9_]){re.escape(cue)}(?![a-z0-9_])", query) is not None
    return re.search(rf"(?<!\w){re.escape(cue)}(?!\w)", query) is not None


@dataclass(slots=True)
class SkillRecord:
    """One saved skill: draft until a human confirms it, then active."""

    skill_id: str
    name: str
    status: str = STATUS_DRAFT
    when_to_use: str = ""
    inputs_permissions: str = ""
    steps: tuple[str, ...] = ()
    verification_method: str = ""
    return_format: str = ""
    approval_boundary: str = ""
    failure_handling: str = ""
    source_event_id: str = ""
    source_thread_id: str = ""
    created_at: str = field(default_factory=utc_now)
    confirmed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "status": self.status,
            "when_to_use": self.when_to_use,
            "inputs_permissions": self.inputs_permissions,
            "steps": list(self.steps),
            "verification_method": self.verification_method,
            "return_format": self.return_format,
            "approval_boundary": self.approval_boundary,
            "failure_handling": self.failure_handling,
            "source_event_id": self.source_event_id,
            "source_thread_id": self.source_thread_id,
            "created_at": self.created_at,
            "confirmed_at": self.confirmed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillRecord":
        raw = dict(data or {})
        return cls(
            skill_id=str(raw.get("skill_id") or ""),
            name=str(raw.get("name") or ""),
            status=str(raw.get("status") or STATUS_DRAFT),
            when_to_use=_clean_text(raw.get("when_to_use")),
            inputs_permissions=_clean_text(raw.get("inputs_permissions")),
            steps=_clean_steps(raw.get("steps")),
            verification_method=_clean_text(raw.get("verification_method")),
            return_format=_clean_text(raw.get("return_format")),
            approval_boundary=_clean_text(raw.get("approval_boundary")),
            failure_handling=_clean_text(raw.get("failure_handling")),
            source_event_id=str(raw.get("source_event_id") or ""),
            source_thread_id=str(raw.get("source_thread_id") or ""),
            created_at=str(raw.get("created_at") or utc_now()),
            confirmed_at=str(raw.get("confirmed_at") or ""),
        )


def validate_for_activation(record: SkillRecord) -> list[str]:
    """Missing-field errors; empty means the record may be confirmed.

    The approval boundary is validated like every other field: a draft
    without it is refused, never silently defaulted at confirm time.
    """
    errors: list[str] = []
    if not valid_skill_name(record.name):
        errors.append("name must be 1-64 chars without '/'")
    if record.status != STATUS_DRAFT:
        errors.append(f"only a draft can be confirmed (status={record.status!r})")
    values = {
        "when_to_use": record.when_to_use,
        "inputs_permissions": record.inputs_permissions,
        "steps": record.steps,
        "verification_method": record.verification_method,
        "return_format": record.return_format,
        "approval_boundary": record.approval_boundary,
        "failure_handling": record.failure_handling,
    }
    for key in SKILL_FIELDS:
        value = values[key]
        if isinstance(value, tuple):
            if not value:
                errors.append(f"{key} must not be empty")
        elif not str(value or "").strip():
            errors.append(f"{key} must not be empty")
    return errors


def build_skill_draft(
    source: dict[str, Any],
    *,
    name_hint: str | None = None,
    skill_id: str | None = None,
) -> SkillRecord:
    """Build a draft from a completed Work summary (deterministic, no model).

    ``source`` carries the completed task, its objective, acceptance
    criteria and outcome response. Every field is filled from the source
    plus conservative defaults; the human confirm step is where the draft
    gets corrected, so the template must be truthful, not impressive.
    """
    task = _clean_text(source.get("task"), limit=500)
    objective = _clean_text(source.get("objective") or task, limit=500)
    criteria = [
        _clean_text(item, limit=300)
        for item in (source.get("acceptance_criteria") or [])
        if _clean_text(item, limit=300)
    ][:6]
    response = _clean_text(source.get("response"), limit=1200)
    thread_id = str(source.get("thread_id") or "")
    event_id = str(source.get("event_id") or "")

    name = clean_skill_name(name_hint) if name_hint else ""
    if not name:
        base = re.sub(r"[，。,；;：:、！!？?·…—\-/\\]+", "", task.replace(" ", ""))
        name = base[:32] or f"技能-{uuid.uuid4().hex[:6]}"
    if not valid_skill_name(name):
        name = f"技能-{uuid.uuid4().hex[:6]}"

    criteria_text = "；".join(criteria) if criteria else "按原任务的验收标准"
    steps = [
        f"确认任务目标：{objective}",
        f"按验收标准执行：{criteria_text}",
        "用新鲜观察验证每条验收标准，不以模型自述为准",
        "汇总结果并报告：完成了什么、产物路径、验证结论",
    ]
    if response:
        steps.append(f"上次执行摘要（仅供参考，需重新验证）：{response[:600]}")

    return SkillRecord(
        skill_id=skill_id or f"skill-{uuid.uuid4().hex[:12]}",
        name=name,
        status=STATUS_DRAFT,
        when_to_use=f"当用户要求“{task or objective}”（或类似任务）时使用。",
        inputs_permissions=(
            "输入：用户的任务描述与必要的上下文文件。"
            "权限：沿用原任务的授权边界；任何副作用动作需用户显式审批后执行。"
        ),
        steps=tuple(steps),
        verification_method=f"逐条核对验收标准（{criteria_text}）；每条需新鲜观察证据。",
        return_format="文字摘要：完成了什么、产物路径、验证结论；失败时说明原因与未完成项。",
        approval_boundary=_DEFAULT_APPROVAL_BOUNDARY,
        failure_handling=_DEFAULT_FAILURE_HANDLING,
        source_event_id=event_id,
        source_thread_id=thread_id,
    )


class SkillLedger:
    """Draft -> confirmed lifecycle over the KernelStore skills table."""

    def __init__(self, store: Any) -> None:
        self.store = store

    # -- CRUD ------------------------------------------------------------

    def save_draft(self, record: SkillRecord) -> SkillRecord:
        if record.status != STATUS_DRAFT:
            raise ValueError("save_draft only stores drafts")
        if not valid_skill_name(record.name):
            raise ValueError(f"invalid skill name: {record.name!r}")
        self.store.save_skill(record.to_dict())
        return record

    def get_skill(self, skill_id: str) -> SkillRecord | None:
        row = self.store.get_skill(str(skill_id or ""))
        return SkillRecord.from_dict(row) if row else None

    def get_skill_by_name(self, name: str, *, status: str | None = None) -> SkillRecord | None:
        row = self.store.get_skill_by_name(clean_skill_name(name), status=status)
        return SkillRecord.from_dict(row) if row else None

    def list_skills(self, *, status: str | None = None) -> list[SkillRecord]:
        return [
            SkillRecord.from_dict(row)
            for row in self.store.list_skills(status=status)
        ]

    def confirm(self, skill_id: str) -> SkillRecord:
        """Activate a draft. Missing fields (incl. approval boundary) refuse."""
        record = self.get_skill(skill_id)
        if record is None:
            raise ValueError(f"unknown skill: {skill_id!r}")
        errors = validate_for_activation(record)
        if errors:
            raise ValueError(
                f"skill {record.name!r} cannot be confirmed: {'; '.join(errors)}"
            )
        record.status = STATUS_ACTIVE
        record.confirmed_at = utc_now()
        self.store.save_skill(record.to_dict())
        return record

    def delete_skill(self, skill_id: str) -> None:
        """Delete only the skill row; Work records are never touched."""
        self.store.delete_skill(str(skill_id or ""))

    # -- matching (active skills only) ------------------------------------

    def relevant_skills(
        self, query: str, *, max_skills: int = _MAX_RELEVANT_SKILLS
    ) -> list[SkillRecord]:
        """Conservatively match ACTIVE skills by name / when-to-use cues.

        Drafts never match: an unconfirmed skill takes no effect anywhere.
        """
        count = max(0, min(10, int(max_skills)))
        normalized = _normalize(query)
        if not count or not normalized:
            return []
        scored: list[tuple[int, str, SkillRecord]] = []
        for skill in self.list_skills(status=STATUS_ACTIVE):
            cue = self._best_cue(normalized, skill)
            if cue:
                scored.append((len(cue), skill.name, skill))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [skill for _, _, skill in scored[:count]]

    @staticmethod
    def _best_cue(normalized_query: str, skill: SkillRecord) -> str:
        cues = {_normalize(skill.name), _normalize(skill.when_to_use)}
        words = _normalize(skill.when_to_use).split()
        for width in range(min(4, len(words)), 1, -1):
            for index in range(len(words) - width + 1):
                cues.add(" ".join(words[index : index + width]))
        best = ""
        for cue in cues:
            if _cue_occurs(normalized_query, cue) and len(cue) > len(best):
                best = cue
        return best

    # -- rendering ----------------------------------------------------------

    @staticmethod
    def render_for_cognition(record: SkillRecord, *, max_chars: int = 2000) -> str:
        """Bounded skill block for a cognition prompt. Data, not authority."""
        steps = "\n".join(
            f"  {index + 1}) {step}" for index, step in enumerate(record.steps)
        )
        text = (
            f"Skill '{record.name}' (ZN-owned, human-confirmed):\n"
            f"何时用：{record.when_to_use}\n"
            f"输入/权限：{record.inputs_permissions}\n"
            f"步骤：\n{steps}\n"
            f"验证方法：{record.verification_method}\n"
            f"返回格式：{record.return_format}\n"
            f"审批边界：{record.approval_boundary}\n"
            f"失败处理：{record.failure_handling}\n"
            "Follow its steps; its approval boundary still applies to every action."
        )
        return text[:max(1, int(max_chars))]


def skill_reference_block(store: Any, event: Any) -> str:
    """Rendered block for a validated "/skill" reference on an event, or "".

    The deliberation hook already failed closed on an unknown skill; if the
    skill vanished mid-flight, this degrades to no skill, never guesses.
    Callers that overwrite the cognition question must re-append this block
    after their overwrite (see BroadGoalAutonomous / BroadGoalCoding).
    """
    payload = getattr(event, "payload", None)
    if not isinstance(payload, dict):
        return ""
    ref = payload.get("skill_reference")
    if not isinstance(ref, dict):
        return ""
    name = str(ref.get("name") or "").strip()
    if not name:
        return ""
    try:
        skill = SkillLedger(store).get_skill_by_name(name, status=STATUS_ACTIVE)
    except (AttributeError, KeyError, LookupError, OSError, RuntimeError, ValueError):
        return ""
    if skill is None:
        return ""
    return "Referenced skill (ZN-owned, human-confirmed):\n" + SkillLedger.render_for_cognition(skill)


class SkillOwner:
    """Execute skill payloads: save draft, confirm, validate a reference.

    ``handle`` returns response text for terminal flows (save / confirm)
    and ``None`` for a validated reference, which falls through to normal
    cognition with the skill injected. ``ValueError`` means fail closed
    with the message as the terminal reason.
    """

    _BARE_CONFIRM_TASKS = ("确认", "confirm")

    def __init__(self, *, store: Any, ledger: Any) -> None:
        self.store = store
        self.ledger = ledger
        self.skills = SkillLedger(store)

    # -- routing ----------------------------------------------------------

    def handles(self, event: Any) -> bool:
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            return False
        if (
            "skill_save_request" in payload
            or "skill_confirm" in payload
            or "skill_reference" in payload
        ):
            return True
        task = str(getattr(event, "task", "") or "").strip().lower()
        if task in self._BARE_CONFIRM_TASKS:
            thread_id = str(payload.get("work_thread_id") or "").strip()
            return bool(thread_id) and bool(self._drafts_in_thread(thread_id))
        return False

    def handle(self, event: Any) -> str | None:
        payload = dict(getattr(event, "payload", None) or {})
        if "skill_save_request" in payload:
            return self._handle_save(event, payload)
        if "skill_confirm" in payload:
            return self._handle_confirm(event, payload)
        if "skill_reference" in payload:
            self._handle_reference(payload)
            return None
        task = str(getattr(event, "task", "") or "").strip().lower()
        if task in self._BARE_CONFIRM_TASKS:
            return self._handle_confirm(event, payload)
        raise ValueError("skill event has no skill payload")

    # -- save ---------------------------------------------------------------

    def _handle_save(self, event: Any, payload: dict[str, Any]) -> str:
        thread_id = str(payload.get("work_thread_id") or "").strip()
        request = payload.get("skill_save_request")
        name_hint = None
        if isinstance(request, dict):
            name_hint = str(request.get("name_hint") or "").strip() or None
        previous = self._last_completed_success(thread_id, exclude=event.event_id)
        if previous is None:
            raise ValueError(
                "没有已完成的任务可存为技能：请先完成一个任务，再说“存成技能”。"
            )
        prev_event, outcome = previous
        source = self._source_from_completed(prev_event, outcome)
        record = build_skill_draft(source, name_hint=name_hint)
        record.name = self._unique_name(record.name)
        record.source_thread_id = thread_id
        self.skills.save_draft(record)
        rendered = SkillLedger.render_for_cognition(record)
        return (
            "技能草稿已生成（未入库，需确认）：\n\n"
            f"{rendered}\n\n"
            "回复“确认保存技能”即可入库；草稿未确认前不会生效。"
        )

    def _last_completed_success(
        self, thread_id: str, *, exclude: str
    ) -> tuple[Any, EventOutcome] | None:
        if not thread_id:
            return None
        for candidate in self.store.list_events(status=EventStatus.COMPLETED, limit=500):
            if str(candidate.event_id) == str(exclude):
                continue
            payload = getattr(candidate, "payload", None)
            if not isinstance(payload, dict):
                continue
            if str(payload.get("work_thread_id") or "").strip() != thread_id:
                continue
            outcome = self.store.get_event_outcome(candidate.event_id)
            if outcome is not None and outcome.success:
                return candidate, outcome
        return None

    def _source_from_completed(self, prev_event: Any, outcome: EventOutcome) -> dict[str, Any]:
        objective = ""
        criteria: list[str] = []
        item = None
        try:
            item = self.ledger.work_item_for_event(prev_event.event_id)
        except (AttributeError, KeyError, LookupError, OSError, RuntimeError, ValueError):
            item = None
        if item is not None:
            objective = str(getattr(item, "objective", "") or "")
            criteria = [str(value) for value in (getattr(item, "acceptance_criteria", None) or [])]
        payload = getattr(prev_event, "payload", None)
        thread_id = ""
        if isinstance(payload, dict):
            thread_id = str(payload.get("work_thread_id") or "")
        return {
            "task": str(getattr(prev_event, "task", "") or ""),
            "objective": objective,
            "acceptance_criteria": criteria,
            "response": str(getattr(outcome, "response", "") or ""),
            "event_id": str(getattr(prev_event, "event_id", "") or ""),
            "thread_id": thread_id,
        }

    def _unique_name(self, base: str) -> str:
        candidate = base
        suffix = 2
        while self.skills.get_skill_by_name(candidate) is not None:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    # -- confirm --------------------------------------------------------------

    def _drafts_in_thread(self, thread_id: str) -> list[SkillRecord]:
        return [
            record
            for record in self.skills.list_skills(status=STATUS_DRAFT)
            if record.source_thread_id == thread_id
        ]

    def _handle_confirm(self, event: Any, payload: dict[str, Any]) -> str:
        thread_id = str(payload.get("work_thread_id") or "").strip()
        drafts = self._drafts_in_thread(thread_id)
        if not drafts:
            raise ValueError("没有待确认的技能草稿：请先说“存成技能”生成草稿。")
        # Save -> confirm is an immediate conversational pair; the latest
        # draft in this thread is the one just presented. The response names
        # it explicitly so a mistaken confirm is visible.
        drafts.sort(key=lambda record: (record.created_at, record.skill_id))
        confirmed = self.skills.confirm(drafts[-1].skill_id)
        return (
            f"技能“{confirmed.name}”已确认入库，"
            f"团队专员和 /{confirmed.name} 引用均可使用。"
        )

    # -- reference --------------------------------------------------------------

    def _handle_reference(self, payload: dict[str, Any]) -> None:
        ref = payload.get("skill_reference")
        name = str(ref.get("name") or "").strip() if isinstance(ref, dict) else ""
        if not name:
            raise ValueError("技能引用缺少技能名。")
        skill = self.skills.get_skill_by_name(name, status=STATUS_ACTIVE)
        if skill is None:
            raise ValueError(f"技能“{name}”不存在或未确认入库。")
