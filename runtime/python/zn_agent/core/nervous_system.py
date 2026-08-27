from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from .models import utc_now
from .store import KernelStore


@dataclass(slots=True)
class NeuralTrace:
    """A persistent associative trace left by perception, thought, or action.

    A trace is not a transcript entry. Repeated or emotionally salient
    experience strengthens the same trace, and co-active traces become linked.
    This lets experience change future recall without turning every episode into
    a new skill or shipping a memory dump to an external model.
    """

    trace_id: str
    fingerprint: str
    channel: str
    summary: str
    features: tuple[str, ...] = ()
    source: str = "self"
    strength: float = 0.5
    salience: float = 0.5
    valence: float = 0.0
    arousal: float = 0.2
    repetitions: int = 1
    first_seen_at: str = field(default_factory=utc_now)
    last_seen_at: str = field(default_factory=utc_now)
    last_activated_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NeuralActivation:
    trace: NeuralTrace
    activation: float
    cue_overlap: float
    associative_gain: float = 0.0


@dataclass(slots=True)
class NeuralConsolidationReport:
    """One local plasticity pass over ZN's lived neural substrate."""

    at: str
    examined: int = 0
    stabilized: int = 0
    faded: int = 0
    pruned: int = 0
    links_faded: int = 0
    abstractions: tuple[str, ...] = ()


@dataclass(slots=True)
class AffectiveState:
    """Persistent internal tone produced by lived experience and body state.

    These values are functional internal dynamics, not a claim of biological
    consciousness. They give ZN continuity of attraction/aversion, arousal,
    tension, curiosity, familiarity, and fatigue across process restarts.
    """

    valence: float = 0.0
    arousal: float = 0.15
    tension: float = 0.05
    curiosity: float = 0.35
    familiarity: float = 0.0
    fatigue: float = 0.0
    heartbeat_count: int = 0
    dominant_signal: str | None = None
    last_body_signal: str | None = None
    last_heartbeat_at: str = field(default_factory=utc_now)
    last_body_action_id: str | None = None
    last_consolidation_at: str | None = None
    last_consolidation_heartbeat: int = 0


