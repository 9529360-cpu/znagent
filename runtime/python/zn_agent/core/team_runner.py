"""Project teams slice 4: the resident-side runner that closes the loop.

Slices 1-3 built the parts (team model, coordinator decisions, scoped
memory + retrospective). This module is the *active caller*: it applies
``TeamCoordinator`` decisions against the real Work ledger so a team
actually runs end to end::

    assemble_team -> ensure_plan_items -> coordinator.step -> apply
        -> verify (fresh observation) -> complete -> retrospective

The coordinator stays pure (decisions only). Every side effect lives
here, executed by the resident under Work authority -- no second control
plane, no new identity, no workflow framework.

Verification is deliberately pluggable: checking "did the work really
happen" needs fresh observation (Body, browser, terminal...), which only
the resident can do. The runner never fakes it -- it calls the injected
``Verifier`` and records the outcome via ``record_worker_verification``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .evidence_bound_work import WorkerRun
from .project_team import ProjectTeam, team_journal_role_prefix
from .steerable_work import WorkItem
from .team_coordinator import TeamCoordinator
from .team_memory import (
    distill_retrospective,
    save_retrospective,
    team_shared_memory,
)


@dataclass(slots=True)
class VerificationOutcome:
    """Result of checking a claimed completion with fresh observation."""

    passed: bool
    notes: str = ""
    artifact_refs: tuple[dict[str, Any], ...] = ()


class Verifier(Protocol):
    """Pluggable fresh-observation check. Implemented by the resident."""

    def verify(self, *, item: WorkItem, run: WorkerRun) -> VerificationOutcome:
        ...


@dataclass(slots=True)
class Escalation:
    """Something the coordinator escalated -- needs the user's judgment."""

    work_item_id: str
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TeamStepResult:
    """What one runner step did."""

    actions: list[str] = field(default_factory=list)
    escalations: list[Escalation] = field(default_factory=list)
    team_complete: bool = False
    retrospective_summary: str | None = None


