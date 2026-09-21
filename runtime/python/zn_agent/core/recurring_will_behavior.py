from __future__ import annotations

"""Bounded recurring triggers for the existing resident Will.

This is not a general scheduler and never owns Work, Body execution, routing, or
completion. A fixed-interval trigger may only materialize one due occurrence as
the existing ``NativeWill`` intention's ``next_task``. Situation/Thought then
decide whether to advance that intention through the normal Resident event path.

The crash window between advancing a recurring due time and handing the exact
occurrence to Will is closed with one durable ``pending_scheduled_at`` stamp.
This is the ZN-shaped form of a mature scheduler invariant: never silently lose
a due slot just because the process stopped between bookkeeping and dispatch.
Missed intervals are coalesced to one latest occurrence so restart/long-running
work cannot create a backlog burst.

Recurring triggers intentionally retain no Body/action argument template and no
execution authority. A future occurrence carries only schedule evidence and
``fresh_revalidation_required``; the existing Resident must establish current
world facts and authority again before any side effect.
"""

import sqlite3
import threading
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from .models import utc_now


_MIN_INTERVAL_SECONDS = 60
_MAX_INTERVAL_SECONDS = 366 * 24 * 60 * 60
_INSTALL_MARKER = "_zn_recurring_will_behavior_installed"


@dataclass(slots=True)
class RecurringWillTrigger:
    intention_id: str
    task: str
    interval_seconds: int
    next_due_at: str
    enabled: bool = True
    pending_scheduled_at: str | None = None
    pending_coalesced_missed: int = 0
    last_activated_at: str | None = None
    created_at: str = ""
    updated_at: str = ""


