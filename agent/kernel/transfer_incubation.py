from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .adaptive_guidance import active_schema_relations
from .integrated_transfer import IntegratedTransferNervousSystem
from .intention_formation import (
    NativeIntentionCandidate,
    NativeIntentionFormation,
    SituatedIntentionalResidentRuntime,
)
from .schema_structure import SchemaStructurePlasticity

if TYPE_CHECKING:
    from .life import BodyState, SituationModel
    from .nervous_system import NeuralActivation


class TransferAwareSituatedResidentRuntime(SituatedIntentionalResidentRuntime):
    """Situated resident whose Will cautiously reuses corrected experience.

    A schema reached only through bounded cross-context transfer may seed one
    candidate, but association alone cannot mature it. Current Situation evidence
    must independently support the candidate relation before repetition is
    allowed to strengthen Will.

    Reality-tested transfer paths remain part of the lived neural substrate. Several
    mutually compatible corrected source schemas may now corroborate one target,
    while conflicting sources reduce its transfer pressure. The resulting evidence
    bundle follows the candidate into its event so later reality feedback can reshape
    every path that actually contributed, without rewriting any source schema truth.
    """

    _TRANSFER_MIN_GAIN = 0.04
    _TRANSFER_CONTRIBUTOR_LIMIT = 4

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.nervous = IntegratedTransferNervousSystem(self.store)
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

    @classmethod
    def _transfer_contributors(cls, activation: NeuralActivation) -> tuple[dict, ...]:
        raw = getattr(activation, "transfer_contributors", ())
        out: list[dict] = []
        for item in raw if isinstance(raw, (list, tuple)) else ():
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_trace_id") or "").strip()
            bridge_id = str(item.get("bridge_trace_id") or "").strip()
            if not source_id or not bridge_id:
                continue
            try:
                gain = max(0.0, min(1.0, float(item.get("gain") or 0.0)))
            except (TypeError, ValueError):
                gain = 0.0
            try:
                tendency = max(0.0, float(item.get("tendency") or 1.0))
            except (TypeError, ValueError):
                tendency = 1.0
            try:
                feedback_count = max(0, int(item.get("feedback_count") or 0))
            except (TypeError, ValueError):
                feedback_count = 0
            out.append(
                {
                    "source_trace_id": source_id,
                    "bridge_trace_id": bridge_id,
                    "gain": round(gain, 5),
                    "tendency": round(tendency, 5),
                    "feedback_count": feedback_count,
                }
            )
        if not out:
            source_id = str(
                getattr(activation, "transfer_source_trace_id", "") or ""
            ).strip()
            bridge_id = str(
                getattr(activation, "transfer_bridge_trace_id", "") or ""
            ).strip()
            if source_id and bridge_id:
                out.append(
                    {
                        "source_trace_id": source_id,
                        "bridge_trace_id": bridge_id,
                        "gain": round(cls._transfer_gain(activation), 5),
                        "tendency": round(
                            max(
                                0.0,
                                float(getattr(activation, "transfer_tendency", 1.0)),
                            ),
                            5,
                        ),
                        "feedback_count": max(
                            0,
                            int(getattr(activation, "transfer_feedback_count", 0)),
                        ),
                    }
                )
        return tuple(out[: cls._TRANSFER_CONTRIBUTOR_LIMIT])

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
        contributors = self._transfer_contributors(activation)
        try:
            consensus = max(
                0.0,
                min(1.0, float(getattr(activation, "transfer_consensus", 1.0))),
            )
        except (TypeError, ValueError):
            consensus = 1.0
        try:
            conflict_count = max(
                0,
                int(getattr(activation, "transfer_conflict_count", 0)),
            )
        except (TypeError, ValueError):
            conflict_count = 0
        if len(contributors) > 1:
            score += min(0.08, 0.025 * (len(contributors) - 1)) * consensus
        if conflict_count:
            score -= min(0.10, 0.025 * conflict_count)
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
                contributors = self._transfer_contributors(activation)
                source_schema_id = (
                    str(contributors[0].get("source_trace_id") or "")
                    if contributors
                    else ""
                )
                bridge_trace_id = (
                    str(contributors[0].get("bridge_trace_id") or "")
                    if contributors
                    else ""
                )
                try:
                    tendency = max(
                        0.0,
                        float(getattr(activation, "transfer_tendency", 1.0)),
                    )
                except (TypeError, ValueError):
                    tendency = 1.0
                try:
                    feedback_count = max(
                        0,
                        int(getattr(activation, "transfer_feedback_count", 0)),
                    )
                except (TypeError, ValueError):
                    feedback_count = 0
                try:
                    consensus = max(
                        0.0,
                        min(
                            1.0,
                            float(getattr(activation, "transfer_consensus", 1.0)),
                        ),
                    )
                except (TypeError, ValueError):
                    consensus = 1.0
                try:
                    conflict_count = max(
                        0,
                        int(getattr(activation, "transfer_conflict_count", 0)),
                    )
                except (TypeError, ValueError):
                    conflict_count = 0
                candidate.payload = {
                    **candidate.payload,
                    "transfer_informed": True,
                    "transfer_gain": round(transfer_gain, 5),
                    "transfer_context_supported": context_supported,
                    "transfer_context_basis": context_basis,
                    "transfer_source_schema_id": source_schema_id,
                    "transfer_bridge_trace_id": bridge_trace_id,
                    "transfer_tendency": round(tendency, 5),
                    "transfer_feedback_count": feedback_count,
                    "transfer_contributors": [dict(item) for item in contributors],
                    "transfer_consensus": round(consensus, 5),
                    "transfer_conflict_count": conflict_count,
                }
                if len(contributors) > 1:
                    integration = (
                        f"{len(contributors)} mutually compatible lived transfer paths "
                        "converged on this pattern"
                    )
                else:
                    integration = "one lived transfer path recalled this pattern"
                if conflict_count:
                    integration += (
                        f" while {conflict_count} conflicting source path(s) reduced "
                        "the transfer pressure"
                    )
                candidate.reason = (
                    f"{candidate.reason}; {integration}; {context_basis}"
                )
                if context_supported:
                    candidate.support = tuple(
                        dict.fromkeys(
                            (
                                *candidate.support,
                                f"current:{context_basis}",
                                f"transfer_sources:{len(contributors) or 1}",
                            )
                        )
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
                    "transferred evidence is relevant but cannot strengthen Will "
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
            contributors = self._transfer_contributors(schema_activation)
            try:
                consensus = max(
                    0.0,
                    min(
                        1.0,
                        float(getattr(schema_activation, "transfer_consensus", 1.0)),
                    ),
                )
            except (TypeError, ValueError):
                consensus = 1.0
            try:
                conflict_count = max(
                    0,
                    int(getattr(schema_activation, "transfer_conflict_count", 0)),
                )
            except (TypeError, ValueError):
                conflict_count = 0
            confidence = min(
                0.74,
                confidence
                + (0.06 if context_supported else -0.12)
                + min(0.05, 0.02 * max(0, len(contributors) - 1)) * consensus
                - min(0.06, 0.02 * conflict_count),
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
                "integrated cross-context recall plus current Situation support"
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

    def _complete_result(self, event, result):
        completed = super()._complete_result(event, result)
        self._apply_transfer_outcome_plasticity(completed.event)
        return completed

    @classmethod
    def _payload_transfer_contributors(cls, payload: dict) -> tuple[dict, ...]:
        raw = payload.get("transfer_contributors")
        out: list[dict] = []
        for item in raw if isinstance(raw, list) else ():
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_trace_id") or "").strip()
            bridge_id = str(item.get("bridge_trace_id") or "").strip()
            if not source_id or not bridge_id:
                continue
            try:
                gain = max(0.0, min(1.0, float(item.get("gain") or 0.0)))
            except (TypeError, ValueError):
                gain = 0.0
            out.append(
                {
                    "source_trace_id": source_id,
                    "bridge_trace_id": bridge_id,
                    "gain": gain,
                }
            )
        if not out:
            source_id = str(payload.get("transfer_source_schema_id") or "").strip()
            bridge_id = str(payload.get("transfer_bridge_trace_id") or "").strip()
            if source_id and bridge_id:
                try:
                    gain = max(
                        0.0,
                        min(1.0, float(payload.get("transfer_gain") or 0.0)),
                    )
                except (TypeError, ValueError):
                    gain = 0.0
                out.append(
                    {
                        "source_trace_id": source_id,
                        "bridge_trace_id": bridge_id,
                        "gain": gain,
                    }
                )
        deduped: dict[tuple[str, str], dict] = {}
        for item in out:
            key = (item["source_trace_id"], item["bridge_trace_id"])
            prior = deduped.get(key)
            if prior is None or float(item["gain"]) > float(prior["gain"]):
                deduped[key] = item
        return tuple(deduped.values())[: cls._TRANSFER_CONTRIBUTOR_LIMIT]

    def _apply_transfer_outcome_plasticity(self, event) -> str | None:
        """Shape every coherent path that contributed to a tested transfer."""
        payload = event.payload if isinstance(event.payload, dict) else {}
        if not bool(payload.get("transfer_informed")):
            return None
        if not bool(payload.get("transfer_context_supported")):
            return None

        target_id = str(payload.get("schema_trace_id") or "").strip()
        expectation = payload.get("schema_expectation")
        contributors = self._payload_transfer_contributors(payload)
        if not target_id or not contributors or not isinstance(expectation, dict):
            return None

        plasticity = SchemaStructurePlasticity(self.nervous)
        target = plasticity.resolve_schema(target_id)
        if target is None or target.channel != "schema":
            return None
        feedback = target.metadata.get("last_prediction_feedback")
        if not isinstance(feedback, dict):
            return None
        if str(feedback.get("event_id") or "").strip() != str(event.event_id):
            return None

        family = self._norm_relation_part(expectation.get("family"))
        value = self._norm_relation_part(expectation.get("value"))
        if not family or not value:
            return None
        label = f"{family}:{value}"
        supported = {
            self._norm_signal(item)
            for item in feedback.get("support") or ()
            if str(item).strip()
        }
        contradicted = {
            self._norm_signal(str(item).partition("->")[0])
            for item in feedback.get("contradictions") or ()
            if str(item).strip()
        }
        if label not in supported and label not in contradicted:
            return "untested"

        valid: list[tuple[object, object, float]] = []
        seen: set[tuple[str, str]] = set()
        for item in contributors:
            source = plasticity.resolve_schema(str(item["source_trace_id"]))
            bridge = self.nervous._get_trace(str(item["bridge_trace_id"]))
            if (
                source is None
                or source.channel != "schema"
                or source.trace_id == target.trace_id
                or bridge is None
                or bridge.channel in {"schema", "schema_merged"}
            ):
                continue
            if not any(
                bool(relation.get("stabilized_from_prediction_error"))
                for relation in active_schema_relations(source)
            ):
                continue
            key = (source.trace_id, bridge.trace_id)
            if key in seen:
                continue
            seen.add(key)
            if self.nervous.link_strength(source.trace_id, bridge.trace_id) <= 0.0:
                continue
            if self.nervous.link_strength(target.trace_id, bridge.trace_id) <= 0.0:
                continue
            valid.append((source, bridge, float(item.get("gain") or 0.0)))
        if not valid:
            return None

        target_gain_by_bridge: dict[str, float] = {}
        for _source, bridge, gain in valid:
            target_gain_by_bridge[bridge.trace_id] = max(
                target_gain_by_bridge.get(bridge.trace_id, 0.0),
                gain,
            )

        if label in supported:
            for source, bridge, gain in valid:
                self.nervous._strengthen_link(
                    source.trace_id,
                    bridge.trace_id,
                    amount=0.015 + 0.04 * gain,
                )
                self.nervous.record_transfer_feedback(
                    source.trace_id,
                    bridge.trace_id,
                    target.trace_id,
                    status="supported",
                )
            for bridge_id, gain in target_gain_by_bridge.items():
                self.nervous._strengthen_link(
                    target.trace_id,
                    bridge_id,
                    amount=0.04 + 0.10 * gain,
                )
            return "supported"

        for source, bridge, _gain in valid:
            self.nervous.record_transfer_feedback(
                source.trace_id,
                bridge.trace_id,
                target.trace_id,
                status="contradicted",
            )
        for bridge_id, gain in target_gain_by_bridge.items():
            self.nervous.weaken_transfer_link(
                target.trace_id,
                bridge_id,
                amount=min(0.42, 0.16 + 0.50 * gain),
            )
        return "contradicted"
