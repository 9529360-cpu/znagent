from __future__ import annotations

"""Shared persistence primitives for resident replay-sensitive side effects.

This module owns the SQLite representation and low-level lifecycle queries for
``resident_side_effect_attempts``. Caller-specific action identity remains with
the caller: Body and compiled capabilities intentionally keep their historical,
different signature-hash algorithms.

Capacity cleanup is terminal-truth gated. An attempt for a nonterminal event may
be ``observed`` or even recovery-verified while the resident still needs it to
resume safely, so status alone never grants deletion authority.
"""

import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .models import utc_now


TABLE = "resident_side_effect_attempts"
MAX_COMPLETED_ATTEMPTS = 4096
_DELETE_GUARD_TRIGGER = "trg_resident_side_effect_attempt_delete_terminal_only_v1"
_TERMINAL_PRUNE_TRIGGER = "trg_resident_side_effect_attempt_prune_terminal_v1"
USER_RESOLUTION_STATUS = {
    "effect_happened": "user_confirmed_effect",
    "retry_authorized": "user_authorized_retry",
}


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Install the single table/index definition and terminal-safe cleanup rules."""

    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE}(
            attempt_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            signature_hash TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            result_action_id TEXT,
            result_success INTEGER,
            resolved_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_resident_side_effect_attempt
            ON {TABLE}(event_id, signature_hash, started_at DESC);

        CREATE TRIGGER IF NOT EXISTS {_DELETE_GUARD_TRIGGER}
        BEFORE DELETE ON {TABLE}
        WHEN NOT EXISTS (
            SELECT 1
            FROM events AS event
            JOIN event_outcomes AS outcome ON outcome.event_id=event.event_id
            WHERE event.event_id=OLD.event_id
              AND event.status IN ('completed','failed')
        )
        BEGIN
            SELECT RAISE(IGNORE);
        END;

        CREATE TRIGGER IF NOT EXISTS {_TERMINAL_PRUNE_TRIGGER}
        AFTER INSERT ON event_outcomes
        BEGIN
            DELETE FROM {TABLE}
            WHERE attempt_id IN (
                SELECT attempt.attempt_id
                FROM {TABLE} AS attempt
                JOIN events AS event ON event.event_id=attempt.event_id
                JOIN event_outcomes AS outcome ON outcome.event_id=attempt.event_id
                WHERE attempt.status!='started'
                  AND event.status IN ('completed','failed')
                ORDER BY COALESCE(attempt.completed_at,attempt.started_at) DESC,
                         attempt.started_at DESC,
                         attempt.attempt_id DESC
                LIMIT -1 OFFSET {MAX_COMPLETED_ATTEMPTS}
            );
        END;
        """
    )
    columns = {
        str(row["name"] if isinstance(row, sqlite3.Row) else row[1])
        for row in conn.execute(f"PRAGMA table_info({TABLE})").fetchall()
    }
    if "resolved_at" not in columns:
        conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN resolved_at TEXT")


def start_attempt(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    event_id: str,
    kind: str,
    signature_hash: str,
    started_at: str | None = None,
) -> None:
    conn.execute(
        f"INSERT INTO {TABLE}"
        "(attempt_id,event_id,signature_hash,kind,status,started_at) "
        "VALUES(?,?,?,?,?,?)",
        (
            attempt_id,
            event_id,
            signature_hash,
            kind,
            "started",
            started_at or utc_now(),
        ),
    )


def attempt(conn: sqlite3.Connection, attempt_id: str) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT attempt_id,event_id,signature_hash,kind,status,started_at,"
        f"completed_at,result_action_id,result_success,resolved_at FROM {TABLE} WHERE attempt_id=?",
        (attempt_id,),
    ).fetchone()


def observe_started_attempt(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    completed_at: str,
    success: bool,
    event_id: str | None = None,
    result_action_id: str | None = None,
) -> int:
    event_clause = " AND event_id=?" if event_id is not None else ""
    params: list[Any] = [
        completed_at,
        result_action_id,
        1 if success else 0,
        attempt_id,
    ]
    if event_id is not None:
        params.append(event_id)
    cursor = conn.execute(
        f"UPDATE {TABLE} SET status='observed',completed_at=?,result_action_id=?,"
        f"result_success=? WHERE attempt_id=?{event_clause} AND status='started'",
        tuple(params),
    )
    return int(cursor.rowcount)


