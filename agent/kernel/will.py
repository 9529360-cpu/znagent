from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import utc_now
from .store import KernelStore


@dataclass(slots=True)
class ResidentIntention:
    """A durable thing ZN still intends to bring about.

    An intention is not a prompt, model Goal, or compiled skill. It belongs to
    the resident Self and may outlive any individual event used to advance it.
    The current ``next_task`` is only one concrete step, not the whole identity
    of the intention.
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
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


class NativeWill:
    """Persistent Will owned by ZN itself.

    This organ stores intentions and their current concrete step. It does not
    invent plans with a model and it does not impose a policy framework. Life
    can notice an intention; Thought can choose to advance it; normal resident
    execution then handles the resulting internal event.
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
            next_task=(str(next_task).strip() if next_task and str(next_task).strip() else None),
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
        """Repair the small crash window between event outcome and Will update.

        Event outcomes are durable resident experience. If a process dies after
        an intention step has completed but before ``observe_event_outcome`` ran,
        the intention must not remain permanently engaged. On wake, Will can
        infer the missing handoff from the already-persisted event outcome.
        """
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
        else:
            intention.status = "active"
        self._save(intention)
        return intention

    def complete(self, intention_id: str, *, summary: str | None = None) -> ResidentIntention:
        intention = self._require(intention_id)
        intention.status = "completed"
        intention.related_event_id = None
        intention.next_task = None
        intention.current_step = None
        if summary:
            intention.last_outcome = str(summary)[:1000]
            intention.progress = (*intention.progress, str(summary)[:500])[-64:]
        intention.updated_at = utc_now()
        self._save(intention)
        return intention

    def pause(self, intention_id: str, *, reason: str | None = None) -> ResidentIntention:
        intention = self._require(intention_id)
        intention.status = "paused"
        intention.related_event_id = None
        if reason:
            intention.progress = (*intention.progress, f"paused: {reason}"[:500])[-64:]
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
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
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
        data.setdefault("current_step", None)
        data.setdefault("next_task", None)
        data.setdefault("related_event_id", None)
        data.setdefault("last_outcome", None)
        data.setdefault("complete_on_step_success", False)
        return ResidentIntention(**data)
