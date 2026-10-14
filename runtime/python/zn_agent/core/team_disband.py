from __future__ import annotations

import re

"""P3-8: execute ``DisbandPlan`` for real in the resident loop.

Before this slice, ``DisbandPlan`` only *computed* the deletion scope --
nothing ever deleted anything. This module is the executor: given a
team id, it deletes every scope item (plan tasks, team journal, team
memory, project-thread content) against the real ledger + memory, then
re-reads each scope and only reports success when the verification
passes. The resident delivers the returned checklist as the disband
event's final response, so the owner can check it afterwards.

Deletion shape (why the thread row survives):

* The project thread's *content* is deleted: all WorkItems except the
  disband event's own Root, all messages except the disband request,
  all artifact rows, all work_run rows except the disband event's.
* The thread *row* itself survives as the checklist carrier. Deleting
  it would destroy the only channel that delivers the cleanup
  checklist (``work.py`` finalizes an event by appending its response
  to the thread). After disband the thread holds the disband request
  + the checklist (+ the one activity note the work layer appends on
  finalize) -- nothing else.
* The work_plan_state counter row is intentionally kept: it is a
  thread-level version counter, not team content, and the disband
  event's own completion still reads it.
* Workspace files and browser logins are NEVER touched: they are the
  user's own state on their own computer. The checklist always carries
  ``SHARED_FILES_REMINDER`` so the owner knows to clean them by hand.

Failure semantics: validation (unknown thread / no team state) raises
*before* deleting anything. Verification runs *before* memory deletion,
so a failed verification leaves the spec + plan map in memory and a
re-issued disband can retry with full evidence. The user's disband
instruction is the confirmation -- no second prompt, ever.
"""

from dataclasses import dataclass
from typing import Any

from .project_team import (
    SHARED_FILES_REMINDER,
    assemble_team,
    team_journal_role_prefix,
    team_memory_prefix,
)
from .team_memory import delete_team_memory, team_shared_memory
from .team_runner import TeamRunner
from .team_timeline import parse_team_role
from .team_work_owner import TEAM_SPEC_KEY

# Verb-first / 把-form disband phrasings. Noun-first statements ("团队解散了",
# "他们团队解散了") are NOT instructions and must not match: the verb has to
# come first ("解散团队") or ride a 把-form ("把团队解散").
_DISBAND_PHRASES = (
    "解散这支团队",
    "解散这个团队",
    "解散团队",
    "解散掉团队",
    "把这支团队解散",
    "把这个团队解散",
    "把团队解散",
    "把这支团队删掉",
    "把这个团队删掉",
    "把团队删掉",
    "删除这支团队",
    "删除这个团队",
    "删除团队",
    "删掉团队",
    "disband the team",
    "disband this team",
    "delete the team",
    "dissolve the team",
    "remove the team",
)

#: Negation guard: "不要解散团队" / "别把团队解散" must NEVER disband.
#: Disbanding is irreversible, so a negation anywhere near the verb wins.
_NEGATION_RE = re.compile(r"不要|别把|别解散|禁止解散|勿解散")


@dataclass(frozen=True, slots=True)
class DisbandRequest:
    """A user's explicit instruction to disband the team in this thread."""

    text: str = ""


def parse_disband_request(task: str) -> DisbandRequest | None:
    """Parse an explicit disband instruction; None when not a disband ask.

    Conservative by design, mirroring ``parse_team_request``: only an
    explicit instruction matches. Bare "解散" (could be a meeting),
    noun-first statements ("团队解散了"), and plain tasks return None.
    """
    if not task or not str(task).strip():
        return None
    lowered = str(task).lower()
    if _NEGATION_RE.search(lowered):
        return None
    for phrase in _DISBAND_PHRASES:
        if phrase in lowered:
            return DisbandRequest(text=str(task).strip())
    return None


def handles_disband(event: Any) -> bool:
    """True when the event carries a daemon-parsed disband request."""
    payload = getattr(event, "payload", None)
    if not isinstance(payload, dict):
        return False
    request = payload.get("disband_request")
    if not isinstance(request, dict):
        return False
    return bool(str(request.get("team_id") or "").strip())


def find_team_id_in_messages(messages: Any) -> str | None:
    """The team id behind a thread's journal, newest first. None if no team."""
    for message in reversed(list(messages or [])):
        parsed = parse_team_role(getattr(message, "role", None))
        if parsed is not None:
            return parsed[0]
    return None


