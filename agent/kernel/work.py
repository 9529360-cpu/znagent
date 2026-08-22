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
_RESERVED_METADATA_KEYS = {"workspace"}


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def title_for_work_task(task: str) -> str:
    normalized = " ".join(str(task or "").strip().split())
    if not normalized:
        return "New work"
    return normalized if len(normalized) <= 48 else f"{normalized[:47].rstrip()}…"


@dataclass(slots=True)
class WorkspaceAssociation:
    path: str
    name: str
    attached_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "name": self.name,
            "attached_at": self.attached_at,
        }


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
    loop; this ledger owns thread/message continuity and the durable local
    workspace associated with that work.
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
    def _public_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
        values = dict(metadata or {})
        for key in _RESERVED_METADATA_KEYS:
            values.pop(key, None)
        return values

    @staticmethod
    def _thread_from_row(row: sqlite3.Row) -> WorkThread:
        raw_metadata = json.loads(row["metadata_json"] or "{}")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        return WorkThread(
            thread_id=str(row["thread_id"]),
            title=str(row["title"]),
            metadata=metadata,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> WorkMessage:
        raw_detail = json.loads(row["detail_json"] or "{}")
        detail = raw_detail if isinstance(raw_detail, dict) else {}
        return WorkMessage(
            message_id=str(row["message_id"]),
            thread_id=str(row["thread_id"]),
            role=str(row["role"]),
            text=str(row["text"]),
            detail=detail,
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
            metadata=self._public_metadata(metadata),
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

    def workspace_for(self, thread: WorkThread) -> WorkspaceAssociation | None:
        raw = thread.metadata.get("workspace")
        if not isinstance(raw, dict):
            return None
        path = str(raw.get("path") or "").strip()
        if not path:
            return None
        name = " ".join(str(raw.get("name") or "").strip().split())
        attached_at = str(raw.get("attached_at") or "").strip() or thread.updated_at
        return WorkspaceAssociation(
            path=path,
            name=name or Path(path).name or path,
            attached_at=attached_at,
        )

    def attach_workspace(
        self,
        thread_id: str,
        workspace_path: str | Path,
        *,
        name: str | None = None,
    ) -> WorkThread:
        # A fresh desktop may display its first empty work before any message has
        # caused that thread to enter the resident ledger. Attaching a folder is
        # itself enough to make that work durable.
        thread = self.get_thread(thread_id) or self.create_thread(thread_id=thread_id)
        raw_path = str(workspace_path or "").strip()
        if not raw_path:
            raise ValueError("workspace path must not be empty")
        try:
            resolved = Path(raw_path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"workspace path is unavailable: {raw_path}") from exc
        if not resolved.is_dir():
            raise ValueError(f"workspace path is not a directory: {resolved}")

        normalized_name = " ".join(str(name or "").strip().split())
        workspace = WorkspaceAssociation(
            path=str(resolved),
            name=(normalized_name or resolved.name or str(resolved))[:120],
        )
        metadata = dict(thread.metadata)
        metadata["workspace"] = workspace.to_dict()
        thread.metadata = metadata
        thread.updated_at = workspace.attached_at
        self._save_thread(thread)
        return thread

    def detach_workspace(self, thread_id: str) -> WorkThread:
        thread = self.get_thread(thread_id)
        if thread is None:
            raise ValueError(f"unknown work thread: {thread_id}")
        metadata = dict(thread.metadata)
        metadata.pop("workspace", None)
        thread.metadata = metadata
        thread.updated_at = utc_now()
        self._save_thread(thread)
        return thread

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
        workspace = self.workspace_for(thread)
        if workspace is not None:
            # The durable work association, not transient renderer state, anchors
            # repository investigation and local command execution for this thread.
            event_payload["workspace_path"] = workspace.path
            event_payload["workdir"] = workspace.path
            event_payload["workspace_name"] = workspace.name

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
        if workspace is not None:
            activity["workspace"] = workspace.to_dict()
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
