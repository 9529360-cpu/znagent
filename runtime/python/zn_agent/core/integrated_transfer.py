from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .adaptive_guidance import active_schema_relations, schema_reality_score
from .adaptive_nervous_system import (
    RealityAwareActivation,
    RealityAwareNervousSystem,
    RealityTransferEvidence,
)
from .models import utc_now
from .nervous_system import NeuralActivation, NeuralTrace


@dataclass(slots=True)
class _TransferPath:
    source: NeuralTrace
    target: NeuralTrace
    bridge_trace_id: str
    gain: float
    tendency: float
    feedback_count: int

    def payload(self) -> dict[str, object]:
        return {
            "source_trace_id": self.source.trace_id,
            "bridge_trace_id": self.bridge_trace_id,
            "gain": round(self.gain, 5),
            "tendency": round(self.tendency, 5),
            "feedback_count": int(self.feedback_count),
        }


@dataclass(slots=True)
class IntegratedTransferActivation(RealityAwareActivation):
    """A transferred activation with the coherent lived paths that supported it."""

    transfer_contributors: tuple[dict[str, object], ...] = field(default_factory=tuple)
    transfer_consensus: float = 1.0
    transfer_conflict_count: int = 0


class IntegratedTransferNervousSystem(RealityAwareNervousSystem):
    """Reality-aware recall that integrates competing cross-context evidence.

    One directly recalled corrected schema still cannot diffuse arbitrarily. Transfer
    remains bounded to schema -> lived trace -> schema. The difference is that paths
    reaching the same target are no longer reduced immediately to one maximum edge.
    Mutually compatible source schemas may corroborate one another, while source
    schemas that disagree on the same structured relation create conflict pressure.

    Transfer outcome history remains on lived bridge traces. When schema structure is
    later compacted, archived schema ids are resolved lazily through their merge chain,
    so old bridge history continues to influence the surviving canonical schema without
    a global migration or a second rule store.
    """

    _MAX_TRANSFER_CONTRIBUTORS = 4
    _MAX_COMPETING_SOURCES = 6

    def __init__(self, store):
        super().__init__(store)
        self._last_transfer_bundles: dict[str, dict[str, object]] = {}

    def activate(
        self,
        cues: str | Iterable[str],
        *,
        channels: Iterable[str] | None = None,
        limit: int = 8,
    ) -> list[NeuralActivation]:
        self._last_transfer_bundles = {}
        base = super().activate(cues, channels=channels, limit=limit)
        integrated: list[NeuralActivation] = []
        for item in base:
            if not isinstance(item, RealityAwareActivation):
                integrated.append(item)
                continue
            bundle = self._last_transfer_bundles.get(item.trace.trace_id) or {}
            contributors = tuple(
                dict(row)
                for row in bundle.get("contributors", ())
                if isinstance(row, dict)
            )[: self._MAX_TRANSFER_CONTRIBUTORS]
            raw_consensus = bundle.get("consensus")
            try:
                consensus = (
                    1.0
                    if raw_consensus is None
                    else max(0.0, min(1.0, float(raw_consensus)))
                )
            except (TypeError, ValueError):
                consensus = 1.0
            try:
                aggregate_tendency = float(
                    bundle.get("aggregate_tendency", item.transfer_tendency)
                )
            except (TypeError, ValueError):
                aggregate_tendency = item.transfer_tendency
            try:
                aggregate_feedback_count = int(
                    bundle.get("aggregate_feedback_count", item.transfer_feedback_count)
                )
            except (TypeError, ValueError):
                aggregate_feedback_count = item.transfer_feedback_count
            integrated.append(
                IntegratedTransferActivation(
                    trace=item.trace,
                    activation=item.activation,
                    cue_overlap=item.cue_overlap,
                    associative_gain=item.associative_gain,
                    transfer_gain=item.transfer_gain,
                    transfer_source_trace_id=item.transfer_source_trace_id,
                    transfer_bridge_trace_id=item.transfer_bridge_trace_id,
                    transfer_tendency=max(0.55, min(1.30, aggregate_tendency)),
                    transfer_feedback_count=max(0, aggregate_feedback_count),
                    transfer_contributors=contributors,
                    transfer_consensus=consensus,
                    transfer_conflict_count=max(
                        0,
                        int(bundle.get("conflict_count") or 0),
                    ),
                )
            )
        return integrated

    def _reality_gated_schema_transfer(
        self,
        direct: dict[str, tuple[float, float]],
        *,
        by_id: dict[str, NeuralTrace],
        allowed: set[str],
    ) -> dict[str, RealityTransferEvidence]:
        sources: list[tuple[NeuralTrace, float, float]] = []
        for trace_id, (score, _overlap) in direct.items():
            trace = by_id.get(trace_id) or self._get_trace(trace_id)
            if trace is None or trace.channel != "schema":
                continue
            if not any(
                bool(item.get("stabilized_from_prediction_error"))
                for item in active_schema_relations(trace)
            ):
                continue
            reality = schema_reality_score(trace)
            if reality < 0.50:
                continue
            sources.append((trace, score, reality))
        if not sources:
            return {}

        paths_by_target: dict[str, list[_TransferPath]] = {}
        for source, source_score, source_reality in sorted(
            sources,
            key=lambda item: item[1],
            reverse=True,
        )[: self._MAX_COMPETING_SOURCES]:
            first_hops: list[tuple[str, float]] = []
            for left, right, strength in self._links_for([source.trace_id]):
                other_id = right if left == source.trace_id else left
                other = by_id.get(other_id) or self._get_trace(other_id)
                if other is None or other.channel in {"schema", "schema_merged"}:
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
                    bridge_strength = self._unit((first_strength * second_strength) ** 0.5)
                    gain = self._unit(
                        source_score
                        * bridge_strength
                        * source_reality
                        * compatibility
                        * 0.60
                        * tendency
                    )
                    # A sub-threshold path may still matter if another independent
                    # source reaches the same target, but extremely weak edges stay noise.
                    if gain < 0.025:
                        continue
                    paths_by_target.setdefault(target_id, []).append(
                        _TransferPath(
                            source=source,
                            target=target,
                            bridge_trace_id=bridge_id,
                            gain=gain,
                            tendency=tendency,
                            feedback_count=feedback_count,
                        )
                    )

        integrated: dict[str, RealityTransferEvidence] = {}
        bundles: dict[str, dict[str, object]] = {}
        for target_id, raw_paths in paths_by_target.items():
            evidence, bundle = self._integrate_target_paths(raw_paths)
            if evidence is None or evidence.gain < 0.04:
                continue
            integrated[target_id] = evidence
            bundles[target_id] = bundle
        self._last_transfer_bundles = bundles
        return integrated

    def _integrate_target_paths(
        self,
        raw_paths: list[_TransferPath],
    ) -> tuple[RealityTransferEvidence | None, dict[str, object]]:
        # One source schema gets one vote. If it reaches the same target through
        # several bridges, its strongest currently-lived route represents it.
        strongest_by_source: dict[str, _TransferPath] = {}
        for path in raw_paths:
            prior = strongest_by_source.get(path.source.trace_id)
            if prior is None or path.gain > prior.gain:
                strongest_by_source[path.source.trace_id] = path
        paths = sorted(
            strongest_by_source.values(),
            key=lambda item: item.gain,
            reverse=True,
        )[: self._MAX_COMPETING_SOURCES]
        if not paths:
            return None, {}

        candidates: list[tuple[float, list[_TransferPath], list[_TransferPath], float]] = []
        for anchor in paths:
            coherent: list[_TransferPath] = [anchor]
            for path in paths:
                if path is anchor:
                    continue
                if all(
                    self._source_schemas_compatible(path.source, member.source)
                    for member in coherent
                ):
                    coherent.append(path)
                if len(coherent) >= self._MAX_TRANSFER_CONTRIBUTORS:
                    break
            coherent.sort(key=lambda item: item.gain, reverse=True)
            coherent = coherent[: self._MAX_TRANSFER_CONTRIBUTORS]
            coherent_ids = {item.source.trace_id for item in coherent}
            conflicting = [
                path
                for path in paths
                if path.source.trace_id not in coherent_ids
                and any(
                    self._source_schemas_conflict(path.source, member.source)
                    for member in coherent
                )
            ]
            primary = coherent[0]
            corroboration = sum(
                min(path.gain, primary.gain) * 0.22
                for path in coherent[1:]
            )
            conflict_pressure = sum(
                min(path.gain, primary.gain) * 0.30
                for path in conflicting[:3]
            )
            gain = self._unit(primary.gain + corroboration - conflict_pressure)
            coherent_weight = sum(path.gain for path in coherent)
            conflict_weight = sum(path.gain for path in conflicting[:3])
            consensus = (
                coherent_weight / (coherent_weight + conflict_weight)
                if conflict_weight > 0.0
                else 1.0
            )
            candidates.append((gain, coherent, conflicting, consensus))

        gain, coherent, conflicting, consensus = max(
            candidates,
            key=lambda item: (item[0], len(item[1]), item[3]),
        )
        if not coherent:
            return None, {}
        primary = coherent[0]
        tendency_weight = sum(max(0.001, path.gain) for path in coherent)
        tendency = sum(
            path.tendency * max(0.001, path.gain)
            for path in coherent
        ) / tendency_weight
        feedback_count = sum(path.feedback_count for path in coherent)
        evidence = RealityTransferEvidence(
            gain=gain,
            source_trace_id=primary.source.trace_id,
            bridge_trace_id=primary.bridge_trace_id,
            tendency=max(0.55, min(1.30, tendency)),
            feedback_count=feedback_count,
        )
        bundle = {
            "contributors": [path.payload() for path in coherent],
            "consensus": round(max(0.0, min(1.0, consensus)), 5),
            "conflict_count": len(conflicting),
            "competing_source_count": len(paths),
            "aggregate_tendency": round(max(0.55, min(1.30, tendency)), 5),
            "aggregate_feedback_count": feedback_count,
        }
        return evidence, bundle

    @staticmethod
    def _relation_values(trace: NeuralTrace) -> dict[str, set[str]]:
        grouped: dict[str, set[str]] = {}
        for relation in active_schema_relations(trace):
            family = str(relation.get("family") or "").strip()
            value = str(relation.get("value") or "").strip()
            if family and value:
                grouped.setdefault(family, set()).add(value)
        return grouped

    @classmethod
    def _source_schemas_conflict(cls, left: NeuralTrace, right: NeuralTrace) -> bool:
        left_values = cls._relation_values(left)
        right_values = cls._relation_values(right)
        for family in left_values.keys() & right_values.keys():
            if left_values[family].isdisjoint(right_values[family]):
                return True
        return False

    @classmethod
    def _source_schemas_compatible(cls, left: NeuralTrace, right: NeuralTrace) -> bool:
        return not cls._source_schemas_conflict(left, right)

    def _resolve_merged_schema_id(self, trace_id: str) -> str:
        current_id = str(trace_id or "").strip()
        if not current_id:
            return ""
        seen: set[str] = set()
        while current_id and current_id not in seen:
            seen.add(current_id)
            trace = self._get_trace(current_id)
            if trace is None or trace.channel != "schema_merged":
                return current_id
            current_id = str(trace.metadata.get("merged_into_schema_id") or "").strip()
        return current_id or str(trace_id or "").strip()

    @staticmethod
    def _bounded_counts(supported: int, contradicted: int) -> tuple[int, int]:
        supported = max(0, int(supported))
        contradicted = max(0, int(contradicted))
        while supported + contradicted > 64:
            supported //= 2
            contradicted //= 2
        return supported, contradicted

    def _canonical_bridge_history(self, bridge: NeuralTrace) -> list[dict[str, object]]:
        raw = bridge.metadata.get(self._TRANSFER_HISTORY_KEY)
        rows = raw if isinstance(raw, list) else ()
        merged: dict[tuple[str, str], dict[str, object]] = {}
        for item in rows:
            if not isinstance(item, dict):
                continue
            source_id = self._resolve_merged_schema_id(
                str(item.get("source_trace_id") or "")
            )
            target_id = self._resolve_merged_schema_id(
                str(item.get("target_trace_id") or "")
            )
            if not source_id or not target_id or source_id == target_id:
                continue
            key = (source_id, target_id)
            row = merged.setdefault(
                key,
                {
                    "source_trace_id": source_id,
                    "target_trace_id": target_id,
                    "supported": 0,
                    "contradicted": 0,
                    "feedback_count": 0,
                    "last_status": "",
                    "last_feedback_at": "",
                },
            )
            try:
                row["supported"] = int(row["supported"]) + max(
                    0, int(item.get("supported") or 0)
                )
                row["contradicted"] = int(row["contradicted"]) + max(
                    0, int(item.get("contradicted") or 0)
                )
            except (TypeError, ValueError):
                pass
            at = str(item.get("last_feedback_at") or "")
            if at >= str(row.get("last_feedback_at") or ""):
                row["last_feedback_at"] = at
                row["last_status"] = str(item.get("last_status") or "")

        out: list[dict[str, object]] = []
        for row in merged.values():
            supported, contradicted = self._bounded_counts(
                int(row.get("supported") or 0),
                int(row.get("contradicted") or 0),
            )
            row["supported"] = supported
            row["contradicted"] = contradicted
            row["feedback_count"] = supported + contradicted
            out.append(row)
        out.sort(key=lambda item: str(item.get("last_feedback_at") or ""))
        return out[-self._TRANSFER_HISTORY_LIMIT :]

    def record_transfer_feedback(
        self,
        source_id: str,
        bridge_id: str,
        target_id: str,
        *,
        status: str,
    ) -> dict | None:
        outcome = str(status or "").strip().lower()
        if outcome not in {"supported", "contradicted"}:
            return None
        source_id = self._resolve_merged_schema_id(source_id)
        target_id = self._resolve_merged_schema_id(target_id)
        source = self._get_trace(source_id)
        target = self._get_trace(target_id)
        bridge = self._get_trace(str(bridge_id))
        if (
            source is None
            or target is None
            or bridge is None
            or source.channel != "schema"
            or target.channel != "schema"
            or bridge.channel in {"schema", "schema_merged"}
            or source.trace_id == target.trace_id
        ):
            return None

        history = self._canonical_bridge_history(bridge)
        record = next(
            (
                item
                for item in history
                if str(item.get("source_trace_id") or "") == source.trace_id
                and str(item.get("target_trace_id") or "") == target.trace_id
            ),
            None,
        )
        if record is None:
            record = {
                "source_trace_id": source.trace_id,
                "target_trace_id": target.trace_id,
                "supported": 0,
                "contradicted": 0,
                "feedback_count": 0,
                "last_status": "",
                "last_feedback_at": "",
            }
            history.append(record)
        supported = max(0, int(record.get("supported") or 0))
        contradicted = max(0, int(record.get("contradicted") or 0))
        if supported + contradicted >= 64:
            supported //= 2
            contradicted //= 2
        if outcome == "supported":
            supported += 1
        else:
            contradicted += 1
        record.update(
            {
                "supported": supported,
                "contradicted": contradicted,
                "feedback_count": supported + contradicted,
                "last_status": outcome,
                "last_feedback_at": utc_now(),
            }
        )
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
        source_id = self._resolve_merged_schema_id(source_id)
        target_id = self._resolve_merged_schema_id(target_id)
        bridge = self._get_trace(str(bridge_id))
        if bridge is None or bridge.channel in {"schema", "schema_merged"}:
            return 1.0, 0
        supported = 0
        contradicted = 0
        for item in self._canonical_bridge_history(bridge):
            if (
                str(item.get("source_trace_id") or "") == source_id
                and str(item.get("target_trace_id") or "") == target_id
            ):
                supported += max(0, int(item.get("supported") or 0))
                contradicted += max(0, int(item.get("contradicted") or 0))
        total = supported + contradicted
        if total <= 0:
            return 1.0, 0
        posterior_support = (supported + 1.0) / (total + 2.0)
        direction = (posterior_support - 0.5) * 2.0
        evidence = min(1.0, total / 4.0)
        scale = 0.30 if direction >= 0.0 else 0.45
        tendency = 1.0 + evidence * scale * direction
        return max(0.55, min(1.30, tendency)), total
