from __future__ import annotations

"""Resident-side owner for project-team Work, mirroring VeteranEngineeringWorkOwner.

The seam: ``work_start`` tags a team request into the event payload
(``team_request``). On every resident pulse for that event, the team layer
calls :meth:`TeamWorkOwner.advance` once -- one durable ``TeamRunner.step()``
per pulse, never a loop that runs the whole team inside one bounded call.

Execution model (no second control plane): the resident itself is the
specialist executor. Each pulse, the runner dispatches the next ready plan
item as a ``team-specialist`` WorkerRun; the resident's existing
cognition/native-action/verification machinery then executes ONE bounded
step for the live run (see ``team_work_resident``), records Body-verified
evidence on the run, and claims completion when the specialist's cognition
returns a structured completion report backed by verified evidence. The
claim is adjudicated against the plan item's ``expected_output`` (CP-3,
see ``completion_verdict``) before it lands, and the runner's verify step
re-adjudicates with fresh observation before the item completes.
Escalations surface through the journal; disband still follows the
existing ``DisbandPlan`` -- never automatic.
"""

import json
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .completion_verdict import (
    CompletionVerdict,
    adjudicate_completion,
    record_verdict_attempt,
)
from .plan_mode import approved_plan_text
from .project_team import ProjectTeam, assemble_team, journal_message
from .skill_ledger import SkillLedger
from .specialist_workspace import (
    materialize_team_workspaces,
    specialist_prompt_for,
)
from .team_memory import team_shared_memory
from .team_runner import (
    Checkpoint,
    CheckpointStorage,
    Escalation,
    TeamRunner,
    VerificationOutcome,
    describe_team_route,
    WorkflowRoute,
)
from .team_timeline import (
    apply_assignee_overrides,
    assignee_overrides,
    record_assignee_override,
)


#: Metrics key holding the Body-verified specialist evidence on a WorkerRun.
EVIDENCE_KEY = "team_specialist_evidence"
#: Team spec key in team shared memory (durable reconstruction across pulses).
TEAM_SPEC_KEY = "team_spec"
#: Working-state key: the durable team id for this event.
TEAM_ID_STATE_KEY = "team_id"
#: Working-state key: a pending completion claim from specialist cognition.
TEAM_CLAIM_STATE_KEY = "team_completion_claim"
#: Working-state key: per-run completion-verdict retry tracking (CP-3).
TEAM_VERDICT_STATE_KEY = "team_completion_verdict"
#: Working-state key: the team already finished (fall through to normal loop).
TEAM_COMPLETE_STATE_KEY = "team_complete"
#: Team shared-memory key for the LG-2 interrupt record (pending decision).
TEAM_INTERRUPT_KEY = "team_interrupt"
#: Interrupt kind for a specialist-reported design/scope gap (P2b).
INTERRUPT_KIND_GAP = "gap"
#: Cap on a stored resume value: decisions stay small and bounded.
MAX_RESUME_VALUE_CHARS = 4000


@dataclass(slots=True)
class TeamOwnerStep:
    """What one owner advance did."""

    state: str  # advanced | blocked | completed
    message: str = ""
    escalations: list[Escalation] = field(default_factory=list)
    team_complete: bool = False
    retrospective_summary: str | None = None
    live_run_id: str | None = None
    live_work_item_id: str | None = None
    live_specialist_name: str | None = None
    # Cognition context for the live specialist run (objective, acceptance,
    # specialist brief, verified evidence so far). None when no run is live.
    live_context: dict[str, Any] | None = None
    # Hard termination (CP-1): set when the runner stopped the team.
    # When set, there is no live run -- the team must not execute more work.
    stop_reason: str | None = None
    stop_trigger: dict[str, Any] = field(default_factory=dict)
    # CP-3: a non-verified verdict on this pulse's claim, fed back to the
    # next cognition call as rejection feedback (reason + fix + missing).
    verdict_feedback: dict[str, Any] | None = None
    # CP-3: set when the verdict retry budget is exhausted -- the resident
    # fails closed with this reason instead of re-asking cognition.
    verdict_escalation: str | None = None
    # AF-4: handoffs executed / rejected by the auto-handoff middleware
    # on this pulse (durable records; see HandoffRecord). Empty when the
    # middleware ran clean with nothing to do.
    handoffs: list[dict[str, Any]] = field(default_factory=list)


def verified_evidence(run: Any) -> list[dict[str, Any]]:
    """Body-verified specialist evidence recorded on a WorkerRun."""
    metrics = getattr(run, "metrics", None)
    if not isinstance(metrics, dict):
        return []
    raw = metrics.get(EVIDENCE_KEY)
    if not isinstance(raw, list):
        return []
    return [
        dict(entry)
        for entry in raw
        if isinstance(entry, dict) and entry.get("verified") is True
    ]


# -- handoff (AF-4) --------------------------------------------------------
#
# Handoff as a tool + automatic-handoff middleware, replacing owner
# re-dispatch. A specialist hands a plan item to another specialist with
# its full context (task + progress + evidence refs); the middleware
# drains explicit handoff requests and applies one conservative
# capability-mismatch rule. Every executed handoff AND every rejected
# request is durably logged in team shared memory (auditable), and every
# executed handoff is journaled (kind="handoff") so the timeline shows
# who handed what to whom, when, and why.
#
# The owner @-reassign path (``record_assignee_override`` via the
# timeline) still works unchanged -- a handoff is the same durable
# override plus a context snapshot, a journal entry, and an audit record.

#: Team shared-memory key holding the durable handoff audit log: a list
#: of ``HandoffRecord`` dicts (executed + rejected).
HANDOFF_LOG_KEY = "handoffs"
#: Team shared-memory key holding pending handoff requests.
HANDOFF_REQUESTS_KEY = "handoff_requests"
#: Tool name specialists call to hand a task to another specialist.
HANDOFF_TOOL_NAME = "handoff_task"
#: Max audit-log entries kept (oldest dropped first).
HANDOFF_LOG_CAP = 200
#: Max pending requests kept.
HANDOFF_REQUESTS_CAP = 50
#: Max characters of a specialist's progress summary kept in a record.
HANDOFF_PROGRESS_CAP = 2000
#: Max evidence refs kept in one record.
HANDOFF_EVIDENCE_CAP = 20

#: Capability signals: capability label -> keywords. A member "has" a
#: capability when any keyword appears in its role key / title /
#: responsibilities; a plan item "requires" it when a keyword appears in
#: its title / objective. Explicit substring matching, no LLM judgment.
#: The auto capability rule only fires on a total mismatch (the current
#: holder covers NONE of the required capabilities) with exactly one
#: member covering ALL of them, so a fuzzy signal can never silently
#: reroute work to an ambiguous target.
CAPABILITY_SIGNALS: dict[str, tuple[str, ...]] = {
    "research": ("research", "调研", "选型", "文献"),
    "design": ("design", "设计", "架构", "接口契约", "数据模型", "原型"),
    "implement": ("implement", "实现", "编码", "开发", "代码", "coding", "build"),
    "test": ("test", "测试", "验收", "qa", "回归", "pytest", "验证"),
    "deploy": ("deploy", "部署", "发布", "上线", "release"),
    "docs": ("doc", "文档", "手册"),
}


