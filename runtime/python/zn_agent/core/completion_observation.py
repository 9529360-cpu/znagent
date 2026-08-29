from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Any

from .models import utc_now

if TYPE_CHECKING:
    from .resident import ZNResidentRuntime


class CompletionObservationJournal:
    """Durable repair queue for resident self-observation after event completion.

    Event completion is the authoritative truth boundary. Life observation happens
    afterwards and may fail independently (for example because its SQLite write is
    temporarily unavailable). This journal records that secondary failure without
    reopening, replaying, or reclassifying the already-completed event.
    """

    _STAGE_LIFE = "life"
    DEFAULT_REPAIR_BATCH = 128
    MAX_STARTUP_REPAIR_RECORDS = 2048

    def __init__(self, store):
        self.store = store
        self._init_schema()

    def observe_life(self, resident: ZNResidentRuntime, result) -> bool:
        """Apply Life observation at-least-once without leaking failures upstream."""
        event_id = result.event.event_id
        tracking = True
        try:
            if self._is_completed(event_id, self._STAGE_LIFE):
                return True
            self._begin(event_id, self._STAGE_LIFE)
        except Exception:
            # The journal shares the same durable body. If tracking itself is
            # temporarily unavailable, still attempt the observation, but never
            # let a secondary observation failure falsify the event outcome.
            tracking = False

        try:
            resident.life.observe_action(result)
        except Exception as exc:
            if tracking:
                try:
                    self._defer(event_id, self._STAGE_LIFE, exc)
                except Exception:
                    pass
            return False

        if tracking:
            try:
                self._finish(event_id, self._STAGE_LIFE)
            except Exception:
                # The Life write already succeeded. Leaving the stage non-terminal
                # means a restart may observe it again; Life observation is a
                # bounded state update and observation merge, so that retry is safe.
                return False
        return True

    def repair_life(self, resident: ZNResidentRuntime, *, limit: int = 128) -> int:
        """Retry one bounded batch of pending Life observations."""
        repaired = 0
        try:
            pending = self.pending(stage=self._STAGE_LIFE, limit=limit)
        except Exception:
            return 0
        for item in pending:
            result = resident.result_for(str(item["event_id"]))
            if result is None:
                continue
            if self.observe_life(resident, result):
                repaired += 1
        return repaired

    def repair_life_sweep(
        self,
        resident: ZNResidentRuntime,
        *,
        batch_size: int = DEFAULT_REPAIR_BATCH,
        max_records: int = MAX_STARTUP_REPAIR_RECORDS,
    ) -> int:
        """Attempt every initially pending Life repair once, within a hard bound.

        A failed retry is deferred with a fresh ``updated_at`` and therefore
        moves behind older pending rows. Taking the initial backlog size before
        sweeping lets finite batches rotate later records into view without
        retrying forever on a persistent Life failure. New rows created while the
        sweep runs wait for the next normal repair opportunity.
        """

        bounded_batch = max(1, min(2048, int(batch_size)))
        bounded_records = max(1, min(8192, int(max_records)))
        try:
            initial = min(
                self.pending_count(stage=self._STAGE_LIFE),
                bounded_records,
            )
        except Exception:
            return 0
        if initial <= 0:
            return 0

        repaired = 0
        remaining = initial
        while remaining > 0:
            current_batch = min(bounded_batch, remaining)
            repaired += self.repair_life(resident, limit=current_batch)
            remaining -= current_batch
        return repaired

    def pending_count(self, *, stage: str | None = None) -> int:
        """Count outstanding repair obligations without exposing their content."""

        with closing(self._connect()) as conn:
            if stage:
                row = conn.execute(
                    "SELECT COUNT(*) AS count FROM resident_completion_observations "
                    "WHERE status != 'completed' AND stage=?",
                    (str(stage),),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS count FROM resident_completion_observations "
                    "WHERE status != 'completed'"
                ).fetchone()
        return max(0, int(row["count"] if row else 0))

    def health(self) -> dict[str, Any]:
        """Return a sanitized control-plane summary without raw repair errors."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT stage,status,COUNT(*) AS count "
                "FROM resident_completion_observations "
                "WHERE status != 'completed' GROUP BY stage,status "
                "ORDER BY stage,status"
            ).fetchall()
        pending_by_stage: dict[str, int] = {}
        running = 0
        pending = 0
        for row in rows:
            stage = str(row["stage"] or "unknown")
            status = str(row["status"] or "pending")
            count = max(0, int(row["count"] or 0))
            pending_by_stage[stage] = pending_by_stage.get(stage, 0) + count
            if status == "running":
                running += count
            else:
                pending += count
        total = pending + running
        return {
            "healthy": total == 0,
            "pending_count": total,
            "waiting_count": pending,
            "running_count": running,
            "stages": pending_by_stage,
        }

    def pending(self, *, stage: str | None = None, limit: int = 128) -> list[dict[str, Any]]:
        bounded = max(1, min(2048, int(limit)))
        with closing(self._connect()) as conn:
            if stage:
                rows = conn.execute(
                    "SELECT event_id,stage,status,attempts,last_error,updated_at "
                    "FROM resident_completion_observations "
                    "WHERE status != 'completed' AND stage=? "
                    "ORDER BY updated_at ASC LIMIT ?",
                    (str(stage), bounded),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT event_id,stage,status,attempts,last_error,updated_at "
                    "FROM resident_completion_observations "
                    "WHERE status != 'completed' ORDER BY updated_at ASC LIMIT ?",
                    (bounded,),
                ).fetchall()
        return [dict(row) for row in rows]

    def state(self, event_id: str, stage: str = _STAGE_LIFE) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT event_id,stage,status,attempts,last_error,updated_at "
                "FROM resident_completion_observations WHERE event_id=? AND stage=?",
                (str(event_id), str(stage)),
            ).fetchone()
        return dict(row) if row else None

    def _is_completed(self, event_id: str, stage: str) -> bool:
        state = self.state(event_id, stage)
        return bool(state and state.get("status") == "completed")

    def _begin(self, event_id: str, stage: str) -> None:
        now = utc_now()
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO resident_completion_observations"
                "(event_id,stage,status,attempts,last_error,updated_at) "
                "VALUES(?,?,'pending',0,NULL,?)",
                (str(event_id), str(stage), now),
            )
            conn.execute(
                "UPDATE resident_completion_observations "
                "SET status='running', attempts=attempts+1, last_error=NULL, updated_at=? "
                "WHERE event_id=? AND stage=? AND status != 'completed'",
                (now, str(event_id), str(stage)),
            )
            conn.commit()

    def _defer(self, event_id: str, stage: str, error: Exception) -> None:
        message = f"{type(error).__name__}: {error}"[:2000]
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE resident_completion_observations "
                "SET status='pending', last_error=?, updated_at=? "
                "WHERE event_id=? AND stage=? AND status != 'completed'",
                (message, utc_now(), str(event_id), str(stage)),
            )
            conn.commit()

    def _finish(self, event_id: str, stage: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE resident_completion_observations "
                "SET status='completed', last_error=NULL, updated_at=? "
                "WHERE event_id=? AND stage=?",
                (utc_now(), str(event_id), str(stage)),
            )
            conn.commit()

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS resident_completion_observations(
                    event_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(event_id, stage)
                );
                CREATE INDEX IF NOT EXISTS idx_resident_completion_observations_pending
                    ON resident_completion_observations(status, stage, updated_at);
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
