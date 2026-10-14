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
from .failure_policy import FailurePolicy
from .project_team import ProjectTeam, team_journal_role_prefix
from .steerable_work import WorkItem
from .team_coordinator import TeamCoordinator
from .team_memory import (
    distill_retrospective,
    save_retrospective,
    team_shared_memory,
)
from .team_timeline import evidence_from_refs


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
    # CP-4: a round-level hard stop (e.g. rate limit) ended this round
    # early; ``blocked_report`` carries tried paths + blocking reason +
    # what the user must do. ``needs_user`` means some item escalated as
    # blocked and needs a user decision.
    hard_stopped: bool = False
    needs_user: bool = False
    blocked_report: dict[str, Any] | None = None


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
        failure_policy: FailurePolicy | None = None,
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
        # CP-4 failure policy. The owner rebuilds this runner every pulse,
        # so rejections + attempt counts are restored from team shared
        # memory (same durable store as the plan map) instead of living
        # only in this instance.
        self._failure_policy = failure_policy or FailurePolicy()
        self._restore_failure_policy_state()

    @property
    def team(self) -> ProjectTeam:
        return self._team

    @property
    def failure_policy(self) -> FailurePolicy:
        return self._failure_policy

    # -- CP-4 durable failure-policy state ------------------------------

    _FAILURE_POLICY_STATE_KEY = "failure_policy_state"

    def _restore_failure_policy_state(self) -> None:
        try:
            shared = team_shared_memory(self._memory, self._team.team_id)
            match = shared.recall(self._FAILURE_POLICY_STATE_KEY)
            if match is not None:
                self._failure_policy.restore_state(match.value)
        except Exception:
            # Failure-policy state is best-effort durability: a runner
            # with a memory that cannot recall still enforces the policy
            # in-memory for this round.
            pass

    def _persist_failure_policy_state(self) -> None:
        try:
            shared = team_shared_memory(self._memory, self._team.team_id)
            shared.remember(
                self._FAILURE_POLICY_STATE_KEY,
                self._failure_policy.snapshot_state(),
            )
        except Exception:
            pass

    def record_approval_rejection(self, action_key: str, reason: str = "") -> None:
        """Record an approval-layer rejection (CP-4: never bypass it).

        The approval layer (or the user) calls this when an action is
        rejected; later attempts to execute the same action -- through
        any path -- are blocked by :meth:`_apply` before any side effect.
        """
        self._failure_policy.record_approval_rejection(action_key, reason)
        self._persist_failure_policy_state()

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
            try:
                self._apply(decision, items, runs, result)
            except Exception as exc:
                # CP-4: classified failures are handled by policy (hard
                # stop / escalate / bounded retry next pulse). An
                # unclassified exception is re-raised -- it may be a
                # programmer bug, and swallowing it would hide it.
                if self._handle_apply_failure(exc, decision, result):
                    break
            else:
                # A successful apply resets consecutive-failure counts
                # for the item: retries count consecutive failures only.
                wid = decision.work_item_id or ""
                if wid and decision.action in ("dispatch", "verify", "complete"):
                    if self._failure_policy.note_success(wid):
                        self._persist_failure_policy_state()
        return result

    # -- CP-4 failure handling ---------------------------------------------

    def _handle_apply_failure(
        self,
        exc: BaseException,
        decision: Any,
        result: TeamStepResult,
    ) -> bool:
        """Handle one failed decision application. True = stop this round."""
        policy = self._failure_policy
        classification = policy.classify(exc)
        if classification is None:
            raise exc
        wid = decision.work_item_id or ""
        action = decision.action or ""
        if classification.category == "hard_stop":
            report = policy.build_blocked_report(
                tried_paths=[action] if action else [],
                blocking_reason=classification.reason,
                user_action=classification.user_action,
                partial_progress=list(result.actions),
                failure_kind=classification.kind,
                reconnect_hint=classification.reconnect_hint,
            )
            self._journal(
                {
                    "role": f"team:{self._team.team_id}:coordinator",
                    "text": f"硬停：{classification.reason}",
                    "detail": {
                        "kind": "blocker",
                        "team_id": self._team.team_id,
                        "author": "coordinator",
                        "failure_kind": classification.kind,
                        "blocked_report": report,
                    },
                }
            )
            result.escalations.append(
                Escalation(
                    work_item_id=wid,
                    reason=classification.reason,
                    detail={
                        "hard_stop": True,
                        "failure_kind": classification.kind,
                        "blocked_report": report,
                    },
                )
            )
            if classification.scope == "round":
                # Rate limit / approval bypass: stop the round now -- no
                # further decisions are applied, nothing is retried.
                result.hard_stopped = True
                result.blocked_report = report
                result.actions.append(f"hard_stopped:{classification.kind}")
                return True
            result.needs_user = True
            result.actions.append(f"hard_stopped:{classification.kind}:{wid}")
            return False
        if classification.category == "needs_user":
            report = policy.build_blocked_report(
                tried_paths=[action] if action else [],
                blocking_reason=classification.reason,
                user_action=classification.user_action,
                partial_progress=list(result.actions),
                failure_kind=classification.kind,
                reconnect_hint=classification.reconnect_hint,
            )
            self._journal(
                {
                    "role": f"team:{self._team.team_id}:coordinator",
                    "text": f"需用户处理：{classification.reason}",
                    "detail": {
                        "kind": "blocker",
                        "team_id": self._team.team_id,
                        "author": "coordinator",
                        "failure_kind": classification.kind,
                        "blocked_report": report,
                    },
                }
            )
            result.escalations.append(
                Escalation(
                    work_item_id=wid,
                    reason=classification.reason,
                    detail={
                        "needs_user": True,
                        "failure_kind": classification.kind,
                        "blocked_report": report,
                    },
                )
            )
            result.needs_user = True
            if classification.scope == "round":
                # Auth / billing block every later decision too: stop.
                result.blocked_report = report
                result.actions.append(f"needs_user:{classification.kind}")
                return True
            result.actions.append(f"needs_user:{classification.kind}:{wid}")
            return False
        # retryable / reroute: bounded consecutive attempts; the next
        # pulse retries (same path) or the caller picks the next path.
        # Nothing is retried inside this round -- re-applying a
        # side-effecting decision in the same step could duplicate it.
        count = policy.record_attempt(wid, classification.kind)
        self._persist_failure_policy_state()
        if policy.attempts_exhausted(wid, classification.kind):
            report = policy.build_blocked_report(
                tried_paths=[f"{action} x{count}"] if action else [],
                blocking_reason=(
                    f"{classification.reason}（连续失败 {count} 次，已耗尽有界尝试）"
                ),
                user_action="确认后手动重试，或调整任务后重新下达",
                partial_progress=list(result.actions),
                failure_kind=classification.kind,
            )
            self._journal(
                {
                    "role": f"team:{self._team.team_id}:coordinator",
                    "text": f"升级：{classification.reason}，连续失败 {count} 次",
                    "detail": {
                        "kind": "blocker",
                        "team_id": self._team.team_id,
                        "author": "coordinator",
                        "failure_kind": classification.kind,
                        "blocked_report": report,
                    },
                }
            )
            result.escalations.append(
                Escalation(
                    work_item_id=wid,
                    reason=report["blocking_reason"],
                    detail={
                        "needs_user": True,
                        "failure_kind": classification.kind,
                        "blocked_report": report,
                    },
                )
            )
            result.needs_user = True
            result.actions.append(f"failure_exhausted:{classification.kind}:{wid}")
            return False
        self._journal(
            {
                "role": f"team:{self._team.team_id}:coordinator",
                "text": (
                    f"尝试 {action or '执行'} 失败（{classification.kind}，"
                    f"第 {count}/{policy.max_attempts_per_item} 次），"
                    "下一轮重试"
                ),
                "detail": {
                    "kind": "note",
                    "team_id": self._team.team_id,
                    "author": "coordinator",
                    "failure_kind": classification.kind,
                },
            }
        )
        result.actions.append(
            f"failed:{classification.kind}:{wid}:attempt_{count}"
        )
        return False

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
        if action in ("dispatch", "complete"):
            # CP-4: an approval-rejected action must never execute through
            # another path. Checked before any side effect.
            context = decision.context or {}
            action_key = context.get("action_key")
            if action_key:
                self._failure_policy.require_not_rejected(str(action_key))
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
            # The verification journal is the timeline's evidence source:
            # artifact refs travel with the decision so the timeline can
            # render evidence links without a second ledger lookup.
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
                        "item_title": item.title,
                        "evidence": evidence_from_refs(outcome.artifact_refs),
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
