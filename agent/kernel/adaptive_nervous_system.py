from __future__ import annotations

import math
from typing import Iterable

from .adaptive_guidance import (
    active_schema_relations,
    schema_current_relation_terms,
    schema_reality_score,
    schema_superseded_relation_terms,
)
from .nervous_system import NeuralActivation, NeuralTrace, PersistentNervousSystem


class RealityAwareNervousSystem(PersistentNervousSystem):
    """Persistent nervous system whose schema recall follows reconsolidated reality.

    The stored trace is not rewritten for recall. Historical summary/features and
    contested relations remain available to reconsolidation and inspection. Only
    the live semantic view used for activation suppresses superseded relation
    values and adds the schema's current active relations.

    A reality-stabilized schema can also influence a neighboring schema through
    shared lived evidence. This transfer is deliberately bounded to two neural
    hops (schema -> lived trace -> schema) and is blocked when the two schemas
    currently disagree about the same structured relation family.
    """

    def activate(
        self,
        cues: str | Iterable[str],
        *,
        channels: Iterable[str] | None = None,
        limit: int = 8,
    ) -> list[NeuralActivation]:
        cue_text = cues if isinstance(cues, str) else " ".join(str(item) for item in cues)
        cue_tokens = self._tokens(cue_text)
        if not cue_tokens:
            return []
        allowed = {
            self._normalize_channel(item)
            for item in (channels or ())
            if str(item).strip()
        }
        traces = self._candidate_traces(limit=384)
        direct: dict[str, tuple[float, float]] = {}
        for trace in traces:
            if allowed and trace.channel not in allowed:
                continue
            trace_tokens = self._activation_tokens(trace)
            overlap = self._overlap(cue_tokens, trace_tokens)
            if overlap <= 0.0:
                continue
            recency = self._recency(trace.last_seen_at)
            repetition = min(1.0, math.log1p(trace.repetitions) / 4.0)
            score = (
                0.46 * overlap
                + 0.22 * trace.strength
                + 0.14 * trace.salience
                + 0.10 * recency
                + 0.08 * repetition
            )
            direct[trace.trace_id] = (self._unit(score), overlap)

        if not direct:
            return []

        seed_ids = [
            item[0]
            for item in sorted(
                direct.items(), key=lambda pair: pair[1][0], reverse=True
            )[:12]
        ]
        associative: dict[str, float] = {}
        for left, right, strength in self._links_for(seed_ids):
            if left in direct:
                associative[right] = max(
                    associative.get(right, 0.0),
                    direct[left][0] * strength * 0.30,
                )
            if right in direct:
                associative[left] = max(
                    associative.get(left, 0.0),
                    direct[right][0] * strength * 0.30,
                )

        by_id = {trace.trace_id: trace for trace in traces}
        transfer = self._reality_gated_schema_transfer(
            direct,
            by_id=by_id,
            allowed=allowed,
        )
        for trace_id, gain in transfer.items():
            associative[trace_id] = max(associative.get(trace_id, 0.0), gain)

        activations: list[NeuralActivation] = []
        for trace_id in set((*direct.keys(), *associative.keys())):
            trace = by_id.get(trace_id)
            if trace is None:
                trace = self._get_trace(trace_id)
            if trace is None or (allowed and trace.channel not in allowed):
                continue
            direct_score, overlap = direct.get(trace_id, (0.0, 0.0))
            gain = associative.get(trace_id, 0.0)
            score = self._unit(direct_score + gain)
            threshold = 0.04 if trace_id in transfer and direct_score <= 0.0 else 0.12
            if score < threshold:
                continue
            activations.append(
                NeuralActivation(
                    trace=trace,
                    activation=score,
                    cue_overlap=overlap,
                    associative_gain=gain,
                )
            )
        activations.sort(key=lambda item: item.activation, reverse=True)
        selected = activations[: max(1, int(limit))]
        self._mark_activated(selected)
        if selected:
            self._state.familiarity = self._unit(
                self._blend(
                    self._state.familiarity,
                    sum(item.activation for item in selected) / len(selected),
                    0.16,
                )
            )
            self._state.dominant_signal = selected[0].trace.summary[:500]
            self._save_state()
        return selected

    def _activation_tokens(self, trace: NeuralTrace) -> set[str]:
        base = self._tokens(f"{trace.summary} {' '.join(trace.features)}")
        if trace.channel != "schema":
            return base

        superseded = set(schema_superseded_relation_terms(trace))
        if superseded:
            base = {token for token in base if token not in superseded}
        current = self._tokens(" ".join(schema_current_relation_terms(trace)))
        return base | current

    def _reality_gated_schema_transfer(
        self,
        direct: dict[str, tuple[float, float]],
        *,
        by_id: dict[str, NeuralTrace],
        allowed: set[str],
    ) -> dict[str, float]:
        """Spread corrected structure across one shared lived-evidence bridge.

        This is not arbitrary graph diffusion. A source must be a directly
        activated schema with a meaningful reality-facing profile. The first hop
        must land on a non-schema lived trace. The second hop may reach another
        schema only when its current structured relations do not contradict the
        source. The resulting gain is a weak associative activation and cannot
        outrank a strong direct cue by itself.
        """
        sources: list[tuple[NeuralTrace, float, float]] = []
        for trace_id, (score, _overlap) in direct.items():
            trace = by_id.get(trace_id) or self._get_trace(trace_id)
            if trace is None or trace.channel != "schema":
                continue
            reality = schema_reality_score(trace)
            if reality < 0.50:
                continue
            sources.append((trace, score, reality))
        if not sources:
            return {}

        gains: dict[str, float] = {}
        for source, source_score, source_reality in sorted(
            sources,
            key=lambda item: item[1],
            reverse=True,
        )[:6]:
            first_hops: list[tuple[str, float]] = []
            for left, right, strength in self._links_for([source.trace_id]):
                other_id = right if left == source.trace_id else left
                other = by_id.get(other_id) or self._get_trace(other_id)
                if other is None or other.channel == "schema":
                    continue
                if strength < 0.08:
                    continue
                first_hops.append((other_id, strength))
            first_hops.sort(key=lambda item: item[1], reverse=True)

            for bridge_id, first_strength in first_hops[:12]:
                for left, right, second_strength in self._links_for([bridge_id]):
                    target_id = right if left == bridge_id else left
                    if target_id == source.trace_id or target_id in direct:
                        continue
                    target = by_id.get(target_id) or self._get_trace(target_id)
                    if target is None or target.channel != "schema":
                        continue
                    if allowed and target.channel not in allowed:
                        continue
                    if second_strength < 0.08:
                        continue
                    compatibility = self._schema_transfer_compatibility(source, target)
                    if compatibility <= 0.0:
                        continue
                    bridge_strength = math.sqrt(first_strength * second_strength)
                    gain = (
                        source_score
                        * bridge_strength
                        * source_reality
                        * compatibility
                        * 0.60
                    )
                    if gain < 0.04:
                        continue
                    gains[target_id] = max(gains.get(target_id, 0.0), self._unit(gain))
        return gains

    @staticmethod
    def _schema_transfer_compatibility(source: NeuralTrace, target: NeuralTrace) -> float:
        source_relations = active_schema_relations(source)
        target_relations = active_schema_relations(target)
        if not source_relations:
            return 0.0

        source_by_family: dict[str, set[str]] = {}
        for relation in source_relations:
            family = str(relation.get("family") or "")
            value = str(relation.get("value") or "")
            if family and value:
                source_by_family.setdefault(family, set()).add(value)
        target_by_family: dict[str, set[str]] = {}
        for relation in target_relations:
            family = str(relation.get("family") or "")
            value = str(relation.get("value") or "")
            if family and value:
                target_by_family.setdefault(family, set()).add(value)

        shared_families = set(source_by_family).intersection(target_by_family)
        for family in shared_families:
            if source_by_family[family].isdisjoint(target_by_family[family]):
                return 0.0

        if shared_families:
            return 1.0
        # Related schemas may describe different aspects of the same lived
        # situation. Permit a weaker transfer when no structured family clashes.
        return 0.62