class PersistentNervousSystem:
    """ZN's persistent associative memory and affective nervous system.

    The important distinction from a conventional memory layer is that lived
    experience changes the network itself:

    * repetition strengthens a trace instead of appending endless copies;
    * co-occurrence strengthens associations between traces;
    * recall is cue-driven activation with spreading association;
    * salient success/failure changes persistent affective state;
    * visual, world/web, body, thought, and action perceptions share the same
      substrate and can therefore become associated;
    * consolidation stabilizes recurring structure while weak isolated detail
      can fade, so living longer does not mean retaining every episode equally.

    No language model is required for encoding, recall, or consolidation.
    """

    _ABSTRACTION_CHANNELS = {"world", "vision", "action", "outcome", "will"}
    _GENERIC_FEATURES = {
        "action",
        "body",
        "event",
        "failure",
        "intention",
        "model",
        "native",
        "outcome",
        "resident",
        "self",
        "success",
        "thought",
        "vision",
        "web",
        "will",
        "world",
    }

    def __init__(self, store: KernelStore):
        self.store = store
        self._init_schema()
        self._state = self._load_state()

    def perceive(
        self,
        channel: str,
        summary: str,
        *,
        features: Iterable[str] = (),
        source: str = "self",
        salience: float = 0.5,
        valence: float = 0.0,
        arousal: float = 0.2,
        metadata: dict[str, Any] | None = None,
    ) -> NeuralTrace:
        text = str(summary or "").strip()
        if not text:
            raise ValueError("neural perception summary must not be empty")
        normalized_channel = self._normalize_channel(channel)
        normalized_features = self._normalize_features(features)
        fingerprint = self._fingerprint(normalized_channel, text, normalized_features)
        now = utc_now()
        prior = self._get_by_fingerprint(fingerprint)
        novelty = 1.0 if prior is None else max(0.0, 1.0 - prior.strength)

        if prior is None:
            trace = NeuralTrace(
                trace_id=f"trace-{fingerprint[:16]}",
                fingerprint=fingerprint,
                channel=normalized_channel,
                summary=text,
                features=normalized_features,
                source=str(source or "self").strip() or "self",
                strength=self._unit(0.30 + 0.45 * self._unit(salience)),
                salience=self._unit(salience),
                valence=self._signed(valence),
                arousal=self._unit(arousal),
                first_seen_at=now,
                last_seen_at=now,
                metadata=dict(metadata or {}),
            )
        else:
            repetitions = prior.repetitions + 1
            alpha = min(0.35, 0.10 + math.log1p(repetitions) * 0.025)
            trace = NeuralTrace(
                trace_id=prior.trace_id,
                fingerprint=prior.fingerprint,
                channel=prior.channel,
                summary=text,
                features=tuple(dict.fromkeys((*prior.features, *normalized_features)))[-32:],
                source=prior.source,
                strength=self._unit(
                    prior.strength
                    + (1.0 - prior.strength)
                    * (0.08 + 0.12 * self._unit(salience))
                ),
                salience=self._blend(prior.salience, self._unit(salience), alpha),
                valence=self._signed(
                    self._blend(prior.valence, self._signed(valence), alpha)
                ),
                arousal=self._unit(
                    self._blend(prior.arousal, self._unit(arousal), alpha)
                ),
                repetitions=repetitions,
                first_seen_at=prior.first_seen_at,
                last_seen_at=now,
                last_activated_at=prior.last_activated_at,
                metadata={**prior.metadata, **dict(metadata or {})},
            )

        recent = self._recent_traces(limit=6, exclude_trace_id=trace.trace_id)
        self._save_trace(trace)
        for other in recent:
            self._strengthen_link(
                trace.trace_id,
                other.trace_id,
                amount=0.025 + 0.10 * trace.salience,
            )

        self._integrate_affect(trace, novelty=novelty)
        return trace

    def remember_visual(
        self,
        summary: str,
        *,
        features: Iterable[str] = (),
        source: str = "vision",
        salience: float = 0.55,
        valence: float = 0.0,
        arousal: float = 0.35,
        metadata: dict[str, Any] | None = None,
    ) -> NeuralTrace:
        """Encode a visual perception into the same associative substrate."""
        return self.perceive(
            "vision",
            summary,
            features=features,
            source=source,
            salience=salience,
            valence=valence,
            arousal=arousal,
            metadata=metadata,
        )

    def remember_world(
        self,
        summary: str,
        *,
        features: Iterable[str] = (),
        source: str = "world/web",
        salience: float = 0.5,
        valence: float = 0.0,
        arousal: float = 0.3,
        metadata: dict[str, Any] | None = None,
    ) -> NeuralTrace:
        """Encode something learned from the outside world or the web."""
        return self.perceive(
            "world",
            summary,
            features=features,
            source=source,
            salience=salience,
            valence=valence,
            arousal=arousal,
            metadata=metadata,
        )

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
            trace_tokens = self._tokens(f"{trace.summary} {' '.join(trace.features)}")
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

    def heartbeat(self, *, body: dict[str, Any] | None = None) -> AffectiveState:
        """Advance persistent homeostatic state without requiring a task or model."""
        now = datetime.now(timezone.utc)
        previous = self._parse_time(self._state.last_heartbeat_at)
        elapsed = max(0.0, (now - previous).total_seconds()) if previous else 0.0
        decay = min(0.35, elapsed / 600.0)

        self._state.arousal = self._blend(self._state.arousal, 0.15, decay)
        self._state.tension = self._blend(self._state.tension, 0.05, decay * 0.8)
        self._state.curiosity = self._blend(
            self._state.curiosity, 0.35, decay * 0.5
        )
        self._state.fatigue = self._blend(self._state.fatigue, 0.0, decay * 0.25)
        self._state.valence = self._blend(self._state.valence, 0.0, decay * 0.20)

        if body:
            signal = self._body_signal(body)
            self._state.last_body_signal = signal
            disk_total = float(body.get("disk_total_bytes") or 0.0)
            disk_free = float(body.get("disk_free_bytes") or 0.0)
            if disk_total > 0:
                free_ratio = max(0.0, min(1.0, disk_free / disk_total))
                if free_ratio < 0.10:
                    self._state.tension = self._unit(
                        max(self._state.tension, 0.65)
                    )
                    self._state.arousal = self._unit(
                        max(self._state.arousal, 0.50)
                    )

        self._state.heartbeat_count += 1
        self._state.last_heartbeat_at = utc_now()
        self._save_state()
        self._maybe_consolidate(now=now)
        return self.snapshot()

    def consolidate(
        self,
        *,
        now: datetime | None = None,
        limit: int = 512,
    ) -> NeuralConsolidationReport:
        """Let lived memory stabilize, fade, and form higher-order schemas.

        Consolidation is resident-native plasticity, not summarization by a
        model. Concrete episodes are not converted one-for-one into objects.
        Recurring structure can become a schema trace while weak, isolated,
        long-unactivated detail gradually loses strength and may eventually be
        forgotten.
        """
        moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        traces = self._traces_for_consolidation(max(32, int(limit)))
        link_strength = self._link_strength_profile({trace.trace_id for trace in traces})
        abstractions = self._form_abstractions(traces, moment=moment)

        stabilized = 0
        faded = 0
        pruned = 0
        for trace in traces:
            age_days = self._age_days(trace.last_seen_at, moment)
            activated_days = self._age_days(trace.last_activated_at, moment)
            recency = math.exp(-age_days / 28.0)
            activation_recency = (
                math.exp(-activated_days / 18.0)
                if trace.last_activated_at
                else 0.0
            )
            repetition = min(1.0, math.log1p(trace.repetitions) / 3.6)
            emotion = self._unit(0.62 * abs(trace.valence) + 0.38 * trace.arousal)
            connectedness = link_strength.get(trace.trace_id, 0.0)
            schema_bonus = 0.16 if trace.channel == "schema" else 0.0
            retention = self._unit(
                0.22 * trace.strength
                + 0.16 * trace.salience
                + 0.18 * repetition
                + 0.12 * emotion
                + 0.12 * connectedness
                + 0.10 * recency
                + 0.10 * activation_recency
                + schema_bonus
            )

            trace.metadata["retention"] = round(retention, 5)
            trace.metadata["last_consolidated_at"] = moment.isoformat()
            trace.metadata["consolidation_count"] = int(
                trace.metadata.get("consolidation_count") or 0
            ) + 1

            if retention >= 0.62 or trace.repetitions >= 4 or trace.channel == "schema":
                prior_strength = trace.strength
                trace.strength = self._unit(
                    trace.strength
                    + (1.0 - trace.strength) * (0.015 + 0.035 * retention)
                )
                if trace.channel == "schema":
                    trace.salience = self._unit(
                        trace.salience + (1.0 - trace.salience) * 0.02
                    )
                trace.metadata["memory_state"] = "consolidated"
                if trace.strength > prior_strength + 1e-9:
                    stabilized += 1
            else:
                fade_pressure = self._unit((1.0 - retention) * (1.0 - recency))
                prior_strength = trace.strength
                prior_salience = trace.salience
                if fade_pressure > 0.04:
                    trace.strength = max(
                        0.03,
                        trace.strength * (1.0 - 0.12 * fade_pressure),
                    )
                    trace.salience = max(
                        0.02,
                        trace.salience * (1.0 - 0.08 * fade_pressure),
                    )
                trace.metadata["memory_state"] = (
                    "fading" if retention < 0.30 else "labile"
                )
                if (
                    trace.strength < prior_strength - 1e-9
                    or trace.salience < prior_salience - 1e-9
                ):
                    faded += 1

            should_prune = (
                trace.channel != "schema"
                and age_days >= 90.0
                and trace.repetitions <= 1
                and trace.strength <= 0.10
                and trace.salience <= 0.12
                and connectedness <= 0.08
                and activation_recency < 0.03
            )
            if should_prune and self._delete_trace(trace.trace_id):
                pruned += 1
            else:
                self._save_trace(trace)

        links_faded = self._fade_links(moment)
        report = NeuralConsolidationReport(
            at=moment.isoformat(),
            examined=len(traces),
            stabilized=stabilized,
            faded=faded,
            pruned=pruned,
            links_faded=links_faded,
            abstractions=abstractions,
        )
        self._state.last_consolidation_at = report.at
        self._state.last_consolidation_heartbeat = self._state.heartbeat_count
        self._save_state()
        self._save_consolidation(report)
        return report

    def latest_consolidation(self) -> NeuralConsolidationReport | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT data FROM neural_consolidations "
                "ORDER BY consolidation_id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        raw = json.loads(row["data"])
        raw["abstractions"] = tuple(raw.get("abstractions") or ())
        return NeuralConsolidationReport(**raw)

    def observe_working_state(self, working_data: dict[str, Any]) -> NeuralTrace | None:
        """Notice a new body movement result exactly once and encode it neurally."""
        raw = working_data.get("native_action_result")
        if not isinstance(raw, dict):
            return None
        action_id = str(raw.get("action_id") or "").strip()
        if not action_id or action_id == self._state.last_body_action_id:
            return None
        self._state.last_body_action_id = action_id
        success = bool(raw.get("success"))
        kind = str(raw.get("kind") or "body_action")
        error = str(raw.get("error") or "").strip()
        summary = (
            f"body movement {kind} succeeded"
            if success
            else f"body movement {kind} failed: {error or 'unknown failure'}"
        )
        trace = self.perceive(
            "action",
            summary,
            features=(kind, "success" if success else "failure"),
            source="body",
            salience=0.62 if success else 0.86,
            valence=0.45 if success else -0.75,
            arousal=0.42 if success else 0.82,
            metadata={"action_id": action_id, "event_id": raw.get("event_id")},
        )
        self._save_state()
        return trace

    def snapshot(self) -> AffectiveState:
        return AffectiveState(**asdict(self._state))

    def recent_traces(self, limit: int = 50) -> list[NeuralTrace]:
        return self._recent_traces(limit=max(1, int(limit)))

    def describe_state(self) -> str:
        state = self._state
        parts: list[str] = []
        if state.tension >= 0.65:
            parts.append("strained")
        elif state.arousal <= 0.25:
            parts.append("calm")
        else:
            parts.append("alert")
        if state.curiosity >= 0.60:
            parts.append("curious")
        if state.familiarity >= 0.60:
            parts.append("familiar")
        if state.fatigue >= 0.65:
            parts.append("fatigued")
        if state.valence >= 0.35:
            parts.append("positive")
        elif state.valence <= -0.35:
            parts.append("averse")
        return " and ".join(dict.fromkeys(parts)) or "steady"

    def _maybe_consolidate(self, *, now: datetime) -> NeuralConsolidationReport | None:
        heartbeat_delta = (
            self._state.heartbeat_count - self._state.last_consolidation_heartbeat
        )
        if heartbeat_delta <= 0:
            return None
        trace_count = self._trace_count()
        if trace_count < 8:
            return None

        # Plasticity cadence adapts to how much has been lived and to internal
        # load. It is not a fixed cron-like memory cleanup job.
        period = max(36, 180 - min(120, trace_count // 2))
        if self._state.fatigue >= 0.65:
            period = max(24, period // 2)
        elif self._state.tension >= 0.70 or self._state.arousal >= 0.75:
            period = max(30, int(period * 0.65))
        if heartbeat_delta < period:
            return None
        return self.consolidate(now=now)

    def _form_abstractions(
        self,
        traces: list[NeuralTrace],
        *,
        moment: datetime,
    ) -> tuple[str, ...]:
        buckets: dict[str, list[NeuralTrace]] = {}
        for trace in traces:
            if trace.channel not in self._ABSTRACTION_CHANNELS:
                continue
            features = [
                feature
                for feature in trace.features
                if self._usable_schema_feature(feature)
            ]
            if not features:
                features = [
                    token
                    for token in sorted(self._tokens(trace.summary))
                    if self._usable_schema_feature(token)
                ][:8]
            for feature in features[:12]:
                buckets.setdefault(feature, []).append(trace)

        ranked: list[tuple[float, str, list[NeuralTrace]]] = []
        for feature, support in buckets.items():
            unique = {trace.trace_id: trace for trace in support}
            support_traces = list(unique.values())
            if len(support_traces) < 2:
                continue
            total_repetitions = sum(max(1, trace.repetitions) for trace in support_traces)
            channels = {trace.channel for trace in support_traces}
            if len(support_traces) < 3 and total_repetitions < 5:
                continue
            avg_salience = sum(trace.salience for trace in support_traces) / len(
                support_traces
            )
            avg_strength = sum(trace.strength for trace in support_traces) / len(
                support_traces
            )
            score = (
                min(1.0, len(support_traces) / 6.0) * 0.45
                + min(1.0, total_repetitions / 12.0) * 0.25
                + avg_salience * 0.16
                + avg_strength * 0.14
            )
            ranked.append((score, feature, support_traces))

        ranked.sort(key=lambda item: item[0], reverse=True)
        created_or_strengthened: list[str] = []
        for _, feature, support in ranked[:3]:
            source_ids = [trace.trace_id for trace in support]
            channels = sorted({trace.channel for trace in support})
            fingerprint = hashlib.sha256(
                f"schema|{self._normalize_text(feature)}".encode("utf-8")
            ).hexdigest()
            existing = self._get_by_fingerprint(fingerprint)
            existing_ids = set(
                str(item)
                for item in (
                    existing.metadata.get("source_trace_ids", ())
                    if existing is not None
                    else ()
                )
            )
            new_ids = [trace_id for trace_id in source_ids if trace_id not in existing_ids]
            if existing is not None and not new_ids:
                continue

            avg_salience = sum(trace.salience for trace in support) / len(support)
            avg_valence = sum(trace.valence for trace in support) / len(support)
            avg_arousal = sum(trace.arousal for trace in support) / len(support)
            merged_ids = tuple(dict.fromkeys((*existing_ids, *source_ids)))[:24]
            summary = (
                f"Persistent pattern: {feature} recurs across "
                f"{', '.join(channels)} in my lived experience."
            )
            if existing is None:
                schema = NeuralTrace(
                    trace_id=f"schema-{fingerprint[:16]}",
                    fingerprint=fingerprint,
                    channel="schema",
                    summary=summary,
                    features=(feature, "consolidated_pattern"),
                    source="self",
                    strength=self._unit(
                        0.46 + 0.05 * len(support) + 0.16 * avg_salience
                    ),
                    salience=self._unit(
                        0.36 + 0.04 * len(support) + 0.20 * avg_salience
                    ),
                    valence=self._signed(avg_valence),
                    arousal=self._unit(avg_arousal),
                    repetitions=max(1, len(support)),
                    first_seen_at=moment.isoformat(),
                    last_seen_at=moment.isoformat(),
                    metadata={
                        "source_trace_ids": list(merged_ids),
                        "support_count": len(merged_ids),
                        "source_channels": channels,
                        "memory_state": "consolidated",
                        "consolidation_count": 1,
                    },
                )
            else:
                schema = existing
                schema.summary = summary
                schema.features = tuple(
                    dict.fromkeys((*schema.features, feature, "consolidated_pattern"))
                )[-32:]
                schema.last_seen_at = moment.isoformat()
                schema.repetitions += max(1, len(new_ids))
                schema.strength = self._unit(
                    schema.strength
                    + (1.0 - schema.strength)
                    * min(0.16, 0.03 + 0.02 * len(new_ids))
                )
                schema.salience = self._unit(
                    self._blend(schema.salience, avg_salience, 0.12)
                )
                schema.valence = self._signed(
                    self._blend(schema.valence, avg_valence, 0.10)
                )
                schema.arousal = self._unit(
                    self._blend(schema.arousal, avg_arousal, 0.10)
                )
                schema.metadata.update(
                    {
                        "source_trace_ids": list(merged_ids),
                        "support_count": len(merged_ids),
                        "source_channels": channels,
                        "memory_state": "consolidated",
                        "consolidation_count": int(
                            schema.metadata.get("consolidation_count") or 0
                        )
                        + 1,
                    }
                )
            self._save_trace(schema)
            created_or_strengthened.append(schema.summary)

            for trace in support:
                schema_ids = list(trace.metadata.get("schema_trace_ids") or ())
                if schema.trace_id not in schema_ids:
                    schema_ids.append(schema.trace_id)
                    trace.metadata["schema_trace_ids"] = schema_ids[-8:]
                    # Once shared structure has a stable representation, the
                    # individual episode can carry slightly less salience while
                    # still remaining available as concrete lived evidence.
                    trace.salience = max(0.02, trace.salience * 0.985)
                    self._save_trace(trace)
                self._strengthen_link(
                    schema.trace_id,
                    trace.trace_id,
                    amount=0.10 + 0.12 * trace.salience,
                )

        return tuple(created_or_strengthened)

    def _integrate_affect(self, trace: NeuralTrace, *, novelty: float) -> None:
        self._state.valence = self._signed(
            self._blend(
                self._state.valence,
                trace.valence,
                0.18 + 0.12 * trace.salience,
            )
        )
        self._state.arousal = self._unit(
            self._blend(
                self._state.arousal,
                max(trace.arousal, trace.salience * 0.7),
                0.22,
            )
        )
        tension_target = self._unit(
            max(0.0, -trace.valence) * 0.72 + trace.arousal * 0.28
        )
        self._state.tension = self._unit(
            self._blend(
                self._state.tension,
                tension_target,
                0.20 + 0.18 * trace.salience,
            )
        )
        curiosity_target = self._unit(
            0.25 + 0.65 * novelty + 0.10 * trace.arousal
        )
        self._state.curiosity = self._unit(
            self._blend(self._state.curiosity, curiosity_target, 0.20)
        )
        familiarity_target = self._unit(1.0 - novelty)
        self._state.familiarity = self._unit(
            self._blend(self._state.familiarity, familiarity_target, 0.16)
        )
        if trace.channel in {"action", "thought"}:
            self._state.fatigue = self._unit(
                self._state.fatigue + 0.01 + 0.025 * trace.arousal
            )
        self._state.dominant_signal = trace.summary[:500]
        self._save_state()

    def _save_trace(self, trace: NeuralTrace) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO neural_traces"
                "(trace_id,fingerprint,channel,strength,salience,repetitions,last_seen_at,data) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    trace.trace_id,
                    trace.fingerprint,
                    trace.channel,
                    trace.strength,
                    trace.salience,
                    trace.repetitions,
                    trace.last_seen_at,
                    json.dumps(
                        asdict(trace),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                ),
            )
            conn.commit()

    def _save_consolidation(self, report: NeuralConsolidationReport) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO neural_consolidations(created_at,data) VALUES(?,?)",
                (
                    report.at,
                    json.dumps(
                        asdict(report),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                ),
            )
            conn.execute(
                "DELETE FROM neural_consolidations WHERE consolidation_id < "
                "(SELECT COALESCE(MAX(consolidation_id),0)-255 "
                "FROM neural_consolidations)"
            )
            conn.commit()

    def _mark_activated(self, activations: list[NeuralActivation]) -> None:
        if not activations:
            return
        now = utc_now()
        for item in activations:
            trace = item.trace
            trace.last_activated_at = now
            trace.strength = self._unit(
                trace.strength
                + (1.0 - trace.strength) * 0.015 * item.activation
            )
            self._save_trace(trace)

    def _strengthen_link(self, left_id: str, right_id: str, *, amount: float) -> None:
        if left_id == right_id:
            return
        left, right = sorted((left_id, right_id))
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT strength,repetitions FROM neural_links "
                "WHERE left_id=? AND right_id=?",
                (left, right),
            ).fetchone()
            if row:
                old = float(row["strength"])
                strength = self._unit(
                    old + (1.0 - old) * self._unit(amount)
                )
                repetitions = int(row["repetitions"]) + 1
            else:
                strength = self._unit(amount)
                repetitions = 1
            conn.execute(
                "INSERT OR REPLACE INTO neural_links"
                "(left_id,right_id,strength,repetitions,updated_at) VALUES(?,?,?,?,?)",
                (left, right, strength, repetitions, utc_now()),
            )
            conn.commit()

    def _fade_links(self, moment: datetime) -> int:
        changed = 0
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT left_id,right_id,strength,repetitions,updated_at "
                "FROM neural_links ORDER BY updated_at ASC LIMIT 4096"
            ).fetchall()
            for row in rows:
                strength = float(row["strength"])
                repetitions = max(1, int(row["repetitions"]))
                age_days = self._age_days(str(row["updated_at"]), moment)
                if age_days <= 1.0:
                    continue
                resistance = self._unit(
                    0.55 * strength
                    + 0.45 * min(1.0, math.log1p(repetitions) / 3.2)
                )
                fade = self._unit((1.0 - resistance) * min(1.0, age_days / 120.0))
                if fade <= 0.03:
                    continue
                new_strength = strength * (1.0 - 0.10 * fade)
                left = str(row["left_id"])
                right = str(row["right_id"])
                if age_days >= 90.0 and repetitions <= 1 and new_strength < 0.03:
                    conn.execute(
                        "DELETE FROM neural_links WHERE left_id=? AND right_id=?",
                        (left, right),
                    )
                else:
                    conn.execute(
                        "UPDATE neural_links SET strength=? WHERE left_id=? AND right_id=?",
                        (new_strength, left, right),
                    )
                changed += 1
            conn.commit()
        return changed

    def _links_for(self, trace_ids: list[str]) -> list[tuple[str, str, float]]:
        if not trace_ids:
            return []
        rows_out: list[tuple[str, str, float]] = []
        # Batch the IN clauses so consolidation/recall keeps working even after
        # the network contains more nodes than SQLite's variable limit.
        for start in range(0, len(trace_ids), 300):
            batch = trace_ids[start : start + 300]
            placeholders = ",".join("?" for _ in batch)
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    f"SELECT left_id,right_id,strength FROM neural_links "
                    f"WHERE left_id IN ({placeholders}) "
                    f"OR right_id IN ({placeholders})",
                    (*batch, *batch),
                ).fetchall()
            rows_out.extend(
                (
                    str(row["left_id"]),
                    str(row["right_id"]),
                    float(row["strength"]),
                )
                for row in rows
            )
        return rows_out

    def _link_strength_profile(self, trace_ids: set[str]) -> dict[str, float]:
        profile: dict[str, float] = {}
        if not trace_ids:
            return profile
        for left, right, strength in self._links_for(list(trace_ids)):
            if left in trace_ids:
                profile[left] = max(profile.get(left, 0.0), strength)
            if right in trace_ids:
                profile[right] = max(profile.get(right, 0.0), strength)
        return profile

    def _delete_trace(self, trace_id: str) -> bool:
        """Delete one unretained trace and report whether it was removed.

        Durable subsystems may install database-level retention guards.  The
        row count is therefore authoritative: an ignored delete must neither
        discard the trace's links nor be reported as successful pruning.
        """
        with closing(self._connect()) as conn:
            removed = conn.execute(
                "DELETE FROM neural_traces WHERE trace_id=?", (trace_id,)
            ).rowcount
            if removed:
                conn.execute(
                    "DELETE FROM neural_links WHERE left_id=? OR right_id=?",
                    (trace_id, trace_id),
                )
            conn.commit()
        return bool(removed)

    def _get_by_fingerprint(self, fingerprint: str) -> NeuralTrace | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT data FROM neural_traces WHERE fingerprint=?",
                (fingerprint,),
            ).fetchone()
        return self._trace_from_row(row)

    def _get_trace(self, trace_id: str) -> NeuralTrace | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT data FROM neural_traces WHERE trace_id=?",
                (trace_id,),
            ).fetchone()
        return self._trace_from_row(row)

    def _trace_count(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM neural_traces").fetchone()
        return int(row["count"] if row else 0)

    def _candidate_traces(self, limit: int) -> list[NeuralTrace]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT data FROM neural_traces "
                "ORDER BY strength DESC, salience DESC, last_seen_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [self._trace_from_row(row) for row in rows if row]

    def _traces_for_consolidation(self, limit: int) -> list[NeuralTrace]:
        bounded = max(32, int(limit))
        half = max(16, bounded // 2)
        with closing(self._connect()) as conn:
            recent_rows = conn.execute(
                "SELECT data FROM neural_traces "
                "ORDER BY last_seen_at DESC LIMIT ?",
                (half,),
            ).fetchall()
            old_rows = conn.execute(
                "SELECT data FROM neural_traces "
                "ORDER BY last_seen_at ASC LIMIT ?",
                (half,),
            ).fetchall()
        deduped: dict[str, NeuralTrace] = {}
        for row in (*recent_rows, *old_rows):
            trace = self._trace_from_row(row)
            if trace is not None:
                deduped[trace.trace_id] = trace
        return list(deduped.values())[:bounded]

    def _recent_traces(
        self,
        limit: int,
        *,
        exclude_trace_id: str | None = None,
    ) -> list[NeuralTrace]:
        query = "SELECT data FROM neural_traces"
        params: list[Any] = []
        if exclude_trace_id:
            query += " WHERE trace_id<>?"
            params.append(exclude_trace_id)
        query += " ORDER BY last_seen_at DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with closing(self._connect()) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._trace_from_row(row) for row in rows if row]

    @staticmethod
    def _trace_from_row(row: sqlite3.Row | None) -> NeuralTrace | None:
        if not row:
            return None
        raw = json.loads(row["data"])
        raw["features"] = tuple(raw.get("features") or ())
        raw["metadata"] = dict(raw.get("metadata") or {})
        return NeuralTrace(**raw)

    def _load_state(self) -> AffectiveState:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT data FROM nervous_state WHERE id=1").fetchone()
        if not row:
            state = AffectiveState()
            self._state = state
            self._save_state()
            return state
        raw = json.loads(row["data"])
        defaults = asdict(AffectiveState())
        defaults.update(raw)
        return AffectiveState(**defaults)

    def _save_state(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO nervous_state(id,data,updated_at) VALUES(1,?,?)",
                (
                    json.dumps(
                        asdict(self._state),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    utc_now(),
                ),
            )
            conn.commit()

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS neural_traces(
                    trace_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    channel TEXT NOT NULL,
                    strength REAL NOT NULL,
                    salience REAL NOT NULL,
                    repetitions INTEGER NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_neural_traces_channel
                    ON neural_traces(channel, strength DESC, last_seen_at DESC);
                CREATE TABLE IF NOT EXISTS neural_links(
                    left_id TEXT NOT NULL,
                    right_id TEXT NOT NULL,
                    strength REAL NOT NULL,
                    repetitions INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(left_id,right_id)
                );
                CREATE TABLE IF NOT EXISTS nervous_state(
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS neural_consolidations(
                    consolidation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @classmethod
    def _fingerprint(
        cls,
        channel: str,
        summary: str,
        features: tuple[str, ...],
    ) -> str:
        normalized = cls._normalize_text(summary)
        stable = f"{channel}|{normalized}|{'|'.join(features[:12])}"
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_channel(value: str) -> str:
        text = str(value or "sense").strip().lower().replace(" ", "_")
        text = re.sub(r"[^a-z0-9_./-]+", "", text)
        return text or "sense"

    @classmethod
    def _normalize_features(cls, values: Iterable[str]) -> tuple[str, ...]:
        normalized: list[str] = []
        for item in values:
            text = cls._normalize_text(str(item))
            if text and text not in normalized:
                normalized.append(text)
        return tuple(normalized[-32:])

    @classmethod
    def _usable_schema_feature(cls, value: str) -> bool:
        text = cls._normalize_text(value)
        if not text or text in cls._GENERIC_FEATURES:
            return False
        if len(text) < 3 and not re.search(r"[\u4e00-\u9fff]", text):
            return False
        return len(text) <= 120

    @staticmethod
    def _normalize_text(value: str) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"\s+", " ", text)
        return text[:2000]

    @classmethod
    def _tokens(cls, value: str) -> set[str]:
        normalized = cls._normalize_text(value)
        latin = re.findall(r"[a-z0-9_+./-]{2,}", normalized)
        han = re.findall(r"[\u4e00-\u9fff]", normalized)
        return set((*latin, *han))

    @staticmethod
    def _overlap(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / max(1, len(left))

    @staticmethod
    def _blend(old: float, new: float, alpha: float) -> float:
        weight = max(0.0, min(1.0, alpha))
        return old * (1.0 - weight) + new * weight

    @staticmethod
    def _unit(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _signed(value: float) -> float:
        return max(-1.0, min(1.0, float(value)))

    @classmethod
    def _recency(cls, timestamp: str) -> float:
        parsed = cls._parse_time(timestamp)
        if parsed is None:
            return 0.0
        age = max(
            0.0,
            (datetime.now(timezone.utc) - parsed).total_seconds(),
        )
        return math.exp(-age / (7.0 * 24.0 * 3600.0))

    @classmethod
    def _age_days(cls, timestamp: str | None, moment: datetime) -> float:
        parsed = cls._parse_time(timestamp)
        if parsed is None:
            return 3650.0
        return max(0.0, (moment - parsed).total_seconds() / 86400.0)

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _body_signal(body: dict[str, Any]) -> str:
        host = str(body.get("hostname") or "unknown-host")
        cwd = str(body.get("cwd") or "unknown-cwd")
        pid = str(body.get("pid") or "unknown-pid")
        return f"host={host}; pid={pid}; cwd={cwd}"[:500]
