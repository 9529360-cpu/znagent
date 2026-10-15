from __future__ import annotations

"""Team coordinator: dispatch / verify / escalate decisions for project teams.

The coordinator is a *decision layer*, not an executor. It reads durable Work
truth (WorkItems + DependencyReadiness) and emits decisions the resident
applies:

- dispatch: a ready plan item goes to its specialist. The resident creates the
  WorkerRun under the Work's authority (executor_kind "team-specialist") and
  marks the item running.
- verify: a run claimed completion; the resident verifies against the
  acceptance criteria with fresh observation before the item completes.
- escalate: a blocked or stalled item needs the user. A blocker journal entry
  is written; the resident surfaces it.
- wait: item is not ready yet; recorded with what it waits on.
- complete: verification passed; the resident marks the item completed.
- team_complete: every plan item completed. The coordinator only *reports*
  this. Disband is NEVER automatic -- the user says "disband the team",
  then the DisbandPlan executes.

This module is ledger-agnostic: it talks to a small duck-typed ledger
protocol (list_work_items / dependency_readiness) so it stays testable and
additive. No second control plane, no new resident identity.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from .project_team import ProjectTeam, journal_message
from .specialist_workspace import specialist_prompt_for
from .worker_progress import worker_stalled


class TeamLedger(Protocol):
    """Minimal durable-Work surface the coordinator needs."""

    def list_work_items(self, thread_id: str) -> list[Any]: ...

    def dependency_readiness(self, work_item_id: str) -> Any: ...


@dataclass(slots=True)
class CoordinatorDecision:
    """One decision for the resident to apply."""

    action: str  # dispatch | wait | verify | escalate | complete | team_complete
    work_item_id: str | None = None
    specialist_name: str | None = None
    reason: str = ""
    journal: dict[str, Any] | None = None
    context: dict[str, Any] | None = None


# -- AF-3: progress ledger + plan + plan-review loop ---------------------
#
# Magentic-style structured plan tracking, additive on top of the
# coordinator's decision layer. Pure stdlib, no I/O, no new resident
# identity:
#
# - ProgressLedger: the task ledger. Every task has one of four states
#   (todo / in_progress / done / failed) and every state change is
#   recorded in the task's history with a reason. ``done`` is terminal;
#   ``failed`` can be retried (failed -> todo / in_progress) after a
#   review says so -- a retry is an explicit, recorded transition, never
#   a silent reset.
# - ProgressPlan: a plan is an ordered list of ledger task ids. Order and
#   dependencies come from the ledger tasks themselves (``depends_on``);
#   ``plan_order`` topologically sorts them, ``ready_tasks`` lists the
#   todo tasks whose dependencies are all done.
# - review_plan: one deterministic review pass over a plan. Verdict is
#   "revise" when any task failed or is reported stalled, else
#   "continue". The conclusion is recorded in the ledger (ledger.reviews)
#   and rendered as a journal ``decision`` message via review_journal, so
#   the existing team timeline shows it without any timeline rewrite.
#
# Relation to CUR-2 Plan Mode (plan_mode.py): CUR-2 gates execution
# *before* it starts (user approves a plan file); AF-3 tracks execution
# *while* it runs (ledger + review loop). AF-3 never re-creates CUR-2's
# approval gate and never changes coordinator decisions: step() mirrors
# dispatch/complete into the ledger only when the caller passes one in,
# and the mirrored decisions are byte-identical to the no-ledger run.

TASK_STATUSES = ("todo", "in_progress", "done", "failed")

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "todo": frozenset({"in_progress", "done", "failed"}),
    "in_progress": frozenset({"todo", "done", "failed"}),
    "failed": frozenset({"todo", "in_progress"}),
    "done": frozenset(),
}


@dataclass(slots=True)
class ProgressTask:
    """One ledger task: current state + full transition history."""

    task_id: str
    title: str
    status: str = "todo"
    assignee: str = ""
    depends_on: tuple[str, ...] = ()
    objective: str = ""
    history: tuple[dict[str, Any], ...] = ()


@dataclass(slots=True)
class PlanReview:
    """One plan-review conclusion, recorded in the ledger."""

    plan_id: str
    verdict: str  # "continue" | "revise"
    findings: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    observations: tuple[str, ...] = ()
    seq: int = 0


@dataclass(slots=True)
class ProgressLedger:
    """In-memory task ledger. The caller owns durability (if it wants
    any): this class only enforces transition rules and records history."""

    tasks: dict[str, ProgressTask] = field(default_factory=dict)
    reviews: tuple[PlanReview, ...] = ()
    _seq: int = 0

    def add_task(
        self,
        task_id: str,
        title: str,
        *,
        assignee: str = "",
        depends_on: tuple[str, ...] | list[str] = (),
        objective: str = "",
        status: str = "todo",
    ) -> ProgressTask:
        """Create a task. Dependencies must already exist (no dangling
        edges); a task may not depend on itself."""
        task_id = str(task_id or "").strip()
        if not task_id:
            raise ValueError("task_id must not be empty")
        if task_id in self.tasks:
            raise ValueError(f"duplicate task_id: {task_id!r}")
        if status not in TASK_STATUSES:
            raise ValueError(f"unknown task status: {status!r}")
        deps = tuple(str(d) for d in depends_on)
        if task_id in deps:
            raise ValueError("a task may not depend on itself")
        for dep in deps:
            if dep not in self.tasks:
                raise ValueError(f"unknown dependency: {dep!r}")
        task = ProgressTask(
            task_id=task_id,
            title=str(title or "").strip(),
            status=status,
            assignee=str(assignee or ""),
            depends_on=deps,
            objective=str(objective or ""),
            history=(
                {"seq": self._next_seq(), "from": "", "to": status, "reason": "created"},
            ),
        )
        self.tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> ProgressTask:
        task = self.tasks.get(str(task_id))
        if task is None:
            raise KeyError(f"unknown task_id: {task_id!r}")
        return task

    def list_tasks(self) -> list[ProgressTask]:
        """Tasks in insertion order (creation order, not plan order)."""
        return list(self.tasks.values())

    def set_status(
        self, task_id: str, status: str, *, reason: str = ""
    ) -> ProgressTask:
        """Move a task. Same-status is a no-op (idempotent). Illegal
        transitions (out of ``done``) raise ValueError and change nothing."""
        if status not in TASK_STATUSES:
            raise ValueError(f"unknown task status: {status!r}")
        task = self.get_task(task_id)
        if task.status == status:
            return task
        if status not in _ALLOWED_TRANSITIONS[task.status]:
            raise ValueError(
                f"illegal transition: {task.status} -> {status} "
                f"(task {task_id!r}); done is terminal, "
                "failed retries go through todo/in_progress"
            )
        updated = ProgressTask(
            task_id=task.task_id,
            title=task.title,
            status=status,
            assignee=task.assignee,
            depends_on=task.depends_on,
            objective=task.objective,
            history=task.history
            + (
                {
                    "seq": self._next_seq(),
                    "from": task.status,
                    "to": status,
                    "reason": str(reason or ""),
                },
            ),
        )
        self.tasks[task.task_id] = updated
        return updated

    def record_review(self, review: PlanReview) -> PlanReview:
        """Append a review conclusion. Returns the stored copy (with seq)."""
        stored = PlanReview(
            plan_id=review.plan_id,
            verdict=review.verdict,
            findings=tuple(review.findings),
            recommendations=tuple(review.recommendations),
            observations=tuple(review.observations),
            seq=self._next_seq(),
        )
        self.reviews = self.reviews + (stored,)
        return stored

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq


@dataclass(slots=True)
class ProgressPlan:
    """A plan: an ordered list of ledger task ids.

    Dependencies live on the ledger tasks (``depends_on``); the plan
    only fixes the display/execution order. All ids must exist in the
    ledger at build time.
    """

    plan_id: str
    task_ids: tuple[str, ...] = ()


def build_plan(ledger: ProgressLedger, plan_id: str, task_ids: Any) -> ProgressPlan:
    """Build a plan over existing ledger tasks (duplicates rejected)."""
    ids = tuple(str(t) for t in task_ids)
    if not ids:
        raise ValueError("a plan needs at least one task")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate task in plan")
    for task_id in ids:
        ledger.get_task(task_id)  # KeyError on unknown id
    return ProgressPlan(plan_id=str(plan_id or "").strip() or "plan-1", task_ids=ids)


def plan_order(ledger: ProgressLedger, plan: ProgressPlan) -> list[str]:
    """Plan tasks in execution order: dependencies first, stable by plan
    order among tasks that are free to run. Raises ValueError on a
    dependency cycle (should be unreachable -- add_task rejects
    self-deps and dangling deps, but a cycle can still be built by
    adding tasks in an order that closes a loop, so check here)."""
    remaining = list(plan.task_ids)
    done: set[str] = set()
    ordered: list[str] = []
    while remaining:
        progressed = False
        for task_id in list(remaining):
            deps = [
                d for d in ledger.get_task(task_id).depends_on if d in plan.task_ids
            ]
            if all(d in done for d in deps):
                ordered.append(task_id)
                done.add(task_id)
                remaining.remove(task_id)
                progressed = True
        if not progressed:
            raise ValueError(
                f"dependency cycle in plan {plan.plan_id!r}: "
                f"unresolved {remaining}"
            )
    return ordered


def ready_tasks(ledger: ProgressLedger, plan: ProgressPlan) -> list[ProgressTask]:
    """Todo tasks whose dependencies are all done, in plan order."""
    ready: list[ProgressTask] = []
    for task_id in plan_order(ledger, plan):
        task = ledger.get_task(task_id)
        if task.status != "todo":
            continue
        if all(
            ledger.get_task(dep).status == "done"
            for dep in task.depends_on
            if dep in plan.task_ids
        ):
            ready.append(task)
    return ready


def review_plan(
    ledger: ProgressLedger,
    plan: ProgressPlan,
    *,
    observations: Mapping[str, str] | None = None,
    stalled: Any = (),
) -> PlanReview:
    """Run one plan review and record its conclusion in the ledger.

    Deterministic, rule-based (no model call): the review looks at
    ledger truth only.

    - Any failed task -> verdict "revise", one finding + one
      recommendation per failed task (retry the task; its dependents
      stay blocked until the retry lands).
    - Any stalled in_progress task (caller reports ``stalled`` ids --
      the caller owns stall detection, e.g. worker_stalled) ->
      verdict "revise", one finding per stalled task.
    - Otherwise -> verdict "continue", no recommendations.
    ``observations`` (task_id -> note) are stored on the review for
    context; they never flip the verdict on their own -- a note is not
    evidence of drift, a failed/stalled task is.

    The review changes no task state: revision is the caller's decision
    (retry via set_status, re-plan, or escalate). The conclusion is
    recorded in ledger.reviews and also renderable as a journal message
    via review_journal().
    """
    stalled_ids = {str(t) for t in (stalled or ())}
    findings: list[str] = []
    recommendations: list[str] = []
    for task_id in plan.task_ids:
        task = ledger.get_task(task_id)
        if task.status == "failed":
            findings.append(f"任务 {task_id}（{task.title}）失败")
            recommendations.append(
                f"重试任务 {task_id}：先定位失败原因，再经 set_status "
                "failed -> todo 重新排队；其依赖项在重试完成前保持阻塞"
            )
        if task_id in stalled_ids and task.status == "in_progress":
            findings.append(f"任务 {task_id}（{task.title}）进行中但无进展")
            recommendations.append(
                f"检查任务 {task_id} 是否停滞：确认执行者仍在推进，"
                "否则升级给用户拍板"
            )
    obs = tuple(
        f"{task_id}: {note.strip()}"
        for task_id, note in (observations or {}).items()
        if str(note or "").strip()
    )
    verdict = "revise" if findings else "continue"
    if verdict == "continue":
        findings = ("计划无失败/停滞任务，继续按计划执行",)
    review = PlanReview(
        plan_id=plan.plan_id,
        verdict=verdict,
        findings=tuple(findings),
        recommendations=tuple(recommendations),
        observations=obs,
    )
    return ledger.record_review(review)


def review_journal(team_id: str, review: PlanReview) -> dict[str, Any]:
    """Render a review conclusion as a journal ``decision`` message, so
    the existing team timeline (build_team_timeline) shows it with no
    timeline rewrite. The structured fields carry the verdict; the text
    is the human-readable summary."""
    if review.verdict == "revise":
        text = (
            f"计划评审：计划 {review.plan_id} 需修订 "
            f"（{len(review.findings)} 个发现）"
        )
    else:
        text = f"计划评审：计划 {review.plan_id} 继续执行，无需修订"
    message = journal_message(team_id, "coordinator", text, kind="decision")
    message["detail"].update(
        {
            "plan_id": review.plan_id,
            "review_verdict": review.verdict,
            "review_findings": list(review.findings),
            "review_recommendations": list(review.recommendations),
            "review_seq": review.seq,
        }
    )
    return message


@dataclass(slots=True)
class TeamCoordinator:
    """Turns Work truth into team decisions. Stateless between steps."""

    team: ProjectTeam
    root_work_item_id: str
    stall_timeout_seconds: float = 1800.0

    def step(
        self,
        ledger: TeamLedger,
        runs: Mapping[str, Any] | None = None,
        id_map: Mapping[str, str] | None = None,
        progress_ledger: ProgressLedger | None = None,
    ) -> list[CoordinatorDecision]:
        """Compute the next decisions for the team, in plan order.

        ``id_map`` translates plan item ids to real WorkItem ids when the
        ledger owns identity (``create_child_item`` generates its own ids).
        When omitted, plan item ids are used directly (synthetic ledgers).
        ``runs`` is keyed by the same ids the items are looked up with.

        AF-3: when ``progress_ledger`` is given, dispatch/complete
        decisions are mirrored into it (dispatch -> in_progress,
        complete -> done) keyed by work_item_id. Mirroring never changes
        the decisions, never raises (unknown ids are skipped), and is
        off entirely when the ledger is None -- existing callers see
        zero behavior change.
        """
        runs = runs or {}
        thread_id = self.team.work_thread_id or ""
        items = {item.work_item_id: item for item in ledger.list_work_items(thread_id)}
        decisions: list[CoordinatorDecision] = []
        all_completed = True

        for plan_item in self.team.plan:
            lookup_id = (
                id_map.get(plan_item.item_id, plan_item.item_id)
                if id_map
                else plan_item.item_id
            )
            item = items.get(lookup_id)
            if item is None:
                decisions.append(
                    self._journaled(
                        "wait", plan_item.item_id,
                        f"plan item {plan_item.item_id} not yet created in Work",
                        kind="note",
                    )
                )
                all_completed = False
                continue
            if item.status == "completed":
                continue
            all_completed = False

            readiness = ledger.dependency_readiness(item.work_item_id)
            run = runs.get(item.work_item_id)

            if item.status == "blocked":
                decisions.append(self._escalate(item, "WorkItem is blocked"))
                continue
            if run is not None and worker_stalled(
                run, timeout_seconds=self.stall_timeout_seconds
            ):
                decisions.append(
                    self._escalate(item, "worker run stalled (no progress)")
                )
                continue
            if (
                run is not None
                and run.claimed_completion
                and run.verification_status == "pending"
            ):
                decisions.append(self._verify(item, plan_item))
                continue
            if run is not None and run.verification_status == "verified":
                decisions.append(self._complete(item))
                continue
            if not readiness.ready:
                decisions.append(
                    CoordinatorDecision(
                        action="wait",
                        work_item_id=item.work_item_id,
                        reason="waiting on: " + ", ".join(readiness.waiting_on),
                        journal=journal_message(
                            self.team.team_id,
                            "coordinator",
                            f"{item.title} 等待依赖: "
                            + ", ".join(readiness.waiting_on),
                            kind="note",
                        ),
                    )
                )
                continue
            if run is None and item.status in ("proposed", "ready", "running"):
                # "running" with no WorkerRun means created but never given
                # to an executor -- the real ledger creates plan children as
                # "running", so this is the normal first-dispatch case.
                decisions.append(self._dispatch(item, plan_item))
                continue
            # Running but healthy, or an unexpected state: leave it alone.
            decisions.append(
                CoordinatorDecision(
                    action="wait",
                    work_item_id=item.work_item_id,
                    reason=f"no action (status={item.status})",
                )
            )

        if all_completed:
            decisions.append(
                CoordinatorDecision(
                    action="team_complete",
                    reason=f"team {self.team.team_id} finished all plan items",
                    journal=journal_message(
                        self.team.team_id,
                        "coordinator",
                        f"团队 {self.team.team_id} 全部任务完成，等待解散指令。",
                        kind="decision",
                    ),
                )
            )
        if progress_ledger is not None:
            self._mirror_to_progress(progress_ledger, decisions)
        return decisions

    @staticmethod
    def _mirror_to_progress(
        progress_ledger: ProgressLedger, decisions: list[CoordinatorDecision]
    ) -> None:
        """Mirror dispatch/complete into the progress ledger. Best-effort
        by design: a decision for a work item the ledger does not track
        is skipped, and an illegal transition (e.g. complete on a task
        never dispatched) is skipped -- the ledger is an observer, never
        a second decider."""
        for decision in decisions:
            if decision.work_item_id is None:
                continue
            if decision.action == "dispatch":
                target = "in_progress"
            elif decision.action == "complete":
                target = "done"
            else:
                continue
            try:
                task = progress_ledger.tasks.get(decision.work_item_id)
                if task is None or task.status == target:
                    continue
                progress_ledger.set_status(
                    decision.work_item_id, target, reason=f"coordinator:{decision.action}"
                )
            except (KeyError, ValueError):
                continue

    def _dispatch(self, item: Any, plan_item: Any) -> CoordinatorDecision:
        specialist = self.team.member(plan_item.assignee)
        context = {
            "root_goal_summary": self.team.project_title,
            "work_item_objective": plan_item.objective,
            "acceptance_criteria": tuple(plan_item.acceptance_criteria),
            "specialist_name": plan_item.assignee,
            # File workspaces are the source of truth: re-read on every
            # dispatch so a SOUL.md edit takes effect next dispatch.
            "specialist_prompt": specialist_prompt_for(self.team, specialist)
            if specialist
            else "",
            "memory_namespace": specialist.memory_namespace if specialist else "",
            # Stable action key for the CP-4 approval-rejection guard:
            # the runner refuses to execute an action the approval layer
            # already rejected, even if it arrives through another path.
            "action_key": f"dispatch:{item.work_item_id}",
        }
        handoff = journal_message(
            self.team.team_id,
            "coordinator",
            f"派活：{item.title} → {plan_item.assignee}",
            kind="handoff",
        )
        # The timeline renders handoffs from these structured fields
        # (from -> to, what, objective), not by re-parsing the text.
        handoff["detail"].update(
            {
                "from_author": "coordinator",
                "to_author": plan_item.assignee,
                "item_title": item.title,
                "objective": plan_item.objective,
            }
        )
        return CoordinatorDecision(
            action="dispatch",
            work_item_id=item.work_item_id,
            specialist_name=plan_item.assignee,
            reason=f"ready; dispatch to {plan_item.assignee}",
            context=context,
            journal=handoff,
        )

    def _verify(self, item: Any, plan_item: Any) -> CoordinatorDecision:
        journal = journal_message(
            self.team.team_id,
            "coordinator",
            f"验收：{item.title} 已 claimed 完成，待按验收标准验证",
            kind="progress",
        )
        journal["detail"].update({"item_title": item.title})
        return CoordinatorDecision(
            action="verify",
            work_item_id=item.work_item_id,
            specialist_name=plan_item.assignee,
            reason="run claimed completion; verification required",
            context={"acceptance_criteria": tuple(plan_item.acceptance_criteria)},
            journal=journal,
        )

    def _complete(self, item: Any) -> CoordinatorDecision:
        journal = journal_message(
            self.team.team_id,
            "coordinator",
            f"完成：{item.title} 验收通过",
            kind="progress",
        )
        journal["detail"].update({"item_title": item.title})
        return CoordinatorDecision(
            action="complete",
            work_item_id=item.work_item_id,
            reason="verification passed",
            journal=journal,
            context={"action_key": f"complete:{item.work_item_id}"},
        )

    def _escalate(self, item: Any, reason: str) -> CoordinatorDecision:
        return CoordinatorDecision(
            action="escalate",
            work_item_id=item.work_item_id,
            reason=reason,
            journal=journal_message(
                self.team.team_id,
                "coordinator",
                f"升级：{item.title} 卡住了（{reason}），需要用户拍板",
                kind="blocker",
            ),
        )

    def _journaled(
        self, action: str, work_item_id: str, reason: str, *, kind: str
    ) -> CoordinatorDecision:
        return CoordinatorDecision(
            action=action,
            work_item_id=work_item_id,
            reason=reason,
            journal=journal_message(
                self.team.team_id, "coordinator", reason, kind=kind  # type: ignore[arg-type]
            ),
        )
