from __future__ import annotations

"""Memory & Learned Behavior 1.0 resident composition.

This layer closes one deliberately narrow L4 path without creating a second
planner, skill runtime, action registry, or memory database.  It reuses the
existing VerifiedExperience -> CandidateProceduralTendency -> applicability
pipeline and only shortens cognition after current Investigation has already
re-formed a safe action choice from current event authority and fresh facts.

The learned record may answer *which familiar procedure* is preferred.  It
never supplies Body arguments, credentials, target identities, or mutation
authority.  Those continue to come from the current event and current Senses.
"""

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .action import NativeActionIntent, derive_native_action_intents
from .current_api_docs_adaptation_resident import (
    CurrentApiDocsAdaptationResidentRuntime,
)
from .models import AgentEvent, ResidentRunResult, WorkingState
from .procedural_influence import (
    ProceduralActionInfluence,
    strongest_supported_action_influence,
    select_procedurally_influenced_intent,
)
from .procedural_tendency import CandidateProceduralTendency
from .self_model import TaskReadiness


_PRIOR_CONTEXT_KEY = "verified_prior_working_context"
_FAST_PATH_KEY = "procedural_fast_path"
_METRICS_KEY = "learned_behavior_metrics"
_MAX_CONTEXT_MATCHES = 3
_MAX_PROVENANCE_ITEMS = 4

# Explicit product-language requests to reuse a prior way of working.  This
# detector never grants execution authority; it only decides whether ambiguity
# in otherwise-safe verified context must be surfaced to the user instead of
# silently choosing one historical preference.
_PRIOR_STYLE_MARKERS = (
    "以前这个项目",
    "之前这个项目",
    "之前的方式",
    "以前的方式",
    "还是按照以前",
    "还是按以前",
    "same way as before",
    "same way we did",
    "previous way",
    "prior way",
)


@dataclass(slots=True, frozen=True)
class VerifiedWorkingContext:
    """Privacy-safe provenance for one currently-applicable learned procedure."""

    tendency_id: str
    action_kind: str
    action_variant: str | None
    maturity_state: str
    reliability: float
    support_count: int
    contradiction_count: int
    native_support_count: int
    first_verified_at: str | None
    last_verified_at: str | None
    current_match_fields: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    source_experience_ids: tuple[str, ...]

    def rank(self) -> tuple[int, float, int, int]:
        return (
            2 if self.maturity_state == "practiced" else 1,
            float(self.reliability),
            int(self.support_count),
            int(self.native_support_count),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in (
            "current_match_fields",
            "source_event_ids",
            "source_experience_ids",
        ):
            data[key] = list(data[key])
        return data

    def product_explanation(self) -> str:
        variant = self.action_variant.replace("_", " ") if self.action_variant else self.action_kind
        fields = ", ".join(self.current_match_fields) or "current reality"
        percent = round(max(0.0, min(1.0, self.reliability)) * 100)
        last = self.last_verified_at or "an earlier verified run"
        return (
            f"Current checks match the previously verified {variant} way of working. "
            f"It has {self.support_count} independent verified successes, reliability "
            f"{percent}%, was last verified at {last}, and current reality re-matched "
            f"{fields}."
        )


@dataclass(slots=True, frozen=True)
class PriorWorkingContextResolution:
    status: str
    matches: tuple[VerifiedWorkingContext, ...] = ()
    selected: VerifiedWorkingContext | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "matches": [item.to_dict() for item in self.matches],
            "selected": self.selected.to_dict() if self.selected is not None else None,
            "reason": self.reason,
        }


def _action_variant(intent: NativeActionIntent) -> str | None:
    expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
    value = str(expected.get("action_variant") or "").strip().lower()
    if value:
        return value
    if intent.kind == "write_text":
        return "append" if bool(intent.args.get("append", False)) else "replace"
    return None