class TeamRunner:
    """Applies coordinator decisions to the real Work ledger.

    ``ledger`` is the resident's ``EvidenceBoundSteerableWorkLedger``
    (duck-typed in tests). ``memory`` is the resident's
    ``StructuredMemory``. ``root_work_item_id`` is the project Root
    WorkItem the resident created when the user asked for the team.
    """

    PLAN_MAP_KEY = "plan_item_map"

    def __init__(
        self,
        *,
        team: ProjectTeam,
        ledger: Any,
        memory: Any,
        verifier: Verifier,
        root_work_item_id: str,
        tool_scope: tuple[str, ...] = ("terminal",),
        authority_scope: tuple[str, ...] | None = None,
    ):
        if not root_work_item_id or not str(root_work_item_id).strip():
            raise ValueError("root_work_item_id must not be empty")
        self._team = team
        self._ledger = ledger
        self._memory = memory
        self._verifier = verifier
        self._root_id = str(root_work_item_id).strip()
        self._tool_scope = tuple(tool_scope)
        thread_id = team.work_thread_id or ""
        self._authority_scope = (
            tuple(authority_scope)
            if authority_scope is not None
            else (f"work:{thread_id}",)
        )
        self._coordinator = TeamCoordinator(
            team=team, root_work_item_id=self._root_id
        )

    @property
    def team(self) -> ProjectTeam:
        return self._team

    # -- plan materialization -------------------------------------------

    def _topological_order(self) -> list[Any]:
        """Plan items with dependencies first (Kahn's algorithm)."""
        plan = list(self._team.plan)
        by_id = {p.item_id: p for p in plan}
        depth: dict[str, int] = {}

        def visit(pid: str, seen: tuple[str, ...]) -> int:
            if pid in depth:
                return depth[pid]
            if pid in seen:
                raise ValueError(f"cyclic team plan at {pid!r}")
            item = by_id.get(pid)
            if item is None:
                depth[pid] = 0
                return 0
            d = 0
            for dep in item.dependency_ids:
                d = max(d, visit(dep, seen + (pid,)) + 1)
            depth[pid] = d
            return d

        for p in plan:
            visit(p.item_id, ())
        return sorted(plan, key=lambda p: depth[p.item_id])

    def ensure_plan_items(self) -> dict[str, str]:
        """Create missing plan WorkItems under the Root, dependencies first.

        Returns the durable plan_item_id -> work_item_id mapping, also
        persisted in team shared memory so a restart resumes instead of
        duplicating items.
        """
        thread_id = self._team.work_thread_id or ""
        shared = team_shared_memory(self._memory, self._team.team_id)
        match = shared.recall(self.PLAN_MAP_KEY)
        id_map: dict[str, str] = dict(match.value) if match else {}
        items = {
            item.work_item_id: item
            for item in self._ledger.list_work_items(thread_id)
        }
        current_version = self._ledger.plan_version(thread_id)
        changed = False
        for plan_item in self._topological_order():
            wid = id_map.get(plan_item.item_id)
            item = items.get(wid) if wid else None
            if (
                item is not None
                and item.plan_version == current_version
                and item.parent_work_item_id == self._root_id
            ):
                continue
            dep_ids = [id_map[d] for d in plan_item.dependency_ids]
            child = self._ledger.create_child_item(
                root_work_item_id=self._root_id,
                objective=plan_item.objective,
                title=plan_item.title,
                acceptance_criteria=list(plan_item.acceptance_criteria),
                dependency_ids=dep_ids,
            )
            id_map[plan_item.item_id] = child.work_item_id
            items[child.work_item_id] = child
            changed = True
        if changed or match is None:
            shared.remember(self.PLAN_MAP_KEY, id_map)
        return id_map

    # -- the loop ---------------------------------------------------------

    def step(self) -> TeamStepResult:
        """One full loop: ensure items, coordinate, apply. Returns a report."""
        thread_id = self._team.work_thread_id or ""
        id_map = self.ensure_plan_items()
        items = {
            item.work_item_id: item
            for item in self._ledger.list_work_items(thread_id)
        }
        runs: dict[str, WorkerRun] = {}
        for wid in id_map.values():
            history = self._ledger.list_worker_runs(work_item_id=wid, limit=50)
            if history:
                runs[wid] = history[-1]  # ASC by started_at: latest last
        decisions = self._coordinator.step(
            self._ledger, runs=runs, id_map=id_map
        )
        result = TeamStepResult()
        for decision in decisions:
            self._apply(decision, items, runs, result)
        return result

    # -- decision application -------------------------------------------------

    def _journal(self, payload: dict[str, Any] | None) -> None:
        if not payload:
            return
        thread_id = self._team.work_thread_id or ""
        self._ledger.append_message(
            thread_id,
            role=str(payload.get("role") or ""),
            text=str(payload.get("text") or ""),
            detail=dict(payload.get("detail") or {}),
        )

    def _apply(
        self,
        decision: Any,
        items: dict[str, WorkItem],
        runs: dict[str, WorkerRun],
        result: TeamStepResult,
    ) -> None:
        action = decision.action
        wid = decision.work_item_id or ""
        if action == "dispatch":
            run = self._ledger.start_worker_run(
                work_item_id=wid,
                executor_kind="team-specialist",
                tool_scope=self._tool_scope,
                authority_scope=self._authority_scope,
            )
            runs[wid] = run
            self._journal(decision.journal)
            result.actions.append(f"dispatched:{wid}")
        elif action == "verify":
            run = runs.get(wid)
            item = items.get(wid)
            if run is None or item is None:
                return
            outcome = self._verifier.verify(item=item, run=run)
            self._ledger.record_worker_verification(
                run.worker_run_id,
                verification_status="verified" if outcome.passed else "failed",
                artifact_refs=[dict(r) for r in outcome.artifact_refs],
            )
            self._journal(
                {
                    "role": f"team:{self._team.team_id}:coordinator",
                    "text": (
                        f"验收{'通过' if outcome.passed else '未通过'}："
                        f"{item.title}——{outcome.notes}"
                    ),
                    "detail": {
                        "kind": "decision",
                        "team_id": self._team.team_id,
                        "author": "coordinator",
                    },
                }
            )
            result.actions.append(
                f"verified:{wid}:{'pass' if outcome.passed else 'fail'}"
            )
        elif action == "complete":
            run = runs.get(wid)
            summary = ""
            if run is not None and run.result_summary:
                summary = run.result_summary
            self._ledger.complete_child_item(wid, result=summary or "verified")
            self._journal(decision.journal)
            result.actions.append(f"completed:{wid}")
        elif action == "escalate":
            self._journal(decision.journal)
            result.escalations.append(
                Escalation(
                    work_item_id=wid,
                    reason=decision.reason,
                    detail=dict(decision.context or {}),
                )
            )
            result.actions.append(f"escalated:{wid}")
        elif action == "team_complete":
            self._journal(decision.journal)
            summary = self._retrospective()
            result.team_complete = True
            result.retrospective_summary = summary
            result.actions.append("team_complete")
        # "wait": deliberately no journal -- waiting is the steady state,
        # not an event worth spamming the shared log with.

    def _retrospective(self) -> str:
        """Distill the project journal into saved team experience.

        Never auto-disbands: the retrospective is a report; the user still
        says when the team goes away.
        """
        thread_id = self._team.work_thread_id or ""
        team_id = self._team.team_id
        prefix = team_journal_role_prefix(team_id)
        entries: list[dict[str, Any]] = []
        for msg in self._ledger.list_messages(thread_id, limit=500):
            if not str(msg.role).startswith(prefix):
                continue
            entries.append(
                {"role": msg.role, "text": msg.text, "detail": dict(msg.detail)}
            )
        retro = distill_retrospective(team_id, entries)
        shared = team_shared_memory(self._memory, team_id)
        save_retrospective(shared, retro)
        return retro.summary()


__all__ = [
    "Escalation",
    "TeamRunner",
    "TeamStepResult",
    "VerificationOutcome",
    "Verifier",
]
