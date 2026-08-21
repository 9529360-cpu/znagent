from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .life import BodyState, LivingState, SituationModel, ThoughtFrame, ZNLifeCore
from .models import AgentEvent, utc_now


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


class EmbodiedLifeCore(ZNLifeCore):
    """Life core where Thought is formed from the resident's active cognition state.

    The base life loop already supplies continuity, body sensing, events,
    impasses and native Thought. This layer makes ongoing orientation,
    investigation and deliberation part of Situation itself, so the next
    Thought is a consequence of what ZN just did rather than a post-hoc rewrite
    by the caller.
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
        elif stage == "external_cognition":
            action = "consult an external cognitive resource for the isolated gap"
            kind = "external_cognition"
            reason = "native cognition has already isolated a specific unresolved gap"
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
        return CognitiveSituation(**data)
