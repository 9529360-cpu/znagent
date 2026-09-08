from __future__ import annotations

"""Resident-owned control plane for durable Work lifecycle decisions."""

import json
from contextlib import closing
from typing import Any

from .models import ResidentRunResult, utc_now
from .work import ResidentWorkLedger, WorkMessage, WorkRun, _event_message_id
from .worker_progress import progress_snapshot


class ResidentWorkControl:
    """Control lifecycle decisions that are not ordinary Work success/failure.

    ``ResidentWorkLedger`` remains the durable interaction ledger for normal
    execution. This facade owns explicit operator control such as abandoning an
    unresolved non-replayable side effect. It repairs ingress linkage and
    cancellation before asking the ordinary ledger to finalize anything, so a
    restart cannot lose Work ownership or reinterpret a durable cancelled
    outcome as an ordinary failed Work result.
    """

    _DELEGATED_KINDS = frozenset({"research", "coding", "review"})
    _DELEGATED_STAGE_MAP = {
        "worker_started": "starting",
        "context_bound": "preparing",
        "provider_result_persisted": "result_ready",
        "provider_result_observed": "result_ready",
        "effect_started": "acting",
        "effect_observed": "verifying",
        "effect_verified": "verified",
    }
    _DELEGATED_PHASE_LIMIT = 32

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

    def inspect_restore_points(
        self,
        thread_id: str,
        *,
        limit: int = 48,
    ) -> list[dict[str, Any]]:
        normalized_thread = self.ledger._normalize_thread_id(thread_id)
        inspector = getattr(self.resident, "inspect_work_restore_points", None)
        if not callable(inspector):
            return []
        points = inspector(normalized_thread, limit=limit)
        if not isinstance(points, list):
            raise RuntimeError("resident returned invalid Work restore-point inspection")
        return points

    def get_snapshot(self, thread_id: str, *, message_limit: int = 120):
        self.reconcile_cancelled_runs(thread_id=thread_id)
        thread, messages = self.ledger.get_snapshot(thread_id, message_limit=message_limit)
        metadata = dict(thread.metadata)
        metadata["restore_points"] = self.inspect_restore_points(thread.thread_id)
        thread.metadata = metadata
        return thread, messages

    @classmethod
    def _delegated_kind(cls, value: object) -> str:
        kind = str(value or "").strip().lower()
        return kind if kind in cls._DELEGATED_KINDS else "work"

    @classmethod
    def _delegated_phase(cls, run, *, current_plan_version: int) -> dict[str, Any]:
        state = str(getattr(run, "state", "") or "").strip().lower()
        try:
            run_version = int(getattr(run, "plan_version", 0) or 0)
        except (TypeError, ValueError):
            run_version = 0
        current = run_version == current_plan_version
        snapshot: dict[str, Any] = {}

        if not current or state == "stale":
            status = "superseded"
            stage = "superseded"
        elif state == "completed":
            status = "completed"
            stage = "completed"
        elif state == "failed":
            status = "failed"
            stage = "failed"
        elif state == "queued":
            status = "pending"
            stage = "waiting"
        elif state == "running":
            status = "running"
            snapshot = progress_snapshot(run)
            internal_stage = str(snapshot.get("stage") or "").strip().lower()
            stage = (
                "starting"
                if not internal_stage
                else cls._DELEGATED_STAGE_MAP.get(internal_stage, "working")
            )
        else:
            status = "pending"
            stage = "working"

        updated_at = (
            getattr(run, "finished_at", None)
            if status in {"completed", "failed", "superseded"}
            else snapshot.get("last_progress_at") if snapshot else None
        ) or getattr(run, "started_at", None)
        phase = {
            "kind": cls._delegated_kind(getattr(run, "executor_kind", None)),
            "status": status,
            "stage": stage,
        }
        if updated_at:
            phase["updated_at"] = str(updated_at)
        return phase

    def _delegation_projection(
        self,
        thread_id: str,
        progress: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Project durable WorkerRuns into a bounded privacy-safe user view.

        This path is observation only. It never records a heartbeat, changes a
        WorkerRun/WorkItem, invokes a provider, dispatches Body work, or creates
        progress persistence. The projection intentionally copies only a small
        allowlist and never exposes WorkerRun identity, route/provider data,
        scopes, metrics/fingerprints, context packs, artifacts, results, or raw
        errors.
        """

        list_worker_runs = getattr(self.ledger, "list_worker_runs", None)
        if not callable(list_worker_runs):
            return None
        try:
            current_plan_version = int(progress.get("current_plan_version") or 0)
        except (TypeError, ValueError):
            return None
        if current_plan_version < 1:
            return None

        runs = list_worker_runs(thread_id=thread_id, limit=256)
        if not runs:
            return None

        counts = {
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "superseded": 0,
        }
        current_phases: list[dict[str, Any]] = []
        historical_phases: list[dict[str, Any]] = []
        for run in runs:
            phase = self._delegated_phase(
                run,
                current_plan_version=current_plan_version,
            )
            counts[phase["status"]] += 1
            if phase["status"] == "superseded":
                historical_phases.append(phase)
            else:
                current_phases.append(phase)

        running = [phase for phase in current_phases if phase["status"] == "running"]
        pending = [phase for phase in current_phases if phase["status"] == "pending"]
        failed = [phase for phase in current_phases if phase["status"] == "failed"]
        completed = [phase for phase in current_phases if phase["status"] == "completed"]
        if running:
            status = "running"
            current_phase = running[-1]["kind"]
        elif pending:
            status = "pending"
            current_phase = pending[0]["kind"]
        elif failed:
            status = "failed"
            current_phase = failed[-1]["kind"]
        elif completed:
            status = "completed"
            current_phase = completed[-1]["kind"]
        else:
            status = "superseded"
            current_phase = None

        phases = current_phases[: self._DELEGATED_PHASE_LIMIT]
        remaining = self._DELEGATED_PHASE_LIMIT - len(phases)
        if remaining > 0:
            phases.extend(historical_phases[-remaining:])

        projection: dict[str, Any] = {
            "plan_version": current_plan_version,
            "status": status,
            "counts": counts,
            "phases": phases,
        }
        if current_phase is not None:
            projection["current_phase"] = current_phase
        return projection

    def _with_delegation_projection(
        self,
        thread_id: str,
        progress: dict[str, Any],
    ) -> dict[str, Any]:
        delegation = self._delegation_projection(thread_id, progress)
        if delegation is not None:
            progress["delegation"] = delegation
        return progress

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
            return self._with_delegation_projection(normalized_thread, progress)

        progress = self.ledger.progress(normalized_thread, normalized_event)
        return self._with_delegation_projection(normalized_thread, progress)

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