@dataclass(slots=True)
class DisbandReport:
    """What one disband execution deleted, plus its verification."""

    team_id: str
    thread_id: str
    member_names: tuple[str, ...] = ()
    plan_items_deleted: int = 0
    worker_runs_deleted: int = 0
    journal_messages_deleted: int = 0
    journal_count_capped: bool = False
    messages_deleted: int = 0
    artifacts_deleted: int = 0
    work_runs_deleted: int = 0
    memory_facts_deleted: int = 0
    verified: bool = False
    leftover: tuple[str, ...] = ()

    def checklist_text(self) -> str:
        """The cleanup checklist delivered to the owner as the final response."""
        members = (
            f"已删除 {len(self.member_names)} 名专员记录"
            + (
                f"（{', '.join(self.member_names)}）"
                if self.member_names
                else ""
            )
        )
        journal_count = (
            f"≥{self.journal_messages_deleted}"
            if self.journal_count_capped
            else str(self.journal_messages_deleted)
        )
        lines = [
            f"团队 {self.team_id} 已解散，清理清单：",
            f"- 成员：{members}（roster 随团队记忆删除）",
            f"- 任务：已删除 {self.plan_items_deleted} 个计划任务、"
            f"{self.worker_runs_deleted} 条专员运行记录",
            f"- 日志：已删除 {journal_count} 条团队日志",
            f"- 记忆：已删除 {self.memory_facts_deleted} 条团队记忆",
            f"- 项目线程：已清空（消息 {self.messages_deleted} 条、产物 "
            f"{self.artifacts_deleted} 项、历史运行 {self.work_runs_deleted} 条已删除，"
            "仅保留本条清单）",
        ]
        if self.verified:
            lines.append("- 验证：逐项复核通过，无残留")
        else:
            lines.append(
                "- 验证：未通过，残留："
                + ("、".join(self.leftover) if self.leftover else "未知")
                + "——请再说一次解散以重试"
            )
        lines.append(SHARED_FILES_REMINDER)
        return "\n".join(lines)


