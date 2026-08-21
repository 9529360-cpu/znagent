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


class PersistentNervousSystem:
    """ZN's persistent associative memory and affective nervous system.

    The important distinction from a conventional memory layer is that lived
    experience changes the network itself:

    * repetition strengthens a trace instead of appending endless copies;
    * co-occurrence strengthens associations between traces;
    * recall is cue-driven activation with spreading association;
    * salient success/failure changes persistent affective state;
    * visual, world/web, body, thought, and action perceptions share the same
      substrate and can therefore become associated.

    No language model is required for encoding or recall.
    """

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
                strength=self._unit(prior.strength + (1.0 - prior.strength) * (0.08 + 0.12 * self._unit(salience))),
                salience=self._blend(prior.salience, self._unit(salience), alpha),
                valence=self._signed(self._blend(prior.valence, self._signed(valence), alpha)),
                arousal=self._unit(self._blend(prior.arousal, self._unit(arousal), alpha)),
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

        seed_ids = [item[0] for item in sorted(direct.items(), key=lambda pair: pair[1][0], reverse=True)[:12]]
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
        self._state.curiosity = self._blend(self._state.curiosity, 0.35, decay * 0.5)
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
                    self._state.tension = self._unit(max(self._state.tension, 0.65))
                    self._state.arousal = self._unit(max(self._state.arousal, 0.50))

        self._state.heartbeat_count += 1
        self._state.last_heartbeat_at = utc_now()
        self._save_state()
        return self.snapshot()

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

    def _integrate_affect(self, trace: NeuralTrace, *, novelty: float) -> None:
        self._state.valence = self._signed(
            self._blend(self._state.valence, trace.valence, 0.18 + 0.12 * trace.salience)
        )
        self._state.arousal = self._unit(
            self._blend(self._state.arousal, max(trace.arousal, trace.salience * 0.7), 0.22)
        )
        tension_target = self._unit(max(0.0, -trace.valence) * 0.72 + trace.arousal * 0.28)
        self._state.tension = self._unit(
            self._blend(self._state.tension, tension_target, 0.20 + 0.18 * trace.salience)
        )
        curiosity_target = self._unit(0.25 + 0.65 * novelty + 0.10 * trace.arousal)
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
                    json.dumps(asdict(trace), ensure_ascii=False, separators=(",", ":")),
                ),
            )
            conn.commit()

    def _mark_activated(self, activations: list[NeuralActivation]) -> None:
        if not activations:
            return
        now = utc_now()
        for item in activations:
            trace = item.trace
            trace.last_activated_at = now
            trace.strength = self._unit(trace.strength + (1.0 - trace.strength) * 0.015 * item.activation)
            self._save_trace(trace)

    def _strengthen_link(self, left_id: str, right_id: str, *, amount: float) -> None:
        if left_id == right_id:
            return
        left, right = sorted((left_id, right_id))
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT strength,repetitions FROM neural_links WHERE left_id=? AND right_id=?",
                (left, right),
            ).fetchone()
            if row:
                old = float(row["strength"])
                strength = self._unit(old + (1.0 - old) * self._unit(amount))
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

    def _links_for(self, trace_ids: list[str]) -> list[tuple[str, str, float]]:
        if not trace_ids:
            return []
        placeholders = ",".join("?" for _ in trace_ids)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT left_id,right_id,strength FROM neural_links "
                f"WHERE left_id IN ({placeholders}) OR right_id IN ({placeholders})",
                (*trace_ids, *trace_ids),
            ).fetchall()
        return [
            (str(row["left_id"]), str(row["right_id"]), float(row["strength"]))
            for row in rows
        ]

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

    def _candidate_traces(self, limit: int) -> list[NeuralTrace]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT data FROM neural_traces "
                "ORDER BY strength DESC, salience DESC, last_seen_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [self._trace_from_row(row) for row in rows if row]

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
                    json.dumps(asdict(self._state), ensure_ascii=False, separators=(",", ":")),
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
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @classmethod
    def _fingerprint(cls, channel: str, summary: str, features: tuple[str, ...]) -> str:
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
        age = max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())
        return math.exp(-age / (7.0 * 24.0 * 3600.0))

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
