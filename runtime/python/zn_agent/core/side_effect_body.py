from __future__ import annotations

"""Durable pre-dispatch guard for generic non-replayable body side effects."""

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from typing import Any

from .body import BodyActionResult
from .keyboard_text_body import KeyboardTextBody
from .models import utc_now


class SideEffectAwareBody(KeyboardTextBody):
    """Keep the real KeyboardTextBody contract while guarding generic side effects.

    Pointer clicks and focused keyboard text already own richer resident-level
    non-replayable lifecycles. This body deliberately leaves those contracts
    unchanged. It adds only a durable pre-dispatch boundary around generic
    command execution and append-style text writes.

    A ``started`` attempt is committed before dispatch. If the process dies after
    that commit, the next resident refuses the same event/action signature rather
    than guessing whether the outside-world side effect happened. No raw command,
    text, environment or other action arguments are copied into this ledger; only
    a deterministic signature hash and bounded execution metadata are persisted.
    """

    _TABLE = "resident_side_effect_attempts"
    _MAX_COMPLETED_ATTEMPTS = 4096
    _COMMAND_KINDS = frozenset({"command", "terminal", "shell"})
    _APPEND_KINDS = frozenset({"write_text", "write_file"})
    _RECOVERY_STATUSES = frozenset({"verified_effect", "verified_absent"})

    def act(
        self,
        kind: str,
        *,
        event_id: str | None = None,
        **args: Any,
    ) -> BodyActionResult:
        normalized_kind = str(kind or "").strip().lower()
        normalized_event = str(event_id or "").strip()
        if not normalized_event or not self._requires_guard(normalized_kind, args):
            return super().act(kind, event_id=event_id, **args)

        signature_hash = self._signature_hash(normalized_kind, args)
        prior = self._started_attempt(normalized_event, signature_hash)
        if prior is not None:
            return self._uncertain_result(
                normalized_kind,
                normalized_event,
                attempt_id=str(prior["attempt_id"]),
                signature_hash=signature_hash,
                error=(
                    f"{normalized_kind} may already have started before resident interruption; "
                    "refusing blind replay until current reality proves what happened"
                ),
            )

        attempt_id = f"sidefx-{uuid.uuid4().hex[:12]}"
        self._start_attempt(
            attempt_id=attempt_id,
            event_id=normalized_event,
            kind=normalized_kind,
            signature_hash=signature_hash,
        )

        try:
            result = super().act(kind, event_id=event_id, **args)
        except Exception as exc:
            # A normal exception cannot establish that a command/append produced
            # no side effect. Keep the durable attempt in ``started`` state and
            # return uncertainty as evidence so the resident investigates rather
            # than terminalizing or replaying the movement.
            return self._uncertain_result(
                normalized_kind,
                normalized_event,
                attempt_id=attempt_id,
                signature_hash=signature_hash,
                error=(
                    "body dispatch ended without a durable result after the non-replayable "
                    f"boundary: {type(exc).__name__}: {exc}; outside-world effect is uncertain"
                ),
            )
        except BaseException:
            # SystemExit/KeyboardInterrupt stand in for process interruption in
            # tests and real shutdown paths. The committed ``started`` marker is
            # intentionally left behind for the next resident.
            raise

        try:
            self._finish_attempt(attempt_id, result)
        except Exception as exc:
            return self._uncertain_result(
                normalized_kind,
                normalized_event,
                attempt_id=attempt_id,
                signature_hash=signature_hash,
                error=(
                    "body dispatch returned but its side-effect attempt could not be durably "
                    f"closed: {type(exc).__name__}: {exc}; outside-world effect is uncertain"
                ),
            )

        result.data = {
            **dict(result.data or {}),
            "side_effect_attempt_id": attempt_id,
            "side_effect_dispatch_observed": True,
        }
        return result

    @classmethod
    def _requires_guard(cls, kind: str, args: dict[str, Any]) -> bool:
        if kind in cls._COMMAND_KINDS:
            return True
        return kind in cls._APPEND_KINDS and bool(args.get("append", False))

    @staticmethod
    def _signature_hash(kind: str, args: dict[str, Any]) -> str:
        encoded = json.dumps(
            {"kind": kind, "args": args},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _init_schema(self) -> None:
        super()._init_schema()
        with closing(self._connect()) as conn:
            conn.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE}(
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
                    ON {self._TABLE}(event_id, signature_hash, started_at DESC);
                """
            )
            conn.commit()

    def _start_attempt(
        self,
        *,
        attempt_id: str,
        event_id: str,
        kind: str,
        signature_hash: str,
    ) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                f"INSERT INTO {self._TABLE}"
                "(attempt_id,event_id,signature_hash,kind,status,started_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    attempt_id,
                    event_id,
                    signature_hash,
                    kind,
                    "started",
                    utc_now(),
                ),
            )
            conn.commit()

    def _finish_attempt(self, attempt_id: str, result: BodyActionResult) -> None:
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                f"UPDATE {self._TABLE} SET status=?,completed_at=?,result_action_id=?,"
                "result_success=? WHERE attempt_id=? AND status='started'",
                (
                    "observed",
                    result.completed_at or utc_now(),
                    result.action_id,
                    1 if result.success else 0,
                    attempt_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("side-effect attempt lost its active started record")
            self._prune_completed(conn)
            conn.commit()

    def resolve_uncertain_attempt(
        self,
        attempt_id: str,
        *,
        event_id: str,
        status: str,
        evidence_action_id: str | None = None,
    ) -> bool:
        """Close one started attempt only after resident-owned recovery evidence.

        This method grants no mutation authority and stores no action arguments.
        ``verified_effect`` means current reality independently satisfies the
        intended effect; ``verified_absent`` means an action-specific recovery
        check proved the pre-dispatch baseline still exists. Lifecycle cancellation
        is intentionally not accepted here because it must be committed atomically
        with the resident event and WorkingState transition.
        """

        normalized_attempt = str(attempt_id or "").strip()
        normalized_event = str(event_id or "").strip()
        normalized_status = str(status or "").strip().lower()
        if (
            not normalized_attempt
            or not normalized_event
            or normalized_status not in self._RECOVERY_STATUSES
        ):
            return False
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                f"UPDATE {self._TABLE} SET status=?,completed_at=?,result_action_id=? "
                "WHERE attempt_id=? AND event_id=? AND status='started'",
                (
                    normalized_status,
                    utc_now(),
                    str(evidence_action_id or "").strip() or None,
                    normalized_attempt,
                    normalized_event,
                ),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return False
            self._prune_completed(conn)
            conn.commit()
            return True

    def _prune_completed(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            f"DELETE FROM {self._TABLE} WHERE attempt_id IN ("
            f"SELECT attempt_id FROM {self._TABLE} WHERE status!='started' "
            "ORDER BY completed_at DESC LIMIT -1 OFFSET ?)",
            (self._MAX_COMPLETED_ATTEMPTS,),
        )

    def _started_attempt(self, event_id: str, signature_hash: str):
        with closing(self._connect()) as conn:
            return conn.execute(
                f"SELECT * FROM {self._TABLE} WHERE event_id=? AND signature_hash=? "
                "AND status='started' ORDER BY started_at DESC LIMIT 1",
                (event_id, signature_hash),
            ).fetchone()

    def uncertain_attempts(self, event_id: str) -> list[dict[str, Any]]:
        """Return bounded, argument-free uncertainty evidence for one event."""

        normalized = str(event_id or "").strip()
        if not normalized:
            return []
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT attempt_id,event_id,signature_hash,kind,status,started_at "
                f"FROM {self._TABLE} WHERE event_id=? AND status='started' "
                "ORDER BY started_at DESC LIMIT 32",
                (normalized,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _uncertain_result(
        kind: str,
        event_id: str,
        *,
        attempt_id: str,
        signature_hash: str,
        error: str,
    ) -> BodyActionResult:
        now = utc_now()
        return BodyActionResult(
            action_id=f"guard-{uuid.uuid4().hex[:12]}",
            kind=kind,
            success=False,
            data={
                "side_effect_uncertain": True,
                "replay_blocked": True,
                "side_effect_attempt_id": attempt_id,
                "side_effect_signature": signature_hash[:16],
            },
            error=error,
            event_id=event_id,
            started_at=now,
            completed_at=now,
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
