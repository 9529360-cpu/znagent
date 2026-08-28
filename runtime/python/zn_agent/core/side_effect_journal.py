from __future__ import annotations

"""Resident-owned durable journal for replay-sensitive execution attempts.

Body actions and compiled capabilities share one SQLite representation and
low-level lifecycle owner. Their action identities intentionally remain distinct:
compiled capabilities keep their historical ``identity`` signature while Body
keeps its historical raw-args signature.
"""

import hashlib
import json
import sqlite3
from contextlib import closing
from typing import Any

from . import side_effect_attempts
from .models import WorkingState, utc_now


class ResidentSideEffectJournal:
    TABLE = side_effect_attempts.TABLE
    MAX_COMPLETED_ATTEMPTS = side_effect_attempts.MAX_COMPLETED_ATTEMPTS

    def __init__(self, store):
        self.store = store
        self._init_schema()

    @staticmethod
    def signature_hash(kind: str, identity: dict[str, Any]) -> str:
        # Historical compiled-capability identity. Do not normalize this to the
        # Body args signature: durable attempt rows depend on these exact bytes.
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
            row = side_effect_attempts.attempt(conn, normalized_attempt)
            if row is None:
                side_effect_attempts.start_attempt(
                    conn,
                    attempt_id=normalized_attempt,
                    event_id=normalized_event,
                    kind=normalized_kind,
                    signature_hash=normalized_signature,
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
            changed = side_effect_attempts.observe_started_attempt(
                conn,
                attempt_id=normalized_attempt,
                event_id=normalized_event,
                completed_at=utc_now(),
                success=success,
            )
            if changed != 1:
                row = side_effect_attempts.attempt(conn, normalized_attempt)
                if not (
                    row is not None
                    and str(row["event_id"]) == normalized_event
                    and str(row["status"]) == "observed"
                    and int(row["result_success"] or 0) == (1 if success else 0)
                ):
                    raise RuntimeError("side-effect attempt lost its active started record")
            side_effect_attempts.prune_terminal_attempts(
                conn,
                max_completed=self.MAX_COMPLETED_ATTEMPTS,
            )
            self._save_state(conn, state)
            conn.commit()

    def attempt(self, attempt_id: str) -> dict[str, Any] | None:
        normalized = str(attempt_id or "").strip()
        if not normalized:
            return None
        with closing(self._connect()) as conn:
            row = side_effect_attempts.attempt(conn, normalized)
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
            row = side_effect_attempts.replay_blocking_attempt(
                conn,
                event_id=normalized_event,
                signature_hash=normalized_signature,
                statuses=("started",),
            )
        return dict(row) if row is not None else None

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            side_effect_attempts.ensure_schema(conn)
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

    def _connect(self) -> sqlite3.Connection:
        return side_effect_attempts.connect(self.store.path)
