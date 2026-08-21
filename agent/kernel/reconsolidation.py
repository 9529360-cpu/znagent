from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from .models import utc_now

if TYPE_CHECKING:
    from .nervous_system import NeuralTrace, PersistentNervousSystem


@dataclass(slots=True)
class SchemaPredictionFeedback:
    schema_trace_id: str
    status: str
    prediction_error: float
    support: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    untested: tuple[str, ...] = ()
    observation_channels: tuple[str, ...] = ()
    at: str = ""
    reconsolidation_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SchemaReconsolidator:
    """Compare schema expectations with current evidence and change the schema."""

    _EXCLUSIVE = {
        "workspace", "branch", "system", "architecture", "disk_state",
        "outcome", "changes", "process_state", "presence", "path_state",
        "path_type",
    }
    _ALIASES = {
        "dirty": ("workspace", "dirty"),
        "clean": ("workspace", "clean"),
        "success": ("outcome", "success"),
        "failure": ("outcome", "failure"),
        "failed": ("outcome", "failure"),
        "succeeded": ("outcome", "success"),
        "alive": ("process_state", "alive"),
        "dead": ("process_state", "dead"),
        "running": ("process_state", "alive"),
        "stopped": ("process_state", "dead"),
        "exists": ("presence", "exists"),
        "missing": ("presence", "missing"),
        "present": ("presence", "exists"),
        "absent": ("presence", "missing"),
        "low_disk": ("disk_state", "low"),
        "disk_ok": ("disk_state", "healthy"),
    }

    def __init__(self, nervous: PersistentNervousSystem):
        self.nervous = nervous

    def evaluate(
        self,
        predictions: list[dict[str, Any]],
        facts: dict[str, Any],
        *,
        event_id: str | None = None,
    ) -> list[SchemaPredictionFeedback]:
        observation = self._observation(facts)
        if not observation["features"] and not observation["relations"]:
            return []
        prior = {
            str(item)
            for item in (facts.get("schema_reconsolidation_keys") or ())
            if str(item).strip()
        }
        emitted: list[SchemaPredictionFeedback] = []
        for prediction in predictions[:3]:
            trace_id = str(prediction.get("trace_id") or "").strip()
            schema = self.nervous._get_trace(trace_id) if trace_id else None
            if schema is None or schema.channel != "schema":
                continue
            profile = self._profile(schema)
            feedback = self._compare(schema, profile, observation)
            if feedback.reconsolidation_key in prior:
                continue
            if feedback.status != "untested":
                self._apply(schema, profile, feedback, observation, event_id=event_id)
            prior.add(feedback.reconsolidation_key)
            emitted.append(feedback)
        if emitted:
            facts["schema_reconsolidation_keys"] = sorted(prior)[-48:]
        return emitted

    def _profile(self, schema: NeuralTrace) -> dict[str, Any]:
        existing = schema.metadata.get("prediction_profile")
        if isinstance(existing, dict) and int(existing.get("version") or 0) >= 1:
            return existing
        source_ids = [
            str(item) for item in (schema.metadata.get("source_trace_ids") or ())
            if str(item).strip()
        ][:24]
        sources = [
            trace for trace in (self.nervous._get_trace(item) for item in source_ids)
            if trace is not None
        ] or [schema]
        anchor = next(
            (
                feature for feature in schema.features
                if feature != "consolidated_pattern"
                and self.nervous._usable_schema_feature(feature)
            ),
            "",
        )
        rows: dict[str, dict[str, Any]] = {}
        channels: dict[str, int] = {}
        for trace in sources:
            channels[trace.channel] = channels.get(trace.channel, 0) + 1
            features = {
                self._norm(item) for item in trace.features
                if self.nervous._usable_schema_feature(item)
            }
            features.discard("")
            if not features:
                features = {
                    token for token in self.nervous._tokens(trace.summary)
                    if self.nervous._usable_schema_feature(token)
                }
            weight = 0.55 + 0.25 * trace.strength + 0.20 * trace.salience
            for feature in features:
                row = rows.setdefault(
                    feature,
                    {"count": 0, "weight": 0.0, "channels": set()},
                )
                row["count"] += 1
                row["weight"] += weight
                row["channels"].add(trace.channel)
        count = max(1, len(sources))
        features = [
            {
                "feature": feature,
                "support_ratio": round(self._unit(row["count"] / count), 5),
                "weight": round(self._unit(row["weight"] / count), 5),
                "channels": sorted(row["channels"]),
                "anchor": feature == anchor,
            }
            for feature, row in rows.items()
        ]
        features.sort(
            key=lambda item: (
                bool(item["anchor"]),
                float(item["support_ratio"]),
                float(item["weight"]),
            ),
            reverse=True,
        )
        features = features[:24]
        relations: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in features:
            relation = self._relation(str(item["feature"]))
            if relation is None or relation in seen:
                continue
            seen.add(relation)
            family, value = relation
            relations.append(
                {
                    "family": family,
                    "value": value,
                    "support_ratio": item["support_ratio"],
                    "weight": item["weight"],
                    "channels": item["channels"],
                    "anchor": item["anchor"],
                    "confidence": round(
                        self._unit(
                            0.55 * item["support_ratio"]
                            + 0.45 * item["weight"]
                        ),
                        5,
                    ),
                    "confirmations": 0,
                    "conflicts": 0,
                    "status": "expected",
                }
            )
        profile = {
            "version": 1,
            "anchor_feature": anchor,
            "source_count": len(sources),
            "features": features,
            "channels": channels,
            "relations": relations,
            "alternatives": {},
            "feedback": {"supported": 0, "refined": 0, "contradicted": 0},
        }
        schema.metadata["prediction_profile"] = profile
        schema.metadata["prediction_confidence"] = round(
            self._unit(
                0.48 * schema.strength
                + 0.27 * schema.salience
                + 0.25 * min(1.0, len(sources) / 6.0)
            ),
            5,
        )
        self.nervous._save_trace(schema)
        return profile

    def _compare(
        self,
        schema: NeuralTrace,
        profile: dict[str, Any],
        observation: dict[str, Any],
    ) -> SchemaPredictionFeedback:
        features = set(observation["features"])
        relations = observation["relations"]
        support: list[str] = []
        conflicts: list[str] = []
        untested: list[str] = []
        support_weight = 0.0
        conflict_weight = 0.0
        anchor_conflict = False
        for item in profile.get("relations") or ():
            if item.get("status") == "contested":
                continue
            ratio = float(item.get("support_ratio") or 0.0)
            if ratio < 0.45 and not item.get("anchor"):
                continue
            family = str(item.get("family") or "")
            value = str(item.get("value") or "")
            label = f"{family}:{value}"
            weight = max(
                0.20,
                0.55 * ratio + 0.45 * float(item.get("confidence") or 0.0),
            )
            if item.get("anchor"):
                weight *= 1.35
            observed = relations.get(family)
            if not observed:
                untested.append(label)
            elif value in observed:
                support.append(label)
                support_weight += weight
            elif family in self._EXCLUSIVE:
                conflicts.append(f"{label}->{','.join(sorted(observed))}")
                conflict_weight += weight
                anchor_conflict = anchor_conflict or bool(item.get("anchor"))
            else:
                untested.append(label)
        anchor = str(profile.get("anchor_feature") or "")
        for item in profile.get("features") or ():
            feature = str(item.get("feature") or "")
            if not feature or self._relation(feature) is not None:
                continue
            ratio = float(item.get("support_ratio") or 0.0)
            if ratio < 0.45 and feature != anchor:
                continue
            weight = max(
                0.16,
                0.60 * ratio + 0.40 * float(item.get("weight") or 0.0),
            )
            if feature == anchor:
                weight *= 1.25
            if feature in features:
                support.append(feature)
                support_weight += weight
            else:
                untested.append(feature)
        tested = support_weight + conflict_weight
        error = self._unit(conflict_weight / tested) if tested > 0 else 0.0
        if tested <= 0:
            status = "untested"
        elif conflict_weight <= 0:
            status = "supported"
        elif support_weight <= 0 or (anchor_conflict and error >= 0.45):
            status = "contradicted"
        else:
            status = "refined"
        key = hashlib.sha256(
            json.dumps(
                {
                    "schema": schema.trace_id,
                    "status": status,
                    "support": sorted(set(support)),
                    "conflicts": sorted(set(conflicts)),
                    "channels": (
                        sorted(observation["channels"])
                        if status == "untested"
                        else []
                    ),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()[:24]
        return SchemaPredictionFeedback(
            schema_trace_id=schema.trace_id,
            status=status,
            prediction_error=round(error, 5),
            support=tuple(dict.fromkeys(support))[:16],
            contradictions=tuple(dict.fromkeys(conflicts))[:16],
            untested=tuple(dict.fromkeys(untested))[:24],
            observation_channels=tuple(sorted(observation["channels"])),
            at=utc_now(),
            reconsolidation_key=key,
        )

    def _apply(
        self,
        schema: NeuralTrace,
        profile: dict[str, Any],
        feedback: SchemaPredictionFeedback,
        observation: dict[str, Any],
        *,
        event_id: str | None,
    ) -> None:
        counters = profile.setdefault("feedback", {})
        counters[feedback.status] = int(counters.get(feedback.status) or 0) + 1
        error = feedback.prediction_error
        if feedback.status == "supported":
            schema.strength = self._unit(
                schema.strength
                + (1.0 - schema.strength)
                * (0.025 + 0.035 * (1.0 - error))
            )
            schema.salience = self._unit(
                schema.salience + (1.0 - schema.salience) * 0.015
            )
            schema.metadata["memory_state"] = "consolidated"
        else:
            if feedback.status == "refined":
                schema.strength = max(
                    0.05,
                    schema.strength * (1.0 - 0.018 - 0.045 * error),
                )
                schema.metadata["memory_state"] = "reconsolidating"
                salience = 0.66
            else:
                schema.strength = max(
                    0.05,
                    schema.strength * (1.0 - 0.075 - 0.10 * error),
                )
                schema.salience = max(
                    0.05,
                    schema.salience * (1.0 - 0.035 - 0.055 * error),
                )
                schema.metadata["memory_state"] = (
                    "contested"
                    if int(counters.get("contradicted") or 0) >= 3
                    else "labile"
                )
                salience = 0.82
            self._revise_relations(profile, feedback)
            self._preserve_exception(
                schema,
                feedback,
                observation,
                event_id,
                salience,
            )
        total = sum(
            int(counters.get(key) or 0)
            for key in ("supported", "refined", "contradicted")
        )
        support_fraction = (
            (
                int(counters.get("supported") or 0)
                + 0.45 * int(counters.get("refined") or 0)
            )
            / total
            if total
            else 0.5
        )
        schema.metadata["prediction_confidence"] = round(
            self._unit(
                0.46 * schema.strength
                + 0.24 * schema.salience
                + 0.30 * support_fraction
            ),
            5,
        )
        schema.metadata["last_prediction_feedback"] = feedback.to_dict()
        schema.metadata["prediction_profile"] = profile
        schema.last_seen_at = feedback.at
        self.nervous._save_trace(schema)

    def _revise_relations(
        self,
        profile: dict[str, Any],
        feedback: SchemaPredictionFeedback,
    ) -> None:
        supported = set(feedback.support)
        conflicts: dict[tuple[str, str], str] = {}
        for item in feedback.contradictions:
            expected, _, observed = item.partition("->")
            family, _, value = expected.partition(":")
            if family and value and observed:
                conflicts[(family, value)] = observed.split(",", 1)[0]
        alternatives = profile.setdefault("alternatives", {})
        existing = {
            (str(item.get("family") or ""), str(item.get("value") or ""))
            for item in profile.get("relations") or ()
        }
        emerging: list[dict[str, Any]] = []
        for relation in profile.get("relations") or ():
            family = str(relation.get("family") or "")
            value = str(relation.get("value") or "")
            label = f"{family}:{value}"
            confidence = float(relation.get("confidence") or 0.0)
            if label in supported:
                relation["confirmations"] = (
                    int(relation.get("confirmations") or 0) + 1
                )
                relation["confidence"] = round(
                    self._unit(confidence + (1.0 - confidence) * 0.08),
                    5,
                )
                continue
            alternative = conflicts.get((family, value))
            if alternative is None:
                continue
            relation["conflicts"] = int(relation.get("conflicts") or 0) + 1
            relation["confidence"] = round(
                max(
                    0.05,
                    confidence
                    * (1.0 - 0.16 - 0.18 * feedback.prediction_error),
                ),
                5,
            )
            family_alts = alternatives.setdefault(family, {})
            family_alts[alternative] = int(family_alts.get(alternative) or 0) + 1
            if family_alts[alternative] >= 2 and relation["confidence"] < 0.50:
                relation["status"] = "contested"
                relation["leading_alternative"] = alternative
                if (family, alternative) not in existing:
                    emerging.append(
                        {
                            "family": family,
                            "value": alternative,
                            "support_ratio": 0.55,
                            "weight": 0.50,
                            "channels": list(feedback.observation_channels),
                            "anchor": False,
                            "confidence": min(
                                0.72,
                                0.42 + 0.08 * family_alts[alternative],
                            ),
                            "confirmations": 0,
                            "conflicts": 0,
                            "status": "emerging",
                            "formed_from_prediction_error": True,
                        }
                    )
                    existing.add((family, alternative))
        if emerging:
            profile.setdefault("relations", []).extend(emerging)
            profile["last_restructured_at"] = feedback.at

    def _preserve_exception(
        self,
        schema: NeuralTrace,
        feedback: SchemaPredictionFeedback,
        observation: dict[str, Any],
        event_id: str | None,
        salience: float,
    ) -> None:
        features: list[str] = []
        for item in feedback.contradictions:
            expected, _, observed = item.partition("->")
            family = expected.split(":", 1)[0]
            for value in observed.split(",") if observed else ():
                if family and value:
                    features.extend((f"{family}:{value}", value))
        if not features:
            features.extend(feedback.support[:4])
        trace = self.nervous.perceive(
            "outcome",
            f"Reality {feedback.status} schema {schema.trace_id}: "
            f"{'; '.join(feedback.contradictions) or 'partial mismatch'}.",
            features=tuple(dict.fromkeys(features))[:16],
            source="reconsolidation",
            salience=salience,
            valence=-0.20 if feedback.status == "refined" else -0.42,
            arousal=0.48 if feedback.status == "refined" else 0.68,
            metadata={
                "event_id": event_id,
                "prediction_schema_id": schema.trace_id,
                "prediction_status": feedback.status,
                "prediction_error": feedback.prediction_error,
                "support": list(feedback.support),
                "contradictions": list(feedback.contradictions),
                "observation_channels": list(feedback.observation_channels),
            },
        )
        self.nervous._strengthen_link(
            schema.trace_id,
            trace.trace_id,
            amount=0.18 + 0.20 * feedback.prediction_error,
        )
        exception_ids = [
            str(item)
            for item in (schema.metadata.get("exception_trace_ids") or ())
            if str(item).strip()
        ]
        if trace.trace_id not in exception_ids:
            exception_ids.append(trace.trace_id)
        schema.metadata["exception_trace_ids"] = exception_ids[-12:]

    @classmethod
    def _observation(cls, facts: dict[str, Any]) -> dict[str, Any]:
        features: set[str] = set()
        relations: dict[str, set[str]] = {}
        channels: set[str] = set()

        def add(raw: Any) -> None:
            feature = cls._norm(raw)
            if not feature:
                return
            features.add(feature)
            relation = cls._relation(feature)
            if relation:
                relations.setdefault(relation[0], set()).add(relation[1])

        body = facts.get("body") if isinstance(facts.get("body"), dict) else None
        if body:
            channels.add("body")
            if body.get("system"):
                add(f"system:{body.get('system')}")
            if body.get("architecture"):
                add(f"architecture:{body.get('architecture')}")
            try:
                ratio = float(body.get("disk_free_ratio"))
            except (TypeError, ValueError):
                ratio = None
            if ratio is not None:
                disk_state = (
                    "low"
                    if ratio < 0.10
                    else "constrained"
                    if ratio < 0.20
                    else "healthy"
                )
                add(f"disk_state:{disk_state}")
        git = facts.get("git") if isinstance(facts.get("git"), dict) else None
        if git and git.get("available") is not False:
            channels.add("git")
            if git.get("branch"):
                add(f"branch:{git.get('branch')}")
            if "dirty" in git:
                add(f"workspace:{'dirty' if git.get('dirty') else 'clean'}")
            try:
                changed = int(git.get("changed_files") or 0)
            except (TypeError, ValueError):
                changed = 0
            add(f"changes:{'present' if changed else 'absent'}")
        paths = facts.get("paths") if isinstance(facts.get("paths"), list) else []
        if paths:
            channels.add("paths")
            for item in paths[:8]:
                if not isinstance(item, dict):
                    continue
                exists = bool(item.get("exists"))
                add(f"path_state:{'exists' if exists else 'missing'}")
                if item.get("type"):
                    add(f"path_type:{item.get('type')}")
        processes = (
            facts.get("processes")
            if isinstance(facts.get("processes"), list)
            else []
        )
        if processes:
            channels.add("processes")
            for item in processes[:8]:
                if isinstance(item, dict):
                    add(
                        f"process_state:"
                        f"{'alive' if item.get('alive') else 'dead'}"
                    )
        previews = (
            facts.get("file_previews")
            if isinstance(facts.get("file_previews"), list)
            else []
        )
        if previews:
            channels.add("file_preview")
            for item in previews[:2]:
                if isinstance(item, dict):
                    text = str(item.get("preview") or "")[:16384].lower()
                    tokens = re.findall(
                        r"[a-z0-9_+./-]{3,}|[\u4e00-\u9fff]{2,}",
                        text,
                    )[:96]
                    for token in tokens:
                        add(token)
        explicit = facts.get("evidence_features")
        if isinstance(explicit, (list, tuple, set)):
            channels.add("explicit_evidence")
            for item in explicit:
                add(item)
        return {
            "features": features,
            "relations": relations,
            "channels": channels,
        }

    @classmethod
    def _relation(cls, raw: str) -> tuple[str, str] | None:
        feature = cls._norm(raw)
        if not feature:
            return None
        if feature in cls._ALIASES:
            return cls._ALIASES[feature]
        match = re.fullmatch(
            r"([a-z0-9_./-]{2,40})[:=]([a-z0-9_+./-]{1,120})",
            feature,
        )
        if not match or match.group(1) in {"http", "https", "source"}:
            return None
        return match.group(1), match.group(2)

    @staticmethod
    def _norm(raw: Any) -> str:
        value = re.sub(r"\s+", "_", str(raw or "").strip().lower())
        return re.sub(r"[^a-z0-9_+./:=-]+", "", value)[:160]

    @staticmethod
    def _unit(value: float) -> float:
        if not math.isfinite(float(value)):
            return 0.0
        return max(0.0, min(1.0, float(value)))
