from __future__ import annotations

"""Deterministic proactive suggestions (P1-1).

The resident derives suggestions from durable state only, with fixed rules
and no model calls:

* a Work thread whose latest run ended FAILED, or whose last user message
  never got a ZN reply (interrupted work);
* an enabled recurring Will trigger whose next due time is overdue or within
  the next 24 hours and which Will has not already picked up;
* a memory fact the user explicitly declared as a routine (key starts with
  ``routine:`` / ``例行:`` / ``例行任务:``).

Every suggestion carries its source (which Work thread, which schedule, which
memory fact) and a stable key derived from kind + target + task, so a
dismissal suppresses exactly that suggestion for 7 days, across restarts.

A suggestion never executes anything by itself. Clicking one routes into the
existing Work flow: Work-backed suggestions reuse their thread; schedule and
routine suggestions start Work on a thread created through the normal
workCreate path. No orphan task is ever created.
"""

import hashlib
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

from .models import utc_now

_DISMISSAL_TTL = timedelta(days=7)
_MAX_SUGGESTIONS = 8
_UPCOMING_WINDOW = timedelta(hours=24)

_ROUTINE_KEY_PREFIXES = ("routine:", "例行:", "例行任务:")

_KIND_RANK = {
    "failed_work": 0,
    "recurring_due": 1,
    "recurring_upcoming": 1,
    "interrupted_work": 2,
    "routine": 3,
}


def suggestion_key(kind: str, target: str, task: str) -> str:
    digest = hashlib.sha256(
        f"{kind}\x00{target}\x00{task}".encode("utf-8", errors="replace")
    ).hexdigest()[:24]
    return f"sug-{digest}"


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


