from __future__ import annotations

import json
import math
from contextlib import closing
from dataclasses import asdict
from typing import Any, Iterable

from .models import utc_now
from .nervous_system import AffectiveState, NeuralTrace, PersistentNervousSystem


class EventOutcomeNervousSystem(PersistentNervousSystem):
    """Persistent nervous system with event-identity-safe outcome plasticity.

    Generic perception remains deliberately plastic: seeing the same thing again
    is new lived evidence and strengthens the network again. A durable resident
    EventOutcome is different. It is terminal truth for one event and may be
    revisited during restart repair, so the outcome's trace, co-active links,
    affect update, and event receipt must become visible together or not at all.
    """

    _OUTCOME_RECEIPT_TABLE = "neural_event_outcomes"
    _OUTCOME_STATE_TABLE = "neural_event_outcome_state"

    def __init__(self, store):
        super().__init__(store)
        self._init_outcome_schema()

    def perceive_event_outcome(
        self,
        event_id: str,
        summary: str,
        *,
        features: Iterable[str] = (),
        source: str = "self",
        salience: float = 0.5,
        valence: float = 0.0,
        arousal: float = 0.2,
        metadata: dict[str, Any] | None = None,
    ) -> NeuralTrace:
        """Apply one durable EventOutcome to nervous plasticity exactly once.

        Event identity, rather than trace fingerprint, is the dedupe key. Two
        distinct events with the same summary are still two lived outcomes and
        therefore strengthen one trace twice. Replaying the same EventOutcome
        during repair is a no-op.
        """
        normalized_event_id = str(event_id or "").strip()
        text = str(summary or "").strip()
        if not normalized_event_id:
            raise ValueError("event outcome perception requires event_id")
        if not text:
            raise ValueError("neural perception summary must not be empty")

        normalized_channel = "outcome"
        normalized_features = self._normalize_features(features)
        fingerprint = self._fingerprint(
            normalized_channel,
            text,
            normalized_features,
        )
        now = utc_now()

        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                receipt = conn.execute(
                    f"SELECT trace_id FROM {self._OUTCOME_RECEIPT_TABLE} "
                    "WHERE event_id=?",
                    (normalized_event_id,),
                ).fetchone()
                if receipt:
                    row = conn.execute(
                        "SELECT data FROM neural_traces WHERE trace_id=?",
                        (str(receipt["trace_id"]),),
                    ).fetchone()
                    trace = self._trace_from_row(row)
                    if trace is None:
                        raise RuntimeError(
                            "event outcome receipt references a missing neural trace"
                        )
                    conn.rollback()
                    return trace

                prior_row = conn.execute(
                    "SELECT data FROM neural_traces WHERE fingerprint=?",
                    (fingerprint,),
                ).fetchone()
                prior = self._trace_from_row(prior_row)
                novelty = 1.0 if prior is None else max(0.0, 1.0 - prior.strength)
                trace = self._build_outcome_trace(
                    prior=prior,
                    fingerprint=fingerprint,
                    text=text,
                    features=normalized_features,
                    source=source,
                    salience=salience,
                    valence=valence,
                    arousal=arousal,
                    event_id=normalized_event_id,
                    metadata=metadata,
                    now=now,
                )

                recent_rows = conn.execute(
                    "SELECT data FROM neural_traces WHERE trace_id<>? "
                    "ORDER BY last_seen_at DESC LIMIT 6",
                    (trace.trace_id,),
                ).fetchall()
                recent = [
                    item
                    for row in recent_rows
                    if (item := self._trace_from_row(row)) is not None
                ]

                self._write_trace(conn, trace)
                for other in recent:
                    self._write_strengthened_link(
                        conn,
                        trace.trace_id,
                        other.trace_id,
                        amount=0.025 + 0.10 * trace.salience,
                    )

                state = self._state_from_connection(conn)
                next_state = self._integrated_state(
                    state,
                    trace,
                    novelty=novelty,
                )
                conn.execute(
                    "INSERT OR REPLACE INTO nervous_state(id,data,updated_at) "
                    "VALUES(1,?,?)",
                    (
                        json.dumps(
                            asdict(next_state),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        now,
                    ),
                )
                conn.execute(
                    f"INSERT INTO {self._OUTCOME_RECEIPT_TABLE}"
                    "(event_id,trace_id,perceived_at) VALUES(?,?,?)",
                    (normalized_event_id, trace.trace_id, now),
                )
                self._before_event_outcome_commit(
                    conn,
                    event_id=normalized_event_id,
                    trace=trace,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        # Never let in-memory affect get ahead of durable truth. The resident can
        # only adopt the new state after the transaction containing its receipt
        # has committed successfully.
        self._state = next_state
        return trace

    def has_event_outcome(self, event_id: str) -> bool:
        normalized = str(event_id or "").strip()
        if not normalized:
            return False
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT 1 FROM {self._OUTCOME_RECEIPT_TABLE} WHERE event_id=?",
                (normalized,),
            ).fetchone()
        return row is not None

    def repair_from(self) -> str:
        """Return the durable activation cutoff for safe restart reconciliation.

        Existing databases may already contain outcomes that the legacy nervous
        path perceived without event receipts. The first installation records a
        cutoff instead of guessing whether those historical outcomes were seen;
        restart repair is therefore limited to terminal outcomes created after
        event-identity-safe perception became active.
        """
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT repair_from FROM {self._OUTCOME_STATE_TABLE} WHERE id=1"
            ).fetchone()
        if not row:
            raise RuntimeError("event outcome nervous activation state is missing")
        return str(row["repair_from"])

    def _build_outcome_trace(
        self,
        *,
        prior: NeuralTrace | None,
        fingerprint: str,
        text: str,
        features: tuple[str, ...],
        source: str,
        salience: float,
        valence: float,
        arousal: float,
        event_id: str,
        metadata: dict[str, Any] | None,
        now: str,
    ) -> NeuralTrace:
        event_metadata = {**dict(metadata or {}), "event_id": event_id}
        if prior is None:
            return NeuralTrace(
                trace_id=f"trace-{fingerprint[:16]}",
                fingerprint=fingerprint,
                channel="outcome",
                summary=text,
                features=features,
                source=str(source or "self").strip() or "self",
                strength=self._unit(0.30 + 0.45 * self._unit(salience)),
                salience=self._unit(salience),
                valence=self._signed(valence),
                arousal=self._unit(arousal),
                first_seen_at=now,
                last_seen_at=now,
                metadata=event_metadata,
            )

        repetitions = prior.repetitions + 1
        alpha = min(0.35, 0.10 + math.log1p(repetitions) * 0.025)
        return NeuralTrace(
            trace_id=prior.trace_id,
            fingerprint=prior.fingerprint,
            channel=prior.channel,
            summary=text,
            features=tuple(dict.fromkeys((*prior.features, *features)))[-32:],
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
            metadata={**prior.metadata, **event_metadata},
        )

    @staticmethod
    def _write_trace(conn, trace: NeuralTrace) -> None:
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

    def _write_strengthened_link(
        self,
        conn,
        left_id: str,
        right_id: str,
        *,
        amount: float,
    ) -> None:
        if left_id == right_id:
            return
        left, right = sorted((left_id, right_id))
        row = conn.execute(
            "SELECT strength,repetitions FROM neural_links "
            "WHERE left_id=? AND right_id=?",
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

    def _state_from_connection(self, conn) -> AffectiveState:
        row = conn.execute("SELECT data FROM nervous_state WHERE id=1").fetchone()
        if not row:
            return AffectiveState()
        raw = json.loads(row["data"])
        defaults = asdict(AffectiveState())
        defaults.update(raw)
        return AffectiveState(**defaults)

    def _integrated_state(
        self,
        state: AffectiveState,
        trace: NeuralTrace,
        *,
        novelty: float,
    ) -> AffectiveState:
        next_state = AffectiveState(**asdict(state))
        next_state.valence = self._signed(
            self._blend(
                next_state.valence,
                trace.valence,
                0.18 + 0.12 * trace.salience,
            )
        )
        next_state.arousal = self._unit(
            self._blend(
                next_state.arousal,
                max(trace.arousal, trace.salience * 0.7),
                0.22,
            )
        )
        tension_target = self._unit(
            max(0.0, -trace.valence) * 0.72 + trace.arousal * 0.28
        )
        next_state.tension = self._unit(
            self._blend(
                next_state.tension,
                tension_target,
                0.20 + 0.18 * trace.salience,
            )
        )
        curiosity_target = self._unit(
            0.25 + 0.65 * novelty + 0.10 * trace.arousal
        )
        next_state.curiosity = self._unit(
            self._blend(next_state.curiosity, curiosity_target, 0.20)
        )
        familiarity_target = self._unit(1.0 - novelty)
        next_state.familiarity = self._unit(
            self._blend(next_state.familiarity, familiarity_target, 0.16)
        )
        next_state.dominant_signal = trace.summary[:500]
        return next_state

    def _before_event_outcome_commit(self, conn, *, event_id: str, trace: NeuralTrace) -> None:
        """Fault-injection seam used to verify rollback of the whole plasticity unit."""

    def _init_outcome_schema(self) -> None:
        activation = utc_now()
        with closing(self._connect()) as conn:
            conn.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._OUTCOME_RECEIPT_TABLE}(
                    event_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    perceived_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_neural_event_outcomes_trace
                    ON {self._OUTCOME_RECEIPT_TABLE}(trace_id);
                CREATE TABLE IF NOT EXISTS {self._OUTCOME_STATE_TABLE}(
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    repair_from TEXT NOT NULL
                );
                """
            )
            conn.execute(
                f"INSERT OR IGNORE INTO {self._OUTCOME_STATE_TABLE}(id,repair_from) "
                "VALUES(1,?)",
                (activation,),
            )
            conn.commit()
