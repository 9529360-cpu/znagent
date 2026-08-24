from __future__ import annotations

import math
from contextlib import closing
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Iterable

from .models import utc_now
from .reconsolidation import SchemaReconsolidator

if TYPE_CHECKING:
    from .nervous_system import NeuralTrace, PersistentNervousSystem


@dataclass(slots=True)
class SchemaStructuralMerge:
    canonical_schema_id: str
    absorbed_schema_id: str
    source_overlap: float
    feature_overlap: float
    at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SchemaStructurePlasticity:
    """Collapse redundant schema nodes while preserving lived distinctions.

    A schema is merged only when its concrete supporting experiences overlap
    substantially with another schema and their structured predictions do not
    conflict. This is resident-native graph plasticity: no model call and no
    text-similarity heuristic decides whether two life patterns are the same.

    Absorbed schema nodes become low-salience archival traces rather than
    disappearing abruptly. This keeps durable historical references readable
    while removing the node from active schema recall and allowing normal
    forgetting to prune it later.
    """

    _STATE_PRIORITY = {
        "consolidated": 0,
        "labile": 1,
        "reconsolidating": 2,
        "contested": 3,
    }

    def __init__(self, nervous: PersistentNervousSystem):
        self.nervous = nervous
        self.reconsolidator = SchemaReconsolidator(nervous)

    def compact(
        self,
        *,
        seed_ids: Iterable[str] = (),
        limit: int = 96,
    ) -> list[SchemaStructuralMerge]:
        preferred = {
            trace.trace_id
            for trace_id in seed_ids
            if (trace := self.resolve_schema(str(trace_id))) is not None
            and trace.channel == "schema"
        }
        active = [
            trace
            for trace in self.nervous.recent_traces(max(16, int(limit) * 3))
            if trace.channel == "schema"
        ][: max(2, int(limit))]
        if len(active) < 2:
            return []

        profiles = {
            trace.trace_id: self.reconsolidator._profile(trace)
            for trace in active
        }
        sources = {
            trace.trace_id: self._source_ids(trace)
            for trace in active
        }
        merges: list[SchemaStructuralMerge] = []
        removed: set[str] = set()
        active.sort(key=self._schema_stability, reverse=True)

        for index, left in enumerate(active):
            if left.trace_id in removed:
                continue
            for right in active[index + 1 :]:
                if right.trace_id in removed or left.trace_id == right.trace_id:
                    continue
                left_sources = sources.get(left.trace_id, set())
                right_sources = sources.get(right.trace_id, set())
                source_overlap, feature_overlap = self._structural_overlap(
                    profiles[left.trace_id],
                    profiles[right.trace_id],
                    left_sources,
                    right_sources,
                )
                if not self._mergeable(
                    profiles[left.trace_id],
                    profiles[right.trace_id],
                    left_sources,
                    right_sources,
                    source_overlap=source_overlap,
                    feature_overlap=feature_overlap,
                ):
                    continue

                canonical, absorbed = self._choose_canonical(
                    left,
                    right,
                    preferred=preferred,
                )
                canonical_profile = profiles[canonical.trace_id]
                absorbed_profile = profiles[absorbed.trace_id]
                canonical_sources = sources[canonical.trace_id]
                absorbed_sources = sources[absorbed.trace_id]
                at = utc_now()
                self._merge_schema_nodes(
                    canonical,
                    absorbed,
                    canonical_profile,
                    absorbed_profile,
                    canonical_sources,
                    absorbed_sources,
                    at=at,
                )
                profiles[canonical.trace_id] = canonical.metadata.get(
                    "prediction_profile",
                    canonical_profile,
                )
                sources[canonical.trace_id] = canonical_sources | absorbed_sources
                removed.add(absorbed.trace_id)
                merges.append(
                    SchemaStructuralMerge(
                        canonical_schema_id=canonical.trace_id,
                        absorbed_schema_id=absorbed.trace_id,
                        source_overlap=round(source_overlap, 5),
                        feature_overlap=round(feature_overlap, 5),
                        at=at,
                    )
                )
                if absorbed.trace_id == left.trace_id:
                    left = canonical
                    break
        return merges

    def resolve_schema(self, trace_id: str) -> NeuralTrace | None:
        """Follow an archived merge chain to the active canonical schema."""
        current = self.nervous._get_trace(trace_id)
        seen: set[str] = set()
        while (
            current is not None
            and current.channel == "schema_merged"
            and current.trace_id not in seen
        ):
            seen.add(current.trace_id)
            target = str(current.metadata.get("merged_into_schema_id") or "").strip()
            if not target:
                break
            current = self.nervous._get_trace(target)
        return current

    def _structural_overlap(
        self,
        left_profile: dict[str, Any],
        right_profile: dict[str, Any],
        left_sources: set[str],
        right_sources: set[str],
    ) -> tuple[float, float]:
        shared = left_sources & right_sources
        minimum = min(len(left_sources), len(right_sources))
        source_overlap = (len(shared) / minimum) if minimum else 0.0
        left_features = self._profile_feature_set(left_profile)
        right_features = self._profile_feature_set(right_profile)
        union = left_features | right_features
        feature_overlap = (
            len(left_features & right_features) / len(union)
            if union
            else 0.0
        )
        return self._unit(source_overlap), self._unit(feature_overlap)

    def _mergeable(
        self,
        left_profile: dict[str, Any],
        right_profile: dict[str, Any],
        left_sources: set[str],
        right_sources: set[str],
        *,
        source_overlap: float,
        feature_overlap: float,
    ) -> bool:
        if len(left_sources & right_sources) < 2:
            return False
        if self._profiles_conflict(left_profile, right_profile):
            return False
        if source_overlap >= 0.78:
            return True
        return source_overlap >= 0.62 and feature_overlap >= 0.45

    def _profiles_conflict(
        self,
        left: dict[str, Any],
        right: dict[str, Any],
    ) -> bool:
        left_relations = self._exclusive_expectations(left)
        right_relations = self._exclusive_expectations(right)
        for family in left_relations.keys() & right_relations.keys():
            if left_relations[family].isdisjoint(right_relations[family]):
                return True
        return False

    def _exclusive_expectations(
        self,
        profile: dict[str, Any],
    ) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for item in profile.get("relations") or ():
            family = str(item.get("family") or "")
            value = str(item.get("value") or "")
            if family not in SchemaReconsolidator._EXCLUSIVE or not value:
                continue
            if item.get("status") == "contested":
                continue
            if float(item.get("confidence") or 0.0) < 0.55:
                continue
            result.setdefault(family, set()).add(value)
        return result

    def _choose_canonical(
        self,
        left: NeuralTrace,
        right: NeuralTrace,
        *,
        preferred: set[str],
    ) -> tuple[NeuralTrace, NeuralTrace]:
        left_preferred = left.trace_id in preferred
        right_preferred = right.trace_id in preferred
        if left_preferred != right_preferred:
            return (left, right) if left_preferred else (right, left)
        if self._schema_stability(left) >= self._schema_stability(right):
            return left, right
        return right, left

    def _schema_stability(self, trace: NeuralTrace) -> float:
        sources = len(self._source_ids(trace))
        prediction = float(trace.metadata.get("prediction_confidence") or 0.0)
        return (
            0.34 * trace.strength
            + 0.22 * trace.salience
            + 0.16 * min(1.0, sources / 8.0)
            + 0.14
            * min(1.0, math.log1p(max(1, trace.repetitions)) / 3.0)
            + 0.14 * prediction
        )

    def _merge_schema_nodes(
        self,
        canonical: NeuralTrace,
        absorbed: NeuralTrace,
        canonical_profile: dict[str, Any],
        absorbed_profile: dict[str, Any],
        canonical_sources: set[str],
        absorbed_sources: set[str],
        *,
        at: str,
    ) -> None:
        all_sources = canonical_sources | absorbed_sources
        new_sources = absorbed_sources - canonical_sources
        canonical_count = max(1, len(canonical_sources))
        absorbed_count = max(1, len(absorbed_sources))
        total_weight = canonical_count + absorbed_count
        profile = self._merge_profiles(
            canonical_profile,
            absorbed_profile,
            canonical_count=canonical_count,
            absorbed_count=absorbed_count,
            source_count=len(all_sources),
        )

        feature_names = [
            str(item.get("feature") or "")
            for item in profile.get("features") or ()
            if str(item.get("feature") or "")
        ]
        structural_features = [
            feature
            for feature in (
                *canonical.features,
                *absorbed.features,
                *feature_names,
            )
            if feature not in {"consolidated_pattern", "merged_schema"}
            and self.nervous._usable_schema_feature(feature)
        ]
        structural_features = list(dict.fromkeys(structural_features))[:31]
        canonical.features = tuple(
            (*structural_features, "consolidated_pattern")
        )[-32:]
        canonical.metadata["source_trace_ids"] = sorted(all_sources)[:48]
        canonical.metadata["support_count"] = len(all_sources)
        canonical.metadata["source_channels"] = sorted(
            set(canonical.metadata.get("source_channels") or ())
            | set(absorbed.metadata.get("source_channels") or ())
        )
        merged_ids = [
            str(item)
            for item in (
                *(canonical.metadata.get("merged_schema_ids") or ()),
                absorbed.trace_id,
                *(absorbed.metadata.get("merged_schema_ids") or ()),
            )
            if str(item).strip() and str(item) != canonical.trace_id
        ]
        canonical.metadata["merged_schema_ids"] = list(
            dict.fromkeys(merged_ids)
        )[-32:]
        canonical.metadata["structural_merge_count"] = int(
            canonical.metadata.get("structural_merge_count") or 0
        ) + 1
        canonical.metadata["last_structural_merge_at"] = at
        canonical.metadata["prediction_profile"] = profile
        canonical.metadata["memory_state"] = self._stronger_memory_state(
            str(canonical.metadata.get("memory_state") or "consolidated"),
            str(absorbed.metadata.get("memory_state") or "consolidated"),
        )

        exception_ids = [
            str(item)
            for item in (
                *(canonical.metadata.get("exception_trace_ids") or ()),
                *(absorbed.metadata.get("exception_trace_ids") or ()),
            )
            if str(item).strip()
        ]
        canonical.metadata["exception_trace_ids"] = list(
            dict.fromkeys(exception_ids)
        )[-20:]
        last_feedback = self._newest_feedback(
            canonical.metadata.get("last_prediction_feedback"),
            absorbed.metadata.get("last_prediction_feedback"),
        )
        if last_feedback:
            canonical.metadata["last_prediction_feedback"] = last_feedback
        canonical.metadata["prediction_confidence"] = round(
            max(
                float(canonical.metadata.get("prediction_confidence") or 0.0),
                float(absorbed.metadata.get("prediction_confidence") or 0.0),
            ),
            5,
        )
        canonical.repetitions = max(
            canonical.repetitions,
            absorbed.repetitions,
        ) + max(0, len(new_sources))
        peak_strength = max(canonical.strength, absorbed.strength)
        canonical.strength = self._unit(
            peak_strength + (1.0 - peak_strength) * 0.025
        )
        canonical.salience = self._unit(
            max(canonical.salience, absorbed.salience)
        )
        canonical.valence = (
            canonical.valence * canonical_count
            + absorbed.valence * absorbed_count
        ) / total_weight
        canonical.arousal = self._unit(
            (
                canonical.arousal * canonical_count
                + absorbed.arousal * absorbed_count
            )
            / total_weight
        )
        canonical.last_seen_at = at
        self.nervous._save_trace(canonical)

        self._rewire_sources(canonical, absorbed, all_sources)
        self._rewire_exceptions(canonical, absorbed, exception_ids)
        self._rewire_links(canonical, absorbed)
        self._archive_absorbed(absorbed, canonical, at=at)

    def _merge_profiles(
        self,
        left: dict[str, Any],
        right: dict[str, Any],
        *,
        canonical_count: int,
        absorbed_count: int,
        source_count: int,
    ) -> dict[str, Any]:
        total = max(1, canonical_count + absorbed_count)
        features: dict[str, dict[str, Any]] = {}
        for profile, weight, keep_anchor in (
            (left, canonical_count, True),
            (right, absorbed_count, False),
        ):
            for item in profile.get("features") or ():
                name = str(item.get("feature") or "")
                if not name:
                    continue
                row = features.setdefault(
                    name,
                    {
                        "feature": name,
                        "support_total": 0.0,
                        "weight_total": 0.0,
                        "channels": set(),
                        "anchor": False,
                    },
                )
                row["support_total"] += (
                    float(item.get("support_ratio") or 0.0) * weight
                )
                row["weight_total"] += (
                    float(item.get("weight") or 0.0) * weight
                )
                row["channels"].update(item.get("channels") or ())
                row["anchor"] = row["anchor"] or (
                    keep_anchor and bool(item.get("anchor"))
                )
        merged_features = [
            {
                "feature": row["feature"],
                "support_ratio": round(
                    self._unit(row["support_total"] / total),
                    5,
                ),
                "weight": round(
                    self._unit(row["weight_total"] / total),
                    5,
                ),
                "channels": sorted(row["channels"]),
                "anchor": bool(row["anchor"]),
            }
            for row in features.values()
        ]
        merged_features.sort(
            key=lambda item: (
                bool(item["anchor"]),
                float(item["support_ratio"]),
                float(item["weight"]),
            ),
            reverse=True,
        )

        relations: dict[tuple[str, str], dict[str, Any]] = {}
        for profile, weight, keep_anchor in (
            (left, canonical_count, True),
            (right, absorbed_count, False),
        ):
            for item in profile.get("relations") or ():
                family = str(item.get("family") or "")
                value = str(item.get("value") or "")
                if not family or not value:
                    continue
                key = (family, value)
                row = relations.setdefault(
                    key,
                    {
                        "family": family,
                        "value": value,
                        "support_total": 0.0,
                        "weight_total": 0.0,
                        "confidence_total": 0.0,
                        "channels": set(),
                        "anchor": False,
                        "confirmations": 0,
                        "conflicts": 0,
                        "status": "",
                        "stabilized_from_prediction_error": False,
                        "stabilized_at": "",
                    },
                )
                row["support_total"] += (
                    float(item.get("support_ratio") or 0.0) * weight
                )
                row["weight_total"] += (
                    float(item.get("weight") or 0.0) * weight
                )
                row["confidence_total"] += (
                    float(item.get("confidence") or 0.0) * weight
                )
                row["channels"].update(item.get("channels") or ())
                row["anchor"] = row["anchor"] or (
                    keep_anchor and bool(item.get("anchor"))
                )
                row["confirmations"] += int(
                    item.get("confirmations") or 0
                )
                row["conflicts"] += int(item.get("conflicts") or 0)
                row["status"] = self._stronger_relation_state(
                    row["status"],
                    str(item.get("status") or "expected"),
                )
                if item.get("leading_alternative"):
                    row["leading_alternative"] = item.get(
                        "leading_alternative"
                    )
                if item.get("formed_from_prediction_error"):
                    row["formed_from_prediction_error"] = True
                if item.get("stabilized_from_prediction_error"):
                    row["stabilized_from_prediction_error"] = True
                    row["stabilized_at"] = max(
                        str(row.get("stabilized_at") or ""),
                        str(item.get("stabilized_at") or ""),
                    )
        merged_relations: list[dict[str, Any]] = []
        for row in relations.values():
            item = {
                "family": row["family"],
                "value": row["value"],
                "support_ratio": round(
                    self._unit(row["support_total"] / total),
                    5,
                ),
                "weight": round(
                    self._unit(row["weight_total"] / total),
                    5,
                ),
                "channels": sorted(row["channels"]),
                "anchor": bool(row["anchor"]),
                "confidence": round(
                    self._unit(row["confidence_total"] / total),
                    5,
                ),
                "confirmations": row["confirmations"],
                "conflicts": row["conflicts"],
                "status": row["status"] or "expected",
            }
            if "leading_alternative" in row:
                item["leading_alternative"] = row["leading_alternative"]
            if row.get("formed_from_prediction_error"):
                item["formed_from_prediction_error"] = True
            if row.get("stabilized_from_prediction_error"):
                item["stabilized_from_prediction_error"] = True
                if row.get("stabilized_at"):
                    item["stabilized_at"] = row["stabilized_at"]
            merged_relations.append(item)

        alternatives: dict[str, dict[str, int]] = {}
        for profile in (left, right):
            for family, values in (
                profile.get("alternatives") or {}
            ).items():
                family_out = alternatives.setdefault(str(family), {})
                if not isinstance(values, dict):
                    continue
                for value, count in values.items():
                    key = str(value)
                    family_out[key] = family_out.get(key, 0) + int(
                        count or 0
                    )
        feedback = {
            "supported": 0,
            "refined": 0,
            "contradicted": 0,
        }
        for profile in (left, right):
            raw = profile.get("feedback") or {}
            for key in feedback:
                feedback[key] += int(raw.get(key) or 0)
        channels: dict[str, int] = {}
        for profile in (left, right):
            for channel, count in (profile.get("channels") or {}).items():
                channel = str(channel)
                channels[channel] = max(
                    channels.get(channel, 0),
                    int(count or 0),
                )
        anchor = str(
            left.get("anchor_feature")
            or right.get("anchor_feature")
            or ""
        )
        merged = {
            "version": max(
                2,
                int(left.get("version") or 1),
                int(right.get("version") or 1),
            ),
            "anchor_feature": anchor,
            "source_count": source_count,
            "features": merged_features[:32],
            "channels": channels,
            "relations": merged_relations[:32],
            "alternatives": alternatives,
            "feedback": feedback,
        }
        restructured = max(
            str(left.get("last_restructured_at") or ""),
            str(right.get("last_restructured_at") or ""),
        )
        if restructured:
            merged["last_restructured_at"] = restructured
        stabilized = max(
            str(left.get("last_stabilized_at") or ""),
            str(right.get("last_stabilized_at") or ""),
        )
        if stabilized:
            merged["last_stabilized_at"] = stabilized
        return merged

    def _rewire_sources(
        self,
        canonical: NeuralTrace,
        absorbed: NeuralTrace,
        source_ids: set[str],
    ) -> None:
        for trace_id in list(source_ids)[:64]:
            source = self.nervous._get_trace(trace_id)
            if source is None:
                continue
            schema_ids = [
                str(item)
                for item in (source.metadata.get("schema_trace_ids") or ())
                if str(item).strip() and str(item) != absorbed.trace_id
            ]
            if canonical.trace_id not in schema_ids:
                schema_ids.append(canonical.trace_id)
            source.metadata["schema_trace_ids"] = list(
                dict.fromkeys(schema_ids)
            )[-8:]
            self.nervous._save_trace(source)

    def _rewire_exceptions(
        self,
        canonical: NeuralTrace,
        absorbed: NeuralTrace,
        exception_ids: list[str],
    ) -> None:
        for trace_id in exception_ids[-20:]:
            trace = self.nervous._get_trace(trace_id)
            if trace is None:
                continue
            if (
                str(trace.metadata.get("prediction_schema_id") or "")
                == absorbed.trace_id
            ):
                trace.metadata["prediction_schema_id"] = canonical.trace_id
                trace.metadata[
                    "prediction_schema_merged_from"
                ] = absorbed.trace_id
                self.nervous._save_trace(trace)

    def _rewire_links(
        self,
        canonical: NeuralTrace,
        absorbed: NeuralTrace,
    ) -> None:
        links = self.nervous._links_for([absorbed.trace_id])
        for left, right, strength in links:
            neighbor = right if left == absorbed.trace_id else left
            if neighbor in {absorbed.trace_id, canonical.trace_id}:
                continue
            self.nervous._strengthen_link(
                canonical.trace_id,
                neighbor,
                amount=max(0.02, min(0.85, float(strength))),
            )
        with closing(self.nervous._connect()) as conn:
            conn.execute(
                "DELETE FROM neural_links WHERE left_id=? OR right_id=?",
                (absorbed.trace_id, absorbed.trace_id),
            )
            conn.commit()

    def _archive_absorbed(
        self,
        absorbed: NeuralTrace,
        canonical: NeuralTrace,
        *,
        at: str,
    ) -> None:
        prior_summary = absorbed.summary
        prior_features = list(absorbed.features)
        prior_sources = list(
            absorbed.metadata.get("source_trace_ids") or ()
        )
        absorbed.channel = "schema_merged"
        absorbed.summary = (
            f"archived schema {absorbed.trace_id} merged into "
            f"{canonical.trace_id}"
        )
        absorbed.features = ("merged_schema",)
        absorbed.strength = 0.02
        absorbed.salience = 0.01
        absorbed.repetitions = 1
        absorbed.last_seen_at = at
        absorbed.metadata = {
            "memory_state": "merged",
            "merged_into_schema_id": canonical.trace_id,
            "merged_at": at,
            "prior_summary": prior_summary[:700],
            "prior_features": prior_features[:32],
            "source_trace_ids": prior_sources[:48],
        }
        self.nervous._save_trace(absorbed)

    def _schema_summary(
        self,
        schema: NeuralTrace,
        profile: dict[str, Any],
    ) -> str:
        ranked = [
            str(item.get("feature") or "")
            for item in profile.get("features") or ()
            if str(item.get("feature") or "")
        ]
        ranked = list(dict.fromkeys(ranked))[:4]
        if ranked:
            pattern = ", ".join(ranked)
        else:
            pattern = next(
                (
                    feature
                    for feature in schema.features
                    if feature != "consolidated_pattern"
                ),
                "shared structure",
            )
        channels = sorted(
            set(schema.metadata.get("source_channels") or ())
        )
        channel_text = (
            ", ".join(channels)
            if channels
            else "lived experience"
        )
        return (
            f"Persistent pattern: {pattern} recur across {channel_text} "
            "in my lived experience."
        )

    @staticmethod
    def _source_ids(schema: NeuralTrace) -> set[str]:
        return {
            str(item)
            for item in (schema.metadata.get("source_trace_ids") or ())
            if str(item).strip()
        }

    @staticmethod
    def _profile_feature_set(profile: dict[str, Any]) -> set[str]:
        return {
            str(item.get("feature") or "")
            for item in profile.get("features") or ()
            if str(item.get("feature") or "")
            and float(item.get("support_ratio") or 0.0) >= 0.35
        }

    @classmethod
    def _stronger_memory_state(cls, left: str, right: str) -> str:
        return max(
            (left, right),
            key=lambda value: cls._STATE_PRIORITY.get(value, 0),
        )

    @staticmethod
    def _stronger_relation_state(left: str, right: str) -> str:
        priority = {
            "": -1,
            "emerging": 0,
            "expected": 1,
            "contested": 2,
        }
        return max(
            (left, right),
            key=lambda value: priority.get(value, 0),
        )

    @staticmethod
    def _newest_feedback(left: Any, right: Any) -> dict[str, Any] | None:
        candidates = [
            item
            for item in (left, right)
            if isinstance(item, dict)
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: str(item.get("at") or ""),
        )

    @staticmethod
    def _unit(value: float) -> float:
        if not math.isfinite(float(value)):
            return 0.0
        return max(0.0, min(1.0, float(value)))
