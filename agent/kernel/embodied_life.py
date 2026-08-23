from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .life import BodyState, LivingState, SituationModel, ThoughtFrame, ZNLifeCore
from .models import AgentEvent


@dataclass(slots=True)
class CognitiveSituation(SituationModel):
    """Situation enriched with what ZN is cognitively and intentionally living now."""

    working_event_id: str | None = None
    working_stage: str = "idle"
    working_next_action: str | None = None
    task_goal: str | None = None
    task_current_gap: str | None = None
    task_expected_outcome_kind: str | None = None
    task_verification_history_count: int = 0
    investigation_id: str | None = None
    investigation_round: int = 0
    investigation_evidence_count: int = 0
    investigation_next_probe: str | None = None
    procedural_applicability: tuple[dict[str, Any], ...] = ()
    native_action_intent_id: str | None = None
    native_action_kind: str | None = None
    native_action_reason: str | None = None
    last_body_action_kind: str | None = None
    last_body_action_success: bool | None = None
    last_body_action_error: str | None = None
    last_verification_kind: str | None = None
    last_verification_verified: bool | None = None
    last_verification_error: str | None = None
    cognitive_increment_id: str | None = None
    cognitive_increment_source: str | None = None
    cognitive_increment_question: str | None = None
    cognitive_increment_confidence: float | None = None
    active_intention_id: str | None = None
    active_intention_description: str | None = None
    active_intention_status: str | None = None
    active_intention_priority: int | None = None
    active_intention_next_task: str | None = None
    active_intention_related_event_id: str | None = None
    active_intention_last_outcome: str | None = None
    nervous_tone: str | None = None
    nervous_valence: float = 0.0
    nervous_arousal: float = 0.0
    nervous_tension: float = 0.0
    nervous_curiosity: float = 0.0
    nervous_familiarity: float = 0.0
    nervous_fatigue: float = 0.0
    activated_neural_traces: tuple[str, ...] = ()