def _context_from_influence(
    influence: ProceduralActionInfluence,
    intent: NativeActionIntent,
    *,
    candidate: CandidateProceduralTendency,
    experience_by_id: dict[str, Any],
) -> VerifiedWorkingContext:
    support_ids = tuple(candidate.supporting_experience_ids[-_MAX_PROVENANCE_ITEMS:])
    source_events: list[str] = []
    source_experiences: list[str] = []
    first_at: str | None = None
    last_at: str | None = None
    for experience_id in support_ids:
        experience = experience_by_id.get(str(experience_id))
        if experience is None or str(getattr(experience, "verdict", "")) != "verified":
            continue
        event_id = str(getattr(experience, "event_id", "")).strip()
        created_at = str(getattr(experience, "created_at", "")).strip()
        if event_id and event_id not in source_events:
            source_events.append(event_id)
        source_experiences.append(str(experience_id))
        if created_at:
            first_at = created_at if first_at is None or created_at < first_at else first_at
            last_at = created_at if last_at is None or created_at > last_at else last_at

    # Candidate timestamps cover retained supporting evidence beyond the bounded
    # provenance excerpt, so use them as fallback without exposing raw history.
    first_at = first_at or candidate.first_seen_at
    last_at = last_at or candidate.last_seen_at
    return VerifiedWorkingContext(
        tendency_id=influence.tendency_id,
        action_kind=influence.action_kind,
        action_variant=_action_variant(intent),
        maturity_state=influence.candidate_maturity_state,
        reliability=float(influence.candidate_reliability),
        support_count=int(candidate.support_count),
        contradiction_count=int(candidate.contradiction_count),
        native_support_count=int(candidate.native_support_count),
        first_verified_at=first_at,
        last_verified_at=last_at,
        current_match_fields=tuple(influence.reality_matched_fields),
        source_event_ids=tuple(source_events[-_MAX_PROVENANCE_ITEMS:]),
        source_experience_ids=tuple(source_experiences[-_MAX_PROVENANCE_ITEMS:]),
    )


def resolve_verified_working_context(
    event: AgentEvent,
    intents: Iterable[NativeActionIntent],
    *,
    candidates: Iterable[CandidateProceduralTendency],
    experiences: Iterable[Any],
    current_domains: Iterable[str],
    facts: dict[str, object] | None,
    revoked_tendency_ids: Iterable[str] = (),
) -> PriorWorkingContextResolution:
    """Return only bounded history independently re-bound to current reality.

    The applicability implementation is the same gate used by L3 action
    influence.  No historical Body args are returned.  Equal-strength divergent
    procedures are explicitly ambiguous rather than being guessed from history.
    """

    current_intents = tuple(intents)
    current_candidates = tuple(candidates)
    candidate_by_id = {item.tendency_id: item for item in current_candidates}
    experience_by_id = {
        str(getattr(item, "experience_id", "")): item for item in experiences
    }
    rows: list[VerifiedWorkingContext] = []
    seen: set[tuple[str, str | None]] = set()

    for intent in current_intents:
        influence = strongest_supported_action_influence(
            event,
            intent,
            candidates=current_candidates,
            current_domains=current_domains,
            facts=facts,
            revoked_tendency_ids=revoked_tendency_ids,
        )
        if influence is None:
            continue
        candidate = candidate_by_id.get(influence.tendency_id)
        if candidate is None:
            continue
        key = (influence.tendency_id, _action_variant(intent))
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            _context_from_influence(
                influence,
                intent,
                candidate=candidate,
                experience_by_id=experience_by_id,
            )
        )

    if not rows:
        return PriorWorkingContextResolution(
            status="none",
            reason="no verified prior procedure is independently applicable to current reality",
        )

    rows.sort(
        key=lambda item: (*item.rank(), item.tendency_id),
        reverse=True,
    )
    bounded = tuple(rows[:_MAX_CONTEXT_MATCHES])
    top = bounded[0]
    if len(bounded) > 1 and bounded[1].rank() == top.rank():
        return PriorWorkingContextResolution(
            status="ambiguous",
            matches=bounded,
            selected=None,
            reason=(
                "multiple equally supported previously verified ways match the current "
                "project and current reality; choosing one would require guessing"
            ),
        )
    return PriorWorkingContextResolution(
        status="resolved",
        matches=bounded,
        selected=top,
        reason=top.product_explanation(),
    )


