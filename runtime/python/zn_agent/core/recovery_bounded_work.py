from __future__ import annotations

"""Recovery-aware synchronous facade over the resident-owned Work ledger."""

import json
import uuid
from contextlib import closing, nullcontext
from typing import Any

from .models import AgentEvent, EventStatus, utc_now
from .recovery_control import raise_if_synchronous_recovery_blocked
from .route_policy_intake import bind_work_event_route_policy
from .work import (
    ResidentWorkLedger,
    WorkMessage,
    WorkRun,
    title_for_work_task,
)


class RecoveryBoundedWorkLedger(ResidentWorkLedger):
    """Reuse Work durability while bounding its legacy synchronous submit face.

    Active Work ingress also owns a short-lived durable checkpoint before the
    resident event exists. The checkpoint is deleted as soon as the ordinary
    Work message -> resident event -> work_runs linkage is durable. It is not a
    second execution checkpoint and never creates replay authority for an event
    that already exists.
    """

    _INGRESS_TABLE = "work_ingress_checkpoints"

    def __init__(self, resident):
        super().__init__(resident)
        self._init_ingress_schema()
        self.reconcile_ingress_checkpoints()

    def _init_ingress_schema(self) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._INGRESS_TABLE}(
                    event_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    message_id TEXT NOT NULL UNIQUE,
                    task TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    message_created_at TEXT NOT NULL,
                    event_created_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(thread_id) REFERENCES work_threads(thread_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_work_ingress_thread
                    ON {self._INGRESS_TABLE}(thread_id, created_at ASC);
                """
            )
            conn.commit()

    def _save_ingress_checkpoint(
        self,
        *,
        event_id: str,
        thread_id: str,
        message_id: str,
        task: str,
        kind: str,
        priority: int,
        payload: dict[str, Any],
        message_created_at: str,
        event_created_at: str,
    ) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                f"""
                INSERT INTO {self._INGRESS_TABLE}(
                    event_id,thread_id,message_id,task,kind,priority,payload_json,
                    message_created_at,event_created_at,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event_id,
                    thread_id,
                    message_id,
                    task,
                    kind,
                    int(priority),
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    message_created_at,
                    event_created_at,
                    event_created_at,
                ),
            )
            conn.commit()

    def _delete_ingress_checkpoint(self, event_id: str) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                f"DELETE FROM {self._INGRESS_TABLE} WHERE event_id=?",
                (str(event_id or "").strip(),),
            )
            conn.commit()

    def _message_row(self, message_id: str):
        with self._lock, closing(self._connect()) as conn:
            return conn.execute(
                "SELECT * FROM work_messages WHERE message_id=?",
                (str(message_id or "").strip(),),
            ).fetchone()

    def _run_row_for_message(self, message_id: str):
        with self._lock, closing(self._connect()) as conn:
            return conn.execute(
                "SELECT * FROM work_runs WHERE message_id=? ORDER BY created_at ASC LIMIT 1",
                (str(message_id or "").strip(),),
            ).fetchone()

    def reconcile_ingress_checkpoints(self, *, thread_id: str | None = None) -> int:
        """Restore only pre-event Work ingress that has no outside-world effect yet.

        A checkpoint allocates the exact message/event identities before either
        can be dispatched into resident life. Restart may therefore recreate a
        missing pending event safely. If the event already exists, reconciliation
        only repairs Work linkage and never enqueues a second event.
        """

        sql = f"SELECT * FROM {self._INGRESS_TABLE}"
        params: list[Any] = []
        if thread_id is not None:
            normalized_thread = self._normalize_thread_id(thread_id)
            sql += " WHERE thread_id=?"
            params.append(normalized_thread)
        sql += " ORDER BY created_at ASC LIMIT 64"
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()

        repaired = 0
        for row in rows:
            event_id = str(row["event_id"] or "").strip()
            normalized_thread = self._normalize_thread_id(str(row["thread_id"] or ""))
            message_id = str(row["message_id"] or "").strip()
            task = str(row["task"] or "").strip()
            kind = str(row["kind"] or "").strip()
            message_created_at = str(row["message_created_at"] or "").strip()
            event_created_at = str(row["event_created_at"] or "").strip()
            try:
                priority = int(row["priority"])
                payload = json.loads(row["payload_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError("durable Work ingress checkpoint is malformed") from exc
            if (
                not event_id
                or not message_id
                or not task
                or not kind
                or not message_created_at
                or not event_created_at
                or not isinstance(payload, dict)
            ):
                raise RuntimeError("durable Work ingress checkpoint is incomplete")
            if (
                str(payload.get("work_thread_id") or "") != normalized_thread
                or str(payload.get("work_message_id") or "") != message_id
            ):
                raise RuntimeError("durable Work ingress checkpoint identity is inconsistent")

            thread = self.get_thread(normalized_thread)
            if thread is None:
                raise RuntimeError("durable Work ingress checkpoint lost its thread")

            message_row = self._message_row(message_id)
            if message_row is None:
                self._append(
                    thread,
                    WorkMessage(
                        message_id=message_id,
                        thread_id=normalized_thread,
                        role="user",
                        text=task,
                        created_at=message_created_at,
                    ),
                )
            elif (
                str(message_row["thread_id"]) != normalized_thread
                or str(message_row["role"]) != "user"
                or str(message_row["text"]) != task
            ):
                raise RuntimeError("durable Work ingress checkpoint conflicts with its user message")

            event = self.resident.store.get_event(event_id)
            if event is None:
                event = AgentEvent(
                    event_id=event_id,
                    task=task,
                    kind=kind,
                    priority=priority,
                    payload=payload,
                    created_at=event_created_at,
                    updated_at=event_created_at,
                )
                self.resident.store.enqueue_event(event)
            elif (
                event.task != task
                or event.kind != kind
                or int(event.priority) != priority
                or event.payload != payload
            ):
                raise RuntimeError("durable Work ingress checkpoint conflicts with resident event truth")

            existing_run = self.get_run(event_id)
            if existing_run is None:
                by_message = self._run_row_for_message(message_id)
                if by_message is not None:
                    existing_run = self._run_from_row(by_message)
            if existing_run is not None:
                if (
                    existing_run.event_id != event_id
                    or existing_run.thread_id != normalized_thread
                    or existing_run.message_id != message_id
                    or existing_run.task != task
                ):
                    raise RuntimeError("durable Work ingress checkpoint conflicts with Work linkage")
            else:
                self._save_run(
                    WorkRun(
                        event_id=event_id,
                        thread_id=normalized_thread,
                        message_id=message_id,
                        task=task,
                        created_at=event_created_at,
                        updated_at=event_created_at,
                    )
                )

            self._delete_ingress_checkpoint(event_id)
            repaired += 1
        return repaired

    def start(
        self,
        thread_id: str,
        task: str,
        *,
        kind: str = "desktop_user_event",
        priority: int = 0,
        payload: dict[str, Any] | None = None,
    ):
        normalized_task = str(task or "").strip()
        if not normalized_task:
            raise ValueError("work start requires task")
        normalized_kind = str(kind or "desktop_user_event").strip() or "desktop_user_event"
        normalized_priority = int(priority)

        thread = self.create_thread(thread_id=thread_id)
        self.reconcile_ingress_checkpoints(thread_id=thread.thread_id)
        self._finalize_completed_runs(thread_id=thread.thread_id)
        active = self._active_run_for_thread(thread.thread_id)
        if active is not None:
            event = self.resident.store.get_event(active.event_id)
            if event is None or event.status not in {EventStatus.COMPLETED, EventStatus.FAILED}:
                raise ValueError("work thread already has an active resident event")
            raise RuntimeError("work thread has a terminal event without a durable finalized outcome")

        thread = self.get_thread(thread.thread_id) or thread
        if not self.list_messages(thread.thread_id, limit=1) and thread.title == "New work":
            thread.title = title_for_work_task(normalized_task)
            thread.updated_at = utc_now()
            self._save_thread(thread)

        message_id = f"msg-{uuid.uuid4().hex[:16]}"
        event_id = f"evt-{uuid.uuid4().hex[:12]}"
        message_created_at = utc_now()
        event_created_at = utc_now()
        user_message = WorkMessage(
            message_id=message_id,
            thread_id=thread.thread_id,
            role="user",
            text=normalized_task,
            created_at=message_created_at,
        )

        event_payload = dict(payload or {})
        event_payload["work_thread_id"] = thread.thread_id
        event_payload["work_message_id"] = message_id
        workspace = self.workspace_for(thread)
        if workspace is not None:
            event_payload["workspace_path"] = workspace.path
            event_payload["workdir"] = workspace.path
            event_payload["workspace_name"] = workspace.name

        # Privacy/provider policy is Work continuity truth. Bind it before the
        # checkpoint can recreate/enqueue this ResidentEvent so every later
        # cognition path sees the same durable policy, including semantic
        # understanding calls that occur before broad Root acceptance.
        thread = self.get_thread(thread.thread_id) or thread
        bind_work_event_route_policy(
            self,
            thread,
            task=normalized_task,
            event_payload=event_payload,
        )

        self._save_ingress_checkpoint(
            event_id=event_id,
            thread_id=thread.thread_id,
            message_id=message_id,
            task=normalized_task,
            kind=normalized_kind,
            priority=normalized_priority,
            payload=event_payload,
            message_created_at=message_created_at,
            event_created_at=event_created_at,
        )
        try:
            self._append(thread, user_message)
            event = AgentEvent(
                event_id=event_id,
                task=normalized_task,
                kind=normalized_kind,
                priority=normalized_priority,
                payload=event_payload,
                created_at=event_created_at,
                updated_at=event_created_at,
            )
            self.resident.store.enqueue_event(event)
            self._save_run(
                WorkRun(
                    event_id=event_id,
                    thread_id=thread.thread_id,
                    message_id=message_id,
                    task=normalized_task,
                    created_at=event_created_at,
                    updated_at=event_created_at,
                )
            )
        except Exception as exc:
            persisted = self.resident.store.get_event(event_id)
            if persisted is not None:
                try:
                    self.reconcile_ingress_checkpoints(thread_id=thread.thread_id)
                except Exception as recovery_exc:
                    raise RuntimeError(
                        "resident event is durable but Work ingress linkage remains recoverable only after restart"
                    ) from recovery_exc
                repaired = self.get_run(event_id)
                if repaired is not None:
                    return self._snapshot_without_finalize(thread.thread_id), persisted
                raise RuntimeError(
                    "resident event is durable but Work ingress linkage is unavailable"
                ) from exc

            self._delete_ingress_checkpoint(event_id)
            if self._message_row(message_id) is not None:
                self._append(
                    thread,
                    WorkMessage(
                        message_id=f"msg-{uuid.uuid4().hex[:16]}",
                        thread_id=thread.thread_id,
                        role="zn",
                        text=f"{type(exc).__name__}: {exc}",
                        detail={"failed": True},
                    ),
                )
            raise

        try:
            self._delete_ingress_checkpoint(event_id)
        except Exception:
            # Message, resident event and Work linkage are already durable. A
            # leftover checkpoint is redundant and will be removed idempotently
            # by the next ledger construction/reconciliation.
            pass
        return self._snapshot_without_finalize(thread.thread_id), event

    def submit(
        self,
        thread_id: str,
        task: str,
        *,
        kind: str = "desktop_user_event",
        priority: int = 0,
        payload: dict[str, Any] | None = None,
    ):
        current = self.resident.store.get_working_state()
        if current.current_event_id:
            raise_if_synchronous_recovery_blocked(current.current_event_id, current)

        scope = getattr(self.resident, "synchronous_recovery_control", None)
        context = scope() if callable(scope) else nullcontext()
        with context:
            return super().submit(
                thread_id,
                task,
                kind=kind,
                priority=priority,
                payload=payload,
            )
