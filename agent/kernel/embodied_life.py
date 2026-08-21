from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .life import BodyState, LivingState, SituationModel, ThoughtFrame, ZNLifeCore
from .models import AgentEvent


@dataclass(slots=True)
class CognitiveSituation(SituationModel):
    """Situation enriched with the resident's currently lived cognition step."""

    working_event_id: str | None = None
    working_stage: str = "idle"
    working_next_action: str | None = None
    investigation_id: str | None = None
    investigation_round: int = 0
    investigation_evidence_count: int = 0
    investigation_next_probe: str | None = None
    native_action_intent_id: str | None = None
    native_action_kind: str | None = None
    native_action_reason: str | None = None
    last_body_action_kind: str | None = None
    last_body_action_success: bool | None = None
    last_body_action_error: str | None = None
    cognitive_increment_id: str | None = None
    cognitive_increment_source: str | None = None
    cognitive_increment_question: str | None = None
    cognitive_increment_confidence: float | None = None


class EmbodiedLifeCore(ZNLifeCore):
    """Life core where Thought is formed from the resident's active cognition state.

    The base life loop already supplies continuity, body sensing, events,
    impasses and native Thought. This layer makes ongoing orientation,
    investigation, deliberation, body movement and borrowed cognition part of
    Situation itself, so each new Thought is a consequence of what ZN just
    experienced.
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

        raw_intent = working.data.get("native_action_intent")
        intent = raw_intent if isinstance(raw_intent, dict) else {}
        raw_result = working.data.get("native_action_result")
        action_result = raw_result if isinstance(raw_result, dict) else {}
        raw_increment = working.data.get("cognitive_increment")
        increment = raw_increment if isinstance(raw_increment, dict) else {}
        data = asdict(base)
        return CognitiveSituation(
            **data,
            working_event_id=working.current_event_id,
            working_stage=str(working.stage or "idle"),
            working_next_action=working.next_action,
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
            native_action_intent_id=(
                str(intent.get("intent_id")) if intent.get("intent_id") else None
            ),
            native_action_kind=(
                str(intent.get("kind")) if intent.get("kind") else None
            ),
            native_action_reason=(
                str(intent.get("reason")) if intent.get("reason") else None
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
        )

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
        if not situation.active_event_id:
            return thought

        stage = situation.working_stage
        stage_known = f"my current cognition stage is {stage}"
        if stage_known not in thought.known:
            thought.known = (*thought.known, stage_known)

        if situation.investigation_id:
            investigation_known = (
                f"investigation {situation.investigation_id} has completed "
                f"{situation.investigation_round} round(s) and retained "
                f"{situation.investigation_evidence_count} observation(s)"
            )
            if investigation_known not in thought.known:
                thought.known = (*thought.known, investigation_known)

        if situation.last_body_action_kind:
            if situation.last_body_action_success is False:
                body_unknown = (
                    situation.last_body_action_error
                    or f"body action {situation.last_body_action_kind} failed"
                )
                if body_unknown not in thought.unknown:
                    thought.unknown = (*thought.unknown, body_unknown)
                body_known = f"my last body movement was {situation.last_body_action_kind} and it failed"
            else:
                body_known = f"my last body movement was {situation.last_body_action_kind}"
            if body_known not in thought.known:
                thought.known = (*thought.known, body_known)

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
        ):
            data[key] = tuple(data.get(key) or ())
        data.setdefault("working_event_id", None)
        data.setdefault("working_stage", "idle")
        data.setdefault("working_next_action", None)
        data.setdefault("investigation_id", None)
        data.setdefault("investigation_round", 0)
        data.setdefault("investigation_evidence_count", 0)
        data.setdefault("investigation_next_probe", None)
        data.setdefault("native_action_intent_id", None)
        data.setdefault("native_action_kind", None)
        data.setdefault("native_action_reason", None)
        data.setdefault("last_body_action_kind", None)
        data.setdefault("last_body_action_success", None)
        data.setdefault("last_body_action_error", None)
        data.setdefault("cognitive_increment_id", None)
        data.setdefault("cognitive_increment_source", None)
        data.setdefault("cognitive_increment_question", None)
        data.setdefault("cognitive_increment_confidence", None)
        return CognitiveSituation(**data)