def _capabilities_of(text: str) -> set[str]:
    """Capability labels whose keywords appear in ``text`` (lowercased)."""
    lowered = str(text or "").lower()
    return {
        label
        for label, keywords in CAPABILITY_SIGNALS.items()
        if any(keyword in lowered for keyword in keywords)
    }


def _member_capabilities(member: Any) -> set[str]:
    """Capabilities a specialist advertises via role + responsibilities."""
    parts = [
        str(getattr(member, "role_key", "") or ""),
        str(getattr(member, "role_title", "") or ""),
    ]
    responsibilities = getattr(member, "responsibilities", None) or ()
    parts.extend(str(item or "") for item in responsibilities)
    return _capabilities_of("\n".join(parts))


def _item_capabilities(plan_item: Any) -> set[str]:
    """Capabilities a plan item's title + objective call for."""
    return _capabilities_of(
        str(getattr(plan_item, "title", "") or "")
        + "\n"
        + str(getattr(plan_item, "objective", "") or "")
    )


def _normalize_evidence_refs(refs: Any) -> list[dict[str, Any]]:
    """Evidence refs as JSON-safe dicts, capped in count and value size."""
    if not isinstance(refs, (list, tuple)):
        return []
    out: list[dict[str, Any]] = []
    for ref in refs[:HANDOFF_EVIDENCE_CAP]:
        if not isinstance(ref, dict):
            continue
        entry: dict[str, Any] = {}
        for key, value in ref.items():
            text = str(value) if not isinstance(value, str) else value
            entry[str(key)[:100]] = text[:300]
        out.append(entry)
    return out


def handoff_tool_spec() -> dict[str, Any]:
    """Tool descriptor the resident exposes to specialist cognition.

    Calling the tool routes to :meth:`TeamWorkOwner.execute_handoff` with
    the same arguments. The specialist hands off the *task*, never just
    a title: ``progress_summary`` + ``evidence_refs`` are the context the
    receiving specialist continues from.
    """
    return {
        "name": HANDOFF_TOOL_NAME,
        "description": (
            "Hand the current plan item to another team specialist when "
            "you cannot or should not finish it (wrong capability, "
            "explicitly asked to hand off). The receiving specialist gets "
            "the full task, your progress summary, and your evidence refs. "
            "Use progress_summary to say what is done, what is left, and "
            "what to watch out for -- never hand off an empty summary on "
            "a half-finished item."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "plan_item_id": {
                    "type": "string",
                    "description": "Plan item id being handed off.",
                },
                "to_specialist": {
                    "type": "string",
                    "description": "Name of the receiving specialist.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why the handoff is needed.",
                },
                "progress_summary": {
                    "type": "string",
                    "description": (
                        "What is done, what is left, and what to watch "
                        "out for (carried verbatim into the handoff)."
                    ),
                },
                "evidence_refs": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "Evidence refs (artifact refs / file paths / "
                        "conclusions) the receiver continues from."
                    ),
                },
            },
            "required": ["plan_item_id", "to_specialist", "reason"],
        },
    }


@dataclass(slots=True)
class HandoffRecord:
    """One auditable handoff: executed or rejected, never silent."""

    handoff_id: str
    plan_item_id: str
    item_title: str
    from_specialist: str
    to_specialist: str
    reason: str
    triggered_by: str  # tool | auto:explicit_request | auto:capability_mismatch
    status: str  # executed | rejected
    created_at: str
    context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "handoff_id": self.handoff_id,
            "plan_item_id": self.plan_item_id,
            "item_title": self.item_title,
            "from_specialist": self.from_specialist,
            "to_specialist": self.to_specialist,
            "reason": self.reason,
            "triggered_by": self.triggered_by,
            "status": self.status,
            "created_at": self.created_at,
            "context": dict(self.context),
        }


@dataclass(slots=True)
class HandoffRequest:
    """A pending handoff request, drained by the auto middleware."""

    request_id: str
    plan_item_id: str
    from_specialist: str
    to_specialist: str
    reason: str
    progress_summary: str = ""
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "plan_item_id": self.plan_item_id,
            "from_specialist": self.from_specialist,
            "to_specialist": self.to_specialist,
            "reason": self.reason,
            "progress_summary": self.progress_summary,
            "evidence_refs": [dict(ref) for ref in self.evidence_refs],
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class AutoHandoffResult:
    """What one middleware pass did."""

    executed: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)


class ResidentTeamVerifier:
    """Runner Verifier: re-adjudicate a landed claim with fresh observation.

    Fresh observation here means re-reading the run from the ledger at
    verify time -- never trusting a cached claim. The claim was already
    adjudicated once when it landed (see ``TeamWorkOwner``); this gate
    re-runs the same CP-3 adjudication against the run's current evidence
    and summary, so evidence lost or a summary rewritten after landing
    cannot smuggle an item through. Semantic judgment (does the evidence
    *mean* the criterion is met) stays the specialist's honest citation,
    gated by the evidence-existence check.
    """

    def __init__(self, ledger: Any) -> None:
        self._ledger = ledger

    def verify(self, *, item: Any, run: Any) -> VerificationOutcome:
        fresh = self._ledger.worker_run(run.worker_run_id)
        if fresh is None:
            return VerificationOutcome(passed=False, notes="WorkerRun disappeared")
        evidence = verified_evidence(fresh)
        summary = str(getattr(fresh, "result_summary", "") or "").strip()
        expected = list(getattr(item, "acceptance_criteria", None) or [])
        verdict = adjudicate_completion(
            expected_output=expected,
            evidence=evidence,
            summary=summary,
            # AS-3: the product path requires both tracks -- the task
            # acceptance criteria AND the standing Definition of Done.
            require_standing_dod=True,
        )
        if verdict.verdict != "verified":
            return VerificationOutcome(
                passed=False,
                notes=f"完成裁决 {verdict.verdict}：{verdict.reason} "
                f"可执行修改：{verdict.actionable_fix}",
            )
        return VerificationOutcome(
            passed=True,
            notes=(
                f"完成裁决 verified：{len(evidence)} verified specialist step(s); "
                f"{len(verdict.evidence_refs)} evidence ref(s) cited"
            ),
            artifact_refs=tuple(
                dict(ref)
                for entry in evidence
                for ref in (entry.get("artifact_refs") or [])
                if isinstance(ref, dict)
            ),
        )


