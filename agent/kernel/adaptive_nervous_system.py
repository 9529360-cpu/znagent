from __future__ import annotations

import math
from typing import Iterable

from .adaptive_guidance import (
    schema_current_relation_terms,
    schema_superseded_relation_terms,
)
from .nervous_system import NeuralActivation, NeuralTrace, PersistentNervousSystem


class RealityAwareNervousSystem(PersistentNervousSystem):
    """Persistent nervous system whose schema recall follows reconsolidated reality.

    The stored trace is not rewritten for recall. Historical summary/features and
    contested relations remain available to reconsolidation and inspection. Only
    the live semantic view used for activation suppresses superseded relation
    values and adds the schema's current active relations.
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
            if score < 0.12:
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
