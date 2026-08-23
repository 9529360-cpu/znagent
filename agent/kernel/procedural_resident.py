from __future__ import annotations

"""First bounded L3 action-influence runtime slice.

This layer sits inside the resident hierarchy and leaves ordinary deliberation
unchanged unless current ZN cognition has independently formed more than one
legal action shape and present reality supports a sufficiently mature low-risk
procedural tendency. Learned evidence can reorder those shapes; it cannot supply
Body arguments, bypass anti-replay, skip verification, or become a fast path.
"""

from typing import Any

from .action import derive_native_action_intents
from .procedural_influence import (
    ProceduralActionInfluence,
    select_procedurally_influenced_intent,
)
from .transfer_incubation import TransferAwareSituatedResidentRuntime


class ProcedurallyInfluencedResidentRuntime(TransferAwareSituatedResidentRuntime):
    """Resident whose verified procedural evidence may bias native choices."""

    _PROCEDURAL_INFLUENCE_KEY = "procedural_action_influence"
    _PROCEDURAL_REVOKED_KEY = "procedural_revoked_tendencies"
    _MAX_PROCEDURAL_REVOKED = 8

    def _deliberation_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        investigation = self.investigator.current(event.event_id)
        facts = dict(investigation.facts) if investigation is not None else {}
        intents = derive_native_action_intents(event, facts=facts)
        if not intents:
            state.data.pop(self._PROCEDURAL_INFLUENCE_KEY, None)
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        candidates = self.verified_experiences.candidate_tendencies(limit=16)
        intent, influence = select_procedurally_influenced_intent(
            event,
            intents,
            candidates=candidates,
            current_domains=readiness.domains,
            facts=facts,
            revoked_tendency_ids=self._revoked_tendency_ids(state),
        )
        if intent is None or influence is None:
            state.data.pop(self._PROCEDURAL_INFLUENCE_KEY, None)
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        # Existing evidence-bound anti-replay remains stronger than learned
        # familiarity. A procedure that points at a movement already contradicted
        # under unchanged reality is immediately revoked for this event.
        if self._action_blocked_by_current_evidence(event, state, intent):
            self._activate_procedural_influence(state, influence)
            self._revoke_active_procedural_influence(
                state,
                reason="blocked_by_current_evidence",
            )
            self.store.save_working_state(state)
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        self._activate_procedural_influence(state, influence)
        self._begin_native_action_cycle(event, state, intent)
        self.store.save_working_state(state)
        if thought is not None:
            action = f"perform body action: {intent.kind}"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            known = (
                f"current reality-supported procedural candidate {influence.tendency_id} "
                f"strengthened an already-formed {intent.kind} choice"
            )
            if known not in thought.known:
                thought.known = (*thought.known, known)
            thought.reason = (
                f"{thought.reason}; verified procedural evidence biased only among current "
                "ZN-owned action shapes, while current event data still supplies the movement"
            )
            self._persist_enriched_thought(thought)
        return None

    def _native_action_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        result = super()._native_action_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )
        if state.stage == "native_investigation" and isinstance(
            state.data.get(self._PROCEDURAL_INFLUENCE_KEY),
            dict,
        ):
            self._revoke_active_procedural_influence(state, reason="body_failure")
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
        return result

    def _fail_postcondition_verification(
        self,
        event,
        state,
        intent,
        *,
        failure: str,
        thought=None,
    ):
        if isinstance(state.data.get(self._PROCEDURAL_INFLUENCE_KEY), dict):
            self._revoke_active_procedural_influence(
                state,
                reason="verification_contradiction",
            )
        return super()._fail_postcondition_verification(
            event,
            state,
            intent,
            failure=failure,
            thought=thought,
        )

    def _enrich_thought_with_working_stage(self, thought, event) -> None:
        super()._enrich_thought_with_working_stage(thought, event)
        state = self.store.get_working_state()
        if state.current_event_id != event.event_id:
            return
        raw = state.data.get(self._PROCEDURAL_INFLUENCE_KEY)
        if not isinstance(raw, dict):
            return
        tendency_id = str(raw.get("tendency_id") or "").strip()
        action_kind = str(raw.get("action_kind") or "unknown").strip() or "unknown"
        if not tendency_id:
            return
        if bool(raw.get("revoked")):
            known = (
                f"procedural candidate {tendency_id} was revoked for this event after "
                "current action evidence contradicted its route"
            )
        else:
            known = (
                f"procedural candidate {tendency_id} currently biases the already-formed "
                f"{action_kind} choice; it does not supply action arguments or waive verification"
            )
        if known not in thought.known:
            thought.known = (*thought.known, known)

    def _activate_procedural_influence(
        self,
        state,
        influence: ProceduralActionInfluence,
    ) -> None:
        data = influence.to_dict()
        data["revoked"] = False
        data["revocation_reason"] = None
        state.data[self._PROCEDURAL_INFLUENCE_KEY] = data

    def _revoke_active_procedural_influence(self, state, *, reason: str) -> None:
        raw = state.data.get(self._PROCEDURAL_INFLUENCE_KEY)
        if not isinstance(raw, dict):
            return
        tendency_id = str(raw.get("tendency_id") or "").strip()
        if not tendency_id:
            return
        revoked = list(self._revoked_tendency_ids(state))
        if tendency_id not in revoked:
            revoked.append(tendency_id)
        state.data[self._PROCEDURAL_REVOKED_KEY] = revoked[-self._MAX_PROCEDURAL_REVOKED :]
        updated: dict[str, Any] = dict(raw)
        updated["revoked"] = True
        updated["revocation_reason"] = str(reason or "current_evidence")[:80]
        state.data[self._PROCEDURAL_INFLUENCE_KEY] = updated

    def _revoked_tendency_ids(self, state) -> tuple[str, ...]:
        raw = state.data.get(self._PROCEDURAL_REVOKED_KEY)
        if not isinstance(raw, list):
            return ()
        return tuple(
            str(item)
            for item in raw[-self._MAX_PROCEDURAL_REVOKED :]
            if str(item).strip()
        )