class TeamWorkOwner:
    """Own one team request through durable TeamRunner steps."""

    def __init__(
        self,
        *,
        ledger: Any,
        memory: Any,
        checkpoint_storage: CheckpointStorage | None = None,
    ) -> None:
        self.ledger = ledger
        self.memory = memory
        # AF-2: pulse-boundary checkpoints. None keeps the previous
        # behavior (no checkpointing); when wired, every runner step
        # persists a snapshot for interrupt-resume.
        self.checkpoint_storage = checkpoint_storage

    # -- routing + checkpoints (AF-2) -------------------------------------

    @staticmethod
    def describe_route(team: ProjectTeam) -> WorkflowRoute:
        """This team's routing as FanOut / FanIn / SwitchCase edges."""
        return describe_team_route(team)

    def latest_checkpoint(self, team_id: str) -> Checkpoint | None:
        """Latest checkpoint for a team, or None when none exists."""
        if self.checkpoint_storage is None:
            return None
        try:
            return self.checkpoint_storage.latest(team_id=team_id)
        except Exception:
            return None

    # -- interrupt + resume (LG-2) --------------------------------------
    #
    # LangGraph's interrupt + Command(resume) shape, not its exception
    # mechanism: a specialist-reported gap (P2b) interrupts the team --
    # the pending decision is persisted into team shared memory (durable
    # across crash/restart) and into the AF-2 checkpoint
    # (``checkpoint.state["pending_interrupt"]``) -- and the event stays
    # alive + blocked until a caller supplies the decision value with
    # :meth:`resume_interrupt`. The interrupted node then re-runs with
    # that value; completed steps are never replayed.
    #
    # One pending interrupt per team: a second gap while one is pending
    # is refused, so a pending decision can never be silently dropped.

    def pending_interrupt(self, *, team_id: str) -> dict[str, Any] | None:
        """The team's interrupt record, or None when nothing is interrupted."""
        if not str(team_id or "").strip():
            return None
        try:
            match = self._shared(str(team_id).strip()).recall(TEAM_INTERRUPT_KEY)
        except (
            AttributeError,
            KeyError,
            LookupError,
            OSError,
            RuntimeError,
            ValueError,
        ):
            return None
        if match is None or not isinstance(match.value, dict):
            return None
        return dict(match.value)

    def record_interrupt(
        self,
        *,
        team_id: str,
        run_id: str,
        work_item_id: str,
        kind: str = INTERRUPT_KIND_GAP,
        missing: str,
        needed: str = "",
        impact: str = "",
    ) -> dict[str, Any]:
        """Persist a pending decision for an interrupted team.

        Idempotent for the same node (same run + work item): a
        crash-replayed integration re-recording the same gap returns
        the existing record instead of duplicating it. A gap for a
        different node while one is pending raises -- resolve the
        pending decision first.
        """
        team_id = str(team_id or "").strip()
        if not team_id:
            raise ValueError("record_interrupt needs a non-empty team_id")
        missing = str(missing or "").strip()
        if not missing:
            raise ValueError("interrupt needs a non-empty missing description")
        existing = self.pending_interrupt(team_id=team_id)
        if existing is not None:
            if str(existing.get("status") or "") == "resumed":
                raise ValueError(
                    "team already has a resumed interrupt awaiting "
                    "consumption; resume a new decision only after it lands"
                )
            if str(existing.get("run_id") or "") == str(run_id or "").strip() and (
                str(existing.get("work_item_id") or "")
                == str(work_item_id or "").strip()
            ):
                return existing
            raise ValueError(
                "team already has a pending interrupt for another node; "
                "resolve it first"
            )
        record = {
            "interrupt_id": f"interrupt-{uuid.uuid4().hex[:12]}",
            "team_id": team_id,
            "status": "pending",
            "kind": str(kind or INTERRUPT_KIND_GAP),
            "run_id": str(run_id or "").strip(),
            "work_item_id": str(work_item_id or "").strip(),
            "missing": missing[:600],
            "needed": str(needed or "")[:600],
            "impact": str(impact or "")[:600],
            "created_at": self._now_iso(None),
            "resume_value": None,
            "resumed_at": None,
        }
        self._shared(team_id).remember(TEAM_INTERRUPT_KEY, record)
        return dict(record)

    def resume_interrupt(self, *, team_id: str, resume_value: str) -> dict[str, Any]:
        """``Command(resume)``: supply the decision value for the pending interrupt.

        Raises when nothing is pending or the value is empty. Replaying
        the *same* resume value after a crash (resume recorded, crash
        before consumption) returns the existing record; a *different*
        value while resumed is ambiguous and raises.
        """
        team_id = str(team_id or "").strip()
        value = str(resume_value or "").strip()
        existing = self.pending_interrupt(team_id=team_id)
        if existing is None:
            raise ValueError(
                f"team {team_id!r} has no pending interrupt to resume"
            )
        if str(existing.get("status") or "") == "resumed":
            if str(existing.get("resume_value") or "") == value:
                return existing
            raise ValueError(
                "interrupt already resumed with a different value; "
                "the resumed decision must be consumed before a new one"
            )
        if not value:
            raise ValueError("resume needs a non-empty resume_value")
        record = {
            **existing,
            "status": "resumed",
            "resume_value": value[:MAX_RESUME_VALUE_CHARS],
            "resumed_at": self._now_iso(None),
        }
        self._shared(team_id).remember(TEAM_INTERRUPT_KEY, record)
        return dict(record)

    def clear_interrupt(self, *, team_id: str) -> None:
        """Consume the interrupt record exactly once. A repeat clear is a no-op."""
        if not str(team_id or "").strip():
            return
        try:
            self._shared(str(team_id).strip()).forget(TEAM_INTERRUPT_KEY)
        except (
            AttributeError,
            KeyError,
            LookupError,
            OSError,
            RuntimeError,
            ValueError,
        ):
            pass

    def save_interrupt_checkpoint(
        self, *, team: ProjectTeam, root_work_item_id: str
    ) -> Checkpoint | None:
        """Persist an AF-2 checkpoint carrying the pending decision.

        The checkpoint is the runner's snapshot (completed vs pending
        steps, LG-1 parent chain) with ``pending_interrupt`` merged into
        ``state``. Returns None when no storage is wired or the save
        fails -- a checkpoint is a resume aid, never a gate.
        """
        if self.checkpoint_storage is None:
            return None
        try:
            runner = TeamRunner(
                team=team,
                ledger=self.ledger,
                memory=self.memory,
                verifier=ResidentTeamVerifier(self.ledger),
                root_work_item_id=root_work_item_id,
                checkpoint_storage=self.checkpoint_storage,
            )
            base = runner.build_checkpoint()
            checkpoint = replace(
                base,
                state={
                    **base.state,
                    "pending_interrupt": self.pending_interrupt(
                        team_id=team.team_id
                    ),
                },
            )
            self.checkpoint_storage.save(checkpoint)
        except Exception:
            return None
        return checkpoint

    # -- routing ---------------------------------------------------------

    @staticmethod
    def handles(event: Any) -> bool:
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            return False
        request = payload.get("team_request")
        if not isinstance(request, dict):
            return False
        if not str(request.get("project_title") or "").strip():
            return False
        roles = request.get("role_keys")
        return isinstance(roles, list) and bool(roles)

    # -- durable team ------------------------------------------------------

    def resolve_team(self, *, event: Any, state: Any, thread_id: str) -> ProjectTeam:
        """Load the team for this event, assembling + persisting on first pulse.

        ``assemble_team`` is deterministic for a fixed (team_id, roles) pair,
        so reconstruction from the persisted spec yields identical members
        and plan items -- a restart resumes instead of duplicating the team.

        Product-path #491 activation: the persona workspace root is
        resolved (explicit ingress/spec root, else ``<attached
        workspace>/agents``) and the team's persona files are
        materialized here, so dispatch re-reads the files from this pulse
        on. Materialize is idempotent and never overwrites edits; a
        filesystem failure degrades to the built-in prompt fragments
        instead of breaking dispatch.
        """
        data = state.data if isinstance(getattr(state, "data", None), dict) else {}
        team_id = str(data.get(TEAM_ID_STATE_KEY) or "").strip()
        request = dict(event.payload.get("team_request") or {})
        if not team_id:
            team_id = f"team-{uuid.uuid4().hex[:8]}"
            data[TEAM_ID_STATE_KEY] = team_id
        shared = team_shared_memory(self.memory, team_id)
        spec = shared.recall(TEAM_SPEC_KEY)
        spec_value = (
            spec.value
            if spec is not None and isinstance(spec.value, dict)
            else None
        )
        workspace_root = self._resolve_workspace_root(
            event=event, request=request, spec_value=spec_value
        )
        if spec_value is not None:
            project = str(spec_value.get("project_title") or "").strip()
            roles = [str(key) for key in (spec_value.get("role_keys") or [])]
            if project and roles:
                team = self._with_overrides(
                    assemble_team(
                        project,
                        roles,
                        team_id=team_id,
                        work_thread_id=thread_id,
                        workspace_root=workspace_root,
                    ),
                    team_id,
                )
                self._materialize_workspaces(team)
                return team
        # First pulse (or spec lost): assemble from the ingress request.
        project = str(request.get("project_title") or "").strip()
        roles = [str(key) for key in (request.get("role_keys") or [])]
        if not project or not roles:
            raise ValueError("team event lost its team_request")
        shared.remember(
            TEAM_SPEC_KEY,
            {
                "project_title": project,
                "role_keys": roles,
                "workspace_root": workspace_root,
            },
        )
        team = self._with_overrides(
            assemble_team(
                project,
                roles,
                team_id=team_id,
                work_thread_id=thread_id,
                workspace_root=workspace_root,
            ),
            team_id,
        )
        self._materialize_workspaces(team)
        return team

    @staticmethod
    def _resolve_workspace_root(
        *,
        event: Any,
        request: dict[str, Any],
        spec_value: dict[str, Any] | None,
    ) -> str | None:
        """Persona workspace root for this team.

        An explicit root (ingress request, then persisted spec) wins;
        otherwise the product-path default is ``<attached
        workspace>/agents``. None when no root is available -- dispatch
        then falls back to the built-in prompt fragments.
        """
        for raw in (
            request.get("workspace_root"),
            (spec_value or {}).get("workspace_root"),
        ):
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        payload = getattr(event, "payload", None)
        attached = ""
        if isinstance(payload, dict):
            attached = str(payload.get("workspace_path") or "").strip()
        if attached:
            return str(Path(attached) / "agents")
        return None

    @staticmethod
    def _materialize_workspaces(team: ProjectTeam) -> None:
        """Create the team's persona files (idempotent, never overwrites).

        On any filesystem failure the team keeps running on its built-in
        prompt fragments -- dispatch never breaks on a workspace problem.
        """
        if not team.workspace_root:
            return
        try:
            materialize_team_workspaces(team.workspace_root, team)
        except (OSError, ValueError):
            team.workspace_root = None

    def _with_overrides(self, team: ProjectTeam, team_id: str) -> ProjectTeam:
        """Apply durable ``@`` assignee overrides (see team_timeline)."""
        return apply_assignee_overrides(
            team, assignee_overrides(self.memory, team_id)
        )

    def _prior_items_for(
        self, *, team: ProjectTeam, live_work_item_id: str
    ) -> list[dict[str, Any]]:
        """Completed plan items before the live one, as cognition context.

        P2: a specialist can only build on prior work (research, design)
        if it can see it. Each entry carries the prior item's title,
        objective, and its completion conclusion + files, so the live
        specialist knows what scope was already decided -- and can tell
        when the design/scope info it needs is missing instead of
        inventing it. Advisory only: any failure degrades to no priors,
        never breaks dispatch.
        """
        try:
            id_map = self._plan_map(team)
            live_index = None
            for index, plan_item in enumerate(team.plan):
                if id_map.get(plan_item.item_id) == live_work_item_id:
                    live_index = index
                    break
            if live_index is None:
                return []
            priors: list[dict[str, Any]] = []
            for plan_item in team.plan[:live_index]:
                wid = id_map.get(plan_item.item_id)
                if not wid:
                    continue
                conclusion = ""
                files: list[str] = []
                for run in self.ledger.list_worker_runs(
                    work_item_id=wid, limit=50
                ):
                    if not getattr(run, "claimed_completion", False):
                        continue
                    summary = str(getattr(run, "result_summary", "") or "")
                    try:
                        parsed = json.loads(summary.strip())
                    except (ValueError, TypeError):
                        parsed = None
                    if isinstance(parsed, dict) and isinstance(
                        parsed.get("completion_report"), dict
                    ):
                        report = parsed["completion_report"]
                        conclusion = str(report.get("conclusion") or "")[:600]
                        raw_files = report.get("files")
                        if isinstance(raw_files, list):
                            files = [str(item)[:300] for item in raw_files][:10]
                    else:
                        conclusion = summary[:600]
                if conclusion or files:
                    priors.append(
                        {
                            "title": str(plan_item.title or "")[:200],
                            "objective": str(plan_item.objective or "")[:600],
                            "conclusion": conclusion,
                            "files": files,
                        }
                    )
            return priors[-3:]
        except (AttributeError, KeyError, LookupError, OSError, RuntimeError, ValueError):
            return []

    def _plan_map(self, team: ProjectTeam) -> dict[str, str]:
        shared = team_shared_memory(self.memory, team.team_id)
        match = shared.recall(TeamRunner.PLAN_MAP_KEY)
        return dict(match.value) if match and isinstance(match.value, dict) else {}

    def _skills_block_for(self, objective: str) -> str:
        """Confirmed-skill block for a specialist item, or "" when none apply.

        Advisory only: any failure here (no store, fake memory in tests,
        ledger error) degrades to no skills, never breaks team dispatch.
        """
        try:
            store = getattr(self.memory, "store", None)
            if store is None:
                return ""
            skills = SkillLedger(store).relevant_skills(objective, max_skills=2)
        except (AttributeError, KeyError, LookupError, OSError, RuntimeError, ValueError):
            return ""
        if not skills:
            return ""
        parts = [
            "Relevant confirmed ZN skills (human-confirmed, advisory -- "
            "follow their steps; approval boundaries still apply):"
        ]
        for skill in skills:
            parts.append(SkillLedger.render_for_cognition(skill, max_chars=800))
        return "\n".join(parts)

    def live_run(self, *, team: ProjectTeam) -> Any | None:
        """The currently-dispatched, unclaimed WorkerRun, if any."""
        id_map = self._plan_map(team)
        for plan_item in team.plan:
            wid = id_map.get(plan_item.item_id)
            if not wid:
                continue
            for run in self.ledger.list_worker_runs(work_item_id=wid, limit=50):
                if run.state in {"queued", "running"} and not run.claimed_completion:
                    return run
        return None

    # -- one durable step --------------------------------------------------

    def _expected_output_for_run(
        self, *, team: ProjectTeam, work_item_id: str
    ) -> list[str]:
        """The plan item's acceptance criteria = the claim's expected_output."""
        id_map = self._plan_map(team)
        for plan_item in team.plan:
            if id_map.get(plan_item.item_id) == work_item_id:
                return list(plan_item.acceptance_criteria)
        return []

    def _apply_pending_claim(
        self, *, state: Any, team: ProjectTeam
    ) -> dict[str, Any] | None:
        """Adjudicate a pending completion claim (CP-3 verdict).

        Returns None when there is no claim to apply, else a dict with the
        verdict and whether the claim landed. A claim lands only on a
        ``verified`` verdict; ``partial`` / ``rejected`` leave the run
        unclaimed, record one retry attempt, and return feedback (reason +
        actionable fix + missing items) for the next cognition call.
        When the retry budget is exhausted the dict carries
        ``escalate_reason`` and the resident fails closed.
        """
        data = state.data if isinstance(getattr(state, "data", None), dict) else {}
        claim = data.get(TEAM_CLAIM_STATE_KEY)
        if not isinstance(claim, dict):
            return None
        data.pop(TEAM_CLAIM_STATE_KEY, None)
        run_id = str(claim.get("run_id") or "").strip()
        summary = str(claim.get("summary") or "").strip()
        if not run_id or not summary:
            return None
        run = self.ledger.worker_run(run_id)
        if run is None or run.claimed_completion:
            return None
        verdict: CompletionVerdict = adjudicate_completion(
            expected_output=self._expected_output_for_run(
                team=team, work_item_id=str(run.work_item_id or "")
            ),
            evidence=verified_evidence(run),
            summary=summary,
            # AS-3: see the verifier above -- both tracks required.
            require_standing_dod=True,
        )
        if verdict.verdict == "verified":
            data.pop(TEAM_VERDICT_STATE_KEY, None)
            # complete_worker_run replaces metrics with the passed dict, so
            # carry the verified evidence forward -- otherwise the claim
            # itself would erase the evidence the verifier needs to see.
            self.ledger.complete_worker_run(
                run_id,
                result_summary=summary,
                claimed_completion=True,
                verification_status="pending",
                metrics=dict(run.metrics or {}),
            )
            return {"landed": True, "verdict": verdict, "escalate_reason": None}
        tracking, escalate, escalate_reason = record_verdict_attempt(
            data.get(TEAM_VERDICT_STATE_KEY),
            run_id=run_id,
            verdict=verdict,
        )
        data[TEAM_VERDICT_STATE_KEY] = tracking
        return {
            "landed": False,
            "verdict": verdict,
            "escalate_reason": escalate_reason if escalate else None,
        }

    def advance(
        self,
        *,
        event: Any,
        state: Any,
        root_work_item_id: str,
    ) -> TeamOwnerStep:
        """One durable TeamRunner step for this pulse."""
        thread_id = str(event.payload.get("work_thread_id") or "").strip()
        team = self.resolve_team(event=event, state=state, thread_id=thread_id)
        # AF-4: automatic handoff runs before the runner step so a
        # handed-off item dispatches to its new specialist this pulse.
        # Advisory by design: a middleware failure must never break the
        # pulse -- the runner step below still runs.
        handoff_result = AutoHandoffResult()
        try:
            handoff_result = self.run_auto_handoff(team=team)
        except (AttributeError, KeyError, LookupError, OSError, RuntimeError, ValueError):
            handoff_result = AutoHandoffResult()
        if handoff_result.executed:
            # Re-resolve so this pulse's team carries the new assignees
            # (resolve_team applies the durable overrides handoff wrote).
            team = self.resolve_team(event=event, state=state, thread_id=thread_id)
        claim_outcome = self._apply_pending_claim(state=state, team=team)
        runner = TeamRunner(
            team=team,
            ledger=self.ledger,
            memory=self.memory,
            verifier=ResidentTeamVerifier(self.ledger),
            root_work_item_id=root_work_item_id,
            checkpoint_storage=self.checkpoint_storage,
        )
        result = runner.step()
        if result.stopped:
            # Hard termination (CP-1): no live run, no more specialist
            # work. The resident fails the event closed with STOP_REASON.
            return TeamOwnerStep(
                state="blocked",
                message=(
                    f"团队已停止（STOP_REASON={result.stop_reason}）。"
                    f"触发：{result.stop_trigger}。"
                    f"进展：{result.stop_progress.get('plan_items_completed')}/"
                    f"{result.stop_progress.get('plan_items_total')} 项完成。"
                ),
                stop_reason=result.stop_reason,
                stop_trigger=dict(result.stop_trigger or {}),
            )
        live = self.live_run(team=team)
        step = TeamOwnerStep(
            state="advanced",
            escalations=list(result.escalations),
            team_complete=result.team_complete,
            retrospective_summary=result.retrospective_summary,
        )
        if claim_outcome is not None and not claim_outcome["landed"]:
            verdict = claim_outcome["verdict"]
            step.verdict_feedback = {
                "run_id": str(
                    (state.data.get(TEAM_VERDICT_STATE_KEY) or {}).get("run_id") or ""
                ),
                "verdict": verdict.verdict,
                "reason": verdict.reason,
                "actionable_fix": verdict.actionable_fix,
                "missing_items": list(verdict.missing_items),
            }
            step.verdict_escalation = claim_outcome["escalate_reason"]
        if result.team_complete:
            step.state = "completed"
            step.message = result.retrospective_summary or "团队全部任务完成"
        elif result.escalations:
            step.state = "advanced"
            step.message = "; ".join(e.reason for e in result.escalations)[:600]
        elif live is not None:
            step.live_run_id = live.worker_run_id
            step.live_work_item_id = live.work_item_id
            step.message = f"specialist run {live.worker_run_id} in progress"
            # Specialist name + cognition context for the resident layer.
            id_map = self._plan_map(team)
            specialist = None
            for plan_item in team.plan:
                if id_map.get(plan_item.item_id) == live.work_item_id:
                    step.live_specialist_name = plan_item.assignee
                    specialist = team.member(plan_item.assignee)
                    # File workspaces are the source of truth: re-read on
                    # every dispatch so a SOUL.md edit takes effect next time.
                    brief = (
                        specialist_prompt_for(team, specialist)
                        if specialist
                        else ""
                    )
                    # P1-3: relevant confirmed skills ride along in the
                    # specialist brief (which already flows into cognition).
                    # Advisory only -- a skill failure never breaks dispatch.
                    skill_block = self._skills_block_for(plan_item.objective)
                    if skill_block:
                        brief = f"{brief}\n\n{skill_block}" if brief else skill_block
                    step.live_context = {
                        "run_id": live.worker_run_id,
                        "work_item_id": live.work_item_id,
                        "specialist_name": plan_item.assignee,
                        "specialist_prompt": brief,
                        "objective": plan_item.objective,
                        "acceptance_criteria": list(plan_item.acceptance_criteria),
                        "prior_items": self._prior_items_for(
                            team=team, live_work_item_id=live.work_item_id
                        ),
                        # CUR-2 Plan Mode: an approved (possibly edited)
                        # plan rides along so the specialist follows it
                        # instead of re-planning or freelancing.
                        "approved_plan": approved_plan_text(
                            state.data
                            if isinstance(
                                getattr(state, "data", None), dict
                            )
                            else {},
                            work_item_id=live.work_item_id,
                        ),
                        "evidence": [
                            {
                                "objective": str(entry.get("objective") or "")[:300],
                                "result": str(entry.get("result") or "")[:900],
                                "relative_path": str(
                                    entry.get("relative_path") or ""
                                )[:300],
                            }
                            for entry in verified_evidence(live)
                        ],
                    }
                    break
        else:
            step.message = "team runner step applied; " + "; ".join(result.actions)[:600]
        step.handoffs = [
            *handoff_result.executed,
            *handoff_result.rejected,
        ]
        return step

    # -- handoff (AF-4) ---------------------------------------------------

    @staticmethod
    def _now_iso(now: datetime | None) -> str:
        return (now or datetime.now(timezone.utc)).isoformat()

    def _shared(self, team_id: str) -> Any:
        return team_shared_memory(self.memory, team_id)

    def handoff_log(self, *, team_id: str) -> list[dict[str, Any]]:
        """Durable handoff audit log for a team (executed + rejected)."""
        try:
            match = self._shared(team_id).recall(HANDOFF_LOG_KEY)
        except (AttributeError, KeyError, LookupError, OSError, RuntimeError, ValueError):
            return []
        if match is None or not isinstance(match.value, list):
            return []
        return [dict(entry) for entry in match.value if isinstance(entry, dict)]

    def _append_handoff_log(self, *, team_id: str, record: dict[str, Any]) -> None:
        entries = self.handoff_log(team_id=team_id)
        entries.append(dict(record))
        self._shared(team_id).remember(
            HANDOFF_LOG_KEY, entries[-HANDOFF_LOG_CAP:]
        )

    def pending_handoff_requests(self, *, team_id: str) -> list[dict[str, Any]]:
        """Pending handoff requests awaiting the middleware drain."""
        try:
            match = self._shared(team_id).recall(HANDOFF_REQUESTS_KEY)
        except (AttributeError, KeyError, LookupError, OSError, RuntimeError, ValueError):
            return []
        if match is None or not isinstance(match.value, list):
            return []
        return [dict(entry) for entry in match.value if isinstance(entry, dict)]

    def _effective_team(self, team: ProjectTeam) -> ProjectTeam:
        """``team`` with durable assignee overrides applied."""
        try:
            return apply_assignee_overrides(
                team, assignee_overrides(self.memory, team.team_id)
            )
        except (AttributeError, KeyError, LookupError, OSError, RuntimeError, ValueError):
            return team

    def _plan_item(self, team: ProjectTeam, plan_item_id: str) -> Any | None:
        for plan_item in team.plan:
            if plan_item.item_id == plan_item_id:
                return plan_item
        return None

    def _completed_plan_item_ids(self, team: ProjectTeam) -> set[str]:
        """Plan items whose WorkItem is already completed (best-effort)."""
        try:
            id_map = self._plan_map(team)
            if not id_map:
                return set()
            thread_id = team.work_thread_id or ""
            items = {
                item.work_item_id: item
                for item in self.ledger.list_work_items(thread_id)
            }
            completed: set[str] = set()
            for plan_item_id, wid in id_map.items():
                item = items.get(wid)
                if item is not None and item.status == "completed":
                    completed.add(plan_item_id)
            return completed
        except (AttributeError, KeyError, LookupError, OSError, RuntimeError, ValueError):
            return set()

    def _live_work_item_ids(self, team: ProjectTeam) -> set[str]:
        """Work item ids with a live (queued/running, unclaimed) run."""
        try:
            id_map = self._plan_map(team)
            live: set[str] = set()
            for wid in id_map.values():
                for run in self.ledger.list_worker_runs(work_item_id=wid, limit=50):
                    if (
                        run.state in {"queued", "running"}
                        and not run.claimed_completion
                    ):
                        live.add(str(run.work_item_id or ""))
                        break
            return live
        except (AttributeError, KeyError, LookupError, OSError, RuntimeError, ValueError):
            return set()

    def _live_evidence_for(
        self, *, team: ProjectTeam, plan_item_id: str
    ) -> list[dict[str, Any]]:
        """Verified evidence on the item's live run, if any (advisory)."""
        try:
            id_map = self._plan_map(team)
            wid = id_map.get(plan_item_id)
            if not wid:
                return []
            for run in self.ledger.list_worker_runs(work_item_id=wid, limit=50):
                if run.state in {"queued", "running"} and not run.claimed_completion:
                    return [
                        {
                            "objective": str(entry.get("objective") or "")[:300],
                            "result": str(entry.get("result") or "")[:900],
                            "relative_path": str(
                                entry.get("relative_path") or ""
                            )[:300],
                        }
                        for entry in verified_evidence(run)
                    ]
            return []
        except (AttributeError, KeyError, LookupError, OSError, RuntimeError, ValueError):
            return []

    def _handoff_context(
        self,
        *,
        team: ProjectTeam,
        plan_item: Any,
        progress_summary: str,
        evidence_refs: Any,
    ) -> dict[str, Any]:
        """Context snapshot the receiving specialist continues from.

        Task (title + objective + acceptance) + progress (caller summary
        + live-run verified evidence) + caller evidence refs + prior
        items' conclusions. Advisory parts degrade to empty, never fail
        the handoff.
        """
        try:
            wid = self._plan_map(team).get(plan_item.item_id) or ""
        except (AttributeError, KeyError, LookupError, OSError, RuntimeError, ValueError):
            wid = ""
        return {
            "task": {
                "plan_item_id": plan_item.item_id,
                "title": str(plan_item.title or ""),
                "objective": str(plan_item.objective or ""),
                "acceptance_criteria": list(plan_item.acceptance_criteria),
            },
            "progress_summary": str(progress_summary or "")[:HANDOFF_PROGRESS_CAP],
            "live_evidence": self._live_evidence_for(
                team=team, plan_item_id=plan_item.item_id
            ),
            "evidence_refs": _normalize_evidence_refs(evidence_refs),
            "prior_items": self._prior_items_for(
                team=team, live_work_item_id=wid
            )
            if wid
            else [],
        }

    def _journal_handoff(self, *, team: ProjectTeam, record: dict[str, Any]) -> None:
        """Journal the handoff (best-effort: never fails the handoff)."""
        thread_id = team.work_thread_id or ""
        if not thread_id:
            return
        try:
            message = journal_message(
                team.team_id,
                str(record.get("from_specialist") or ""),
                f"交接：{record.get('item_title') or record.get('plan_item_id')} "
                f"{record.get('from_specialist')} → {record.get('to_specialist')} "
                f"（{record.get('reason')}）",
                kind="handoff",
            )
            message["detail"].update(
                {
                    "handoff_id": record.get("handoff_id"),
                    "plan_item_id": record.get("plan_item_id"),
                    "from_author": record.get("from_specialist"),
                    "to_author": record.get("to_specialist"),
                    "triggered_by": record.get("triggered_by"),
                    "status": record.get("status"),
                }
            )
            self.ledger.append_message(
                thread_id,
                role=str(message.get("role") or ""),
                text=str(message.get("text") or ""),
                detail=dict(message.get("detail") or {}),
            )
        except (AttributeError, KeyError, LookupError, OSError, RuntimeError, ValueError):
            return

    def request_handoff(
        self,
        *,
        team: ProjectTeam,
        plan_item_id: str,
        from_specialist: str,
        to_specialist: str,
        reason: str,
        progress_summary: str = "",
        evidence_refs: Any = (),
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Record a pending handoff request for the middleware to drain.

        Validates shape only (item exists, both ends are members, from !=
        to, reason non-empty). Whether the request is *executable* (from
        is the current holder, item not completed) is decided at drain
        time and audited as executed / rejected there.
        """
        plan_item = self._plan_item(team, str(plan_item_id or ""))
        if plan_item is None:
            raise ValueError(f"unknown plan item: {plan_item_id!r}")
        members = {member.name for member in team.members}
        if str(from_specialist or "") not in members:
            raise ValueError(f"unknown specialist: {from_specialist!r}")
        if str(to_specialist or "") not in members:
            raise ValueError(f"unknown specialist: {to_specialist!r}")
        if str(from_specialist or "") == str(to_specialist or ""):
            raise ValueError("handoff target must differ from the source")
        if not str(reason or "").strip():
            raise ValueError("handoff reason must not be empty")
        pending = self.pending_handoff_requests(team_id=team.team_id)
        for existing in pending:
            if (
                existing.get("plan_item_id") == plan_item.item_id
                and existing.get("from_specialist") == str(from_specialist or "")
                and existing.get("to_specialist") == str(to_specialist or "")
            ):
                return existing
        request = HandoffRequest(
            request_id=f"handoff-req-{uuid.uuid4().hex[:12]}",
            plan_item_id=plan_item.item_id,
            from_specialist=str(from_specialist or ""),
            to_specialist=str(to_specialist or ""),
            reason=str(reason or "").strip()[:600],
            progress_summary=str(progress_summary or "")[:HANDOFF_PROGRESS_CAP],
            evidence_refs=_normalize_evidence_refs(evidence_refs),
            created_at=self._now_iso(now),
        ).as_dict()
        pending.append(request)
        self._shared(team.team_id).remember(
            HANDOFF_REQUESTS_KEY, pending[-HANDOFF_REQUESTS_CAP:]
        )
        return request

    def execute_handoff(
        self,
        *,
        team: ProjectTeam,
        plan_item_id: str,
        from_specialist: str,
        to_specialist: str,
        reason: str,
        progress_summary: str = "",
        evidence_refs: Any = (),
        triggered_by: str = "tool",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Hand a plan item to another specialist, with full context.

        This is the handoff tool's implementation (see
        :func:`handoff_tool_spec`). Validates: item exists, both ends
        are members, from is the *current* holder, to differs from from,
        reason non-empty, item not completed. On success: durable
        assignee override + audit-log record + journal entry. Raises
        ``ValueError`` on any validation failure (the middleware turns
        those into audited rejections instead of crashing the pulse).
        """
        effective = self._effective_team(team)
        plan_item = self._plan_item(effective, str(plan_item_id or ""))
        if plan_item is None:
            raise ValueError(f"unknown plan item: {plan_item_id!r}")
        members = {member.name for member in effective.members}
        if str(from_specialist or "") not in members:
            raise ValueError(f"unknown specialist: {from_specialist!r}")
        if str(to_specialist or "") not in members:
            raise ValueError(f"unknown specialist: {to_specialist!r}")
        if str(from_specialist or "") == str(to_specialist or ""):
            raise ValueError("handoff target must differ from the source")
        if not str(reason or "").strip():
            raise ValueError("handoff reason must not be empty")
        if plan_item.assignee != str(from_specialist or ""):
            raise ValueError(
                f"plan item {plan_item.item_id} is held by "
                f"{plan_item.assignee!r}, not {from_specialist!r}"
            )
        if plan_item.item_id in self._completed_plan_item_ids(effective):
            raise ValueError(f"plan item {plan_item.item_id} is already completed")
        context = self._handoff_context(
            team=effective,
            plan_item=plan_item,
            progress_summary=progress_summary,
            evidence_refs=evidence_refs,
        )
        record = HandoffRecord(
            handoff_id=f"handoff-{uuid.uuid4().hex[:12]}",
            plan_item_id=plan_item.item_id,
            item_title=str(plan_item.title or ""),
            from_specialist=str(from_specialist or ""),
            to_specialist=str(to_specialist or ""),
            reason=str(reason or "").strip()[:600],
            triggered_by=triggered_by,
            status="executed",
            created_at=self._now_iso(now),
            context=context,
        ).as_dict()
        record_assignee_override(
            self.memory,
            effective.team_id,
            plan_item.item_id,
            str(to_specialist or ""),
        )
        self._append_handoff_log(team_id=effective.team_id, record=record)
        self._journal_handoff(team=effective, record=record)
        return record

    def run_auto_handoff(
        self,
        *,
        team: ProjectTeam,
        now: datetime | None = None,
    ) -> AutoHandoffResult:
        """Automatic-handoff middleware: drain requests + capability rule.

        Rules (explicit, testable, auditable):
        - ``explicit_request``: a pending :meth:`request_handoff` is
          executed when valid, else audited as rejected with the reason.
        - ``capability_mismatch``: a not-yet-dispatched, uncompleted
          item whose current holder covers NONE of its required
          capabilities is handed to the single member covering ALL of
          them. Ties (two or more full-cover candidates) and partial
          coverage never auto-fire -- the owner decides those. An item
          is never handed straight back to the specialist who just
          handed it away (ping-pong guard).
        """
        result = AutoHandoffResult()
        # -- drain pending explicit requests ------------------------------
        pending = self.pending_handoff_requests(team_id=team.team_id)
        if pending:
            self._shared(team.team_id).remember(HANDOFF_REQUESTS_KEY, [])
        for request in pending:
            try:
                record = self.execute_handoff(
                    team=team,
                    plan_item_id=str(request.get("plan_item_id") or ""),
                    from_specialist=str(request.get("from_specialist") or ""),
                    to_specialist=str(request.get("to_specialist") or ""),
                    reason=str(request.get("reason") or ""),
                    progress_summary=str(request.get("progress_summary") or ""),
                    evidence_refs=request.get("evidence_refs") or (),
                    triggered_by="auto:explicit_request",
                    now=now,
                )
            except ValueError as exc:
                rejected = HandoffRecord(
                    handoff_id=f"handoff-{uuid.uuid4().hex[:12]}",
                    plan_item_id=str(request.get("plan_item_id") or ""),
                    item_title="",
                    from_specialist=str(request.get("from_specialist") or ""),
                    to_specialist=str(request.get("to_specialist") or ""),
                    reason=str(exc)[:600],
                    triggered_by="auto:explicit_request",
                    status="rejected",
                    created_at=self._now_iso(now),
                    context={
                        "request_reason": str(request.get("reason") or "")[:600],
                        "progress_summary": str(
                            request.get("progress_summary") or ""
                        )[:HANDOFF_PROGRESS_CAP],
                        "evidence_refs": _normalize_evidence_refs(
                            request.get("evidence_refs") or ()
                        ),
                    },
                ).as_dict()
                self._append_handoff_log(team_id=team.team_id, record=rejected)
                result.rejected.append(rejected)
            else:
                result.executed.append(record)
        # -- capability-mismatch rule (pre-dispatch only) ------------------
        completed = self._completed_plan_item_ids(team)
        live = self._live_work_item_ids(team)
        id_map = self._plan_map(team)
        for plan_item in list(self._effective_team(team).plan):
            if plan_item.item_id in completed:
                continue
            wid = id_map.get(plan_item.item_id) or ""
            if wid and wid in live:
                continue
            required = _item_capabilities(plan_item)
            if not required:
                continue
            effective = self._effective_team(team)
            current_item = self._plan_item(effective, plan_item.item_id)
            if current_item is None:
                continue
            current = effective.member(current_item.assignee)
            if current is None:
                continue
            current_caps = _member_capabilities(current)
            if required <= current_caps:
                continue
            if current_caps & required:
                result.skipped.append(
                    {
                        "plan_item_id": plan_item.item_id,
                        "rule": "capability_mismatch",
                        "reason": (
                            f"partial capability coverage "
                            f"({sorted(current_caps & required)}); owner decides"
                        ),
                    }
                )
                continue
            candidates = [
                member
                for member in effective.members
                if member.name != current_item.assignee
                and required <= _member_capabilities(member)
            ]
            if len(candidates) != 1:
                result.skipped.append(
                    {
                        "plan_item_id": plan_item.item_id,
                        "rule": "capability_mismatch",
                        "reason": (
                            f"{len(candidates)} full-cover candidates; "
                            "auto-handoff needs exactly one"
                        ),
                    }
                )
                continue
            target = candidates[0]
            log = self.handoff_log(team_id=team.team_id)
            last = next(
                (
                    entry
                    for entry in reversed(log)
                    if entry.get("plan_item_id") == plan_item.item_id
                    and entry.get("status") == "executed"
                ),
                None,
            )
            if last is not None and last.get("from_specialist") == target.name:
                result.skipped.append(
                    {
                        "plan_item_id": plan_item.item_id,
                        "rule": "capability_mismatch",
                        "reason": (
                            f"ping-pong guard: {target.name} just handed "
                            "this item away"
                        ),
                    }
                )
                continue
            try:
                record = self.execute_handoff(
                    team=team,
                    plan_item_id=plan_item.item_id,
                    from_specialist=current_item.assignee,
                    to_specialist=target.name,
                    reason=(
                        f"capability mismatch: item requires "
                        f"{sorted(required)}, {current_item.assignee} covers "
                        f"{sorted(current_caps)}; {target.name} covers all"
                    ),
                    progress_summary="",
                    evidence_refs=(),
                    triggered_by="auto:capability_mismatch",
                    now=now,
                )
            except ValueError as exc:
                result.skipped.append(
                    {
                        "plan_item_id": plan_item.item_id,
                        "rule": "capability_mismatch",
                        "reason": str(exc)[:600],
                    }
                )
            else:
                result.executed.append(record)
        return result


__all__ = [
    "EVIDENCE_KEY",
    "HANDOFF_LOG_KEY",
    "HANDOFF_REQUESTS_KEY",
    "HANDOFF_TOOL_NAME",
    "TEAM_CLAIM_STATE_KEY",
    "TEAM_COMPLETE_STATE_KEY",
    "TEAM_ID_STATE_KEY",
    "TEAM_INTERRUPT_KEY",
    "TEAM_VERDICT_STATE_KEY",
    "AutoHandoffResult",
    "Checkpoint",
    "CheckpointStorage",
    "HandoffRecord",
    "HandoffRequest",
    "ResidentTeamVerifier",
    "TeamOwnerStep",
    "TeamWorkOwner",
    "WorkflowRoute",
    "handoff_tool_spec",
    "verified_evidence",
]
