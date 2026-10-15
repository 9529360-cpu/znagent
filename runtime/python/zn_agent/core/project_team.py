from __future__ import annotations

"""Project teams: durable multi-specialist teams on top of Work/WorkItem/WorkerRun.

A user says "this project is too slow, assemble a professional team for it" and
ZN stands up a team: named specialists (architect, researcher, developer,
tester) that persist across sessions, share a project journal, and take tasks
as WorkItems with dependencies.

Red lines (from docs/ZN-PROJECT-TEAMS.md):
- No second control plane. A team lives inside one work thread; execution is
  WorkerRun under the Work's authority; the model router stays kernel-owned.
- No new resident/orchestrator identity. The coordinator is the resident
  itself (or a worker it delegates), not a new subject.
- This module is ledger-agnostic on purpose: it produces roster, journal
  message payloads and WorkItem-ready dicts. The resident wires them into
  ResidentWorkLedger / SteerableWorkLedger in slice 2. Pure stdlib, no I/O.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from .privacy_choke import strip_tags

JOURNAL_KINDS = ("note", "progress", "handoff", "blocker", "decision")

#: Deletion-scope reminder, shown in every disband plan / cleanup checklist:
#: ZN deletes its own team records only. Workspace files and browser logins
#: are the user's own state on their own computer -- disband never touches
#: them, and the owner must clean them by hand if they want them gone.
SHARED_FILES_REMINDER = (
    "注意：共享文件与登录不会随之删除——工作区里的文件、浏览器登录态"
    "需主人手动清理。解散只删 ZN 侧的团队记录，不碰工作区文件与登录态。"
)


@dataclass(frozen=True, slots=True)
class SpecialistRole:
    """A reusable role template a team can be assembled from."""

    key: str
    title: str
    responsibilities: tuple[str, ...]
    default_objective: str
    default_acceptance: tuple[str, ...]
    prompt_fragment: str


ROLE_TEMPLATES: dict[str, SpecialistRole] = {
    "researcher": SpecialistRole(
        key="researcher",
        title="调研",
        responsibilities=(
            "调研技术选型与现有方案",
            "输出调研结论与风险清单",
            "为架构设计提供事实依据",
        ),
        default_objective="完成项目所需的技术与方案调研，输出结论与风险清单",
        default_acceptance=("调研结论有明确选型建议", "风险清单覆盖主要未知项"),
        prompt_fragment="你是团队的调研专员：只给结论和依据，不做实现决策；不确定的如实标注。",
    ),
    "architect": SpecialistRole(
        key="architect",
        title="架构",
        responsibilities=(
            "输出系统设计与模块划分",
            "定义接口契约与数据模型",
            "评审开发方案的技术可行性",
        ),
        default_objective="输出系统设计：模块划分、接口契约、数据模型",
        default_acceptance=("设计文档覆盖全部核心流程", "接口契约无二义性"),
        prompt_fragment="你是团队的架构专员：设计先行，接口契约明确；不写业务实现代码。",
    ),
    "developer": SpecialistRole(
        key="developer",
        title="开发",
        responsibilities=(
            "按设计实现功能",
            "编写单元测试",
            "修复测试与联调中发现的问题",
        ),
        default_objective="按设计文档实现功能，并编写单元测试",
        default_acceptance=("功能按验收标准实现", "新增代码有测试覆盖"),
        prompt_fragment="你是团队的开发专员：按设计实现，不擅自改接口；测试先行。",
    ),
    "tester": SpecialistRole(
        key="tester",
        title="测试",
        responsibilities=(
            "设计测试用例与验收验证",
            "执行集成测试并记录缺陷",
            "回归验证修复结果",
        ),
        default_objective="按验收标准验证交付物，记录并跟踪缺陷到关闭",
        default_acceptance=("验收标准逐条有验证结论", "缺陷有记录且已回归"),
        prompt_fragment="你是团队的测试专员：按验收标准说话，用证据验收，不许'看起来行了'。",
    ),
}


@dataclass(slots=True)
class Specialist:
    """A durable named team member. Persists across sessions."""

    name: str
    role_key: str
    role_title: str
    responsibilities: tuple[str, ...]
    memory_namespace: str
    prompt_fragment: str


@dataclass(slots=True)
class TeamPlanItem:
    """One task in the team plan, ready to become a WorkItem."""

    item_id: str
    title: str
    objective: str
    acceptance_criteria: tuple[str, ...]
    assignee: str  # specialist name
    dependency_ids: tuple[str, ...] = ()

    def as_work_item_kwargs(
        self,
        work_thread_id: str,
        plan_version: int,
        parent_work_item_id: str | None = None,
    ) -> dict[str, Any]:
        """Kwargs matching SteerableWorkLedger's WorkItem creation shape.

        Pass the project Root WorkItem id as parent_work_item_id: the
        dependency-readiness check requires plan items to hang under a Root.
        """
        return {
            "work_thread_id": work_thread_id,
            "title": self.title,
            "objective": self.objective,
            "status": "proposed",
            "plan_version": plan_version,
            "parent_work_item_id": parent_work_item_id,
            "acceptance_criteria": list(self.acceptance_criteria),
            "dependency_ids": list(self.dependency_ids),
        }


@dataclass(slots=True)
class ProjectTeam:
    team_id: str
    project_title: str
    members: tuple[Specialist, ...] = ()
    plan: tuple[TeamPlanItem, ...] = ()
    work_thread_id: str | None = None
    # Root of the specialists' file workspaces (``agents/<name>/`` per
    # member, see specialist_workspace). None means specialists keep using
    # their built-in prompt fragments; when set, dispatch re-reads each
    # specialist's files so edits take effect on the next dispatch.
    workspace_root: str | None = None

    def member(self, name: str) -> Specialist | None:
        for specialist in self.members:
            if specialist.name == name:
                return specialist
        return None

    def disband_plan(self) -> DisbandPlan:
        """Compute the full deletion scope for disbanding this team."""
        return DisbandPlan(
            team_id=self.team_id,
            work_thread_id=self.work_thread_id,
            memory_key_prefix=team_memory_prefix(self.team_id),
            journal_role_prefix=team_journal_role_prefix(self.team_id),
            plan_item_ids=tuple(item.item_id for item in self.plan),
        )


def team_memory_key(team_id: str, specialist_name: str, key: str) -> str:
    """Project-scoped memory key so specialists don't pollute shared memory."""
    return f"team:{team_id}:{specialist_name}:{key}"


