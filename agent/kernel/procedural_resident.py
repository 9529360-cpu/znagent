from __future__ import annotations

"""Bounded L3 influence and resident-owned recovery over native choices.

This layer sits inside the active world-aware resident hierarchy. Ordinary
single-action deliberation is unchanged. Choice recovery can consume either an
explicit current ``native_action_options`` contract or a resident-formed choice
whose equivalence is proven from a typed task postcondition plus current
Investigation evidence. Procedural evidence may reorder eligible choices, but it
never supplies Body arguments, bypasses anti-replay, skips verification, or
becomes a fast path.
"""

from typing import Any, Iterable

from .action import (
    NativeActionIntent,
    current_text_equals_postcondition,
    derive_native_action_intents,
)
from .procedural_influence import (
    ProceduralActionInfluence,
    select_procedurally_influenced_intent,
)
from .world_closed_loop import WorldAwareTransferResidentRuntime


class ProcedurallyInfluencedResidentRuntime(WorldAwareTransferResidentRuntime):
    """Active resident with reality-gated procedural and native choice behavior."""

    _PROCEDURAL_INFLUENCE_KEY = "procedural_action_influence"
    _PROCEDURAL_REVOKED_KEY = "procedural_revoked_tendencies"
    _NATIVE_CHOICE_RECOVERY_KEY = "native_choice_recovery"
    _RECOVERABLE_CHOICE_SOURCES = frozenset({"structured_choice", "resident_choice"})
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
        # Any prior recovery marker described the previous movement. It remains
        # visible through action/verification but cannot silently describe a new
        # deliberation cycle.
        state.data.pop(self._NATIVE_CHOICE_RECOVERY_KEY, None)

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
            if self._recover_from_blocked_structured_choices(
                event,
                state,
                intents,
                thought=thought,
            ):
                return None
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
            # A later choice, if any, is a native recovery rather than a
            # procedurally selected movement. Keep only the event-local revoked
            # ID so failure cannot be misattributed to the old candidate.
            state.data.pop(self._PROCEDURAL_INFLUENCE_KEY, None)
            if self._recover_from_blocked_structured_choices(
                event,
                state,
                intents,
                thought=thought,
            ):
                return None
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

    def _recover_from_blocked_structured_choices(
        self,
        event,
        state,
        intents: Iterable[NativeActionIntent],
        *,
        thought=None,
    ) -> bool:
        """Advance to a later proven choice after current evidence blocks one.

        The bounded choice must already exist in current ZN action formation.
        Explicit event choices are accepted as their own structured contract;
        resident choices are accepted only because ``action.py`` formed them
        from typed goal semantics plus current Investigation evidence. This
        method never infers alternatives from task text, memories, model text or
        failed action arguments.
        """

        current = tuple(intents)
        if len(current) < 2:
            return False
        sources = {str(intent.source or "") for intent in current}
        if len(sources) != 1 or not sources.issubset(self._RECOVERABLE_CHOICE_SOURCES):
            return False
        choice_source = next(iter(sources))

        blocked_count = 0
        for index, intent in enumerate(current):
            if self._action_blocked_by_current_evidence(event, state, intent):
                blocked_count += 1
                continue
            if blocked_count == 0:
                return False

            self._begin_native_action_cycle(event, state, intent)
            state.data[self._NATIVE_CHOICE_RECOVERY_KEY] = {
                "selected_index": index,
                "choice_count": len(current),
                "blocked_prior_choices": blocked_count,
                "action_kind": intent.kind,
                "choice_source": choice_source,
                "evidence_version": self._evidence_fingerprint(event.event_id)[:16],
            }
            self.store.save_working_state(state)
            if thought is not None:
                action = f"perform body action: {intent.kind}"
                if action not in thought.possible_actions:
                    thought.possible_actions = (*thought.possible_actions, action)
                known = (
                    f"current evidence blocked {blocked_count} earlier {choice_source} "
                    f"choice(s); choice {index + 1} remains admissible"
                )
                if known not in thought.known:
                    thought.known = (*thought.known, known)
                thought.reason = (
                    f"{thought.reason}; current Investigation evidence ruled out earlier "
                    "bounded alternatives, so native deliberation selected the first "
                    "remaining structured choice"
                )
                self._persist_enriched_thought(thought)
            return True
        return False

    def _verification_contract(self, event, intent):
        """Accept the exact-text goal contract used by resident choice formation."""

        explicit = event.payload.get("expected_outcome")
        if isinstance(explicit, dict) and str(
            explicit.get("kind") or ""
        ).strip().lower() == "text_equals":
            goal = current_text_equals_postcondition(event)
            if goal is None:
                return {
                    "kind": "unsupported",
                    "requested_kind": "text_equals",
                    "error": "text_equals postcondition requires path and expected_text",
                    "intent_id": intent.intent_id,
                    "action_signature": self._intent_signature(intent),
                }
            return {
                **goal,
                "intent_id": intent.intent_id,
                "action_signature": self._intent_signature(intent),
            }
        return super()._verification_contract(event, intent)

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

        recovery = state.data.get(self._NATIVE_CHOICE_RECOVERY_KEY)
        if isinstance(recovery, dict):
            try:
                selected_index = int(recovery.get("selected_index"))
                blocked = int(recovery.get("blocked_prior_choices") or 0)
            except (TypeError, ValueError):
                selected_index = -1
                blocked = 0
            action_kind = str(recovery.get("action_kind") or "unknown").strip() or "unknown"
            choice_source = str(
                recovery.get("choice_source") or "structured_choice"
            ).strip() or "structured_choice"
            if selected_index >= 0 and blocked > 0:
                known = (
                    f"native choice recovery selected {choice_source} choice {selected_index + 1} "
                    f"({action_kind}) after current evidence blocked {blocked} earlier choice(s)"
                )
                if known not in thought.known:
                    thought.known = (*thought.known, known)

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
