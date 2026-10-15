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
from datetime import datetime, timezone
from typing import Any, Protocol

from .evidence_bound_work import WorkerRun
from .project_team import ProjectTeam, journal_message, team_journal_role_prefix
from .steerable_work import WorkItem
from .team_coordinator import TeamCoordinator
from .team_memory import (
    distill_retrospective,
    save_retrospective,
    team_shared_memory,
)
from .team_termination import (
    TerminationLimits,
    TerminationResult,
    TerminationState,
    evaluate_termination,
    load_termination_state,
    record_token_usage,
    record_tool_call,
    request_stop,
    save_termination_state,
    take_stop,
)
from .team_timeline import evidence_from_refs
from .failure_policy import FailurePolicy


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

    # CP-4: a round-level hard stop (e.g. rate limit) ended this round
    # early; ``blocked_report`` carries tried paths + blocking reason +
    # what the user must do. ``needs_user`` means some item escalated as
    # blocked and needs a user decision.
    hard_stopped: bool = False
    needs_user: bool = False
    blocked_report: dict[str, Any] | None = None
    actions: list[str] = field(default_factory=list)
    escalations: list[Escalation] = field(default_factory=list)
    team_complete: bool = False
    retrospective_summary: str | None = None
    # Hard termination (CP-1): when True, this step dispatched, verified,
    # and completed nothing -- the team is stopped with ``stop_reason``.
    stopped: bool = False
    stop_reason: str | None = None
    stop_trigger: dict[str, Any] = field(default_factory=dict)
    stop_progress: dict[str, Any] = field(default_factory=dict)


# -- workflow edge vocabulary (AF-2) ---------------------------------------
#
# A small descriptive vocabulary for team routing. These edges describe --
# never execute -- how work flows: the runner/coordinator still own the
# actual dispatch/verify/complete behavior. Descriptions stay honest by
# construction: ``describe_team_route`` is derived from the team's real
# plan (dependency edges + verdict switch), not hand-written prose.


@dataclass(frozen=True, slots=True)
class FanOut:
    """One step fans out to N parallel branches (all start together)."""

    from_step: str
    to_steps: tuple[str, ...] = ()
    condition: str = ""

    def validate(self) -> None:
        if not str(self.from_step or "").strip():
            raise ValueError("FanOut.from_step must not be empty")
        if not self.to_steps:
            raise ValueError("FanOut.to_steps must not be empty")
        if len(set(self.to_steps)) != len(self.to_steps):
            raise ValueError(f"FanOut has duplicate targets: {self.to_steps!r}")
        if self.from_step in self.to_steps:
            raise ValueError("FanOut.from_step must not fan out to itself")
        for step in self.to_steps:
            if not str(step or "").strip():
                raise ValueError("FanOut.to_steps must not contain empty steps")


@dataclass(frozen=True, slots=True)
class FanIn:
    """N branches join into one step.

    ``require_all=True`` means every branch must finish first (the team
    completion join); ``False`` means any one branch continuing is enough
    (e.g. either roll-forward or investigation leads to the next pulse).
    """

    from_steps: tuple[str, ...] = ()
    to_step: str = ""
    require_all: bool = True

    def validate(self) -> None:
        if not str(self.to_step or "").strip():
            raise ValueError("FanIn.to_step must not be empty")
        if not self.from_steps:
            raise ValueError("FanIn.from_steps must not be empty")
        if len(set(self.from_steps)) != len(self.from_steps):
            raise ValueError(f"FanIn has duplicate sources: {self.from_steps!r}")
        if self.to_step in self.from_steps:
            raise ValueError("FanIn.to_step must not join from itself")
        for step in self.from_steps:
            if not str(step or "").strip():
                raise ValueError("FanIn.from_steps must not contain empty steps")


@dataclass(frozen=True, slots=True)
class SwitchCase:
    """Branch on one key: the first matching label wins, else ``default``."""

    on: str
    cases: tuple[tuple[str, str], ...] = ()
    default: str = ""

    def validate(self) -> None:
        if not str(self.on or "").strip():
            raise ValueError("SwitchCase.on must not be empty")
        if not self.cases:
            raise ValueError("SwitchCase.cases must not be empty")
        labels = [label for label, _ in self.cases]
        if len(set(labels)) != len(labels):
            raise ValueError(f"SwitchCase has duplicate labels: {labels!r}")
        for label, target in self.cases:
            if not str(label or "").strip():
                raise ValueError("SwitchCase.cases must not contain empty labels")
            if not str(target or "").strip():
                raise ValueError("SwitchCase.cases must not contain empty targets")