def execute_disband(
    *,
    team_id: str,
    ledger: Any,
    memory: Any,
    thread_id: str,
    current_event_id: str | None = None,
    current_work_item_id: str | None = None,
    current_message_id: str | None = None,
) -> DisbandReport:
    """Delete everything in a team's ``DisbandPlan`` scope, then verify.

    ``current_*`` are the disband event's own rows, preserved so the event
    can complete and deliver the checklist. Pass None when calling outside
    an event (tests / tooling) -- then nothing is preserved.

    Raises ``ValueError`` before deleting anything when the thread is
    unknown or no team state exists, and ``RuntimeError`` when the
    post-delete verification finds leftovers (memory is still intact in
    that case, so re-issuing disband retries with full evidence).
    """
    team_id = str(team_id or "").strip()
    thread_id = str(thread_id or "").strip()
    if not team_id:
        raise ValueError("team_id must not be empty")
    if not thread_id:
        raise ValueError("thread_id must not be empty")
    if ledger.get_thread(thread_id) is None:
        raise ValueError(f"unknown work thread: {thread_id!r}")

    shared = team_shared_memory(memory, team_id)
    spec_match = shared.recall(TEAM_SPEC_KEY)
    plan_match = shared.recall(TeamRunner.PLAN_MAP_KEY)
    plan_map: dict[str, str] = (
        dict(plan_match.value)
        if plan_match is not None and isinstance(plan_match.value, dict)
        else {}
    )
    memory_prefix = team_memory_prefix(team_id)
    journal_prefix = team_journal_role_prefix(team_id)
    messages = ledger.list_messages(thread_id, limit=500)
    team_journal = [m for m in messages if str(m.role).startswith(journal_prefix)]
    memory_facts = [
        f
        for f in memory.store.list_facts()
        if str(f["key"]).startswith(memory_prefix)
    ]
    spec = (
        spec_match.value
        if spec_match is not None and isinstance(spec_match.value, dict)
        else None
    )
    if spec is None and not plan_map and not team_journal and not memory_facts:
        raise ValueError(
            f"未找到团队 {team_id} 的任何状态（spec / 计划映射 / 日志 / 记忆），"
            "未删除任何内容"
        )

    member_names: list[str] = []
    if spec is not None:
        project = str(spec.get("project_title") or "").strip()
        roles = [str(key) for key in (spec.get("role_keys") or [])]
        if project and roles:
            try:
                member_names = [
                    member.name
                    for member in assemble_team(
                        project,
                        roles,
                        team_id=team_id,
                        work_thread_id=thread_id,
                    ).members
                ]
            except ValueError:
                # A malformed spec must not block deletion: the roster
                # dies with the memory sweep below either way.
                member_names = []

    # -- plan tasks (+ their WorkerRuns, via the item cascade) -----------
    items_before = {
        item.work_item_id: item
        for item in ledger.list_work_items(thread_id, limit=500)
    }
    plan_work_ids = [
        str(wid) for wid in dict.fromkeys(plan_map.values()) if str(wid).strip()
    ]
    plan_items_deleted = sum(
        1 for wid in plan_work_ids if wid in items_before
    )
    worker_runs_deleted = 0
    for wid in plan_work_ids:
        worker_runs_deleted += len(
            ledger.list_worker_runs(work_item_id=wid, limit=1024)
        )

    keep_items = (
        (str(current_work_item_id).strip(),)
        if current_work_item_id and str(current_work_item_id).strip()
        else ()
    )
    ledger.delete_thread_work_items(thread_id, keep_work_item_ids=keep_items)

    # -- project-thread content ------------------------------------------
    journal_count_capped = len(messages) >= 500
    journal_messages_deleted = len(team_journal)
    keep_messages = (
        (str(current_message_id).strip(),)
        if current_message_id and str(current_message_id).strip()
        else ()
    )
    messages_deleted = ledger.delete_thread_messages(
        thread_id, keep_message_ids=keep_messages
    )
    artifacts_deleted = ledger.delete_thread_artifacts(thread_id)
    keep_events = (
        (str(current_event_id).strip(),)
        if current_event_id and str(current_event_id).strip()
        else ()
    )
    work_runs_deleted = ledger.delete_thread_work_runs(
        thread_id, keep_event_ids=keep_events
    )

    # -- verify BEFORE memory deletion (retry stays possible) ------------
    leftover: list[str] = []
    remaining_items = ledger.list_work_items(thread_id, limit=500)
    for item in remaining_items:
        if item.work_item_id not in set(keep_items):
            leftover.append(f"WorkItem 残留：{item.work_item_id}")
    remaining_messages = ledger.list_messages(thread_id, limit=500)
    for msg in remaining_messages:
        if msg.message_id not in set(keep_messages):
            leftover.append(f"消息残留：{msg.message_id}")
        if str(msg.role).startswith(journal_prefix):
            leftover.append(f"团队日志残留：{msg.message_id}")
    if ledger.list_artifacts(thread_id, limit=96):
        leftover.append("产物残留")
    remaining_runs = ledger.count_thread_work_runs(thread_id)
    expected_runs = len(keep_events)
    if remaining_runs != expected_runs:
        leftover.append(f"历史运行残留：{remaining_runs} 条（应为 {expected_runs} 条）")
    if leftover:
        raise RuntimeError(
            "解散验证未通过，记忆未删除、请再说一次解散以重试；"
            + "; ".join(leftover)[:1000]
        )

    # -- team memory (last, so a retry still finds evidence) -------------
    memory_facts_deleted = delete_team_memory(memory, team_id)
    remaining_facts = [
        f
        for f in memory.store.list_facts()
        if str(f["key"]).startswith(memory_prefix)
    ]
    if remaining_facts:
        raise RuntimeError(
            f"解散验证未通过：团队记忆残留 {len(remaining_facts)} 条"
        )

    return DisbandReport(
        team_id=team_id,
        thread_id=thread_id,
        member_names=tuple(member_names),
        plan_items_deleted=plan_items_deleted,
        worker_runs_deleted=worker_runs_deleted,
        journal_messages_deleted=journal_messages_deleted,
        journal_count_capped=journal_count_capped,
        messages_deleted=messages_deleted,
        artifacts_deleted=artifacts_deleted,
        work_runs_deleted=work_runs_deleted,
        memory_facts_deleted=memory_facts_deleted,
        verified=True,
    )


__all__ = [
    "DisbandReport",
    "DisbandRequest",
    "execute_disband",
    "find_team_id_in_messages",
    "handles_disband",
    "parse_disband_request",
]