class SuggestionEngine:
    """Deterministic suggestions over the resident's durable state."""

    def __init__(self, resident, ledger):
        self.resident = resident
        self.ledger = ledger
        self.store = resident.store
        self._lock = threading.RLock()
        # Schema is created lazily on first use, never at construction:
        # building the daemon must not fail because an auxiliary feature's
        # table cannot be created while the store is busy.
        self._schema_ready = False

    def list_suggestions(
        self,
        *,
        now: datetime | None = None,
        limit: int = _MAX_SUGGESTIONS,
    ) -> list[dict[str, Any]]:
        self._ensure_schema()
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        self._prune_expired(current)
        dismissed = self._dismissed_keys(current)
        candidates: list[dict[str, Any]] = []
        candidates.extend(self._work_suggestions())
        candidates.extend(self._recurring_suggestions(current))
        candidates.extend(self._routine_suggestions())
        seen: set[str] = set()
        ranked: list[tuple[int, str, dict[str, Any]]] = []
        for item in candidates:
            key = item["key"]
            if key in dismissed or key in seen:
                continue
            seen.add(key)
            ranked.append((_KIND_RANK[item["kind"]], item.get("_sort", ""), item))
        ranked.sort(key=lambda entry: (entry[0], entry[1]))
        suggestions = []
        for _, _, item in ranked[: max(1, min(50, int(limit)))]:
            item = {k: v for k, v in item.items() if not k.startswith("_")}
            suggestions.append(item)
        return suggestions

    def dismiss(
        self,
        key: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        normalized = str(key or "").strip()
        if not normalized:
            raise ValueError("suggestions_dismiss requires a suggestion key")
        self._ensure_schema()
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        expires = current + _DISMISSAL_TTL
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO resident_suggestion_dismissals(
                    suggestion_key,dismissed_at,expires_at
                ) VALUES(?,?,?)
                ON CONFLICT(suggestion_key) DO UPDATE SET
                    dismissed_at=excluded.dismissed_at,
                    expires_at=excluded.expires_at
                """,
                (normalized, current.isoformat(), expires.isoformat()),
            )
            conn.commit()
        return {
            "dismissed": True,
            "key": normalized,
            "dismissed_at": current.isoformat(),
            "expires_at": expires.isoformat(),
        }

    # -- sources ---------------------------------------------------------

    def _work_suggestions(self) -> list[dict[str, Any]]:
        suggestions: list[dict[str, Any]] = []
        try:
            snapshots = self.ledger.list_snapshots(thread_limit=24, message_limit=120)
        except Exception:
            return []
        for thread, messages in snapshots:
            item = self._work_suggestion_for_thread(thread, messages)
            if item is not None:
                suggestions.append(item)
        return suggestions

    def _work_suggestion_for_thread(self, thread, messages) -> dict[str, Any] | None:
        if not messages:
            return None
        latest_run = None
        latest_run_for_thread = getattr(self.ledger, "latest_run_for_thread", None)
        if callable(latest_run_for_thread):
            try:
                latest_run = latest_run_for_thread(thread.thread_id)
            except Exception:
                latest_run = None
        failed_task: str | None = None
        if latest_run is not None:
            try:
                event = self.resident.store.get_event(latest_run.event_id)
            except Exception:
                event = None
            event_failed = (
                event is not None
                and str(getattr(event.status, "value", event.status)) == "failed"
            )
            if event_failed:
                failed_task = str(latest_run.task or "").strip()
            elif latest_run.ledger_state == "active":
                # In-flight work is never suggested: clicking it would
                # collide with the active resident event (Work.start refuses
                # a second active run).
                return None
        last = messages[-1]
        last_role = str(getattr(last, "role", "") or "")
        last_detail = getattr(last, "detail", None) or {}
        if failed_task:
            return self._work_item(
                kind="failed_work",
                thread=thread,
                task=failed_task,
                sort_key=thread.updated_at,
            )
        if last_role == "user":
            task = str(getattr(last, "text", "") or "").strip()
            if task:
                return self._work_item(
                    kind="interrupted_work",
                    thread=thread,
                    task=task,
                    sort_key=thread.updated_at,
                )
            return None
        if last_role == "zn" and last_detail.get("failed") is True:
            user_texts = [
                str(getattr(m, "text", "") or "").strip()
                for m in messages
                if str(getattr(m, "role", "") or "") == "user"
            ]
            task = user_texts[-1] if user_texts else ""
            if task:
                return self._work_item(
                    kind="failed_work",
                    thread=thread,
                    task=task,
                    sort_key=thread.updated_at,
                )
        return None

    @staticmethod
    def _work_item(*, kind: str, thread, task: str, sort_key: str) -> dict[str, Any]:
        # Newest unfinished thread first: reverse-lexicographic on the
        # ISO-8601 updated_at stamp approximates recency deterministically.
        return {
            "key": suggestion_key(kind, thread.thread_id, task),
            "kind": kind,
            "title": str(thread.title or task),
            "task": task,
            "thread_id": thread.thread_id,
            "source": {
                "type": "work",
                "label": str(thread.title or task),
                "thread_id": thread.thread_id,
            },
            "_sort": _reverse_sort_key(str(sort_key or "")),
        }

    def _recurring_suggestions(self, current: datetime) -> list[dict[str, Any]]:
        triggers = getattr(self.resident, "recurring_will", None)
        if triggers is None:
            return []
        try:
            items = triggers.list(enabled_only=True, limit=100)
        except Exception:
            return []
        suggestions: list[dict[str, Any]] = []
        for trigger in items:
            due = _parse_time(trigger.next_due_at)
            if due is None:
                continue
            if due > current + _UPCOMING_WINDOW:
                continue
            intention = None
            will = getattr(self.resident, "will", None)
            if will is not None:
                try:
                    intention = will.get(trigger.intention_id)
                except Exception:
                    intention = None
            if intention is not None:
                # Will already picked this occurrence up (or is running it);
                # suggesting it again would duplicate the existing path.
                if str(getattr(intention, "status", "") or "") != "active":
                    continue
                if getattr(intention, "next_task", None):
                    continue
            task = str(trigger.task or "").strip()
            if not task:
                continue
            overdue = due <= current
            kind = "recurring_due" if overdue else "recurring_upcoming"
            suggestions.append(
                {
                    # One stable key per schedule+task: dismissing the
                    # upcoming suggestion also suppresses it once due.
                    "key": suggestion_key("recurring", trigger.intention_id, task),
                    "kind": kind,
                    "title": task,
                    "task": task,
                    "thread_id": None,
                    "source": {
                        "type": "schedule",
                        "label": task,
                        "intention_id": trigger.intention_id,
                        "next_due_at": trigger.next_due_at,
                    },
                    "_sort": trigger.next_due_at,
                }
            )
        return suggestions

    def _routine_suggestions(self) -> list[dict[str, Any]]:
        try:
            facts = self.resident.store.list_facts()
        except Exception:
            return []
        suggestions: list[dict[str, Any]] = []
        for fact in facts:
            key = str(fact.get("key") or "")
            normalized = key.strip().lower()
            if not any(normalized.startswith(prefix) for prefix in _ROUTINE_KEY_PREFIXES):
                continue
            task = self._routine_task(fact)
            if not task:
                continue
            suggestions.append(
                {
                    "key": suggestion_key("routine", key, task),
                    "kind": "routine",
                    "title": task,
                    "task": task,
                    "thread_id": None,
                    "source": {
                        "type": "memory",
                        "label": key,
                        "fact_key": key,
                    },
                    "_sort": key,
                }
            )
        return suggestions

    @staticmethod
    def _routine_task(fact: dict[str, Any]) -> str:
        value = fact.get("value")
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            task = value.get("task")
            if isinstance(task, str) and task.strip():
                return task.strip()
        key = str(fact.get("key") or "")
        for prefix in _ROUTINE_KEY_PREFIXES:
            if key.strip().lower().startswith(prefix):
                suffix = key.strip()[len(prefix):].strip()
                if suffix:
                    return suffix
        return ""

    # -- dismissals ------------------------------------------------------

    def _dismissed_keys(self, current: datetime) -> set[str]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT suggestion_key FROM resident_suggestion_dismissals "
                "WHERE expires_at > ?",
                (current.isoformat(),),
            ).fetchall()
        return {str(row["suggestion_key"]) for row in rows}

    def _prune_expired(self, current: datetime) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "DELETE FROM resident_suggestion_dismissals WHERE expires_at <= ?",
                (current.isoformat(),),
            )
            conn.commit()

    def _ensure_schema(self) -> None:
        with self._lock:
            if self._schema_ready:
                return
            self._init_schema()
            self._schema_ready = True

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS resident_suggestion_dismissals(
                    suggestion_key TEXT PRIMARY KEY,
                    dismissed_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_suggestion_dismissals_expiry
                    ON resident_suggestion_dismissals(expires_at);
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn


def _reverse_sort_key(value: str) -> str:
    """Invert an ISO timestamp string so ascending sort yields newest first."""
    return "".join(chr(0x10FFFF - ord(ch)) for ch in value)
