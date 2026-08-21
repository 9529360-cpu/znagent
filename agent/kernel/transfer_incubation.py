from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .adaptive_nervous_system import RealityAwareNervousSystem
from .intention_formation import (
    NativeIntentionCandidate,
    NativeIntentionFormation,
    SituatedIntentionalResidentRuntime,
)

if TYPE_CHECKING:
    from .life import BodyState, SituationModel
    from .nervous_system import NeuralActivation


class TransferAwareSituatedResidentRuntime(SituatedIntentionalResidentRuntime):
    """Situated resident whose Will cautiously reuses corrected experience.

    A schema reached only through bounded cross-context transfer may seed one
    candidate, but association alone cannot mature it. Current Situation evidence
    must independently support the candidate relation before repetition is
    allowed to strengthen Will.
    """

    _TRANSFER_MIN_GAIN = 0.04

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.nervous = RealityAwareNervousSystem(self.store)
        self.intention_formation = NativeIntentionFormation(
            self.nervous,
            resident=self,
        )

    @staticmethod
    def _transfer_gain(activation: NeuralActivation) -> float:
        try:
            value = float(getattr(activation, "transfer_gain", 0.0))
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, value))

    def _transfer_context_support(
        self,
        candidate: NativeIntentionCandidate,
        *,
        situation: SituationModel | None,
        body: BodyState | None,
    ) -> tuple[bool, str]:
        expectation = candidate.payload.get("schema_expectation")
        if not isinstance(expectation, dict):
            return False, "candidate has no structured relation"
        family = self._norm_relation_part(expectation.get("family"))
        value = self._norm_relation_part(expectation.get("value"))
        if not family or not value:
            return False, "candidate relation is incomplete"

        if body is not None:
            if family == "system" and self._norm_relation_part(body.system) == value:
                return True, f"body:system:{value}"
            if family == "architecture" and self._norm_relation_part(body.architecture) == value:
                return True, f"body:architecture:{value}"
            if family == "disk_state":
                ratio = float(body.disk_free_ratio)
                observed = "low" if ratio < 0.10 else "constrained" if ratio < 0.20 else "healthy"
                if observed == value:
                    return True, f"body:disk_state:{value}"

        if situation is not None:
            signals = [
                *(str(item) for item in tuple(situation.body_signals or ())),
                *(str(item) for item in tuple(situation.changes or ())),
            ]
            if situation.recent_outcome:
                signals.append(str(situation.recent_outcome))
            label = f"{family}:{value}"
            equals = f"{family}={value}"
            for signal in signals[:24]:
                normalized = self._norm_signal(signal)
                if label in normalized or equals in normalized:
                    return True, f"situation:{label}"
        return False, f"current Situation does not support {family}:{value}"

    @staticmethod
    def _norm_relation_part(raw) -> str:
        text = str(raw or "").strip().lower().replace(" ", "_")
        return re.sub(r"[^a-z0-9_+./-]+", "", text)[:120]

    @staticmethod
    def _norm_signal(raw) -> str:
        text = re.sub(r"\s+", "_", str(raw or "").strip().lower())
        return re.sub(r"[^a-z0-9_+./:=-]+", "", text)[:1000]

    def _candidate_score(
        self,
        activation: NeuralActivation,
        candidate: NativeIntentionCandidate,
        *,
        context_supported: bool,
    ) -> float:
        score = self._formed_candidate_score(activation, candidate)
        transfer_gain = self._transfer_gain(activation)
        if transfer_gain <= 0.0:
            return score
        score -= 0.18
        if context_supported:
            score += 0.34
        score += min(0.08, 0.40 * transfer_gain)
        return score

    def _incubate_primary_intention(self, thought) -> bool:
        life_state = self.life.snapshot()
        situation = life_state.current_situation
        if situation is not None and (
            situation.active_event_id or situation.active_impasse_id
        ):
            return False
        primary = self.will.primary()
        if primary is None or primary.status != "active":
            return False
        if primary.next_task or primary.related_event_id:
            return False

        activations = [
            item
            for item in self.nervous.activate(
                primary.description,
                channels=self._INCUBATION_CHANNELS,
                limit=8,
            )
            if item.trace.channel == "schema"
            and (
                item.activation >= 0.30
                or self._transfer_gain(item) >= self._TRANSFER_MIN_GAIN
            )
        ]
        if not activations:
            existing = self.will.get(primary.intention_id)
            if existing is not None and existing.candidate_step:
                self._surface_incubating_candidate(thought, existing)
                return True
            return False

        formed: list[
            tuple[NeuralActivation, NativeIntentionCandidate, bool, str]
        ] = []
        for activation in activations:
            candidate = self.intention_formation.form(
                primary,
                activation,
                situation=situation,
                body=life_state.body,
            )
            if candidate is None:
                continue
            transfer_gain = self._transfer_gain(activation)
            context_supported = False
            context_basis = "direct schema recall"
            if transfer_gain > 0.0:
                context_supported, context_basis = self._transfer_context_support(
                    candidate,
                    situation=situation,
                    body=life_state.body,
                )
                candidate.payload = {
                    **candidate.payload,
                    "transfer_informed": True,
                    "transfer_gain": round(transfer_gain, 5),
                    "transfer_context_supported": context_supported,
                    "transfer_context_basis": context_basis,
                }
                candidate.reason = (
                    f"{candidate.reason}; a reality-corrected neighboring schema "
                    f"recalled this pattern through shared lived evidence; {context_basis}"
                )
                if context_supported:
                    candidate.support = tuple(
                        dict.fromkeys((*candidate.support, f"current:{context_basis}"))
                    )[-12:]
            formed.append((activation, candidate, context_supported, context_basis))
        if not formed:
            return False

        schema_activation, candidate, context_supported, context_basis = max(
            formed,
            key=lambda item: self._candidate_score(
                item[0],
                item[1],
                context_supported=item[2],
            ),
        )
        schema = schema_activation.trace
        step = candidate.step
        if primary.current_step == step and primary.last_outcome:
            return False

        transfer_gain = self._transfer_gain(schema_activation)
        is_transfer = transfer_gain > 0.0
        existing = self.will.get(primary.intention_id)
        if is_transfer and not context_supported and existing is not None:
            if existing.candidate_step:
                self._surface_incubating_candidate(thought, existing)
                waiting = (
                    "a transferred schema is relevant but cannot strengthen Will "
                    f"until current reality supports it: {context_basis}"
                )
                if waiting not in thought.known:
                    thought.known = (*thought.known, waiting)
                return True

        confidence = min(
            0.96,
            0.34
            + 0.42 * schema_activation.activation
            + 0.14 * schema.strength
            + 0.10 * schema.salience,
        )
        if is_transfer:
            confidence = min(
                0.72,
                confidence + (0.06 if context_supported else -0.12),
            )

        updated = self.will.incubate_candidate(
            primary.intention_id,
            kind=candidate.kind,
            step=step,
            reason=candidate.reason,
            confidence=confidence,
            support=candidate.support,
            payload=candidate.payload,
        )
        self._surface_incubating_candidate(thought, updated)

        if is_transfer and not context_supported:
            waiting = (
                "this candidate was seeded by cross-context recall and is frozen "
                f"until current reality supports it: {context_basis}"
            )
            if waiting not in thought.known:
                thought.known = (*thought.known, waiting)
            return True

        if updated.candidate_repetitions >= 2 and updated.candidate_maturity >= 0.72:
            action = "commit the matured native candidate as my next intention step"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            thought.chosen_action = action
            thought.action_kind = "incubate"
            thought.action_target = updated.intention_id
            evidence = (
                "cross-context recall plus current Situation support"
                if is_transfer
                else "repeated resident-side evidence"
            )
            thought.reason = (
                f"{thought.reason}; a candidate next step matured through {evidence} "
                f"(maturity={updated.candidate_maturity:.2f})"
            )
            thought.confidence = max(
                thought.confidence,
                min(0.95, updated.candidate_maturity),
            )
        return True
