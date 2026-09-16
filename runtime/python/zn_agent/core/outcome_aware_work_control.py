from __future__ import annotations

"""Expose honest terminal Work outcomes without creating another Work truth.

The underlying EvidenceBoundSteerableWorkLedger remains authoritative. This control
surface only projects current-plan facts and reconciles the already-existing final ZN
transcript message after Work finalization has settled.
"""

from contextlib import closing
from typing import Any

from .work import _event_message_id
from .work_outcome_summary import project_work_outcome, render_work_outcome_summary
from .work_restore_control import RestoreAwareWorkControl


class OutcomeAwareRestoreWorkControl(RestoreAwareWorkControl):
    """Restore-aware Work control with a bounded terminal outcome observation."""

    _FINALIZED_SCAN_LIMIT = 16

    def _projection(self, event_id: str) -> dict[str, Any] | None:
        projection = project_work_outcome(self.ledger, event_id)
        return projection if isinstance(projection, dict) else None

    def _reconcile_terminal_message(
        self,
        event_id: str,
        projection: dict[str, Any] | None,
    ) -> None:
        if not projection:
            return
        summary = render_work_outcome_summary(projection)
        if not summary:
            return

        work_run = self.ledger.get_run(event_id)
        if work_run is None or work_run.ledger_state != "finalized":
            return
        message_id = _event_message_id(event_id, "zn")
        with self.ledger._lock, closing(self.ledger._connect()) as conn:
            row = conn.execute(
                "SELECT text FROM work_messages WHERE message_id=? AND thread_id=?",
                (message_id, work_run.thread_id),
            ).fetchone()
            if row is None or str(row["text"] or "") == summary:
                return
            conn.execute(
                "UPDATE work_messages SET text=? WHERE message_id=? AND thread_id=?",
                (summary, message_id, work_run.thread_id),
            )
            conn.commit()

    def _reconcile_thread_outcomes(self, thread_id: str) -> None:
        normalized = self.ledger._normalize_thread_id(thread_id)
        with self.ledger._lock, closing(self.ledger._connect()) as conn:
            rows = conn.execute(
                "SELECT event_id FROM work_runs "
                "WHERE thread_id=? AND ledger_state='finalized' "
                "ORDER BY finalized_at DESC LIMIT ?",
                (normalized, self._FINALIZED_SCAN_LIMIT),
            ).fetchall()
        for row in rows:
            event_id = str(row["event_id"] or "").strip()
            if event_id:
                self._reconcile_terminal_message(event_id, self._projection(event_id))

    def progress(self, thread_id: str, event_id: str) -> dict[str, Any]:
        progress = super().progress(thread_id, event_id)
        projection = self._projection(event_id)
        if projection is not None:
            progress["outcome"] = projection
            if progress.get("finalized"):
                self._reconcile_terminal_message(event_id, projection)
        return progress

    def get_snapshot(self, thread_id: str, *, message_limit: int = 120):
        # The inherited call is allowed to finalize a completed Resident result and
        # also attaches restore-point metadata. Reconcile only after that authority
        # has settled, then call it once more so the returned snapshot preserves all
        # inherited metadata while containing the corrected terminal transcript.
        super().get_snapshot(thread_id, message_limit=message_limit)
        self._reconcile_thread_outcomes(thread_id)
        return super().get_snapshot(thread_id, message_limit=message_limit)

    def list_snapshots(
        self,
        *,
        thread_limit: int = 24,
        message_limit: int = 120,
    ):
        snapshots = super().list_snapshots(
            thread_limit=thread_limit,
            message_limit=message_limit,
        )
        result = []
        for thread, _messages in snapshots:
            self._reconcile_thread_outcomes(thread.thread_id)
            result.append(
                self.ledger._snapshot_without_finalize(
                    thread.thread_id,
                    message_limit=message_limit,
                )
            )
        return result