def resolve_attempt(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    event_id: str,
    status: str,
    evidence_action_id: str | None = None,
) -> int:
    now = utc_now()
    cursor = conn.execute(
        f"UPDATE {TABLE} SET status=?,completed_at=COALESCE(completed_at,?),"
        "result_action_id=COALESCE(result_action_id,?),resolved_at=COALESCE(resolved_at,?) "
        "WHERE attempt_id=? AND event_id=? AND status IN ('started','observed')",
        (
            status,
            now,
            evidence_action_id,
            now,
            attempt_id,
            event_id,
        ),
    )
    return int(cursor.rowcount)


def user_resolution_status(decision: str) -> str:
    """Map one explicit operator decision to an audit-distinct terminal status."""

    normalized = str(decision or "").strip().lower()
    try:
        return USER_RESOLUTION_STATUS[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported uncertain side-effect decision: {normalized or '<empty>'}") from exc


def resolve_user_attempt(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    event_id: str,
    decision: str,
    resolved_at: str | None = None,
) -> int:
    """Persist explicit user authority without impersonating machine evidence."""

    status = user_resolution_status(decision)
    now = resolved_at or utc_now()
    cursor = conn.execute(
        f"UPDATE {TABLE} SET status=?,completed_at=COALESCE(completed_at,?),"
        "resolved_at=COALESCE(resolved_at,?) "
        "WHERE attempt_id=? AND event_id=? AND status IN ('started','observed')",
        (status, now, now, attempt_id, event_id),
    )
    return int(cursor.rowcount)


def replay_blocking_attempt(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    signature_hash: str,
    statuses: Iterable[str] = ("started",),
) -> sqlite3.Row | None:
    normalized_statuses = tuple(str(item).strip().lower() for item in statuses if str(item).strip())
    if not normalized_statuses:
        return None
    placeholders = ",".join("?" for _ in normalized_statuses)
    return conn.execute(
        f"SELECT attempt_id,event_id,signature_hash,kind,status,started_at,"
        f"completed_at,result_action_id,result_success,resolved_at FROM {TABLE} "
        "WHERE event_id=? AND signature_hash=? "
        f"AND status IN ({placeholders}) ORDER BY started_at DESC LIMIT 1",
        (event_id, signature_hash, *normalized_statuses),
    ).fetchone()


def event_attempts(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    statuses: Iterable[str] = ("started",),
    limit: int = 32,
) -> list[sqlite3.Row]:
    normalized_statuses = tuple(str(item).strip().lower() for item in statuses if str(item).strip())
    if not normalized_statuses:
        return []
    placeholders = ",".join("?" for _ in normalized_statuses)
    return list(
        conn.execute(
            f"SELECT attempt_id,event_id,signature_hash,kind,status,started_at,"
            f"completed_at,result_action_id,result_success,resolved_at FROM {TABLE} "
            f"WHERE event_id=? AND status IN ({placeholders}) "
            "ORDER BY started_at DESC LIMIT ?",
            (event_id, *normalized_statuses, max(1, int(limit))),
        ).fetchall()
    )


def prune_terminal_attempts(
    conn: sqlite3.Connection,
    *,
    max_completed: int = MAX_COMPLETED_ATTEMPTS,
) -> int:
    """Prune only attempts whose owning event has durable terminal truth.

    The event row and EventOutcome must both be terminal before an attempt is
    eligible. This remains safe when called inside the same transaction that
    publishes terminal truth: rollback restores both truth and retained attempt.
    """

    before = conn.total_changes
    conn.execute(
        f"DELETE FROM {TABLE} WHERE attempt_id IN ("
        f"SELECT attempt.attempt_id FROM {TABLE} AS attempt "
        "JOIN events AS event ON event.event_id=attempt.event_id "
        "JOIN event_outcomes AS outcome ON outcome.event_id=attempt.event_id "
        "WHERE attempt.status!='started' AND event.status IN ('completed','failed') "
        "ORDER BY COALESCE(attempt.completed_at,attempt.started_at) DESC, "
        "attempt.started_at DESC, attempt.attempt_id DESC LIMIT -1 OFFSET ?)",
        (max(0, int(max_completed)),),
    )
    return int(conn.total_changes - before)
