from __future__ import annotations

"""Resident-owned durable journal for replay-sensitive execution attempts.

The same SQLite table is shared with ``SideEffectAwareBody`` so Work recovery,
cancellation and compiled-capability interruption use one resident truth model:
commit ``started`` before an effect-capable dispatch, then never guess after a
restart unless the action contract explicitly permits replay.
"""

import hashlib
import json
import sqlite3
from contextlib import closing
from typing import Any

from .models import WorkingState, utc_now


class ResidentSideEffectJournal:
    TABLE = "resident_side_effect_attempts"
    MAX_COMPLETED_ATTEMPTS = 4096

    def __init__(self, store):
        self.store = store
        self._init_schema()

    @staticmethod
    def signature_hash(kind: str, identity: dict[str, Any]) -> str:
        encoded = json.dumps(
            {"kind": str(kind or "").strip().lower(), "identity": identity},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def start_with_checkpoint(
        self,
        *,
        attempt_id: str,
        event_id: str,
        kind: str,
        signature_hash: str,
        state: WorkingState,
    ) -> None:
        """Atomically commit a replay boundary and its resident checkpoint."""
        normalized_attempt = str(attempt_id or "").strip()
        normalized_event = str(event_id or "").strip()
        normalized_kind = str(kind or "").strip().lower()
        normalized_signature = str(signature_hash or "").strip()
        if not all(
            (
                normalized_attempt,
                normalized_event,
                normalized_kind,
                normalized_signature,
            )
        ):
            raise ValueError("side-effect attempt requires complete identity")

        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT event_id,signature_hash,kind,status FROM {self.TABLE} "
                "WHERE attempt_id=?",
                (normalized_attempt,),
            ).fetchone()
            if row is None:
                conn.execute(
                    f"INSERT INTO {self.TABLE}"
                    "(attempt_id,event_id,signature_hash,kind,status,started_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        normalized_attempt,
                        normalized_event,
                        normalized_signature,
                        normalized_kind,
                        "started",
                        utc_now(),
                    ),
                )
            elif not (
                str(row["event_id"]) == normalized_event
                and str(row["signature_hash"]) == normalized_signature
                and str(row["kind"]) == normalized_kind
                and str(row["status"]) == "started"
            ):
                raise RuntimeError("side-effect attempt identity or lifecycle changed")

            self._save_state(conn, state)
            conn.commit()

    def observe_with_checkpoint(
        self,
        *,
        attempt_id: str,
        event_id: str,
        state: WorkingState,
        success: bool,
    ) -> None:
        """Atomically close one dispatch observation and persist its next state."""
        normalized_attempt = str(attempt_id or "").strip()
        normalized_event = str(event_id or "").strip()
        if not normalized_attempt or not normalized_event:
            raise ValueError("observed side-effect attempt requires identity")

        with closing(self._connect()) as conn:
            cursor = conn.execute(
                f"UPDATE {self.TABLE} SET status='observed',completed_at=?,result_success=? "
                "WHERE attempt_id=? AND event_id=? AND status='started'",
                (
                    utc_now(),
                    1 if success else 0,
                    normalized_attempt,
                    normalized_event,
                ),
            )
            if cursor.rowcount != 1:
                row = conn.execute(
                    f"SELECT event_id,status,result_success FROM {self.TABLE} "
                    "WHERE attempt_id=?",
                    (normalized_attempt,),
                ).fetchone()
                if not (
                    row is not None
                    and str(row["event_id"]) == normalized_event
                    and str(row["status"]) == "observed"
                    and int(row["result_success"] or 0) == (1 if success else 0)
                ):
                    raise RuntimeError("side-effect attempt lost its active started record")
            self._prune_completed(conn)
            self._save_state(conn, state)
            conn.commit()

    def attempt(self, attempt_id: str) -> dict[str, Any] | None:
        normalized = str(attempt_id or "").strip()
        if not normalized:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT attempt_id,event_id,signature_hash,kind,status,started_at,"
                f"completed_at,result_success FROM {self.TABLE} WHERE attempt_id=?",
                (normalized,),
            ).fetchone()
        return dict(row) if row is not None else None

    def replay_blocking_attempt(
        self,
        event_id: str,
        signature_hash: str,
    ) -> dict[str, Any] | None:
        normalized_event = str(event_id or "").strip()
        normalized_signature = str(signature_hash or "").strip()
        if not normalized_event or not normalized_signature:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT attempt_id,event_id,signature_hash,kind,status,started_at "
                f"FROM {self.TABLE} WHERE event_id=? AND signature_hash=? "
                "AND status='started' ORDER BY started_at DESC LIMIT 1",
                (normalized_event, normalized_signature),
            ).fetchone()
        return dict(row) if row is not None else None

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE}(
                    attempt_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    signature_hash TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    result_action_id TEXT,
                    result_success INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_resident_side_effect_attempt
                    ON {self.TABLE}(event_id, signature_hash, started_at DESC);
                """
            )
            conn.commit()

    @staticmethod
    def _state_data(state: WorkingState) -> dict[str, Any]:
        state.updated_at = utc_now()
        return {
            "current_event_id": state.current_event_id,
            "current_goal_id": state.current_goal_id,
            "stage": state.stage,
            "next_action": state.next_action,
            "blocked_by": state.blocked_by,
            "data": state.data,
            "updated_at": state.updated_at,
        }

    def _save_state(self, conn: sqlite3.Connection, state: WorkingState) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO working_state(id,data) VALUES(1,?)",
            (
                json.dumps(
                    self._state_data(state),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ),
        )

    def _prune_completed(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            f"DELETE FROM {self.TABLE} WHERE attempt_id IN ("
            f"SELECT attempt_id FROM {self.TABLE} WHERE status!='started' "
            "ORDER BY completed_at DESC LIMIT -1 OFFSET ?)",
            (self.MAX_COMPLETED_ATTEMPTS,),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