class EmbodiedLifeCore(ZNLifeCore):
    """Life core where Thought is formed from ZN's lived state.

    Ongoing investigation, body movement, borrowed cognition, durable Will,
    associative neural memory, and persistent affect are all present in
    Situation before Thought is formed. An external caller does not reconstruct
    these after the pulse.
    """

    def _build_situation(
        self,
        *,
        previous: LivingState,
        body: BodyState,
        next_event: AgentEvent | None,
        capabilities: tuple[str, ...],
        external_brains: tuple[str, ...],
        changes: tuple[str, ...],
    ) -> CognitiveSituation:
        base = super()._build_situation(
            previous=previous,
            body=body,
            next_event=next_event,
            capabilities=capabilities,
            external_brains=external_brains,
            changes=changes,
        )
        working = self.store.get_working_state()
        investigation = None
        event_id = working.current_event_id or base.active_event_id
        investigator = getattr(self.resident, "investigator", None)
        if event_id and investigator is not None:
            try:
                investigation = investigator.current(event_id)
            except Exception:
                investigation = None

        intention = None
        will = getattr(self.resident, "will", None)
        if will is not None:
            try:
                intention = will.primary()
            except Exception:
                intention = None

        nervous = getattr(self.resident, "nervous", None)
        affect = None
        neural_summaries: tuple[str, ...] = ()
        nervous_tone: str | None = None
        if nervous is not None:
            try:
                affect = nervous.snapshot()
                nervous_tone = nervous.describe_state()
                cue = (
                    base.active_task
                    or (intention.description if intention is not None else None)
                    or working.next_action
                    or previous.attention
                    or ""
                )
                if cue:
                    activations = nervous.activate(cue, limit=4)
                    neural_summaries = tuple(
                        item.trace.summary[:500] for item in activations[:4]
                    )
            except Exception:
                affect = None
                neural_summaries = ()
                nervous_tone = None

        raw_execution = working.data.get("execution_context")
        execution = raw_execution if isinstance(raw_execution, dict) else {}
        raw_expected = execution.get("expected_outcome")
        expected = raw_expected if isinstance(raw_expected, dict) else {}
        raw_history = execution.get("verification_history")
        verification_history = raw_history if isinstance(raw_history, list) else []
        raw_applicability = working.data.get("procedural_applicability")
        procedural_applicability = self._safe_procedural_applicability(raw_applicability)
        raw_intent = working.data.get("native_action_intent")
        action_intent = raw_intent if isinstance(raw_intent, dict) else {}
        raw_result = working.data.get("native_action_result")
        action_result = raw_result if isinstance(raw_result, dict) else {}
        raw_verification = working.data.get("native_verification_result")
        verification = raw_verification if isinstance(raw_verification, dict) else {}
        raw_increment = working.data.get("cognitive_increment")
        increment = raw_increment if isinstance(raw_increment, dict) else {}
        local_failure = str(working.data.get("local_failure") or "").strip() or None
        verification_failed = (
            bool(verification)
            and "verified" in verification
            and not bool(verification.get("verified"))
        )
        data = asdict(base)
        return CognitiveSituation(
            **data,
            working_event_id=working.current_event_id,
            working_stage=str(working.stage or "idle"),
            working_next_action=working.next_action,
            task_goal=(str(execution.get("goal")) if execution.get("goal") else None),
            task_current_gap=(
                str(execution.get("current_gap"))
                if execution.get("current_gap")
                else None
            ),
            task_expected_outcome_kind=(
                str(expected.get("kind")) if expected.get("kind") else None
            ),
            task_verification_history_count=len(verification_history),
            investigation_id=(
                investigation.investigation_id if investigation is not None else None
            ),
            investigation_round=(investigation.rounds if investigation is not None else 0),
            investigation_evidence_count=(
                len(investigation.evidence) if investigation is not None else 0
            ),
            investigation_next_probe=(
                investigation.next_probe if investigation is not None else None
            ),
            procedural_applicability=procedural_applicability,
            native_action_intent_id=(
                str(action_intent.get("intent_id"))
                if action_intent.get("intent_id")
                else None
            ),
            native_action_kind=(
                str(action_intent.get("kind")) if action_intent.get("kind") else None
            ),
            native_action_reason=(
                str(action_intent.get("reason")) if action_intent.get("reason") else None
            ),
            last_body_action_kind=(
                str(action_result.get("kind")) if action_result.get("kind") else None
            ),
            last_body_action_success=(
                bool(action_result.get("success"))
                if "success" in action_result
                else None
            ),
            last_body_action_error=(
                str(action_result.get("error")) if action_result.get("error") else None
            ),
            last_verification_kind=(
                str(verification.get("kind")) if verification.get("kind") else None
            ),
            last_verification_verified=(
                bool(verification.get("verified"))
                if "verified" in verification
                else None
            ),
            last_verification_error=(local_failure if verification_failed else None),
            cognitive_increment_id=(
                str(increment.get("increment_id"))
                if increment.get("increment_id")
                else None
            ),
            cognitive_increment_source=(
                str(increment.get("source")) if increment.get("source") else None
            ),
            cognitive_increment_question=(
                str(increment.get("question")) if increment.get("question") else None
            ),
            cognitive_increment_confidence=(
                float(increment.get("confidence"))
                if increment.get("confidence") is not None
                else None
            ),
            active_intention_id=(intention.intention_id if intention is not None else None),
            active_intention_description=(
                intention.description if intention is not None else None
            ),
            active_intention_status=(intention.status if intention is not None else None),
            active_intention_priority=(intention.priority if intention is not None else None),
            active_intention_next_task=(
                intention.next_task if intention is not None else None
            ),
            active_intention_related_event_id=(
                intention.related_event_id if intention is not None else None
            ),
            active_intention_last_outcome=(
                intention.last_outcome if intention is not None else None
            ),
            nervous_tone=nervous_tone,
            nervous_valence=(float(affect.valence) if affect is not None else 0.0),
            nervous_arousal=(float(affect.arousal) if affect is not None else 0.0),
            nervous_tension=(float(affect.tension) if affect is not None else 0.0),
            nervous_curiosity=(float(affect.curiosity) if affect is not None else 0.0),
            nervous_familiarity=(
                float(affect.familiarity) if affect is not None else 0.0
            ),
            nervous_fatigue=(float(affect.fatigue) if affect is not None else 0.0),
            activated_neural_traces=neural_summaries,
        )

    @staticmethod
    def _safe_procedural_applicability(raw: Any) -> tuple[dict[str, Any], ...]:
        if not isinstance(raw, list):
            return ()
        safe: list[dict[str, Any]] = []
        for item in raw[-8:]:
            if not isinstance(item, dict):
                continue
            safe.append(
                {
                    "evaluation_id": str(item.get("evaluation_id") or "")[:40],
                    "tendency_id": str(item.get("tendency_id") or "")[:40],
                    "status": str(item.get("status") or "untested")[:20],
                    "action_kind": str(item.get("action_kind") or "unknown")[:80],
                    "candidate_maturity_state": str(
                        item.get("candidate_maturity_state") or "candidate"
                    )[:40],
                    "candidate_reliability": float(
                        item.get("candidate_reliability") or 0.0
                    ),
                    "candidate_inhibited": bool(item.get("candidate_inhibited")),
                    "matched_fields": [
                        str(value)[:80] for value in item.get("matched_fields") or ()
                    ][:16],
                    "mismatched_fields": [
                        str(value)[:80] for value in item.get("mismatched_fields") or ()
                    ][:16],
                    "untested_fields": [
                        str(value)[:80] for value in item.get("untested_fields") or ()
                    ][:16],
                    "reality_matched_fields": [
                        str(value)[:80]
                        for value in item.get("reality_matched_fields") or ()
                    ][:8],
                    "context_fingerprint": str(
                        item.get("context_fingerprint") or ""
                    )[:64],
                }
            )
        return tuple(safe)

    def _form_thought(
        self,
        *,
        previous: LivingState,
        situation: SituationModel,
        drives: tuple[str, ...],
    ) -> ThoughtFrame:
        thought = super()._form_thought(
            previous=previous,
            situation=situation,
            drives=drives,
        )
        if not isinstance(situation, CognitiveSituation):
            return thought

        if situation.nervous_tone:
            tone_known = f"my current internal tone is {situation.nervous_tone}"
            if tone_known not in thought.known:
                thought.known = (*thought.known, tone_known)
        for trace in situation.activated_neural_traces[:3]:
            memory_known = f"an associated lived trace became active: {trace}"
            if memory_known not in thought.known:
                thought.known = (*thought.known, memory_known)

        # Persistent affect has a functional influence on cognition. Familiar
        # associated experience slightly stabilizes confidence; strong tension
        # slightly reduces it so native observation is favored over certainty.
        if situation.activated_neural_traces and situation.nervous_familiarity >= 0.60:
            thought.confidence = min(1.0, thought.confidence + 0.05)
        if situation.nervous_tension >= 0.70:
            thought.confidence = max(0.0, thought.confidence - 0.12)

        # When no event or impasse currently owns attention, ZN still has a
        # durable Will. A concrete next step may become an internal event; an
        # intention without a step remains present without inventing work.
        if not situation.active_event_id:
            if situation.active_impasse_id:
                return thought
            if situation.active_intention_id and situation.active_intention_description:
                known = (
                    f"I still hold intention {situation.active_intention_id}: "
                    f"{situation.active_intention_description}"
                )
                if known not in thought.known:
                    thought.known = (*thought.known, known)
                if situation.active_intention_last_outcome:
                    outcome = (
                        "the last step of this intention resulted in: "
                        f"{situation.active_intention_last_outcome}"
                    )
                    if outcome not in thought.known:
                        thought.known = (*thought.known, outcome)
                thought.focus = situation.active_intention_description

                if (
                    situation.active_intention_status == "active"
                    and situation.active_intention_next_task
                    and not situation.active_intention_related_event_id
                ):
                    action = (
                        "advance intention with next step: "
                        f"{situation.active_intention_next_task}"
                    )
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.chosen_action = action
                    thought.action_kind = "intention"
                    thought.action_target = situation.active_intention_id
                    thought.reason = (
                        "a durable intention has a concrete native next step ready to pursue"
                    )
                    thought.confidence = max(thought.confidence, 0.95)
                else:
                    action = "maintain the active intention until a concrete next step exists"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.chosen_action = action
                    thought.action_kind = "observe"
                    thought.action_target = None
                    thought.reason = (
                        "the intention persists, but there is no new concrete step to execute"
                    )
                return thought
            return thought

        stage = situation.working_stage
        stage_known = f"my current cognition stage is {stage}"
        if stage_known not in thought.known:
            thought.known = (*thought.known, stage_known)

        if situation.task_goal:
            goal_known = f"my active task goal remains: {situation.task_goal[:700]}"
            if goal_known not in thought.known:
                thought.known = (*thought.known, goal_known)
        if situation.task_current_gap and situation.task_current_gap not in thought.unknown:
            thought.unknown = (*thought.unknown, situation.task_current_gap)
        if situation.task_expected_outcome_kind:
            expected_known = (
                "my current completion criterion requires independent "
                f"{situation.task_expected_outcome_kind} verification"
            )
            if expected_known not in thought.known:
                thought.known = (*thought.known, expected_known)
        if situation.task_verification_history_count:
            history_known = (
                f"this task retains {situation.task_verification_history_count} prior "
                "verification result(s) as bounded execution history"
            )
            if history_known not in thought.known:
                thought.known = (*thought.known, history_known)

        if situation.investigation_id:
            investigation_known = (
                f"investigation {situation.investigation_id} has completed "
                f"{situation.investigation_round} round(s) and retained "
                f"{situation.investigation_evidence_count} observation(s)"
            )
            if investigation_known not in thought.known:
                thought.known = (*thought.known, investigation_known)

        for applicability in situation.procedural_applicability[:4]:
            tendency_id = str(applicability.get("tendency_id") or "unknown")
            status = str(applicability.get("status") or "untested")
            action_kind = str(applicability.get("action_kind") or "unknown")
            if status == "supported":
                procedural_known = (
                    f"current independent evidence supports procedural candidate "
                    f"{tendency_id} for {action_kind}, but it remains observational"
                )
            elif status == "mismatch":
                procedural_known = (
                    f"current evidence mismatches procedural candidate {tendency_id} "
                    f"for {action_kind}; it must not qualify"
                )
            else:
                procedural_known = (
                    f"procedural candidate {tendency_id} for {action_kind} remains "
                    "untested by current independent evidence and must not qualify"
                )
            if procedural_known not in thought.known:
                thought.known = (*thought.known, procedural_known)

        if situation.last_body_action_kind:
            if situation.last_body_action_success is False:
                body_unknown = (
                    situation.last_body_action_error
                    or f"body action {situation.last_body_action_kind} failed"
                )
                if body_unknown not in thought.unknown:
                    thought.unknown = (*thought.unknown, body_unknown)
                body_known = (
                    f"my last body movement was {situation.last_body_action_kind} and it failed"
                )
            else:
                body_known = f"my last body movement was {situation.last_body_action_kind}"
            if body_known not in thought.known:
                thought.known = (*thought.known, body_known)

        if situation.last_verification_verified is not None:
            verification_kind = situation.last_verification_kind or "postcondition"
            if situation.last_verification_verified:
                verification_known = (
                    f"my last {verification_kind} verification matched current reality"
                )
            else:
                verification_known = (
                    f"my last {verification_kind} verification was contradicted by current reality"
                )
                verification_error = (
                    situation.last_verification_error
                    or "the previous postcondition was not verified"
                )
                if verification_error not in thought.unknown:
                    thought.unknown = (*thought.unknown, verification_error)
            if verification_known not in thought.known:
                thought.known = (*thought.known, verification_known)

        if situation.cognitive_increment_id:
            increment_known = (
                f"borrowed cognition {situation.cognitive_increment_id} returned from "
                f"{situation.cognitive_increment_source or 'an external resource'}"
            )
            if situation.cognitive_increment_confidence is not None:
                increment_known += (
                    f" with confidence={situation.cognitive_increment_confidence:.2f}"
                )
            if increment_known not in thought.known:
                thought.known = (*thought.known, increment_known)

        if stage in {"idle", "orient"}:
            action = "orient to the active event using my own state"
            kind = "event"
            reason = "the active event has not yet been oriented into a native action path"
        elif stage == "native_investigation":
            if situation.investigation_next_probe:
                action = f"run native probe: {situation.investigation_next_probe}"
                reason = "the previous evidence produced another concrete body observation to test"
            else:
                action = "advance native investigation from current evidence"
                reason = "the active task still has a native evidence path to explore"
            kind = "investigate"
        elif stage == "native_deliberation":
            action = "integrate native evidence and isolate the remaining gap"
            kind = "deliberate"
            reason = "native probes are exhausted and their evidence must now be integrated"
        elif stage == "native_action" and situation.native_action_kind:
            action = f"perform body action: {situation.native_action_kind}"
            kind = "body_action"
            reason = (
                situation.native_action_reason
                or "native cognition selected a concrete movement of my body"
            )
            intent_known = (
                f"I intend body action {situation.native_action_kind} "
                f"as {situation.native_action_intent_id or 'the next movement'}"
            )
            if intent_known not in thought.known:
                thought.known = (*thought.known, intent_known)
        elif stage == "native_verification":
            action = "verify the previous body movement against current reality"
            kind = "verify_action"
            reason = (
                "the body movement returned successfully, but the requested state must "
                "be independently observed before task completion"
            )
        elif stage == "external_cognition":
            action = "consult an external cognitive resource for the isolated gap"
            kind = "external_cognition"
            reason = "native cognition has already isolated a specific unresolved gap"
        elif stage == "cognition_integration" and situation.cognitive_increment_id:
            action = "integrate borrowed cognition into my own state"
            kind = "integrate_cognition"
            reason = (
                "external cognition has returned as bounded input and must be judged "
                "inside my own continuing state before I complete or act"
            )
        else:
            return thought

        if action not in thought.possible_actions:
            thought.possible_actions = (*thought.possible_actions, action)
        thought.chosen_action = action
        thought.action_kind = kind
        thought.action_target = situation.active_event_id
        thought.reason = reason
        thought.confidence = max(thought.confidence, 0.9)
        return thought

    @staticmethod
    def _situation_from_raw(raw: dict[str, Any]) -> CognitiveSituation:
        data = dict(raw)
        for key in (
            "body_signals",
            "unresolved_questions",
            "local_capabilities",
            "external_brains",
            "changes",
            "activated_neural_traces",
            "procedural_applicability",
        ):
            data[key] = tuple(data.get(key) or ())
        data.setdefault("working_event_id", None)
        data.setdefault("working_stage", "idle")
        data.setdefault("working_next_action", None)
        data.setdefault("task_goal", None)
        data.setdefault("task_current_gap", None)
        data.setdefault("task_expected_outcome_kind", None)
        data.setdefault("task_verification_history_count", 0)
        data.setdefault("investigation_id", None)
        data.setdefault("investigation_round", 0)
        data.setdefault("investigation_evidence_count", 0)
        data.setdefault("investigation_next_probe", None)
        data.setdefault("procedural_applicability", ())
        data.setdefault("native_action_intent_id", None)
        data.setdefault("native_action_kind", None)
        data.setdefault("native_action_reason", None)
        data.setdefault("last_body_action_kind", None)
        data.setdefault("last_body_action_success", None)
        data.setdefault("last_body_action_error", None)
        data.setdefault("last_verification_kind", None)
        data.setdefault("last_verification_verified", None)
        data.setdefault("last_verification_error", None)
        data.setdefault("cognitive_increment_id", None)
        data.setdefault("cognitive_increment_source", None)
        data.setdefault("cognitive_increment_question", None)
        data.setdefault("cognitive_increment_confidence", None)
        data.setdefault("active_intention_id", None)
        data.setdefault("active_intention_description", None)
        data.setdefault("active_intention_status", None)
        data.setdefault("active_intention_priority", None)
        data.setdefault("active_intention_next_task", None)
        data.setdefault("active_intention_related_event_id", None)
        data.setdefault("active_intention_last_outcome", None)
        data.setdefault("nervous_tone", None)
        data.setdefault("nervous_valence", 0.0)
        data.setdefault("nervous_arousal", 0.0)
        data.setdefault("nervous_tension", 0.0)
        data.setdefault("nervous_curiosity", 0.0)
        data.setdefault("nervous_familiarity", 0.0)
        data.setdefault("nervous_fatigue", 0.0)
        data.setdefault("activated_neural_traces", ())
        return CognitiveSituation(**data)