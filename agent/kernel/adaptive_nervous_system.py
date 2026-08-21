from __future__ import annotations

import math
from contextlib import closing
from dataclasses import dataclass
from typing import Iterable

from .adaptive_guidance import (
    active_schema_relations,
    schema_current_relation_terms,
    schema_reality_score,
    schema_superseded_relation_terms,
)
from .models import utc_now
from .nervous_system import NeuralActivation, NeuralTrace, PersistentNervousSystem


@dataclass(slots=True)
class RealityTransferEvidence:
    """The strongest lived two-hop path responsible for one schema transfer."""

    gain: float
    source_trace_id: str
    bridge_trace_id: str
    tendency: float = 1.0
    feedback_count: int = 0


@dataclass(slots=True)
class RealityAwareActivation(NeuralActivation):
    """One neural activation with explicit bounded-transfer provenance."""

    transfer_gain: float = 0.0
    transfer_source_trace_id: str = ""
    transfer_bridge_trace_id: str = ""
    transfer_tendency: float = 1.0
    transfer_feedback_count: int = 0


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

    Lived bridge traces retain bounded feedback about whether their past transfers
    held up in reality. Repeated support gradually favors that same bridge in
    future recall; repeated contradiction suppresses it. This history remains
    part of the neural substrate instead of becoming a separate context-rule
    store or planner policy.
    """

    _TRANSFER_HISTORY_KEY = "reality_transfer_history"
    _TRANSFER_HISTORY_LIMIT = 32

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
        for trace_id, evidence in transfer.items():
            associative[trace_id] = max(
                associative.get(trace_id, 0.0),
                evidence.gain,
            )

        activations: list[NeuralActivation] = []
        for trace_id in set((*direct.keys(), *associative.keys())):
            trace = by_id.get(trace_id)
            if trace is None:
                trace = self._get_trace(trace_id)
            if trace is None or (allowed and trace.channel not in allowed):
                continue
            direct_score, overlap = direct.get(trace_id, (0.0, 0.0))
            gain = associative.get(trace_id, 0.0)
            transfer_evidence = transfer.get(trace_id)
            transfer_gain = transfer_evidence.gain if transfer_evidence is not None else 0.0
            score = self._unit(direct_score + gain)
            threshold = 0.04 if transfer_gain > 0.0 and direct_score <= 0.0 else 0.12
            if score < threshold:
                continue
            activations.append(
                RealityAwareActivation(
                    trace=trace,
                    activation=score,
                    cue_overlap=overlap,
                    associative_gain=gain,
                    transfer_gain=transfer_gain,
                    transfer_source_trace_id=(
                        transfer_evidence.source_trace_id
                        if transfer_evidence is not None
                        else ""
                    ),
                    transfer_bridge_trace_id=(
                        transfer_evidence.bridge_trace_id
                        if transfer_evidence is not None
                        else ""
                    ),
                    transfer_tendency=(
                        transfer_evidence.tendency
                        if transfer_evidence is not None
                        else 1.0
                    ),
                    transfer_feedback_count=(
                        transfer_evidence.feedback_count
                        if transfer_evidence is not None
                        else 0
                    ),
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
    ) -> dict[str, RealityTransferEvidence]:
        """Spread corrected structure across one shared lived-evidence bridge.

        This is not arbitrary graph diffusion. A source must be a directly
        activated schema with at least one relation that was corrected and then
        stabilized by lived prediction error. The first hop must land on a
        non-schema lived trace. The second hop may reach another schema only when
        its current structured relations do not contradict the source. The
        resulting gain is a weak associative activation and cannot outrank a
        strong direct cue by itself.

        The strongest source/bridge path is retained as provenance so later Will
        feedback can reshape that exact transfer route without rewriting either
        schema's structured relations. Repeated relation-level feedback stored on
        the lived bridge gently biases which otherwise-compatible route wins.
        """
        sources: list[tuple[NeuralTrace, float, float]] = []
        for trace_id, (score, _overlap) in direct.items():
            trace = by_id.get(trace_id) or self._get_trace(trace_id)
            if trace is None or trace.channel != "schema":
                continue
            current_relations = active_schema_relations(trace)
            if not any(
                bool(item.get("stabilized_from_prediction_error"))
                for item in current_relations
            ):
                continue
            reality = schema_reality_score(trace)
            if reality < 0.50:
                continue
            sources.append((trace, score, reality))
        if not sources:
            return {}

        gains: dict[str, RealityTransferEvidence] = {}
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
                    tendency, feedback_count = self.transfer_tendency(
                        source.trace_id,
                        bridge_id,
                        target.trace_id,
                    )
                    bridge_strength = math.sqrt(first_strength * second_strength)
                    gain = self._unit(
                        source_score
                        * bridge_strength
                        * source_reality
                        * compatibility
                        * 0.60
                        * tendency
                    )
                    if gain < 0.04:
                        continue
                    evidence = RealityTransferEvidence(
                        gain=gain,
                        source_trace_id=source.trace_id,
                        bridge_trace_id=bridge_id,
                        tendency=tendency,
                        feedback_count=feedback_count,
                    )
                    prior = gains.get(target_id)
                    if prior is None or evidence.gain > prior.gain:
                        gains[target_id] = evidence
        return gains

    def record_transfer_feedback(
        self,
        source_id: str,
        bridge_id: str,
        target_id: str,
        *,
        status: str,
    ) -> dict | None:
        """Keep bounded reality feedback on the lived bridge that carried transfer."""
        outcome = str(status or "").strip().lower()
        if outcome not in {"supported", "contradicted"}:
            return None

        source = self._get_trace(str(source_id))
        bridge = self._get_trace(str(bridge_id))
        target = self._get_trace(str(target_id))
        if (
            source is None
            or target is None
            or bridge is None
            or source.channel != "schema"
            or target.channel != "schema"
            or bridge.channel == "schema"
            or source.trace_id == target.trace_id
        ):
            return None

        raw_history = bridge.metadata.get(self._TRANSFER_HISTORY_KEY)
        history = [
            dict(item)
            for item in (raw_history if isinstance(raw_history, list) else ())
            if isinstance(item, dict)
        ]
        index = next(
            (
                idx
                for idx, item in enumerate(history)
                if str(item.get("source_trace_id") or "") == source.trace_id
                and str(item.get("target_trace_id") or "") == target.trace_id
            ),
            None,
        )
        prior = history[index] if index is not None else {}
        try:
            supported = max(0, int(prior.get("supported") or 0))
        except (TypeError, ValueError):
            supported = 0
        try:
            contradicted = max(0, int(prior.get("contradicted") or 0))
        except (TypeError, ValueError):
            contradicted = 0

        # Preserve a long-running ratio without allowing unbounded counters.
        if supported + contradicted >= 64:
            supported //= 2
            contradicted //= 2
        if outcome == "supported":
            supported += 1
        else:
            contradicted += 1

        record = {
            "source_trace_id": source.trace_id,
            "target_trace_id": target.trace_id,
            "supported": supported,
            "contradicted": contradicted,
            "feedback_count": supported + contradicted,
            "last_status": outcome,
            "last_feedback_at": utc_now(),
        }
        if index is None:
            history.append(record)
        else:
            history[index] = record
        history.sort(key=lambda item: str(item.get("last_feedback_at") or ""))
        bridge.metadata[self._TRANSFER_HISTORY_KEY] = history[
            -self._TRANSFER_HISTORY_LIMIT :
        ]
        self._save_trace(bridge)
        return dict(record)

    def transfer_tendency(
        self,
        source_id: str,
        bridge_id: str,
        target_id: str,
    ) -> tuple[float, int]:
        """Return a smoothed path multiplier learned from repeated lived feedback."""
        bridge = self._get_trace(str(bridge_id))
        if bridge is None or bridge.channel == "schema":
            return 1.0, 0
        raw_history = bridge.metadata.get(self._TRANSFER_HISTORY_KEY)
        history = raw_history if isinstance(raw_history, list) else ()
        record = next(
            (
                item
                for item in history
                if isinstance(item, dict)
                and str(item.get("source_trace_id") or "") == str(source_id)
                and str(item.get("target_trace_id") or "") == str(target_id)
            ),
            None,
        )
        if not isinstance(record, dict):
            return 1.0, 0
        try:
            supported = max(0, int(record.get("supported") or 0))
            contradicted = max(0, int(record.get("contradicted") or 0))
        except (TypeError, ValueError):
            return 1.0, 0
        total = supported + contradicted
        if total <= 0:
            return 1.0, 0

        # Beta(1,1) smoothing keeps one lucky or unlucky observation from becoming
        # policy. Evidence influence reaches full weight only after four tested
        # transfers, so tendency emerges from repeated life rather than one event.
        posterior_support = (supported + 1.0) / (total + 2.0)
        direction = (posterior_support - 0.5) * 2.0
        evidence = min(1.0, total / 4.0)
        scale = 0.30 if direction >= 0.0 else 0.45
        tendency = 1.0 + evidence * scale * direction
        return max(0.55, min(1.30, tendency)), total

    def weaken_transfer_link(
        self,
        left_id: str,
        right_id: str,
        *,
        amount: float,
    ) -> float:
        """Weaken one specific learned transfer edge without changing schema truth."""
        if left_id == right_id:
            return 0.0
        left, right = sorted((str(left_id), str(right_id)))
        penalty = self._unit(amount)
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT strength FROM neural_links WHERE left_id=? AND right_id=?",
                (left, right),
            ).fetchone()
            if not row:
                return 0.0
            old = self._unit(float(row["strength"]))
            strength = self._unit(old * (1.0 - penalty))
            if strength < 0.02:
                conn.execute(
                    "DELETE FROM neural_links WHERE left_id=? AND right_id=?",
                    (left, right),
                )
                strength = 0.0
            else:
                conn.execute(
                    "UPDATE neural_links SET strength=?,updated_at=? "
                    "WHERE left_id=? AND right_id=?",
                    (strength, utc_now(), left, right),
                )
            conn.commit()
        return strength

    def link_strength(self, left_id: str, right_id: str) -> float:
        """Read one existing neural edge strength for bounded plasticity checks."""
        if left_id == right_id:
            return 0.0
        left, right = sorted((str(left_id), str(right_id)))
        for seen_left, seen_right, strength in self._links_for([left]):
            if seen_left == left and seen_right == right:
                return self._unit(strength)
        return 0.0

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