class MemoryLearnedBehaviorResidentRuntime(CurrentApiDocsAdaptationResidentRuntime):
    """One active Resident with bounded prior-context reuse and an L4 fast path."""

    @staticmethod
    def _is_prior_working_style_request(event: AgentEvent) -> bool:
        task = str(event.task or "").strip().lower()
        return any(marker in task for marker in _PRIOR_STYLE_MARKERS)

    def _current_verified_working_context(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness: TaskReadiness,
    ) -> PriorWorkingContextResolution:
        investigation = self.investigator.current(event.event_id)
        facts = dict(investigation.facts) if investigation is not None else {}
        intents = derive_native_action_intents(event, facts=facts)
        if not intents:
            return PriorWorkingContextResolution(
                status="none",
                reason="current reality has not formed a safe reusable procedure yet",
            )
        candidates = self.verified_experiences.candidate_tendencies(limit=16)
        experiences = self.verified_experiences.recent(
            min(self.verified_experiences.max_records, 128)
        )
        return resolve_verified_working_context(
            event,
            intents,
            candidates=candidates,
            experiences=experiences,
            current_domains=readiness.domains,
            facts=facts,
            revoked_tendency_ids=self._revoked_tendency_ids(state),
        )

    def _refresh_verified_working_context(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness: TaskReadiness,
    ) -> PriorWorkingContextResolution:
        resolution = self._current_verified_working_context(
            event,
            state,
            readiness=readiness,
        )
        state.data[_PRIOR_CONTEXT_KEY] = resolution.to_dict()
        return resolution

    @staticmethod
    def _state_context_resolution(state: WorkingState) -> dict[str, Any]:
        raw = state.data.get(_PRIOR_CONTEXT_KEY)
        return dict(raw) if isinstance(raw, dict) else {}

    def _try_practiced_fast_path(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness: TaskReadiness,
        thought=None,
    ) -> bool:
        """Skip one rediscovery pulse only after fresh Investigation is complete."""

        investigation = self.investigator.current(event.event_id)
        if investigation is None:
            return False
        facts = dict(investigation.facts)
        intents = derive_native_action_intents(event, facts=facts)
        if not intents:
            return False

        context = self._state_context_resolution(state)
        if self._is_prior_working_style_request(event) and context.get("status") == "ambiguous":
            return False

        candidates = self.verified_experiences.candidate_tendencies(limit=16)
        selected, influence = select_procedurally_influenced_intent(
            event,
            intents,
            candidates=candidates,
            current_domains=readiness.domains,
            facts=facts,
            revoked_tendency_ids=self._revoked_tendency_ids(state),
        )
        if (
            selected is None
            or influence is None
            or influence.candidate_maturity_state != "practiced"
            or float(influence.candidate_reliability) < 0.80
        ):
            return False
        if self._action_blocked_by_current_evidence(event, state, selected):
            return False

        self._activate_procedural_influence(state, influence)
        state.data[_FAST_PATH_KEY] = {
            "status": "active",
            "tendency_id": influence.tendency_id,
            "evaluation_id": influence.evaluation_id,
            "action_kind": influence.action_kind,
            "maturity_state": influence.candidate_maturity_state,
            "reliability": influence.candidate_reliability,
            "support_count": influence.support_count,
            "current_match_fields": list(influence.reality_matched_fields),
            "current_context_fingerprint": influence.context_fingerprint,
            "authority_source": "current event + fresh Investigation",
            "history_supplied_body_args": False,
            "verification_required": True,
            "native_deliberation_steps_avoided": 1,
        }
        metrics = state.data.get(_METRICS_KEY)
        metric_data = dict(metrics) if isinstance(metrics, dict) else {}
        metric_data["native_deliberation_steps_avoided"] = int(
            metric_data.get("native_deliberation_steps_avoided") or 0
        ) + 1
        metric_data["investigation_rounds_before_fast_path"] = int(
            investigation.rounds
        )
        metric_data["fresh_investigation_probe_count"] = len(investigation.probe_keys)
        metric_data["verification_required"] = True
        state.data[_METRICS_KEY] = metric_data
        self._begin_native_action_cycle(event, state, selected)
        if thought is not None:
            known = (
                "fresh current evidence matches a practiced resident-owned procedure; "
                "I can skip rediscovering the same mechanical choice, but not execution or verification"
            )
            if known not in thought.known:
                thought.known = (*thought.known, known)
            thought.reason = (
                f"{thought.reason}; repeated independently verified experience now removes one "
                "redundant native deliberation pulse"
            )
            self._persist_enriched_thought(thought)
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return True

    def _investigation_step(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness: TaskReadiness,
        learning_evidence: list[dict[str, Any]],
        thought=None,
    ) -> ResidentRunResult | None:
        result = super()._investigation_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )
        # The parent just performed at most one real probe.  Re-bind history only
        # after that observation; historical records never stand in for Sense.
        resolution = self._refresh_verified_working_context(
            event,
            state,
            readiness=readiness,
        )
        if thought is not None and self._is_prior_working_style_request(event):
            if resolution.status == "resolved" and resolution.selected is not None:
                known = resolution.selected.product_explanation()
                if known not in thought.known:
                    thought.known = (*thought.known, known)
            elif resolution.status == "ambiguous":
                unknown = (
                    "multiple equally supported verified ways match this project; I need "
                    "the user to identify which prior way they mean"
                )
                if unknown not in thought.unknown:
                    thought.unknown = (*thought.unknown, unknown)
            self._persist_enriched_thought(thought)

        if result is None and state.stage == "native_deliberation":
            if self._try_practiced_fast_path(
                event,
                state,
                readiness=readiness,
                thought=thought,
            ):
                return None
        self.store.save_working_state(state)
        return result

    def _deliberation_step(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness: TaskReadiness,
        learning_evidence: list[dict[str, Any]],
        thought=None,
    ) -> ResidentRunResult | None:
        context = self._state_context_resolution(state)
        if self._is_prior_working_style_request(event) and context.get("status") == "ambiguous":
            reason = (
                "I found multiple equally supported previously verified ways for this current "
                "project/context. Current reality does not distinguish them, so I will not "
                "guess or dispatch a learned mutation; please tell me which prior way you mean."
            )
            state.data[_FAST_PATH_KEY] = {
                "status": "abandoned_ambiguous",
                "history_supplied_body_args": False,
                "verification_required": True,
            }
            return self._checkpoint_terminal_failure(event, state, reason=reason)
        return super()._deliberation_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    def _fail_postcondition_verification(
        self,
        event,
        state,
        intent,
        *,
        failure: str,
        thought=None,
    ):
        raw = state.data.get(_FAST_PATH_KEY)
        if isinstance(raw, dict) and raw.get("status") == "active":
            updated = dict(raw)
            updated["status"] = "prediction_error"
            updated["verification_contradicted"] = True
            updated["fallback"] = "fresh Investigation"
            state.data[_FAST_PATH_KEY] = updated
        return super()._fail_postcondition_verification(
            event,
            state,
            intent,
            failure=failure,
            thought=thought,
        )

    def _complete_successful_body_action(
        self,
        event,
        state,
        intent,
        *,
        response: str,
        reason: str,
    ):
        raw_fast = state.data.get(_FAST_PATH_KEY)
        fast = dict(raw_fast) if isinstance(raw_fast, dict) else {}
        if fast.get("status") == "active":
            fast["status"] = "verified"
            fast["fresh_postcondition_verified"] = True
            state.data[_FAST_PATH_KEY] = fast
            reason = (
                f"{reason}; a practiced resident-owned procedure removed one redundant "
                "deliberation pulse only after fresh current checks, and completion still "
                "required the ordinary independent postcondition verification"
            )
        elif self._is_prior_working_style_request(event):
            context = self._state_context_resolution(state)
            selected = context.get("selected")
            if context.get("status") == "resolved" and isinstance(selected, dict):
                support = int(selected.get("support_count") or 0)
                reliability = round(float(selected.get("reliability") or 0.0) * 100)
                reason = (
                    f"{reason}; reused a way previously independently verified {support} times "
                    f"for the current context (reliability {reliability}%) after fresh current checks"
                )
        return super()._complete_successful_body_action(
            event,
            state,
            intent,
            response=response,
            reason=reason,
        )

    def _enrich_thought_with_working_stage(self, thought, event) -> None:
        super()._enrich_thought_with_working_stage(thought, event)
        if not self._is_prior_working_style_request(event):
            return
        state = self.store.get_working_state()
        if state.current_event_id != event.event_id:
            return
        context = self._state_context_resolution(state)
        if context.get("status") == "resolved":
            reason = str(context.get("reason") or "").strip()
            if reason and reason not in thought.known:
                thought.known = (*thought.known, reason)
        elif context.get("status") == "ambiguous":
            unknown = (
                "verified prior context is ambiguous under the current project/reality evidence"
            )
            if unknown not in thought.unknown:
                thought.unknown = (*thought.unknown, unknown)