class RecurringWillTriggers:
    """Fixed-interval trigger metadata feeding one existing ``NativeWill``.

    Trigger state is deliberately separate from intention identity. The
    authoritative goal remains the Will intention; this organ stores only when
    that intention should recur and the exact occurrence awaiting handoff.
    """

    def __init__(self, resident):
        self.resident = resident
        self.store = resident.store
        self._lock = threading.RLock()
        self._init_schema()

    def register(
        self,
        intention_id: str,
        *,
        task: str,
        interval_seconds: int,
        first_due_at: datetime | str | None = None,
    ) -> RecurringWillTrigger:
        intention = self.resident.will.get(intention_id)
        if intention is None:
            raise KeyError(f"unknown resident intention: {intention_id}")
        if intention.status not in {"active", "paused"}:
            raise ValueError("only an active or paused intention may receive a recurring trigger")

        normalized_task = str(task or "").strip()
        if not normalized_task:
            raise ValueError("recurring intention task must not be empty")
        interval = self._interval(interval_seconds)
        now = datetime.now(timezone.utc)
        due = (
            self._coerce_time(first_due_at)
            if first_due_at is not None
            else now + timedelta(seconds=interval)
        )

        created = utc_now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO resident_recurring_will_triggers(
                    intention_id,task,interval_seconds,next_due_at,enabled,
                    pending_scheduled_at,pending_coalesced_missed,last_activated_at,
                    created_at,updated_at
                ) VALUES(?,?,?,?,1,NULL,0,NULL,?,?)
                ON CONFLICT(intention_id) DO UPDATE SET
                    task=excluded.task,
                    interval_seconds=excluded.interval_seconds,
                    next_due_at=excluded.next_due_at,
                    enabled=1,
                    pending_scheduled_at=NULL,
                    pending_coalesced_missed=0,
                    updated_at=excluded.updated_at
                """,
                (
                    intention.intention_id,
                    normalized_task,
                    interval,
                    self._iso(due),
                    created,
                    created,
                ),
            )
            conn.commit()
        trigger = self.get(intention.intention_id)
        if trigger is None:
            raise RuntimeError("recurring Will trigger did not persist")
        return trigger

    def disable(self, intention_id: str) -> RecurringWillTrigger | None:
        now = utc_now()
        with self._lock, closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                UPDATE resident_recurring_will_triggers
                SET enabled=0,pending_scheduled_at=NULL,pending_coalesced_missed=0,updated_at=?
                WHERE intention_id=?
                """,
                (now, str(intention_id)),
            )
            conn.commit()
        if cursor.rowcount <= 0:
            return None
        return self.get(intention_id)

    def get(self, intention_id: str) -> RecurringWillTrigger | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT intention_id,task,interval_seconds,next_due_at,enabled,
                       pending_scheduled_at,pending_coalesced_missed,last_activated_at,
                       created_at,updated_at
                FROM resident_recurring_will_triggers
                WHERE intention_id=?
                """,
                (str(intention_id),),
            ).fetchone()
        return self._snapshot(row) if row else None

    def list(
        self,
        *,
        enabled_only: bool = False,
        limit: int = 100,
    ) -> list[RecurringWillTrigger]:
        query = (
            "SELECT intention_id,task,interval_seconds,next_due_at,enabled,"
            "pending_scheduled_at,pending_coalesced_missed,last_activated_at,"
            "created_at,updated_at FROM resident_recurring_will_triggers"
        )
        if enabled_only:
            query += " WHERE enabled=1"
        query += " ORDER BY next_due_at ASC,intention_id ASC LIMIT ?"
        with closing(self._connect()) as conn:
            rows = conn.execute(query, (max(1, min(500, int(limit))),)).fetchall()
        return [self._snapshot(row) for row in rows]

    def activate_due(
        self,
        *,
        now: datetime | str | None = None,
        limit: int = 100,
    ) -> list[RecurringWillTrigger]:
        """Materialize due occurrences into Will without executing them directly.

        Each trigger can contribute at most one ``next_task`` per call. Multiple
        missed intervals coalesce to the latest due instant. An engaged or
        otherwise occupied intention is never overlapped; its due time stays
        pending until Will becomes available again.
        """

        current = (
            self._coerce_time(now)
            if now is not None
            else datetime.now(timezone.utc)
        )
        activated: list[RecurringWillTrigger] = []
        for trigger in self.list(enabled_only=True, limit=limit):
            result = self._activate_one(trigger.intention_id, current=current)
            if result is not None:
                activated.append(result)
        return activated

    def _activate_one(
        self,
        intention_id: str,
        *,
        current: datetime,
    ) -> RecurringWillTrigger | None:
        with self._lock:
            trigger = self.get(intention_id)
            if trigger is None or not trigger.enabled:
                return None

            intention = self.resident.will.get(intention_id)
            if intention is None or intention.status not in {"active", "engaged"}:
                return None

            pending_at = trigger.pending_scheduled_at
            if pending_at:
                if self._intention_has_pending_occurrence(intention, pending_at):
                    self._clear_pending(intention_id, activated_at=pending_at)
                    return None
                if (
                    intention.status != "active"
                    or intention.related_event_id
                    or intention.next_task
                ):
                    return None
                self._handoff_pending(trigger)
                return self.get(intention_id)

            if (
                intention.status != "active"
                or intention.related_event_id
                or intention.next_task
            ):
                return None

            due = self._coerce_time(trigger.next_due_at)
            if current < due:
                return None

            interval = timedelta(seconds=trigger.interval_seconds)
            elapsed_seconds = max(0.0, (current - due).total_seconds())
            due_count = int(elapsed_seconds // trigger.interval_seconds) + 1
            latest_due = due + interval * (due_count - 1)
            next_due = due + interval * due_count
            coalesced_missed = max(0, due_count - 1)

            # Advance cadence and stamp the exact pending occurrence in one
            # durable trigger-row transaction BEFORE handing anything to Will.
            # A crash after this point is recoverable without losing the slot.
            stamp_time = utc_now()
            with closing(self._connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT enabled,pending_scheduled_at,next_due_at
                    FROM resident_recurring_will_triggers
                    WHERE intention_id=?
                    """,
                    (intention_id,),
                ).fetchone()
                if row is None or not bool(row["enabled"]):
                    conn.rollback()
                    return None
                if row["pending_scheduled_at"]:
                    conn.rollback()
                    return None
                stored_due = self._coerce_time(str(row["next_due_at"]))
                if stored_due != due:
                    conn.rollback()
                    return None
                conn.execute(
                    """
                    UPDATE resident_recurring_will_triggers
                    SET next_due_at=?,pending_scheduled_at=?,
                        pending_coalesced_missed=?,updated_at=?
                    WHERE intention_id=?
                    """,
                    (
                        self._iso(next_due),
                        self._iso(latest_due),
                        coalesced_missed,
                        stamp_time,
                        intention_id,
                    ),
                )
                conn.commit()

            stamped = self.get(intention_id)
            if stamped is None:
                raise RuntimeError(
                    "recurring Will pending occurrence disappeared after stamp"
                )
            self._handoff_pending(stamped)
            return self.get(intention_id)

    def _handoff_pending(self, trigger: RecurringWillTrigger) -> None:
        scheduled_at = str(trigger.pending_scheduled_at or "").strip()
        if not scheduled_at:
            raise RuntimeError("recurring Will handoff requires a pending occurrence")
        intention = self.resident.will.get(trigger.intention_id)
        if intention is None:
            raise KeyError(f"unknown resident intention: {trigger.intention_id}")
        if intention.status != "active" or intention.related_event_id or intention.next_task:
            return

        # Only schedule evidence crosses into Will. It is historical context,
        # never reusable execution authority or stale Body arguments.
        occurrence_payload = {
            "recurring_intention_id": trigger.intention_id,
            "recurring_scheduled_at": scheduled_at,
            "recurring_interval_seconds": trigger.interval_seconds,
            "recurring_coalesced_missed": max(
                0, trigger.pending_coalesced_missed
            ),
            "execution_authority": False,
            "fresh_revalidation_required": True,
        }
        self.resident.will.set_next_step(
            trigger.intention_id,
            trigger.task,
            payload=occurrence_payload,
        )
        self._clear_pending(trigger.intention_id, activated_at=scheduled_at)

    def _clear_pending(self, intention_id: str, *, activated_at: str) -> None:
        now = utc_now()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE resident_recurring_will_triggers
                SET pending_scheduled_at=NULL,pending_coalesced_missed=0,
                    last_activated_at=?,updated_at=?
                WHERE intention_id=?
                """,
                (str(activated_at), now, str(intention_id)),
            )
            conn.commit()

    @staticmethod
    def _intention_has_pending_occurrence(intention, pending_at: str) -> bool:
        payload = (
            intention.next_payload
            if isinstance(intention.next_payload, dict)
            else {}
        )
        return (
            bool(intention.next_task)
            and str(payload.get("recurring_intention_id") or "")
            == intention.intention_id
            and str(payload.get("recurring_scheduled_at") or "")
            == str(pending_at)
        )

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> RecurringWillTrigger:
        return RecurringWillTrigger(
            intention_id=str(row["intention_id"]),
            task=str(row["task"]),
            interval_seconds=max(0, int(row["interval_seconds"] or 0)),
            next_due_at=str(row["next_due_at"]),
            enabled=bool(row["enabled"]),
            pending_scheduled_at=(
                str(row["pending_scheduled_at"])
                if row["pending_scheduled_at"]
                else None
            ),
            pending_coalesced_missed=max(
                0, int(row["pending_coalesced_missed"] or 0)
            ),
            last_activated_at=(
                str(row["last_activated_at"])
                if row["last_activated_at"]
                else None
            ),
            created_at=str(row["created_at"] or ""),
            updated_at=str(row["updated_at"] or ""),
        )

    @staticmethod
    def _interval(value: int) -> int:
        try:
            interval = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "recurring intention interval must be an integer number of seconds"
            ) from exc
        if interval < _MIN_INTERVAL_SECONDS:
            raise ValueError(
                f"recurring intention interval must be at least {_MIN_INTERVAL_SECONDS} seconds"
            )
        if interval > _MAX_INTERVAL_SECONDS:
            raise ValueError(
                f"recurring intention interval must be at most {_MAX_INTERVAL_SECONDS} seconds"
            )
        return interval

    @staticmethod
    def _coerce_time(value: datetime | str) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        else:
            text = str(value or "").strip()
            if not text:
                raise ValueError("scheduled time must not be empty")
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("scheduled time must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("scheduled time must include a timezone offset")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _iso(value: datetime) -> str:
        if value.tzinfo is None:
            raise ValueError("scheduled time must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat()

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS resident_recurring_will_triggers(
                    intention_id TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    interval_seconds INTEGER NOT NULL,
                    next_due_at TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    pending_scheduled_at TEXT,
                    pending_coalesced_missed INTEGER NOT NULL DEFAULT 0,
                    last_activated_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_recurring_will_due
                    ON resident_recurring_will_triggers(enabled,next_due_at);
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn


def install_recurring_will_behavior(resident) -> None:
    """Attach bounded fixed-interval triggers to the existing product Resident."""

    if getattr(resident, _INSTALL_MARKER, False):
        return
    if not hasattr(resident, "will"):
        raise ValueError("recurring Will behavior requires the existing NativeWill")

    triggers = RecurringWillTriggers(resident)
    original_pulse = resident.pulse
    original_status = resident.status

    def pulse():
        # Trigger failure is never allowed to replace the Resident life loop.
        # The due state remains durable and can be retried on a later pulse.
        try:
            triggers.activate_due()
        except Exception:
            pass
        return original_pulse()

    def status():
        data = original_status()
        items = triggers.list(enabled_only=False, limit=100)
        data["recurring_will"] = {
            "trigger_count": len(items),
            "enabled_count": sum(1 for item in items if item.enabled),
            "triggers": [asdict(item) for item in items],
        }
        return data

    def schedule_recurring_intention(
        description: str,
        *,
        task: str,
        interval_seconds: int,
        source: str = "self",
        priority: int = 0,
        first_due_at: datetime | str | None = None,
    ):
        intention = resident.intend(
            description,
            source=source,
            priority=priority,
            complete_on_step_success=False,
        )
        try:
            trigger = triggers.register(
                intention.intention_id,
                task=task,
                interval_seconds=interval_seconds,
                first_due_at=first_due_at,
            )
        except Exception:
            # Do not leave a silently active intention if trigger admission
            # fails. A paused Will item is visible and can be repaired explicitly.
            try:
                resident.will.pause(
                    intention.intention_id,
                    reason="recurring trigger registration failed",
                )
            except Exception:
                pass
            raise
        resident.nervous.perceive(
            "will",
            f"I scheduled a recurring intention: {intention.description}",
            features=("intention", "recurring", intention.source),
            source="will",
            salience=min(
                1.0,
                0.58 + max(0, intention.priority) * 0.03,
            ),
            valence=0.18,
            arousal=0.36,
            metadata={
                "intention_id": intention.intention_id,
                "interval_seconds": trigger.interval_seconds,
                "next_due_at": trigger.next_due_at,
                "execution_authority": False,
            },
        )
        return intention

    resident.recurring_will = triggers
    resident.schedule_recurring_intention = schedule_recurring_intention
    resident.disable_recurring_intention = triggers.disable
    resident.pulse = pulse
    resident.status = status
    setattr(resident, _INSTALL_MARKER, True)