WorkflowEdge = FanOut | FanIn | SwitchCase


@dataclass(frozen=True, slots=True)
class WorkflowRoute:
    """A named, validated list of routing edges describing one workflow."""

    name: str
    edges: tuple[WorkflowEdge, ...] = ()

    def validate(self) -> None:
        if not str(self.name or "").strip():
            raise ValueError("WorkflowRoute.name must not be empty")
        for edge in self.edges:
            edge.validate()

    def describe(self) -> str:
        """Deterministic one-line-per-edge rendering, for logs and PRs."""
        lines = [f"route {self.name} ({len(self.edges)} edges)"]
        for edge in self.edges:
            if isinstance(edge, FanOut):
                joined = ", ".join(edge.to_steps)
                cond = f" [{edge.condition}]" if edge.condition else ""
                lines.append(f"fan_out {edge.from_step} -> {joined}{cond}")
            elif isinstance(edge, FanIn):
                joined = ", ".join(edge.from_steps)
                mode = "require_all" if edge.require_all else "require_any"
                lines.append(f"fan_in {joined} -> {edge.to_step} [{mode}]")
            elif isinstance(edge, SwitchCase):
                joined = "; ".join(f"{label} -> {target}" for label, target in edge.cases)
                default = f"; default -> {edge.default}" if edge.default else ""
                lines.append(f"switch {edge.on}: {joined}{default}")
        return "\n".join(lines)


def describe_team_route(team: ProjectTeam) -> WorkflowRoute:
    """Describe a team's real routing from its plan.

    - FanOut: the plan fans out to every dependency-free item.
    - FanIn: each item with dependencies joins after all of them.
    - SwitchCase: the completion verdict routes to complete / retry /
      escalate (the CP-3 verdict the owner and verifier both apply).
    - FanIn: all plan items join into team completion.
    """
    edges: list[WorkflowEdge] = []
    ready = tuple(
        item.item_id for item in team.plan if not item.dependency_ids
    )
    if ready:
        edges.append(FanOut(from_step="plan", to_steps=ready))
    for item in team.plan:
        if item.dependency_ids:
            edges.append(
                FanIn(
                    from_steps=tuple(item.dependency_ids),
                    to_step=item.item_id,
                    require_all=True,
                )
            )
    edges.append(
        SwitchCase(
            on="completion_verdict",
            cases=(
                ("verified", "complete"),
                ("partial", "retry"),
                ("rejected", "escalate"),
            ),
            default="retry",
        )
    )
    if team.plan:
        edges.append(
            FanIn(
                from_steps=tuple(item.item_id for item in team.plan),
                to_step="team_complete",
                require_all=True,
            )
        )
    route = WorkflowRoute(name=f"team:{team.team_id}", edges=tuple(edges))
    route.validate()
    return route


# -- checkpoints (AF-2) ---------------------------------------------------
#
# The pulse-boundary resume protocol. A checkpoint is a durable snapshot of
# which plan steps are done; a runner interrupted mid-team loads the latest
# checkpoint and resumes from the pending steps instead of re-running the
# completed ones. This is the *protocol shape only*: correctness invariants
# (two-phase writes, "checkpoint not older than parent chain") land in LG-1
# on top of this protocol -- this module deliberately does not change the
# overwrite-recovery completion semantics.


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """One durable pulse-boundary snapshot for a team.

    Step ids are plan item ids (stable across restarts, unlike WorkItem
    ids minted per materialization). ``state`` carries small JSON-safe
    extras (plan map, stop reason); the completed/pending lists are the
    resume contract, not ``state``.
    """

    checkpoint_id: str
    team_id: str
    pulse: int
    completed_step_ids: tuple[str, ...] = ()
    pending_step_ids: tuple[str, ...] = ()
    state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "team_id": self.team_id,
            "pulse": int(self.pulse),
            "completed_step_ids": list(self.completed_step_ids),
            "pending_step_ids": list(self.pending_step_ids),
            "state": dict(self.state),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Checkpoint:
        if not isinstance(raw, dict):
            raise ValueError("checkpoint must be a dict")
        checkpoint_id = str(raw.get("checkpoint_id") or "").strip()
        team_id = str(raw.get("team_id") or "").strip()
        if not checkpoint_id or not team_id:
            raise ValueError("checkpoint needs checkpoint_id and team_id")
        return cls(
            checkpoint_id=checkpoint_id,
            team_id=team_id,
            pulse=max(0, int(raw.get("pulse") or 0)),
            completed_step_ids=tuple(
                str(s) for s in (raw.get("completed_step_ids") or ())
            ),
            pending_step_ids=tuple(
                str(s) for s in (raw.get("pending_step_ids") or ())
            ),
            state=dict(raw.get("state") or {}),
        )


