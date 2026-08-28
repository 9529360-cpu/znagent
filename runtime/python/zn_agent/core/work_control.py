from __future__ import annotations

"""Resident-owned control plane for durable Work lifecycle decisions."""

import json
from contextlib import closing
from typing import Any

from .models import ResidentRunResult, utc_now
from .work import ResidentWorkLedger, WorkMessage, WorkRun, _event_message_id


class ResidentWorkControl:
    """Control lifecycle decisions that are not ordinary Work success/failure.

    ``ResidentWorkLedger`` remains the durable interaction ledger for normal
    execution. This facade owns explicit operator control such as abandoning an
    unresolved non-replayable side effect. It repairs ingress linkage and
    cancellation before asking the ordinary ledger to finalize anything, so a
    restart cannot lose Work ownership or reinterpret a durable cancelled
    outcome as an ordinary failed Work result.
    """

    def __init__(self, ledger: ResidentWorkLedger):
        self.ledger = ledger
        self.resident = ledger.resident
        self.reconcile_missing_ingress_runs()
        self.reconcile_cancelled_runs()

    def reconcile_missing_ingress_runs(self) -> int:
        """Repair only the enqueue -> Work-run crash window.

        ``ResidentWorkLedger.start()`` persists the resident event before it
        persists ``work_runs``. A hard process exit between those commits leaves
        a real resident event carrying its Work thread/message identity but no
        Work linkage. Reconstruct that linkage from mutually agreeing durable
        records. This repair never claims, executes, requeues, or terminalizes an
        event; the resident event/outcome/checkpoint remain the execution truth.
        """

        with self.ledger._lock, closing(self.ledger._connect()) as conn:
            rows = conn.execute(
                """
                SELECT events.event_id, events.data
                FROM events
                LEFT JOIN work_runs ON work_runs.event_id=events.event_id
                WHERE work_runs.event_id IS NULL
                ORDER BY events.created_at ASC
                """
            ).fetchall()

            candidates: list[WorkRun] = []
            for row in rows:
                try:
                    data = json.loads(row["data"] or "{}")
                except Exception:
                    continue
                payload = data.get("payload")
                if not isinstance(payload, dict):
                    continue

                event_id = str(data.get("event_id") or "").strip()
                thread_id = str(payload.get("work_thread_id") or "").strip()
                message_id = str(payload.get("work_message_id") or "").strip()
                task = str(data.get("task") or "").strip()
                if (
                    not event_id
                    or event_id != str(row["event_id"])
                    or not thread_id
                    or not message_id
                    or not task
                ):
                    continue
                try:
                    thread_id = self.ledger._normalize_thread_id(thread_id)
                except ValueError:
                    continue

                thread = conn.execute(
                    "SELECT 1 FROM work_threads WHERE thread_id=?",
                    (thread_id,),
                ).fetchone()
                message = conn.execute(
                    """
                    SELECT role, text
                    FROM work_messages
                    WHERE message_id=? AND thread_id=?
                    """,
                    (message_id, thread_id),
                ).fetchone()
                if (
                    thread is None
                    or message is None
                    or str(message["role"]) != "user"
                    or str(message["text"]) != task
                ):
                    continue

                created_at = str(data.get("created_at") or "").strip() or utc_now()
                candidates.append(
                    WorkRun(
                        event_id=event_id,
                        thread_id=thread_id,
                        message_id=message_id,
                        task=task,
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )

        repaired = 0
        for work_run in candidates:
            if self.ledger.get_run(work_run.event_id) is not None:
                continue
            self.ledger._save_run(work_run)
            repaired += 1
        return repaired

    def reconcile_cancelled_runs(self, *, thread_id: str | None = None) -> int:
        sql = "SELECT * FROM work_runs WHERE ledger_state='active'"
        params: list[Any] = []
        if thread_id is not None:
            normalized_thread = self.ledger._normalize_thread_id(thread_id)
            sql += " AND thread_id=?"
            params.append(normalized_thread)
        sql += " ORDER BY created_at ASC LIMIT 64"
        with self.ledger._lock, closing(self.ledger._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()

        repaired = 0
        for row in rows:
            work_run = self.ledger._run_from_row(row)
            outcome = self.resident.store.get_event_outcome(work_run.event_id)
            if outcome is None or not outcome.cancelled:
                continue
            run = self.resident.result_for(work_run.event_id)
            if run is None or not run.cancelled:
                raise RuntimeError(
                    "cancelled Work outcome cannot be reconstructed by the resident"
                )
            self._finalize_cancelled(work_run, run)
            repaired += 1
        return repaired

    def list_snapshots(
        self,
        *,
        thread_limit: int = 24,
        message_limit: int = 120,
    ):
        self.reconcile_cancelled_runs()
        return self.ledger.list_snapshots(
            thread_limit=thread_limit,
            message_limit=message_limit,
        )

    def get_snapshot(self, thread_id: str, *, message_limit: int = 120):
        self.reconcile_cancelled_runs(thread_id=thread_id)
        return self.ledger.get_snapshot(thread_id, message_limit=message_limit)

    def start(self, thread_id: str, task: str, **kwargs):
        self.reconcile_cancelled_runs(thread_id=thread_id)
        return self.ledger.start(thread_id, task, **kwargs)

    def progress(self, thread_id: str, event_id: str) -> dict[str, Any]:
        normalized_thread = self.ledger._normalize_thread_id(thread_id)
        normalized_event = str(event_id or "").strip()
        if not normalized_event:
            raise ValueError("work progress requires event_id")
        work_run = self.ledger.get_run(normalized_event)
        if work_run is None or work_run.thread_id != normalized_thread:
            raise ValueError("unknown work event for thread")

        outcome = self.resident.store.get_event_outcome(normalized_event)
        if outcome is not None and outcome.cancelled:
            if work_run.ledger_state != "finalized":
                run = self.resident.result_for(normalized_event)
                if run is None or not run.cancelled:
                    raise RuntimeError(
                        "cancelled Work outcome cannot be reconstructed by the resident"
                    )
                self._finalize_cancelled(work_run, run)
            progress = self.ledger.progress(normalized_thread, normalized_event)
            progress.update(
                {
                    "status": "cancelled",
                    "stage": "cancelled",
                    "next_action": "work stopped",
                    "terminal": True,
                    "finalized": True,
                    "recovery": None,
                    "error": None,
                }
            )
            return progress

        return self.ledger.progress(normalized_thread, normalized_event)

    def cancel(
        self,
        thread_id: str,
        event_id: str,
        *,
        reason: str = "user cancelled Work while outside-world effect remained uncertain",
    ) -> dict[str, Any]:
        normalized_thread = self.ledger._normalize_thread_id(thread_id)
        normalized_event = str(event_id or "").strip()
        if not normalized_event:
            raise ValueError("work cancellation requires event_id")
        work_run = self.ledger.get_run(normalized_event)
        if work_run is None or work_run.thread_id != normalized_thread:
            raise ValueError("unknown work event for thread")
        if work_run.ledger_state != "active":
            outcome = self.resident.store.get_event_outcome(normalized_event)
            if outcome is not None and outcome.cancelled:
                return self.progress(normalized_thread, normalized_event)
            raise RuntimeError("work cancellation requires an active Work run")

        run = self.resident.cancel_uncertain_event(
            normalized_event,
            reason=reason,
        )
        if not run.cancelled:
            raise RuntimeError("resident cancellation did not return a cancelled result")
        self._finalize_cancelled(work_run, run)
        return self.progress(normalized_thread, normalized_event)

    def _finalize_cancelled(
        self,
        work_run: WorkRun,
        run: ResidentRunResult,
    ) -> None:
        if not run.cancelled:
            raise ValueError("cancelled Work finalization requires a cancelled result")
        with self.ledger._lock:
            current = self.ledger.get_run(work_run.event_id)
            if current is None:
                raise ValueError(f"unknown work run: {work_run.event_id}")
            if current.ledger_state == "finalized":
                return
            thread = self.ledger.get_thread(current.thread_id)
            if thread is None:
                raise ValueError(f"unknown work thread: {current.thread_id}")

            message = (
                str(run.reason or "").strip()
                or "Work cancelled. ZN will not continue it; the uncertain outside-world effect remains unresolved."
            )
            self.ledger._append(
                thread,
                WorkMessage(
                    message_id=_event_message_id(current.event_id, "zn"),
                    thread_id=thread.thread_id,
                    role="zn",
                    text=message,
                    detail={
                        "cancelled": True,
                        "outside_world_effect": "uncertain",
                    },
                ),
            )
            self.ledger._append(
                thread,
                WorkMessage(
                    message_id=_event_message_id(current.event_id, "activity"),
                    thread_id=thread.thread_id,
                    role="activity",
                    text="Resident control",
                    detail={
                        "event_id": run.event.event_id,
                        "execution_path": run.execution_path.value,
                        "cancelled": True,
                        "outside_world_effect": "uncertain",
                        "reason": run.reason,
                    },
                ),
            )

            now = utc_now()
            current.ledger_state = "finalized"
            current.updated_at = now
            current.finalized_at = now
            self.ledger._save_run(current)
