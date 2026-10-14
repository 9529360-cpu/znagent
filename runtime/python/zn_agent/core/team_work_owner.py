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

import uuid
from dataclasses import dataclass, field
from typing import Any

from .completion_verdict import (
    CompletionVerdict,
    adjudicate_completion,
    record_verdict_attempt,
)
from .project_team import ProjectTeam, assemble_team
from .team_memory import team_shared_memory
from .team_runner import Escalation, TeamRunner, VerificationOutcome
from .team_timeline import apply_assignee_overrides, assignee_overrides


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
    # CP-3: a non-verified verdict on this pulse's claim, fed back to the
    # next cognition call as rejection feedback (reason + fix + missing).
    verdict_feedback: dict[str, Any] | None = None
    # CP-3: set when the verdict retry budget is exhausted -- the resident
    # fails closed with this reason instead of re-asking cognition.
    verdict_escalation: str | None = None


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

    def __init__(self, *, ledger: Any, memory: Any) -> None:
        self.ledger = ledger
        self.memory = memory

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
        """
        data = state.data if isinstance(getattr(state, "data", None), dict) else {}
        team_id = str(data.get(TEAM_ID_STATE_KEY) or "").strip()
        request = dict(event.payload.get("team_request") or {})
        if not team_id:
            team_id = f"team-{uuid.uuid4().hex[:8]}"
            data[TEAM_ID_STATE_KEY] = team_id
        shared = team_shared_memory(self.memory, team_id)
        spec = shared.recall(TEAM_SPEC_KEY)
        if spec is not None and isinstance(spec.value, dict):
            project = str(spec.value.get("project_title") or "").strip()
            roles = [str(key) for key in (spec.value.get("role_keys") or [])]
            if project and roles:
                return self._with_overrides(
                    assemble_team(
                        project,
                        roles,
                        team_id=team_id,
                        work_thread_id=thread_id,
                    ),
                    team_id,
                )
        # First pulse (or spec lost): assemble from the ingress request.
        project = str(request.get("project_title") or "").strip()
        roles = [str(key) for key in (request.get("role_keys") or [])]
        if not project or not roles:
            raise ValueError("team event lost its team_request")
        shared.remember(
            TEAM_SPEC_KEY, {"project_title": project, "role_keys": roles}
        )
        return self._with_overrides(
            assemble_team(
                project, roles, team_id=team_id, work_thread_id=thread_id
            ),
            team_id,
        )

    def _with_overrides(self, team: ProjectTeam, team_id: str) -> ProjectTeam:
        """Apply durable ``@`` assignee overrides (see team_timeline)."""
        return apply_assignee_overrides(
            team, assignee_overrides(self.memory, team_id)
        )

    def _plan_map(self, team: ProjectTeam) -> dict[str, str]:
        shared = team_shared_memory(self.memory, team.team_id)
        match = shared.recall(TeamRunner.PLAN_MAP_KEY)
        return dict(match.value) if match and isinstance(match.value, dict) else {}

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
        claim_outcome = self._apply_pending_claim(state=state, team=team)
        runner = TeamRunner(
            team=team,
            ledger=self.ledger,
            memory=self.memory,
            verifier=ResidentTeamVerifier(self.ledger),
            root_work_item_id=root_work_item_id,
        )
        result = runner.step()
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
                    step.live_context = {
                        "run_id": live.worker_run_id,
                        "work_item_id": live.work_item_id,
                        "specialist_name": plan_item.assignee,
                        "specialist_prompt": (
                            specialist.prompt_fragment if specialist else ""
                        ),
                        "objective": plan_item.objective,
                        "acceptance_criteria": list(plan_item.acceptance_criteria),
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
        return step


__all__ = [
    "EVIDENCE_KEY",
    "TEAM_CLAIM_STATE_KEY",
    "TEAM_COMPLETE_STATE_KEY",
    "TEAM_ID_STATE_KEY",
    "TEAM_VERDICT_STATE_KEY",
    "ResidentTeamVerifier",
    "TeamOwnerStep",
    "TeamWorkOwner",
    "verified_evidence",
]