class CheckpointStorage(Protocol):
    """Save / load / delete for checkpoints. Implementations own durability."""

    def save(self, checkpoint: Checkpoint) -> None:
        ...

    def load(
        self, *, team_id: str, checkpoint_id: str
    ) -> Checkpoint | None:
        ...

    def latest(self, *, team_id: str) -> Checkpoint | None:
        ...

    def delete(self, *, team_id: str, checkpoint_id: str) -> bool:
        ...

    def list_ids(self, *, team_id: str) -> list[str]:
        ...


class InMemoryCheckpointStorage:
    """In-memory CheckpointStorage: the protocol reference + test double.

    Keeps every saved checkpoint per team in insertion order; ``latest``
    is the highest pulse (ties keep the earliest saved). Production
    durability (SQLite / file) is a later storage backend behind the same
    protocol, not a change to the callers.
    """

    def __init__(self) -> None:
        self._by_team: dict[str, dict[str, Checkpoint]] = {}

    def save(self, checkpoint: Checkpoint) -> None:
        if not checkpoint.team_id or not checkpoint.checkpoint_id:
            raise ValueError("checkpoint needs team_id and checkpoint_id")
        self._by_team.setdefault(checkpoint.team_id, {})[
            checkpoint.checkpoint_id
        ] = checkpoint

    def load(
        self, *, team_id: str, checkpoint_id: str
    ) -> Checkpoint | None:
        return self._by_team.get(team_id, {}).get(checkpoint_id)

    def latest(self, *, team_id: str) -> Checkpoint | None:
        entries = self._by_team.get(team_id, {})
        if not entries:
            return None
        best: Checkpoint | None = None
        for checkpoint in entries.values():
            if best is None or checkpoint.pulse > best.pulse:
                best = checkpoint
        return best

    def delete(self, *, team_id: str, checkpoint_id: str) -> bool:
        entries = self._by_team.get(team_id)
        if entries is None or checkpoint_id not in entries:
            return False
        del entries[checkpoint_id]
        return True

    def list_ids(self, *, team_id: str) -> list[str]:
        return list(self._by_team.get(team_id, {}).keys())


