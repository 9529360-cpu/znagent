from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .models import utc_now
from .store import KernelStore


@dataclass(slots=True)
class ResidentIntention:
    """A durable thing ZN still intends to bring about.

    An intention is not a prompt, model Goal, or compiled skill. It belongs to
    the resident Self and may outlive any individual event used to advance it.
    The current ``next_task`` is only one concrete step, not the whole identity
    of the intention. When no step exists, a single candidate can incubate over
    repeated lived evidence instead of being invented and discarded every
    heartbeat.
    """

    intention_id: str
    description: str
    source: str = "self"
    priority: int = 0
    status: str = "active"
    current_step: str | None = None
    next_task: str | None = None
    next_payload: dict[str, Any] = field(default_factory=dict)
    related_event_id: str | None = None
    last_outcome: str | None = None
    complete_on_step_success: bool = False
    progress: tuple[str, ...] = ()
    candidate_kind: str | None = None
    candidate_step: str | None = None
    candidate_reason: str | None = None
    candidate_payload: dict[str, Any] = field(default_factory=dict)
    candidate_support: tuple[str, ...] = ()
    candidate_confidence: float = 0.0
    candidate_repetitions: int = 0
    incubation_count: int = 0
    last_incubated_at: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @property
    def candidate_maturity(self) -> float:
        """How stable the one currently incubating next step has become."""
        repetition = min(1.0, max(0, self.candidate_repetitions) / 4.0)
        support = min(1.0, len(self.candidate_support) / 5.0)
        return max(
            0.0,
            min(
                1.0,
                0.62 * float(self.candidate_confidence)
                + 0.23 * repetition
                + 0.15 * support,
            ),
        )


