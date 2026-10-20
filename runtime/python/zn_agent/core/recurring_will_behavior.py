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

A third schedule kind, ``file_changed``, watches one file's content
fingerprint by polling (no filesystem watcher dependency): when the
fingerprint changes, a trailing-edge debounce window starts, and one due
occurrence materializes after the fingerprint has been stable for
``debounce_seconds``. It reuses the same pending stamp, coalescing, and
fresh-revalidation handoff as the time-based kinds; only the "when is it
due" decision differs.
"""

import hashlib
import os
import sqlite3
import threading
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from .models import utc_now
from .routine_schedule import (
    RoutineSchedule,
    count_cron_occurrences,
    resolve_timezone,
)


_INSTALL_MARKER = "_zn_recurring_will_behavior_installed"

_MISSING_FINGERPRINT = "missing"


def fingerprint_file(path: str) -> str:
    """Content fingerprint of a watched file, polled without dependencies.

    Returns ``sha256:<hex>`` for a readable file and the ``missing``
    sentinel when the path cannot be read. A transition into or out of
    ``missing`` (creation / deletion) counts as a change, exactly like a
    content change; a path that stays unreadable never re-triggers.
    """
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    except OSError:
        return _MISSING_FINGERPRINT


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
    # Wall-clock schedules: when schedule_kind is "cron", next_due_at is the
    # next cron occurrence in `timezone` and interval_seconds is unused (0).
    schedule_kind: str = "interval"
    cron_expression: str | None = None
    timezone: str | None = None
    # File-change triggers: when schedule_kind is "file_changed",
    # next_due_at/interval_seconds are unused; the organ polls the content
    # fingerprint of file_path and materializes one due occurrence after
    # the fingerprint has been stable for debounce_seconds (trailing-edge
    # debounce: a change inside the window restarts it, and the whole
    # burst merges into exactly one occurrence).
    file_path: str | None = None
    file_fingerprint: str | None = None
    debounce_seconds: int = 0
    last_change_at: str | None = None
    file_change_count: int = 0


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
        # Optional seam for layers on top of the trigger organ (routines):
        # called with (trigger, occurrence_payload) just before a due
        # occurrence is handed to Will. The layer may record the occurrence
        # and add its own fields to the payload. Never set in this module.
        # Return contract: None (or anything else) hands off as before;
        # False holds the occurrence (pending stamp stays, next pulse
        # retries); "void" drops it (pending stamp cleared, no handoff).
        self._on_handoff = None
        self._init_schema()

    def register(
        self,
        intention_id: str,
        *,
        task: str,
        interval_seconds: int | None = None,
        first_due_at: datetime | str | None = None,
        schedule_kind: str = "interval",
        cron_expression: str | None = None,
        tz_name: str | None = None,
        file_path: str | None = None,
        debounce_seconds: int = 0,
    ) -> RecurringWillTrigger:
        intention = self.resident.will.get(intention_id)
        if intention is None:
            raise KeyError(f"unknown resident intention: {intention_id}")
        if intention.status not in {"active", "paused"}:
            raise ValueError("only an active or paused intention may receive a recurring trigger")

        normalized_task = str(task or "").strip()
        if not normalized_task:
            raise ValueError("recurring intention task must not be empty")
        kind = str(schedule_kind or "interval").strip().lower()
        if kind == "file_changed":
            return self._register_file_trigger(
                intention.intention_id,
                normalized_task,
                file_path=file_path,
                debounce_seconds=debounce_seconds,
            )
        schedule = self._schedule(
            schedule_kind,
            interval_seconds=interval_seconds,
            cron_expression=cron_expression,
            timezone=tz_name,
        )
        now = datetime.now(timezone.utc)
        if first_due_at is not None:
            due = self._coerce_time(first_due_at)
        elif schedule.kind == "cron":
            due = schedule.next_due_after(now)
        else:
            due = now + timedelta(seconds=int(schedule.interval_seconds or 0))

        created = utc_now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO resident_recurring_will_triggers(
                    intention_id,task,interval_seconds,next_due_at,enabled,
                    pending_scheduled_at,pending_coalesced_missed,last_activated_at,
                    created_at,updated_at,schedule_kind,cron_expression,timezone,
                    file_path,file_fingerprint,debounce_seconds,last_change_at,
                    file_change_count
                ) VALUES(?,?,?,?,1,NULL,0,NULL,?,?,?,?,?,NULL,NULL,0,NULL,0)
                ON CONFLICT(intention_id) DO UPDATE SET
                    task=excluded.task,
                    interval_seconds=excluded.interval_seconds,
                    next_due_at=excluded.next_due_at,
                    enabled=1,
                    pending_scheduled_at=NULL,
                    pending_coalesced_missed=0,
                    updated_at=excluded.updated_at,
                    schedule_kind=excluded.schedule_kind,
                    cron_expression=excluded.cron_expression,
                    timezone=excluded.timezone,
                    file_path=NULL,
                    file_fingerprint=NULL,
                    debounce_seconds=0,
                    last_change_at=NULL,
                    file_change_count=0
                """,
                (
                    intention.intention_id,
                    normalized_task,
                    int(schedule.interval_seconds or 0),
                    self._iso(due),
                    created,
                    created,
                    schedule.kind,
                    schedule.cron_expression,
                    schedule.timezone,
                ),
            )
            conn.commit()
        trigger = self.get(intention.intention_id)
        if trigger is None:
            raise RuntimeError("recurring Will trigger did not persist")
        return trigger

    def _register_file_trigger(
        self,
        intention_id: str,
        task: str,
        *,
        file_path: str | None,
        debounce_seconds: int = 0,
    ) -> RecurringWillTrigger:
        """Register a file-change trigger on an existing Will intention.

        The current fingerprint is baselined at registration, so
        registering on an already-existing file does not fire on its
        current content. Re-registering resets the window and the merge
        counter, exactly like the time-based kinds clear their pending
        state on re-registration.
        """
        raw_path = str(file_path or "").strip()
        if not raw_path:
            raise ValueError("file_changed trigger requires file_path")
        try:
            debounce = int(debounce_seconds or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("debounce_seconds must be an integer >= 0") from exc
        if debounce < 0:
            raise ValueError("debounce_seconds must be >= 0")
        # Store the absolute path: a relative path would silently change
        # meaning if the process ever restarts with another CWD.
        path = os.path.abspath(raw_path)
        baseline = fingerprint_file(path)
        created = utc_now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO resident_recurring_will_triggers(
                    intention_id,task,interval_seconds,next_due_at,enabled,
                    pending_scheduled_at,pending_coalesced_missed,last_activated_at,
                    created_at,updated_at,schedule_kind,cron_expression,timezone,
                    file_path,file_fingerprint,debounce_seconds,last_change_at,
                    file_change_count
                ) VALUES(?,?,0,?,1,NULL,0,NULL,?,?,'file_changed',NULL,NULL,
                         ?,?,?,NULL,0)
                ON CONFLICT(intention_id) DO UPDATE SET
                    task=excluded.task,
                    interval_seconds=0,
                    next_due_at=excluded.next_due_at,
                    enabled=1,
                    pending_scheduled_at=NULL,
                    pending_coalesced_missed=0,
                    updated_at=excluded.updated_at,
                    schedule_kind='file_changed',
                    cron_expression=NULL,
                    timezone=NULL,
                    file_path=excluded.file_path,
                    file_fingerprint=excluded.file_fingerprint,
                    debounce_seconds=excluded.debounce_seconds,
                    last_change_at=NULL,
                    file_change_count=0
                """,
                (
                    intention_id,
                    task,
                    created,
                    created,
                    created,
                    path,
                    baseline,
                    debounce,
                ),
            )
            conn.commit()
        trigger = self.get(intention_id)
        if trigger is None:
            raise RuntimeError("file change trigger did not persist")
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

    def clear_pending_occurrence(self, intention_id: str, *, scheduled_at: str) -> None:
        """Clear a stamped pending occurrence without handing it to Will.

        Used by layers (routines) that void a held occurrence, e.g. when
        its approval was denied: the occurrence must not be retried.
        """
        self._clear_pending(str(intention_id), activated_at=str(scheduled_at))

    def get(self, intention_id: str) -> RecurringWillTrigger | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT intention_id,task,interval_seconds,next_due_at,enabled,
                       pending_scheduled_at,pending_coalesced_missed,last_activated_at,
                       created_at,updated_at,schedule_kind,cron_expression,timezone,
                       file_path,file_fingerprint,debounce_seconds,last_change_at,
                       file_change_count
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
            "created_at,updated_at,schedule_kind,cron_expression,timezone,"
            "file_path,file_fingerprint,debounce_seconds,last_change_at,"
            "file_change_count "
            "FROM resident_recurring_will_triggers"
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

            if trigger.schedule_kind == "file_changed":
                return self._activate_file_change(
                    trigger.intention_id, current=current
                )

            due = self._coerce_time(trigger.next_due_at)
            if current < due:
                return None

            schedule = self._schedule_of(trigger)
            if schedule.kind == "cron":
                # The stored next_due_at is always a cron occurrence, so it
                # is the occurrence being handed off. The next due jumps past
                # now (no backlog burst); missed occurrences between due and
                # now coalesce into the count, capped by the counter.
                tz = resolve_timezone(schedule.timezone)
                latest_due = due
                next_due = schedule.next_due_after(current)
                coalesced_missed = count_cron_occurrences(
                    schedule.parsed_cron(), due, current, tz
                )
            else:
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

    def _activate_file_change(
        self,
        intention_id: str,
        *,
        current: datetime,
    ) -> RecurringWillTrigger | None:
        """Poll one file-change trigger; stamp a due occurrence when quiet.

        This reuses the trigger organ's crash-safety shape instead of
        reinventing it: the exact due occurrence is stamped
        (``pending_scheduled_at``) in one durable transaction BEFORE Will
        sees it, missed changes coalesce into one occurrence, and the
        handoff carries only evidence with ``fresh_revalidation_required``
        — the resident must re-establish current world facts before any
        side effect.

        Debounce is trailing-edge: every newly observed fingerprint
        restarts the ``debounce_seconds`` window, so a burst of changes
        merges into exactly one occurrence carrying the final fingerprint.
        With ``debounce_seconds=0`` the occurrence materializes on the
        same pulse that observes the change.
        """
        trigger = self.get(intention_id)
        if trigger is None or not trigger.enabled:
            return None
        if trigger.schedule_kind != "file_changed" or not trigger.file_path:
            return None

        fingerprint = fingerprint_file(trigger.file_path)
        stamp_time = utc_now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT enabled,pending_scheduled_at,file_fingerprint,
                       debounce_seconds,last_change_at,file_change_count
                FROM resident_recurring_will_triggers
                WHERE intention_id=?
                """,
                (intention_id,),
            ).fetchone()
            if (
                row is None
                or not bool(row["enabled"])
                or row["pending_scheduled_at"]
            ):
                # A stamped-but-unhanded occurrence is retried by the
                # pending path in _activate_one; new changes simply wait
                # for the next pulse. Nothing is lost: the stored
                # fingerprint is still the old one, so the change is
                # observed again after the pending occurrence clears.
                conn.rollback()
                return None
            stored_fingerprint = str(row["file_fingerprint"] or "")
            debounce = max(0, int(row["debounce_seconds"] or 0))
            if fingerprint != stored_fingerprint:
                # Newly observed fingerprint: restart the debounce
                # window; the burst merges into one later occurrence.
                change_at = self._iso(current)
                conn.execute(
                    """
                    UPDATE resident_recurring_will_triggers
                    SET file_fingerprint=?,last_change_at=?,
                        file_change_count=file_change_count+1,
                        next_due_at=?,updated_at=?
                    WHERE intention_id=?
                    """,
                    (
                        fingerprint,
                        change_at,
                        self._iso(current + timedelta(seconds=debounce)),
                        stamp_time,
                        intention_id,
                    ),
                )
                stored_change_at = change_at
                merged = max(0, int(row["file_change_count"] or 0)) + 1
            else:
                stored_change_at = row["last_change_at"]
                if not stored_change_at:
                    # Quiet since the registration baseline: nothing due.
                    conn.commit()
                    return None
                merged = max(0, int(row["file_change_count"] or 0))
            due_at = self._coerce_time(str(stored_change_at)) + timedelta(
                seconds=debounce
            )
            if current < due_at:
                conn.commit()
                return None
            # Due: stamp the exact pending occurrence in the same
            # transaction, exactly like the interval path, so a crash
            # between bookkeeping and the Will handoff loses nothing.
            # last_change_at/file_change_count stay until the pending
            # occurrence clears, so the handoff payload still carries the
            # change evidence and a crash recovery retries the same one.
            conn.execute(
                """
                UPDATE resident_recurring_will_triggers
                SET next_due_at=?,pending_scheduled_at=?,
                    pending_coalesced_missed=?,updated_at=?
                WHERE intention_id=?
                """,
                (
                    self._iso(due_at),
                    self._iso(due_at),
                    merged,
                    stamp_time,
                    intention_id,
                ),
            )
            conn.commit()

        stamped = self.get(intention_id)
        if stamped is None:
            raise RuntimeError(
                "file change pending occurrence disappeared after stamp"
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
            "execution_authority": False,
            "fresh_revalidation_required": True,
        }
        if trigger.schedule_kind == "file_changed":
            # File-change evidence: which path changed, the fingerprint it
            # settled on, when the change was first observed, and how many
            # observed changes merged into this one occurrence.
            occurrence_payload.update(
                {
                    "recurring_schedule_kind": "file_changed",
                    "recurring_coalesced_missed": max(
                        0, trigger.pending_coalesced_missed
                    ),
                    "file_trigger_path": trigger.file_path,
                    "file_trigger_fingerprint": str(
                        trigger.file_fingerprint or ""
                    ),
                    "file_trigger_changed_at": str(
                        trigger.last_change_at or ""
                    ),
                    "file_trigger_debounce_seconds": max(
                        0, int(trigger.debounce_seconds or 0)
                    ),
                }
            )
        else:
            occurrence_payload.update(
                {
                    "recurring_interval_seconds": trigger.interval_seconds,
                    "recurring_coalesced_missed": max(
                        0, trigger.pending_coalesced_missed
                    ),
                }
            )
        # Layers on top of the trigger organ (routines) record the
        # occurrence and add their own context before Will sees it. A hook
        # failure must not lose the occurrence: the trigger row already
        # stamped it, and the next pulse retries the handoff.
        # The hook may veto the handoff: False holds the occurrence (the
        # pending stamp stays so the next pulse retries the handoff and
        # the hook re-evaluates), "void" drops the occurrence (the pending
        # stamp is cleared without handing anything to Will, e.g. its
        # approval was denied). Anything else hands off as before.
        hold = None
        if self._on_handoff is not None:
            try:
                hold = self._on_handoff(trigger, occurrence_payload)
            except Exception:
                pass
        if hold is False:
            return
        if hold == "void":
            self._clear_pending(trigger.intention_id, activated_at=scheduled_at)
            return
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
                    last_activated_at=?,updated_at=?,
                    last_change_at=NULL,file_change_count=0
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
        columns = set(row.keys())
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
            schedule_kind=(
                str(row["schedule_kind"])
                if "schedule_kind" in columns and row["schedule_kind"]
                else "interval"
            ),
            cron_expression=(
                str(row["cron_expression"])
                if "cron_expression" in columns and row["cron_expression"]
                else None
            ),
            timezone=(
                str(row["timezone"])
                if "timezone" in columns and row["timezone"]
                else None
            ),
            file_path=(
                str(row["file_path"])
                if "file_path" in columns and row["file_path"]
                else None
            ),
            file_fingerprint=(
                str(row["file_fingerprint"])
                if "file_fingerprint" in columns and row["file_fingerprint"]
                else None
            ),
            debounce_seconds=(
                max(0, int(row["debounce_seconds"] or 0))
                if "debounce_seconds" in columns
                else 0
            ),
            last_change_at=(
                str(row["last_change_at"])
                if "last_change_at" in columns and row["last_change_at"]
                else None
            ),
            file_change_count=(
                max(0, int(row["file_change_count"] or 0))
                if "file_change_count" in columns
                else 0
            ),
        )

    @staticmethod
    def _schedule(
        schedule_kind: str,
        *,
        interval_seconds: int | None,
        cron_expression: str | None,
        timezone: str | None,
    ) -> RoutineSchedule:
        """Validate schedule params into a RoutineSchedule."""
        kind = str(schedule_kind or "interval").strip().lower()
        if kind == "cron":
            return RoutineSchedule(
                kind="cron",
                cron_expression=cron_expression,
                timezone=timezone or "UTC",
            )
        if kind != "interval":
            raise ValueError("schedule_kind must be interval or cron")
        if interval_seconds is None:
            raise ValueError("interval schedule requires interval_seconds")
        return RoutineSchedule(
            kind="interval",
            interval_seconds=interval_seconds,
            timezone=timezone or "UTC",
        )

    @staticmethod
    def _schedule_of(trigger: RecurringWillTrigger) -> RoutineSchedule:
        if trigger.schedule_kind == "cron":
            return RoutineSchedule(
                kind="cron",
                cron_expression=trigger.cron_expression,
                timezone=trigger.timezone or "UTC",
            )
        return RoutineSchedule(
            kind="interval",
            interval_seconds=trigger.interval_seconds,
            timezone=trigger.timezone or "UTC",
        )

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
                    updated_at TEXT NOT NULL,
                    schedule_kind TEXT NOT NULL DEFAULT 'interval',
                    cron_expression TEXT,
                    timezone TEXT,
                    file_path TEXT,
                    file_fingerprint TEXT,
                    debounce_seconds INTEGER NOT NULL DEFAULT 0,
                    last_change_at TEXT,
                    file_change_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_recurring_will_due
                    ON resident_recurring_will_triggers(enabled,next_due_at);
                """
            )
            # Databases created before cron support lack the schedule
            # columns; add them in place so existing triggers keep working.
            existing = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(resident_recurring_will_triggers)"
                ).fetchall()
            }
            if "schedule_kind" not in existing:
                conn.execute(
                    "ALTER TABLE resident_recurring_will_triggers "
                    "ADD COLUMN schedule_kind TEXT NOT NULL DEFAULT 'interval'"
                )
            if "cron_expression" not in existing:
                conn.execute(
                    "ALTER TABLE resident_recurring_will_triggers "
                    "ADD COLUMN cron_expression TEXT"
                )
            if "timezone" not in existing:
                conn.execute(
                    "ALTER TABLE resident_recurring_will_triggers "
                    "ADD COLUMN timezone TEXT"
                )
            # Databases created before file-change triggers lack the
            # file-watch columns; add them in place so existing triggers
            # keep working.
            if "file_path" not in existing:
                conn.execute(
                    "ALTER TABLE resident_recurring_will_triggers "
                    "ADD COLUMN file_path TEXT"
                )
            if "file_fingerprint" not in existing:
                conn.execute(
                    "ALTER TABLE resident_recurring_will_triggers "
                    "ADD COLUMN file_fingerprint TEXT"
                )
            if "debounce_seconds" not in existing:
                conn.execute(
                    "ALTER TABLE resident_recurring_will_triggers "
                    "ADD COLUMN debounce_seconds INTEGER NOT NULL DEFAULT 0"
                )
            if "last_change_at" not in existing:
                conn.execute(
                    "ALTER TABLE resident_recurring_will_triggers "
                    "ADD COLUMN last_change_at TEXT"
                )
            if "file_change_count" not in existing:
                conn.execute(
                    "ALTER TABLE resident_recurring_will_triggers "
                    "ADD COLUMN file_change_count INTEGER NOT NULL DEFAULT 0"
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

    def schedule_file_change_intention(
        description: str,
        *,
        task: str,
        file_path: str,
        debounce_seconds: int = 0,
        source: str = "self",
        priority: int = 0,
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
                schedule_kind="file_changed",
                file_path=file_path,
                debounce_seconds=debounce_seconds,
            )
        except Exception:
            # Do not leave a silently active intention if trigger admission
            # fails. A paused Will item is visible and can be repaired explicitly.
            try:
                resident.will.pause(
                    intention.intention_id,
                    reason="file change trigger registration failed",
                )
            except Exception:
                pass
            raise
        resident.nervous.perceive(
            "will",
            f"I scheduled a file-change intention: {intention.description}",
            features=("intention", "file_changed", intention.source),
            source="will",
            salience=min(
                1.0,
                0.58 + max(0, intention.priority) * 0.03,
            ),
            valence=0.18,
            arousal=0.36,
            metadata={
                "intention_id": intention.intention_id,
                "file_path": trigger.file_path,
                "debounce_seconds": trigger.debounce_seconds,
                "execution_authority": False,
            },
        )
        return intention

    resident.recurring_will = triggers
    resident.schedule_recurring_intention = schedule_recurring_intention
    resident.schedule_file_change_intention = schedule_file_change_intention
    resident.disable_recurring_intention = triggers.disable
    resident.pulse = pulse
    resident.status = status
    setattr(resident, _INSTALL_MARKER, True)