def pending_steps(
    checkpoint: Checkpoint, step_ids: list[str] | tuple[str, ...]
) -> list[str]:
    """Steps not yet completed at the checkpoint, in plan order.

    The resume contract: a restarted runner runs exactly these -- never
    re-running a completed step, never dropping a pending one.
    """
    completed = set(checkpoint.completed_step_ids)
    return [step for step in step_ids if step not in completed]


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
        failure_policy: FailurePolicy | None = None,
        team: ProjectTeam,
        ledger: Any,
        memory: Any,
        verifier: Verifier,
        root_work_item_id: str,
        tool_scope: tuple[str, ...] = ("terminal",),
        authority_scope: tuple[str, ...] | None = None,
        termination_limits: TerminationLimits | None = None,
        now_fn: Any | None = None,
        checkpoint_storage: CheckpointStorage | None = None,
    ):
        if not root_work_item_id or not str(root_work_item_id).strip():
            raise ValueError("root_work_item_id must not be empty")
        self._team = team
        self._ledger = ledger
        self._memory = memory
        self._verifier = verifier
        self._root_id = str(root_work_item_id).strip()
        self._checkpoint_storage = checkpoint_storage
        self._tool_scope = tuple(tool_scope)
        # CP-4 failure policy. The owner rebuilds this runner every pulse,
        # so rejections + attempt counts are restored from team shared
        # memory (same durable store as the plan map) instead of living
        # only in this instance.
        self._failure_policy = failure_policy or FailurePolicy()
        self._restore_failure_policy_state()
        thread_id = team.work_thread_id or ""
        self._authority_scope = (
            tuple(authority_scope)
            if authority_scope is not None
            else (f"work:{thread_id}",)
        )
        self._coordinator = TeamCoordinator(
            team=team, root_work_item_id=self._root_id
        )
        self._limits = termination_limits or TerminationLimits()
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    @property
    def team(self) -> ProjectTeam:
        return self._team

    @property
    def checkpoint_storage(self) -> CheckpointStorage | None:
        return self._checkpoint_storage

    # -- checkpoints (AF-2) ----------------------------------------------

    def build_checkpoint(self) -> Checkpoint:
        """Snapshot completed vs pending plan steps from the live ledger."""
        shared = team_shared_memory(self._memory, self._team.team_id)
        state = load_termination_state(shared)
        match = shared.recall(self.PLAN_MAP_KEY)
        id_map: dict[str, str] = (
            dict(match.value)
            if match is not None and isinstance(match.value, dict)
            else {}
        )
        thread_id = self._team.work_thread_id or ""
        items = {
            item.work_item_id: item
            for item in self._ledger.list_work_items(thread_id)
        }
        completed: list[str] = []
        for plan_item in self._team.plan:
            item = items.get(id_map.get(plan_item.item_id) or "")
            if item is not None and item.status == "completed":
                completed.append(plan_item.item_id)
        pending = [p.item_id for p in self._team.plan if p.item_id not in completed]
        pulse = max(0, int(state.pulses or 0))
        return Checkpoint(
            checkpoint_id=f"{self._team.team_id}:pulse-{pulse}",
            team_id=self._team.team_id,
            pulse=pulse,
            completed_step_ids=tuple(completed),
            pending_step_ids=tuple(pending),
            state={
                "plan_item_map": dict(id_map),
                "stop_reason": state.stop_reason,
            },
        )

    def save_checkpoint(self) -> Checkpoint | None:
        """Persist the current snapshot. Best-effort: never breaks stepping.

        Returns the saved checkpoint, or None when no storage is wired or
        the save failed (a checkpoint is a resume aid, not a gate).
        """
        if self._checkpoint_storage is None:
            return None
        try:
            checkpoint = self.build_checkpoint()
            self._checkpoint_storage.save(checkpoint)
        except Exception:
            return None
        return checkpoint

    def latest_checkpoint(self) -> Checkpoint | None:
        """Latest checkpoint for this team, or None when none exists."""
        if self._checkpoint_storage is None:
            return None
        try:
            return self._checkpoint_storage.latest(team_id=self._team.team_id)
        except Exception:
            return None

    def pending_step_ids(self, checkpoint: Checkpoint | None = None) -> list[str]:
        """Plan steps still pending at the checkpoint (default: latest).

        A restarted runner resumes exactly these steps -- completed steps
        are never re-run. No checkpoint yet means every step is pending.
        """
        checkpoint = checkpoint if checkpoint is not None else self.latest_checkpoint()
        step_ids = [item.item_id for item in self._team.plan]
        if checkpoint is None:
            return list(step_ids)
        return pending_steps(checkpoint, step_ids)

    # -- hard termination (CP-1) -------------------------------------------

    def termination_state(self) -> TerminationState:
        """Current durable termination counters + stop record, if any."""
        shared = team_shared_memory(self._memory, self._team.team_id)
        return load_termination_state(shared)

    def record_token_usage(self, total_tokens: int) -> TerminationState:
        """Add real provider token usage to the team's running total."""
        shared = team_shared_memory(self._memory, self._team.team_id)
        state = load_termination_state(shared)
        record_token_usage(state, total_tokens)
        save_termination_state(shared, state)
        return state

    def record_tool_call(self) -> TerminationState:
        """Count one executed specialist tool step against the tool cap."""
        shared = team_shared_memory(self._memory, self._team.team_id)
        state = load_termination_state(shared)
        record_tool_call(state)
        save_termination_state(shared, state)
        return state

    def request_stop(self, reason: str, *, detail: str = "") -> TerminationState:
        """Request an external stop (``user_cancel`` | ``error``).

        The stop takes effect on the next :meth:`step` -- no more work is
        dispatched after it. ``converged`` is rejected here: only the CP-3
        structured completion verdict may declare convergence.
        """
        shared = team_shared_memory(self._memory, self._team.team_id)
        state = load_termination_state(shared)
        request_stop(state, reason, detail=detail)
        save_termination_state(shared, state)
        return state

    def _progress_snapshot(
        self, state: TerminationState, *, now: datetime
    ) -> dict[str, Any]:
        """Read-only progress at stop time: counters + plan completion."""
        from .team_termination import elapsed_seconds

        thread_id = self._team.work_thread_id or ""
        shared = team_shared_memory(self._memory, self._team.team_id)
        id_map: dict[str, str] = {}
        match = shared.recall(self.PLAN_MAP_KEY)
        if match is not None and isinstance(match.value, dict):
            id_map = dict(match.value)
        items = {
            item.work_item_id: item
            for item in self._ledger.list_work_items(thread_id)
        }
        completed = sum(
            1
            for wid in id_map.values()
            if items.get(wid) is not None and items[wid].status == "completed"
        )
        live_wid: str | None = None
        for plan_item in self._team.plan:
            wid = id_map.get(plan_item.item_id)
            item = items.get(wid) if wid else None
            if item is None or item.status != "completed":
                live_wid = wid
                break
        return {
            "team_id": self._team.team_id,
            "pulses": max(0, int(state.pulses or 0)),
            "elapsed_seconds": elapsed_seconds(state, now=now),
            "tokens_used": max(0, int(state.tokens_used or 0)),
            "tool_calls": max(0, int(state.tool_calls or 0)),
            "plan_items_total": len(self._team.plan),
            "plan_items_completed": completed,
            "live_work_item_id": live_wid,
        }

    def _take_stop(
        self,
        shared: Any,
        state: TerminationState,
        result: TerminationResult,
        *,
        now: datetime,
    ) -> TeamStepResult:
        """Persist the stop, journal it, and report it. No work dispatched."""
        progress = self._progress_snapshot(state, now=now)
        taken = take_stop(state, result, now=now, progress=progress)
        save_termination_state(shared, state)
        journal = journal_message(
            self._team.team_id,
            "coordinator",
            f"停止：团队 {self._team.team_id} 已停止 "
            f"（STOP_REASON={taken.stop_reason}）。"
            f"触发：{taken.trigger}。"
            f"进展：{progress['plan_items_completed']}/"
            f"{progress['plan_items_total']} 项完成。",
            kind="blocker",
        )
        journal["detail"].update(
            {
                "stop_reason": taken.stop_reason,
                "trigger": dict(taken.trigger),
                "progress": dict(taken.progress),
            }
        )
        self._journal(journal)
        return TeamStepResult(
            stopped=True,
            stop_reason=taken.stop_reason,
            stop_trigger=dict(taken.trigger),
            stop_progress=dict(taken.progress),
        )

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
        """One full loop: terminate-check, ensure items, coordinate, apply.

        Hard termination (CP-1) runs first, every pulse: a team that has
        already stopped reports the stored stop with no side effects, and
        a team hitting a cap (or a requested external stop) stops here --
        before any dispatch, verification, or completion.
        """
        shared = team_shared_memory(self._memory, self._team.team_id)
        state = load_termination_state(shared)
        if state.stop_reason is not None:
            self.save_checkpoint()
            return TeamStepResult(
                stopped=True,
                stop_reason=state.stop_reason,
                stop_trigger=dict(state.trigger or {}),
                stop_progress=dict(state.progress or {}),
            )
        now = self._now_fn()
        if state.started_at is None:
            state.started_at = now.isoformat()
        state.pulses = max(0, int(state.pulses or 0)) + 1
        save_termination_state(shared, state)
        # An externally requested stop (user_cancel / error) wins over caps:
        # the user asked to stop, so no more work is dispatched this pulse.
        if state.requested_stop is not None:
            stopped = self._take_stop(
                shared,
                state,
                TerminationResult(
                    stop_reason=state.requested_stop,
                    trigger={
                        "requested_stop": state.requested_stop,
                        "detail": state.requested_stop_detail,
                    },
                ),
                now=now,
            )
            self.save_checkpoint()
            return stopped
        cap = evaluate_termination(state, self._limits, now=now)
        if cap is not None:
            stopped = self._take_stop(shared, state, cap, now=now)
            self.save_checkpoint()
            return stopped

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
        self.save_checkpoint()
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

    # -- CP-4 durable failure-policy state ------------------------------

    @property
    def failure_policy(self) -> FailurePolicy:
        return self._failure_policy

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


__all__ = [
    "Checkpoint",
    "CheckpointStorage",
    "Escalation",
    "FanIn",
    "FanOut",
    "InMemoryCheckpointStorage",
    "SwitchCase",
    "TeamRunner",
    "TeamStepResult",
    "TerminationLimits",
    "TerminationState",
    "VerificationOutcome",
    "Verifier",
    "WorkflowEdge",
    "WorkflowRoute",
    "describe_team_route",
    "pending_steps",
]
