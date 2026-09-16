from __future__ import annotations

"""Expose honest terminal Work outcomes without creating another Work truth.

The underlying EvidenceBoundSteerableWorkLedger remains authoritative. This control
surface only projects current-plan facts and reconciles the already-existing final ZN
transcript message after Work finalization has settled.
"""

import json
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
                "SELECT text,detail_json FROM work_messages WHERE message_id=? AND thread_id=?",
                (message_id, work_run.thread_id),
            ).fetchone()
            if row is None:
                return
            try:
                raw_detail = json.loads(row["detail_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                raw_detail = {}
            detail = raw_detail if isinstance(raw_detail, dict) else {}
            detail = dict(detail)
            detail["work_outcome"] = projection
            detail["partial"] = projection.get("status") == "partial"
            detail["blocked"] = projection.get("status") == "blocked"
            if projection.get("status") == "blocked":
                detail["failed"] = True
            encoded = json.dumps(detail, ensure_ascii=False, separators=(",", ":"))
            if str(row["text"] or "") == summary and str(row["detail_json"] or "") == encoded:
                return
            conn.execute(
                "UPDATE work_messages SET text=?,detail_json=? WHERE message_id=? AND thread_id=?",
                (summary, encoded, message_id, work_run.thread_id),
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
        snapshot = super().get_snapshot(thread_id, message_limit=message_limit)
        self._reconcile_thread_outcomes(thread_id)
        # Re-read only after reconciliation so the returned transcript contains the
        # final bounded outcome text. No Work execution/state authority is changed.
        return self.ledger._snapshot_without_finalize(thread_id, message_limit=message_limit)

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
