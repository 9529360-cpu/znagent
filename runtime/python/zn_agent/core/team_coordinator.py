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
    ) -> list[CoordinatorDecision]:
        """Compute the next decisions for the team, in plan order.

        ``id_map`` translates plan item ids to real WorkItem ids when the
        ledger owns identity (``create_child_item`` generates its own ids).
        When omitted, plan item ids are used directly (synthetic ledgers).
        ``runs`` is keyed by the same ids the items are looked up with.
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
        return decisions

    def _dispatch(self, item: Any, plan_item: Any) -> CoordinatorDecision:
        specialist = self.team.member(plan_item.assignee)
        context = {
            "root_goal_summary": self.team.project_title,
            "work_item_objective": plan_item.objective,
            "acceptance_criteria": tuple(plan_item.acceptance_criteria),
            "specialist_name": plan_item.assignee,
            "specialist_prompt": specialist.prompt_fragment if specialist else "",
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