class NativeWill:
    """Persistent Will owned by ZN itself.

    This organ stores intentions, their current concrete step, and at most one
    incubating candidate step. It does not invent plans with a model and it
    does not accumulate a list of micro-plans. Repeated native evidence can
    strengthen or replace the one candidate that currently makes most sense.
    """

    def __init__(self, store: KernelStore):
        self.store = store
        self._init_schema()

    def intend(
        self,
        description: str,
        *,
        source: str = "self",
        priority: int = 0,
        next_task: str | None = None,
        next_payload: dict[str, Any] | None = None,
        complete_on_step_success: bool = False,
    ) -> ResidentIntention:
        text = str(description or "").strip()
        if not text:
            raise ValueError("intention description must not be empty")
        now = utc_now()
        intention = ResidentIntention(
            intention_id=f"intent-{uuid.uuid4().hex[:12]}",
            description=text,
            source=str(source or "self").strip() or "self",
            priority=int(priority),
            next_task=(
                str(next_task).strip()
                if next_task and str(next_task).strip()
                else None
            ),
            next_payload=dict(next_payload or {}),
            complete_on_step_success=bool(complete_on_step_success),
            created_at=now,
            updated_at=now,
        )
        self._save(intention)
        return intention

    def get(self, intention_id: str) -> ResidentIntention | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT data FROM resident_intentions WHERE intention_id=?",
                (str(intention_id),),
            ).fetchone()
        return self._from_raw(json.loads(row["data"])) if row else None

    def active(self, limit: int = 50) -> list[ResidentIntention]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT data FROM resident_intentions "
                "WHERE status IN ('active','engaged') "
                "ORDER BY priority DESC, updated_at ASC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [self._from_raw(json.loads(row["data"])) for row in rows]

    def primary(self) -> ResidentIntention | None:
        intentions = self.active(1)
        return intentions[0] if intentions else None

    def reconcile_outcomes(self, limit: int = 100) -> int:
        """Repair the small crash window between event outcome and Will update."""
        repaired = 0
        for intention in self.active(limit):
            if intention.status != "engaged" or not intention.related_event_id:
                continue
            outcome = self.store.get_event_outcome(intention.related_event_id)
            if outcome is None:
                continue
            summary = (
                outcome.response
                or outcome.reason
                or ("step succeeded" if outcome.success else "step failed")
            )
            self.observe_event_outcome(
                intention.intention_id,
                event_id=intention.related_event_id,
                success=outcome.success,
                summary=summary,
            )
            repaired += 1
        return repaired

    def incubate_candidate(
        self,
        intention_id: str,
        *,
        kind: str,
        step: str,
        reason: str,
        confidence: float,
        support: Iterable[str] = (),
        payload: dict[str, Any] | None = None,
    ) -> ResidentIntention:
        """Let one possible next step mature across repeated native evidence.

        Will deliberately keeps one candidate rather than a plan list. Seeing
        the same candidate again strengthens it. A different candidate replaces
        the current one only when it has materially stronger support or the old
        candidate never became established.
        """
        intention = self._require(intention_id)
        if intention.status != "active" or intention.related_event_id:
            return intention
        if intention.next_task:
            return intention

        normalized_kind = str(kind or "native_reflection").strip() or "native_reflection"
        normalized_step = str(step or "").strip()
        normalized_reason = str(reason or "").strip()
        if not normalized_step:
            raise ValueError("incubating intention step must not be empty")
        incoming_confidence = max(0.0, min(1.0, float(confidence)))
        incoming_support = tuple(
            dict.fromkeys(
                str(item).strip()
                for item in support
                if str(item).strip()
            )
        )[-12:]
        same = (
            intention.candidate_kind == normalized_kind
            and intention.candidate_step == normalized_step
        )

        if same:
            intention.candidate_repetitions += 1
            intention.candidate_confidence = min(
                1.0,
                max(intention.candidate_confidence, incoming_confidence)
                + 0.04 * (1.0 - intention.candidate_confidence),
            )
            intention.candidate_support = tuple(
                dict.fromkeys((*intention.candidate_support, *incoming_support))
            )[-12:]
            if normalized_reason:
                intention.candidate_reason = normalized_reason[:1000]
            if payload:
                intention.candidate_payload = {
                    **intention.candidate_payload,
                    **dict(payload),
                }
        else:
            existing_maturity = intention.candidate_maturity
            replace = (
                intention.candidate_step is None
                or intention.candidate_repetitions <= 1
                or incoming_confidence >= existing_maturity + 0.08
            )
            if replace:
                intention.candidate_kind = normalized_kind
                intention.candidate_step = normalized_step
                intention.candidate_reason = normalized_reason[:1000] or None
                intention.candidate_payload = dict(payload or {})
                intention.candidate_support = incoming_support
                intention.candidate_confidence = incoming_confidence
                intention.candidate_repetitions = 1

        intention.incubation_count += 1
        intention.last_incubated_at = utc_now()
        intention.updated_at = intention.last_incubated_at
        self._save(intention)
        return intention

    def clear_candidate(self, intention_id: str) -> ResidentIntention:
        intention = self._require(intention_id)
        self._clear_candidate_fields(intention)
        intention.updated_at = utc_now()
        self._save(intention)
        return intention

    def promote_candidate(
        self,
        intention_id: str,
        *,
        min_maturity: float = 0.72,
        min_repetitions: int = 2,
    ) -> ResidentIntention:
        """Turn a sufficiently stable candidate into the intention's next step."""
        intention = self._require(intention_id)
        if not intention.candidate_step:
            return intention
        if intention.candidate_repetitions < max(1, int(min_repetitions)):
            return intention
        if intention.candidate_maturity < max(0.0, min(1.0, float(min_maturity))):
            return intention

        step = intention.candidate_step
        payload = dict(intention.candidate_payload)
        payload.setdefault("incubated_kind", intention.candidate_kind)
        payload.setdefault("incubated_reason", intention.candidate_reason)
        payload.setdefault("incubated_support", list(intention.candidate_support))
        self._clear_candidate_fields(intention)
        intention.next_task = step
        intention.next_payload = payload
        intention.status = "active"
        intention.related_event_id = None
        intention.progress = (
            *intention.progress,
            f"incubated next step matured: {step[:500]}",
        )[-64:]
        intention.updated_at = utc_now()
        self._save(intention)
        return intention

    def set_next_step(
        self,
        intention_id: str,
        task: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> ResidentIntention:
        intention = self._require(intention_id)
        step = str(task or "").strip()
        if not step:
            raise ValueError("intention step must not be empty")
        self._clear_candidate_fields(intention)
        intention.next_task = step
        intention.next_payload = dict(payload or {})
        intention.status = "active"
        intention.related_event_id = None
        intention.updated_at = utc_now()
        self._save(intention)
        return intention

    def engage(self, intention_id: str, event_id: str) -> ResidentIntention:
        intention = self._require(intention_id)
        if not intention.next_task:
            raise ValueError("intention has no concrete next task")
        intention.current_step = intention.next_task
        intention.next_task = None
        intention.next_payload = {}
        intention.related_event_id = str(event_id)
        intention.status = "engaged"
        intention.updated_at = utc_now()
        intention.progress = (
            *intention.progress,
            f"engaged step via event {event_id}: {intention.current_step}",
        )[-64:]
        self._save(intention)
        return intention

    def observe_event_outcome(
        self,
        intention_id: str,
        *,
        event_id: str,
        success: bool,
        summary: str,
    ) -> ResidentIntention:
        intention = self._require(intention_id)
        outcome = str(summary or "").strip() or (
            "step succeeded" if success else "step failed"
        )
        intention.last_outcome = outcome[:1000]
        intention.related_event_id = None
        intention.updated_at = utc_now()
        intention.progress = (
            *intention.progress,
            f"event {event_id} {'succeeded' if success else 'failed'}: {outcome[:500]}",
        )[-64:]
        if success and intention.complete_on_step_success:
            intention.status = "completed"
            intention.current_step = None
            self._clear_candidate_fields(intention)
        else:
            intention.status = "active"
        self._save(intention)
        return intention

    def complete(
        self,
        intention_id: str,
        *,
        summary: str | None = None,
    ) -> ResidentIntention:
        intention = self._require(intention_id)
        intention.status = "completed"
        intention.related_event_id = None
        intention.next_task = None
        intention.current_step = None
        self._clear_candidate_fields(intention)
        if summary:
            intention.last_outcome = str(summary)[:1000]
            intention.progress = (*intention.progress, str(summary)[:500])[-64:]
        intention.updated_at = utc_now()
        self._save(intention)
        return intention

    def pause(
        self,
        intention_id: str,
        *,
        reason: str | None = None,
    ) -> ResidentIntention:
        intention = self._require(intention_id)
        intention.status = "paused"
        intention.related_event_id = None
        if reason:
            intention.progress = (
                *intention.progress,
                f"paused: {reason}"[:500],
            )[-64:]
        intention.updated_at = utc_now()
        self._save(intention)
        return intention

    def list_all(self, limit: int = 100) -> list[ResidentIntention]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT data FROM resident_intentions "
                "ORDER BY updated_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [self._from_raw(json.loads(row["data"])) for row in rows]

    def _require(self, intention_id: str) -> ResidentIntention:
        intention = self.get(intention_id)
        if intention is None:
            raise KeyError(f"unknown resident intention: {intention_id}")
        return intention

    @staticmethod
    def _clear_candidate_fields(intention: ResidentIntention) -> None:
        intention.candidate_kind = None
        intention.candidate_step = None
        intention.candidate_reason = None
        intention.candidate_payload = {}
        intention.candidate_support = ()
        intention.candidate_confidence = 0.0
        intention.candidate_repetitions = 0

    def _save(self, intention: ResidentIntention) -> None:
        intention.updated_at = utc_now()
        payload = asdict(intention)
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO resident_intentions"
                "(intention_id,status,priority,updated_at,data) VALUES(?,?,?,?,?)",
                (
                    intention.intention_id,
                    intention.status,
                    intention.priority,
                    intention.updated_at,
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                ),
            )
            conn.commit()

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS resident_intentions(
                    intention_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_resident_intentions_active
                    ON resident_intentions(status, priority DESC, updated_at ASC);
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @staticmethod
    def _from_raw(raw: dict[str, Any]) -> ResidentIntention:
        data = dict(raw)
        data["next_payload"] = dict(data.get("next_payload") or {})
        data["progress"] = tuple(data.get("progress") or ())
        data["candidate_payload"] = dict(data.get("candidate_payload") or {})
        data["candidate_support"] = tuple(data.get("candidate_support") or ())
        data.setdefault("current_step", None)
        data.setdefault("next_task", None)
        data.setdefault("related_event_id", None)
        data.setdefault("last_outcome", None)
        data.setdefault("complete_on_step_success", False)
        data.setdefault("candidate_kind", None)
        data.setdefault("candidate_step", None)
        data.setdefault("candidate_reason", None)
        data.setdefault("candidate_confidence", 0.0)
        data.setdefault("candidate_repetitions", 0)
        data.setdefault("incubation_count", 0)
        data.setdefault("last_incubated_at", None)
        return ResidentIntention(**data)