def team_memory_prefix(team_id: str) -> str:
    """Prefix covering every memory key owned by the team."""
    return f"team:{team_id}:"


def team_journal_role_prefix(team_id: str) -> str:
    """Role prefix covering every journal message written by the team."""
    return f"team:{team_id}:"


@dataclass(slots=True)
class DisbandPlan:
    """Everything disbanding a team must delete. Executed by the coordinator
    (slice 2) against the ledger; computed here so the rule stays in one place.

    The user's disband instruction is the confirmation -- no second prompt.
    """

    team_id: str
    work_thread_id: str | None
    memory_key_prefix: str
    journal_role_prefix: str
    plan_item_ids: tuple[str, ...]

    def describe(self) -> str:
        parts = [
            f"删除团队 {self.team_id}：",
            f"- {len(self.plan_item_ids)} 个计划任务",
            "- 项目记忆命名空间",
            "- 项目共享日志",
        ]
        if self.work_thread_id:
            parts.append("- 项目工作线程（含消息与产物，级联清理）")
        parts.append(SHARED_FILES_REMINDER)
        return "\n".join(parts)


def journal_message(
    team_id: str, author: str, text: str, *, kind: str = "note"
) -> dict[str, Any]:
    """Payload ready for work_messages. role carries team routing; the ledger
    schema is untouched (slice 1).

    CM-3 follow-up F2: journal payloads are choked at construction --
    the team log never reaches the ledger carrying credential-shaped
    text. The ledger's ``append_message`` chokes again at the write
    boundary (defense in depth); choke output is idempotent.
    """
    if kind not in JOURNAL_KINDS:
        raise ValueError(f"unknown journal kind: {kind!r}")
    if not text or not text.strip():
        raise ValueError("journal text must not be empty")
    team_id = strip_tags(team_id)
    author = strip_tags(author)
    text = strip_tags(text)
    return {
        "role": f"team:{team_id}:{author}",
        "text": text,
        "detail": {"kind": kind, "team_id": team_id, "author": author},
    }


def assemble_team(
    project_title: str,
    role_keys: tuple[str, ...] | list[str],
    *,
    team_id: str | None = None,
    work_thread_id: str | None = None,
    roles: dict[str, SpecialistRole] | None = None,
    workspace_root: str | None = None,
) -> ProjectTeam:
    """Build a team: roster of named specialists plus a dependency-chained plan.

    Plan order follows the given role order; each item depends on the previous
    one (research -> design -> build -> test by default).

    ROLE_TEMPLATES are built-in defaults, not a closed set: pass ``roles`` with
    extra (or overriding) SpecialistRole entries to assemble non-dev teams
    (design, legal, marketing, ...) without touching this module.
    """
    if not project_title or not project_title.strip():
        raise ValueError("project_title must not be empty")
    keys = list(role_keys or [])
    if not keys:
        raise ValueError("at least one role is required")
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate roles are not allowed")
    registry: dict[str, SpecialistRole] = dict(ROLE_TEMPLATES)
    if roles:
        for role_key, role in roles.items():
            if not isinstance(role, SpecialistRole) or role.key != role_key:
                raise ValueError(
                    f"role entry {role_key!r} must be a SpecialistRole with matching key"
                )
            registry[role_key] = role
    unknown = [key for key in keys if key not in registry]
    if unknown:
        raise ValueError(f"unknown role(s): {', '.join(unknown)}")

    resolved_team_id = team_id or f"team-{uuid.uuid4().hex[:8]}"
    members: list[Specialist] = []
    for index, key in enumerate(keys):
        role = registry[key]
        name = f"{role.title}-{index + 1:02d}"
        members.append(
            Specialist(
                name=name,
                role_key=key,
                role_title=role.title,
                responsibilities=role.responsibilities,
                memory_namespace=f"team:{resolved_team_id}:{name}",
                prompt_fragment=role.prompt_fragment,
            )
        )

    plan: list[TeamPlanItem] = []
    for index, (key, specialist) in enumerate(zip(keys, members)):
        role = registry[key]
        dependencies = (plan[index - 1].item_id,) if index > 0 else ()
        plan.append(
            TeamPlanItem(
                item_id=f"{resolved_team_id}-item-{index + 1:02d}",
                title=f"{project_title}·{role.title}",
                objective=role.default_objective,
                acceptance_criteria=role.default_acceptance,
                assignee=specialist.name,
                dependency_ids=dependencies,
            )
        )

    return ProjectTeam(
        team_id=resolved_team_id,
        project_title=project_title,
        members=tuple(members),
        plan=tuple(plan),
        work_thread_id=work_thread_id,
        workspace_root=workspace_root,
    )
