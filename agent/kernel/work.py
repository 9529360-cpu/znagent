from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import ResidentRunResult, utc_now


_WORK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def title_for_work_task(task: str) -> str:
    normalized = " ".join(str(task or "").strip().split())
    if not normalized:
        return "New work"
    return normalized if len(normalized) <= 48 else f"{normalized[:47].rstrip()}…"


@dataclass(slots=True)
class WorkThread:
    thread_id: str
    title: str = "New work"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class WorkMessage:
    message_id: str
    thread_id: str
    role: str
    text: str
    detail: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)


class ResidentWorkLedger:
    """Resident-owned durable work/thread history for desktop and future faces.

    Work history is durable interaction state, not lived-memory facts and not a
    separate agent. User work still enters the same ``ZNResidentRuntime`` event
    loop; this ledger only owns thread/message continuity around those events.
    """

    def __init__(self, resident):
        self.resident = resident
        self.path = Path(resident.store.path)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS work_threads(
                    thread_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_work_threads_recent
                    ON work_threads(updated_at DESC);
                CREATE TABLE IF NOT EXISTS work_messages(
                    message_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(thread_id) REFERENCES work_threads(thread_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_work_messages_thread
                    ON work_messages(thread_id, created_at ASC);
                """
            )

    @staticmethod
    def _normalize_thread_id(value: str | None) -> str:
        candidate = str(value or "").strip()
        if not candidate:
            return _id("work")
        if not _WORK_ID_RE.fullmatch(candidate):
            raise ValueError("invalid work thread id")
        return candidate

    @staticmethod
    def _thread_from_row(row: sqlite3.Row) -> WorkThread:
        return WorkThread(
            thread_id=str(row["thread_id"]),
            title=str(row["title"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> WorkMessage:
        return WorkMessage(
            message_id=str(row["message_id"]),
            thread_id=str(row["thread_id"]),
            role=str(row["role"]),
            text=str(row["text"]),
            detail=json.loads(row["detail_json"] or "{}"),
            created_at=str(row["created_at"]),
        )

    def create_thread(
        self,
        *,
        title: str = "New work",
        metadata: dict[str, Any] | None = None,
        thread_id: str | None = None,
    ) -> WorkThread:
        normalized_id = self._normalize_thread_id(thread_id)
        existing = self.get_thread(normalized_id)
        if existing is not None:
            return existing
        now = utc_now()
        normalized_title = " ".join(str(title or "").strip().split()) or "New work"
        thread = WorkThread(
            thread_id=normalized_id,
            title=normalized_title[:120],
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )
        self._save_thread(thread)
        return thread

    def _save_thread(self, thread: WorkThread) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO work_threads(
                    thread_id,title,metadata_json,created_at,updated_at
                ) VALUES(?,?,?,?,?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    title=excluded.title,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    thread.thread_id,
                    thread.title,
                    json.dumps(thread.metadata, ensure_ascii=False, separators=(",", ":")),
                    thread.created_at,
                    thread.updated_at,
                ),
            )

    def get_thread(self, thread_id: str) -> WorkThread | None:
        normalized_id = self._normalize_thread_id(thread_id)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM work_threads WHERE thread_id=?", (normalized_id,)
            ).fetchone()
        return self._thread_from_row(row) if row else None

    def list_threads(self, *, limit: int = 24) -> list[WorkThread]:
        bounded = max(1, min(100, int(limit)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM work_threads ORDER BY updated_at DESC LIMIT ?", (bounded,)
            ).fetchall()
        return [self._thread_from_row(row) for row in rows]

    def list_messages(self, thread_id: str, *, limit: int = 120) -> list[WorkMessage]:
        normalized_id = self._normalize_thread_id(thread_id)
        bounded = max(1, min(500, int(limit)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM (
                    SELECT * FROM work_messages
                    WHERE thread_id=?
                    ORDER BY created_at DESC
                    LIMIT ?
                ) ORDER BY created_at ASC
                """,
                (normalized_id, bounded),
            ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def get_snapshot(
        self,
        thread_id: str,
        *,
        message_limit: int = 120,
    ) -> tuple[WorkThread, list[WorkMessage]]:
        thread = self.get_thread(thread_id)
        if thread is None:
            raise ValueError(f"unknown work thread: {thread_id}")
        return thread, self.list_messages(thread.thread_id, limit=message_limit)

    def list_snapshots(
        self,
        *,
        thread_limit: int = 24,
        message_limit: int = 120,
    ) -> list[tuple[WorkThread, list[WorkMessage]]]:
        return [
            (thread, self.list_messages(thread.thread_id, limit=message_limit))
            for thread in self.list_threads(limit=thread_limit)
        ]

    def submit(
        self,
        thread_id: str,
        task: str,
        *,
        kind: str = "desktop_user_event",
        priority: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> tuple[tuple[WorkThread, list[WorkMessage]], ResidentRunResult]:
        normalized_task = str(task or "").strip()
        if not normalized_task:
            raise ValueError("work submit requires task")

        thread = self.create_thread(thread_id=thread_id)
        if not self.list_messages(thread.thread_id, limit=1) and thread.title == "New work":
            thread.title = title_for_work_task(normalized_task)
            thread.updated_at = utc_now()
            self._save_thread(thread)

        user_message = WorkMessage(
            message_id=_id("msg"),
            thread_id=thread.thread_id,
            role="user",
            text=normalized_task,
        )
        self._append(thread, user_message)

        event_payload = dict(payload or {})
        event_payload["work_thread_id"] = thread.thread_id
        event_payload["work_message_id"] = user_message.message_id

        try:
            run = self.resident.submit(
                normalized_task,
                kind=str(kind or "desktop_user_event").strip() or "desktop_user_event",
                priority=int(priority),
                payload=event_payload,
            )
        except Exception as exc:
            self._append(
                thread,
                WorkMessage(
                    message_id=_id("msg"),
                    thread_id=thread.thread_id,
                    role="zn",
                    text=f"{type(exc).__name__}: {exc}",
                    detail={"failed": True},
                ),
            )
            raise

        response_text = str(run.response or "").strip() or str(run.reason or "").strip()
        if not response_text:
            response_text = "Completed." if run.success else "The resident could not complete this event."
        self._append(
            thread,
            WorkMessage(
                message_id=_id("msg"),
                thread_id=thread.thread_id,
                role="zn",
                text=response_text,
                detail={} if run.success else {"failed": True},
            ),
        )

        activity: dict[str, Any] = {
            "event_id": run.event.event_id,
            "execution_path": run.execution_path.value,
            "model_invocations": run.model_invocations,
        }
        if run.capability_name:
            activity["capability_name"] = run.capability_name
        if run.reason:
            activity["reason"] = run.reason
        self._append(
            thread,
            WorkMessage(
                message_id=_id("msg"),
                thread_id=thread.thread_id,
                role="activity",
                text="Resident activity",
                detail=activity,
            ),
        )
        return self.get_snapshot(thread.thread_id), run

    def _append(self, thread: WorkThread, message: WorkMessage) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO work_messages(
                    message_id,thread_id,role,text,detail_json,created_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    message.message_id,
                    message.thread_id,
                    message.role,
                    message.text,
                    json.dumps(message.detail, ensure_ascii=False, separators=(",", ":")),
                    message.created_at,
                ),
            )
        thread.updated_at = message.created_at
        self._save_thread(thread)
