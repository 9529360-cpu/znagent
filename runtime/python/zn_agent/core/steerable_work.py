from __future__ import annotations

"""Minimal plan-versioned Work semantics for active Resident Work steering.

Root Work remains the existing WorkThread. This layer adds only the durable plan
version and WorkItem structure required to change one active plan safely, retain
old evidence, and prevent stale results from advancing the current plan.
"""

import json
import uuid
from contextlib import closing, nullcontext
from dataclasses import dataclass, field
from typing import Any

from .models import EventOutcome, EventStatus, ExecutionPath, ResidentRunResult, utc_now
from .recovery_bounded_work import RecoveryBoundedWorkLedger
from .work import WorkMessage, WorkRun, _event_message_id, title_for_work_task


@dataclass(slots=True)
class WorkItem:
    work_item_id: str
    work_thread_id: str
    title: str
    objective: str
    status: str
    plan_version: int
    parent_work_item_id: str | None = None
    acceptance_criteria: list[str] = field(default_factory=list)
    result: str | None = None
    blocker: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    completed_at: str | None = None


class SteerableWorkLedger(RecoveryBoundedWorkLedger):
    """Recovery-bounded Work with the smallest steering/versioning extension."""

    _ACTIVE_ITEM_STATES = ("proposed", "ready", "running", "blocked")

    def __init__(self, resident):
        super().__init__(resident)
        self._init_plan_schema()
        self.reconcile_run_plan_bindings()

    def _init_plan_schema(self) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS work_plan_state(
                    thread_id TEXT PRIMARY KEY,
                    plan_version INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(thread_id) REFERENCES work_threads(thread_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS work_items(
                    work_item_id TEXT PRIMARY KEY,
                    work_thread_id TEXT NOT NULL,
                    parent_work_item_id TEXT,
                    title TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_version INTEGER NOT NULL,
                    acceptance_criteria_json TEXT NOT NULL,
                    result TEXT,
                    blocker TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY(work_thread_id) REFERENCES work_threads(thread_id) ON DELETE CASCADE,
                    FOREIGN KEY(parent_work_item_id) REFERENCES work_items(work_item_id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_work_items_thread_plan
                    ON work_items(work_thread_id, plan_version, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_work_items_status
                    ON work_items(status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS work_run_plans(
                    event_id TEXT PRIMARY KEY,
                    work_item_id TEXT NOT NULL,
                    plan_version INTEGER NOT NULL,
                    FOREIGN KEY(event_id) REFERENCES work_runs(event_id) ON DELETE CASCADE,
                    FOREIGN KEY(work_item_id) REFERENCES work_items(work_item_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_work_run_plans_item
                    ON work_run_plans(work_item_id, plan_version);
                """
            )
            conn.commit()

    @staticmethod
    def _item_from_row(row) -> WorkItem:
        raw = json.loads(row["acceptance_criteria_json"] or "[]")
        return WorkItem(
            work_item_id=str(row["work_item_id"]),
            work_thread_id=str(row["work_thread_id"]),
            parent_work_item_id=(
                str(row["parent_work_item_id"])
                if row["parent_work_item_id"] is not None
                else None
            ),
            title=str(row["title"]),
            objective=str(row["objective"]),
            status=str(row["status"]),
            plan_version=max(1, int(row["plan_version"])),
            acceptance_criteria=(
                [str(value) for value in raw] if isinstance(raw, list) else []
            ),
            result=str(row["result"]) if row["result"] is not None else None,
            blocker=str(row["blocker"]) if row["blocker"] is not None else None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            completed_at=(str(row["completed_at"]) if row["completed_at"] else None),
        )

    def plan_version(self, thread_id: str) -> int:
        normalized = self._normalize_thread_id(thread_id)
        now = utc_now()
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT plan_version FROM work_plan_state WHERE thread_id=?",
                (normalized,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO work_plan_state(thread_id,plan_version,updated_at) VALUES(?,?,?)",
                    (normalized, 1, now),
                )
                conn.commit()
                return 1
            return max(1, int(row["plan_version"]))

    def _set_plan_version(self, thread_id: str, version: int) -> None:
        normalized = self._normalize_thread_id(thread_id)
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO work_plan_state(thread_id,plan_version,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(thread_id) DO UPDATE SET plan_version=excluded.plan_version,updated_at=excluded.updated_at",
                (normalized, max(1, int(version)), utc_now()),
            )
            conn.commit()

    def list_work_items(self, thread_id: str, *, limit: int = 64) -> list[WorkItem]:
        normalized = self._normalize_thread_id(thread_id)
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM work_items WHERE work_thread_id=? ORDER BY created_at ASC LIMIT ?",
                (normalized, max(1, min(256, int(limit)))),
            ).fetchall()
        return [self._item_from_row(row) for row in rows]

    def work_item_for_event(self, event_id: str) -> WorkItem | None:
        normalized = str(event_id or "").strip()
        if not normalized:
            return None
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT work_items.* FROM work_run_plans "
                "JOIN work_items ON work_items.work_item_id=work_run_plans.work_item_id "
                "WHERE work_run_plans.event_id=?",
                (normalized,),
            ).fetchone()
        return self._item_from_row(row) if row is not None else None

    def _run_plan_version(self, event_id: str) -> int | None:
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT plan_version FROM work_run_plans WHERE event_id=?",
                (str(event_id or "").strip(),),
            ).fetchone()
        return int(row["plan_version"]) if row is not None else None

    def _save_item(self, item: WorkItem) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO work_items(
                    work_item_id,work_thread_id,parent_work_item_id,title,objective,status,
                    plan_version,acceptance_criteria_json,result,blocker,created_at,updated_at,completed_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(work_item_id) DO UPDATE SET
                    status=excluded.status,result=excluded.result,blocker=excluded.blocker,
                    updated_at=excluded.updated_at,completed_at=excluded.completed_at
                """,
                (
                    item.work_item_id,
                    item.work_thread_id,
                    item.parent_work_item_id,
                    item.title,
                    item.objective,
                    item.status,
                    int(item.plan_version),
                    json.dumps(item.acceptance_criteria, ensure_ascii=False, separators=(",", ":")),
                    item.result,
                    item.blocker,
                    item.created_at,
                    item.updated_at,
                    item.completed_at,
                ),
            )
            conn.commit()

    def _bind_run(self, event_id: str, work_item_id: str, plan_version: int) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO work_run_plans(event_id,work_item_id,plan_version) VALUES(?,?,?)",
                (event_id, work_item_id, max(1, int(plan_version))),
            )
            conn.commit()

    def reconcile_run_plan_bindings(self) -> int:
        """Repair the event/run -> WorkItem crash window from resident-owned payload."""
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT work_runs.event_id,work_runs.thread_id,events.data
                FROM work_runs
                JOIN events ON events.event_id=work_runs.event_id
                LEFT JOIN work_run_plans ON work_run_plans.event_id=work_runs.event_id
                WHERE work_run_plans.event_id IS NULL
                ORDER BY work_runs.created_at ASC
                LIMIT 128
                """
            ).fetchall()

        repaired = 0
        for row in rows:
            try:
                data = json.loads(row["data"] or "{}")
            except Exception:
                continue
            payload = data.get("payload")
            if not isinstance(payload, dict):
                continue
            work_item_id = str(payload.get("work_item_id") or "").strip()
            raw_version = payload.get("work_plan_version")
            if not work_item_id or isinstance(raw_version, bool):
                continue
            try:
                version = max(1, int(raw_version))
            except (TypeError, ValueError):
                continue
            with self._lock, closing(self._connect()) as conn:
                item = conn.execute(
                    "SELECT work_thread_id,plan_version FROM work_items WHERE work_item_id=?",
                    (work_item_id,),
                ).fetchone()
            if item is None:
                continue
            if (
                str(item["work_thread_id"]) != str(row["thread_id"])
                or int(item["plan_version"]) != version
            ):
                raise RuntimeError("durable Work plan binding conflicts with WorkItem truth")
            self._bind_run(str(row["event_id"]), work_item_id, version)
            repaired += 1
        return repaired

    def _delete_unbound_item(self, work_item_id: str) -> None:
        with self._lock, closing(self._connect()) as conn:
            bound = conn.execute(
                "SELECT 1 FROM work_run_plans WHERE work_item_id=? LIMIT 1",
                (work_item_id,),
            ).fetchone()
            if bound is None:
                conn.execute("DELETE FROM work_items WHERE work_item_id=?", (work_item_id,))
                conn.commit()

    def _snapshot_without_finalize(self, thread_id: str, *, message_limit: int = 120):
        thread, messages = super()._snapshot_without_finalize(
            thread_id,
            message_limit=message_limit,
        )
        metadata = dict(thread.metadata)
        metadata["plan_version"] = self.plan_version(thread.thread_id)
        metadata["work_items"] = [
            {
                "work_item_id": item.work_item_id,
                "parent_work_item_id": item.parent_work_item_id,
                "title": item.title,
                "objective": item.objective,
                "status": item.status,
                "plan_version": item.plan_version,
                "acceptance_criteria": list(item.acceptance_criteria),
                "result": item.result,
                "blocker": item.blocker,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
                "completed_at": item.completed_at,
            }
            for item in self.list_work_items(thread.thread_id)
        ]
        thread.metadata = metadata
        return thread, messages

    def start(
        self,
        thread_id: str,
        task: str,
        *,
        kind: str = "desktop_user_event",
        priority: int = 0,
        payload: dict[str, Any] | None = None,
        objective: str | None = None,
        acceptance_criteria: list[str] | None = None,
    ):
        normalized_task = str(task or "").strip()
        if not normalized_task:
            raise ValueError("work start requires task")
        raw_payload = dict(payload or {})
        if "work_plan_version" in raw_payload or "work_item_id" in raw_payload:
            raise ValueError("work plan identity is resident-owned metadata")

        thread = self.create_thread(thread_id=thread_id)
        version = self.plan_version(thread.thread_id)
        item = WorkItem(
            work_item_id=f"item-{uuid.uuid4().hex[:16]}",
            work_thread_id=thread.thread_id,
            title=title_for_work_task(objective or normalized_task),
            objective=str(objective or normalized_task).strip(),
            status="running",
            plan_version=version,
            acceptance_criteria=[
                str(value).strip()
                for value in (acceptance_criteria or [])
                if str(value).strip()
            ],
        )
        self._save_item(item)
        raw_payload["work_plan_version"] = version
        raw_payload["work_item_id"] = item.work_item_id
        try:
            snapshot, event = super().start(
                thread.thread_id,
                normalized_task,
                kind=kind,
                priority=priority,
                payload=raw_payload,
            )
        except Exception:
            self.reconcile_run_plan_bindings()
            self._delete_unbound_item(item.work_item_id)
            raise
        self._bind_run(event.event_id, item.work_item_id, version)
        return self._snapshot_without_finalize(thread.thread_id), event

    def _supersede_items_before(self, thread_id: str, version: int) -> None:
        placeholders = ",".join("?" for _ in self._ACTIVE_ITEM_STATES)
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                f"UPDATE work_items SET status='superseded',updated_at=? "
                f"WHERE work_thread_id=? AND plan_version<? AND status IN ({placeholders})",
                (utc_now(), thread_id, int(version), *self._ACTIVE_ITEM_STATES),
            )
            conn.commit()

    def _mark_run_stale(self, event_id: str) -> WorkRun:
        run = self.get_run(event_id)
        if run is None or run.ledger_state != "active":
            raise RuntimeError("active steering requires the current active Work run")
        run.ledger_state = "stale"
        run.updated_at = utc_now()
        self._save_run(run)
        return run

    def _assert_steerable_resident_state(self, event_id: str) -> None:
        event = self.resident.store.get_event(event_id)
        if event is None:
            raise RuntimeError("active Work lost its resident event")
        if event.status in {EventStatus.COMPLETED, EventStatus.FAILED}:
            raise RuntimeError("active Work completed before steering could be applied")

        working = self.resident.store.get_working_state()
        stage = str(working.stage or "").strip().lower()
        if working.current_event_id == event_id and stage == "side_effect_recovery":
            raise RuntimeError(
                "active Work steering is blocked by an unresolved outside-world effect; reconcile or explicitly cancel that uncertainty first"
            )
        if working.current_event_id and working.current_event_id != event_id:
            raise RuntimeError(
                "another resident event owns the live checkpoint; active Work steering will not erase it"
            )

    def _supersede_resident_event(self, event_id: str, *, new_plan_version: int) -> None:
        event = self.resident.store.get_event(event_id)
        if event is None:
            raise RuntimeError("active Work lost its resident event")
        if event.status == EventStatus.PENDING:
            event = self.resident.store.claim_event(event_id)
            if event is None:
                raise RuntimeError("active Work changed before steering could claim it")
        if event.status != EventStatus.PROCESSING:
            raise RuntimeError("active Work changed before steering could supersede it")
        reason = f"superseded by user steering to plan v{int(new_plan_version)}"
        self.resident.store.complete_event(
            EventOutcome(
                event_id=event_id,
                success=False,
                execution_path=ExecutionPath.CONTROL,
                reason=reason,
            ),
            error=reason,
        )

    def steer_active(
        self,
        thread_id: str,
        active_event_id: str,
        task: str,
        *,
        objective: str,
        reference: str | None = None,
        kind: str = "desktop_user_event",
        priority: int = 0,
        payload: dict[str, Any] | None = None,
    ):
        normalized_thread = self._normalize_thread_id(thread_id)
        active = self.get_run(active_event_id)
        if active is None or active.thread_id != normalized_thread or active.ledger_state != "active":
            raise ValueError("active steering requires the current Work run")

        previous_version = self.plan_version(normalized_thread)
        bound_version = self._run_plan_version(active_event_id) or previous_version
        if bound_version != previous_version:
            raise RuntimeError("active Work run is already stale against the current plan")
        next_version = previous_version + 1

        raw_payload = dict(payload or {})
        if "work_steering" in raw_payload:
            raise ValueError("work_steering is resident-owned metadata")
        raw_payload["work_steering"] = {
            "mode": "active_steer",
            "reference": str(reference or "").strip() or None,
            "previous_event_id": active_event_id,
            "previous_plan_version": previous_version,
            "plan_version": next_version,
            "objective": str(objective or "").strip(),
            "requires_fresh_resense": True,
            "replay_previous_event": False,
        }
        if not str(raw_payload.get("cognition_question") or "").strip():
            raw_payload["cognition_question"] = (
                "The user changed the plan of the same durable Work. "
                f"Current objective under plan v{next_version}: {str(objective or '').strip()}. "
                "Treat the previous plan as historical context only. Re-sense the current computer, workspace, browser, application, and target state before any new side effect. "
                "Do not replay a prior side effect merely because the old plan performed it. "
                "A result created under an older plan must not advance this plan without fresh verification."
            )

        cycle_lock = getattr(self.resident, "_cycle_lock", None)
        context = (
            cycle_lock
            if cycle_lock is not None and hasattr(cycle_lock, "__enter__")
            else nullcontext()
        )
        with context:
            self._assert_steerable_resident_state(active_event_id)
            self._set_plan_version(normalized_thread, next_version)
            self._supersede_items_before(normalized_thread, next_version)
            self._mark_run_stale(active_event_id)
            self._supersede_resident_event(
                active_event_id,
                new_plan_version=next_version,
            )
            stale_result = self.resident.result_for(active_event_id)
            if stale_result is None:
                raise RuntimeError("superseded resident event has no durable outcome")
            self._finalize_run(active_event_id, run=stale_result)
            return self.start(
                normalized_thread,
                task,
                kind=kind,
                priority=max(1, int(priority)),
                payload=raw_payload,
                objective=objective,
            )

    def _finalize_completed_runs(self, *, thread_id: str | None = None) -> None:
        sql = "SELECT * FROM work_runs WHERE ledger_state IN ('active','stale')"
        params: list[Any] = []
        if thread_id is not None:
            sql += " AND thread_id=?"
            params.append(self._normalize_thread_id(thread_id))
        sql += " ORDER BY created_at ASC LIMIT 64"
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()
        for row in rows:
            work_run = self._run_from_row(row)
            completed = self.resident.result_for(work_run.event_id)
            if completed is not None:
                self._finalize_run(work_run.event_id, run=completed)

    def _finalize_run(self, event_id: str, *, run: ResidentRunResult) -> None:
        work_run = self.get_run(event_id)
        if work_run is None:
            raise ValueError(f"unknown work run: {event_id}")
        run_version = self._run_plan_version(event_id)
        current_version = self.plan_version(work_run.thread_id)
        stale = work_run.ledger_state == "stale" or (
            run_version is not None and run_version != current_version
        )
        if not stale:
            super()._finalize_run(event_id, run=run)
            item = self.work_item_for_event(event_id)
            if item is not None and item.status != "completed":
                item.status = "completed" if run.success else "blocked"
                item.result = str(run.response or run.reason or "").strip()[:4000] or None
                item.blocker = (
                    None
                    if run.success
                    else (str(run.reason or "").strip()[:1000] or "resident event failed")
                )
                item.updated_at = utc_now()
                item.completed_at = item.updated_at if run.success else None
                self._save_item(item)
            return

        if work_run.ledger_state == "stale_finalized":
            return
        thread = self.get_thread(work_run.thread_id)
        if thread is None:
            raise ValueError(f"unknown work thread: {work_run.thread_id}")
        workspace = self._workspace_from_event(run.event)
        artifacts = self._collect_artifacts(
            thread,
            run,
            task=work_run.task,
            workspace=workspace,
        )
        detail: dict[str, Any] = {
            "event_id": event_id,
            "stale": True,
            "accepted": False,
            "run_plan_version": run_version,
            "current_plan_version": current_version,
            "execution_path": run.execution_path.value,
            "model_invocations": run.model_invocations,
            "result_excerpt": str(run.response or run.reason or "").strip()[:1000],
        }
        if artifacts:
            detail["artifacts"] = [
                {
                    "id": artifact.artifact_id,
                    "kind": artifact.kind,
                    "name": artifact.name,
                    "path": artifact.path,
                }
                for artifact in artifacts
            ]
        self._append(
            thread,
            WorkMessage(
                message_id=_event_message_id(event_id, "activity"),
                thread_id=thread.thread_id,
                role="activity",
                text="Stale resident result retained for review",
                detail=detail,
            ),
        )
        item = self.work_item_for_event(event_id)
        if item is not None:
            item.status = "superseded"
            item.result = str(run.response or run.reason or "").strip()[:4000] or item.result
            item.updated_at = utc_now()
            self._save_item(item)
        work_run.ledger_state = "stale_finalized"
        work_run.updated_at = utc_now()
        work_run.finalized_at = work_run.updated_at
        self._save_run(work_run)

    def progress(self, thread_id: str, event_id: str) -> dict[str, Any]:
        progress = super().progress(thread_id, event_id)
        work_run = self.get_run(event_id)
        if work_run is not None and work_run.ledger_state == "stale_finalized":
            progress.update(
                {
                    "status": "stale",
                    "stage": "stale",
                    "next_action": "result retained; current plan unchanged",
                    "terminal": True,
                    "finalized": True,
                    "stale": True,
                    "accepted": False,
                    "plan_version": self._run_plan_version(event_id),
                    "current_plan_version": self.plan_version(work_run.thread_id),
                    "error": None,
                }
            )
        elif work_run is not None:
            progress["plan_version"] = self._run_plan_version(event_id)
            progress["current_plan_version"] = self.plan_version(work_run.thread_id)
            progress["stale"] = work_run.ledger_state.startswith("stale")
        item = self.work_item_for_event(event_id)
        if item is not None:
            progress["work_item_id"] = item.work_item_id
            progress["work_item_status"] = item.status
        return progress
