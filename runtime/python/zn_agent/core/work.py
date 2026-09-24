from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import AgentEvent, EventStatus, ResidentRunResult, utc_now
from .path_context import canonical_host_path, resolved_within


_WORK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RESERVED_METADATA_KEYS = {"workspace"}
_ARTIFACT_CONTENT_LIMIT = 60_000
_MAX_ARTIFACTS_PER_THREAD = 96
_TERMINAL_ACTION_KINDS = {
    "command",
    "terminal",
    "shell",
    "terminal_poll",
    "command_poll",
    "terminal_stop",
    "command_stop",
    "terminal_input",
    "terminal_write",
    "command_input",
    "terminal_resize",
    "command_resize",
}


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _event_message_id(event_id: str, role: str) -> str:
    digest = hashlib.sha256(
        f"{event_id}\x00{role}".encode("utf-8", errors="replace")
    ).hexdigest()[:20]
    return f"msg-{digest}"


def _artifact_id(event_id: str, kind: str, key: str) -> str:
    digest = hashlib.sha256(
        f"{event_id}\x00{kind}\x00{key}".encode("utf-8", errors="replace")
    ).hexdigest()[:20]
    return f"artifact-{digest}"


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


@dataclass(slots=True)
class WorkArtifact:
    artifact_id: str
    thread_id: str
    event_id: str
    kind: str
    name: str
    content: str
    path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class WorkRun:
    event_id: str
    thread_id: str
    message_id: str
    task: str
    ledger_state: str = "active"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    finalized_at: str | None = None


class ResidentWorkLedger:
    """Resident-owned durable work/thread history for desktop and future faces.

    Work history, active-run linkage and contextual artifacts are durable
    interaction state, not lived-memory facts and not a separate agent. User work
    enters the same ``ZNResidentRuntime`` event loop. The resident can therefore
    continue a started work item while every desktop window is disconnected.
    """

    def __init__(self, resident):
        self.resident = resident
        self.path = Path(resident.store.path)
        self._lock = threading.RLock()
        self._response_streams: dict[str, tuple[list[str], int]] = {}
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_schema(self) -> None:
        with self._lock, closing(self._connect()) as conn:
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
                CREATE TABLE IF NOT EXISTS work_artifacts(
                    artifact_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    path TEXT,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(thread_id) REFERENCES work_threads(thread_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_work_artifacts_thread
                    ON work_artifacts(thread_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_work_artifacts_event
                    ON work_artifacts(event_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS work_runs(
                    event_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    task TEXT NOT NULL,
                    ledger_state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finalized_at TEXT,
                    FOREIGN KEY(thread_id) REFERENCES work_threads(thread_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_work_runs_thread
                    ON work_runs(thread_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_work_runs_active
                    ON work_runs(ledger_state, updated_at DESC);
                """
            )
            conn.commit()

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
    def _public_recovery(raw: Any) -> dict[str, Any] | None:
        """Project resident recovery state without exporting action arguments.

        The durable resident state may carry internal intent/signature material
        needed to reason about replay. Work is a control-plane face, so it gets a
        stable allowlist only and never raw command/text/environment authority.
        """
        if not isinstance(raw, dict):
            return None

        def text(key: str, limit: int = 128) -> str | None:
            value = raw.get(key)
            if value is None:
                return None
            normalized = " ".join(str(value).strip().split())
            return normalized[:limit] if normalized else None

        replay = raw.get("replay_blocked")
        recovery: dict[str, Any] = {
            "status": text("status", 64),
            "kind": text("kind", 64),
            "attempt_id": text("attempt_id", 128),
            "replay_blocked": replay if isinstance(replay, bool) else None,
            "verification_kind": text("verification_kind", 64),
            "decision": text("decision", 96),
            "reason": text("reason", 500),
            "verification": None,
        }

        verification = raw.get("verification")
        if isinstance(verification, dict):
            action_id = verification.get("action_id")
            success = verification.get("success")
            truncated = verification.get("truncated")
            observed_chars = verification.get("observed_chars")
            if isinstance(observed_chars, bool) or not isinstance(observed_chars, int):
                observed_chars = None
            elif observed_chars < 0:
                observed_chars = 0
            else:
                observed_chars = min(observed_chars, 10_000_000)
            recovery["verification"] = {
                "action_id": (
                    " ".join(str(action_id).strip().split())[:128]
                    if action_id is not None and str(action_id).strip()
                    else None
                ),
                "success": success if isinstance(success, bool) else None,
                "truncated": truncated if isinstance(truncated, bool) else None,
                "observed_chars": observed_chars,
            }
        return recovery

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

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> WorkArtifact:
        raw_metadata = json.loads(row["metadata_json"] or "{}")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        return WorkArtifact(
            artifact_id=str(row["artifact_id"]),
            thread_id=str(row["thread_id"]),
            event_id=str(row["event_id"]),
            kind=str(row["kind"]),
            name=str(row["name"]),
            path=str(row["path"]) if row["path"] is not None else None,
            content=str(row["content"]),
            metadata=metadata,
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> WorkRun:
        return WorkRun(
            event_id=str(row["event_id"]),
            thread_id=str(row["thread_id"]),
            message_id=str(row["message_id"]),
            task=str(row["task"]),
            ledger_state=str(row["ledger_state"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            finalized_at=str(row["finalized_at"]) if row["finalized_at"] else None,
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
        with self._lock, closing(self._connect()) as conn:
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
            conn.commit()

    def get_thread(self, thread_id: str) -> WorkThread | None:
        normalized_id = self._normalize_thread_id(thread_id)
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM work_threads WHERE thread_id=?", (normalized_id,)
            ).fetchone()
        return self._thread_from_row(row) if row else None

    def list_threads(self, *, limit: int = 24) -> list[WorkThread]:
        bounded = max(1, min(100, int(limit)))
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM work_threads ORDER BY updated_at DESC LIMIT ?", (bounded,)
            ).fetchall()
        return [self._thread_from_row(row) for row in rows]

    def list_messages(self, thread_id: str, *, limit: int = 120) -> list[WorkMessage]:
        normalized_id = self._normalize_thread_id(thread_id)
        bounded = max(1, min(500, int(limit)))
        with self._lock, closing(self._connect()) as conn:
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

    def list_artifacts(self, thread_id: str, *, limit: int = 48) -> list[WorkArtifact]:
        normalized_id = self._normalize_thread_id(thread_id)
        bounded = max(1, min(_MAX_ARTIFACTS_PER_THREAD, int(limit)))
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM work_artifacts WHERE thread_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (normalized_id, bounded),
            ).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def get_snapshot(
        self,
        thread_id: str,
        *,
        message_limit: int = 120,
    ) -> tuple[WorkThread, list[WorkMessage]]:
        normalized_id = self._normalize_thread_id(thread_id)
        self._finalize_completed_runs(thread_id=normalized_id)
        return self._snapshot_without_finalize(normalized_id, message_limit=message_limit)

    def _snapshot_without_finalize(
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
        self._finalize_completed_runs()
        return [
            self._snapshot_without_finalize(thread.thread_id, message_limit=message_limit)
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

    @staticmethod
    def _workspace_from_event(event: AgentEvent) -> WorkspaceAssociation | None:
        path = str(event.payload.get("workspace_path") or "").strip()
        if not path:
            return None
        name = str(event.payload.get("workspace_name") or "").strip()
        return WorkspaceAssociation(
            path=path,
            name=name or Path(path).name or path,
            attached_at=event.created_at,
        )

    def attach_workspace(
        self,
        thread_id: str,
        workspace_path: str | Path,
        *,
        name: str | None = None,
    ) -> WorkThread:
        thread = self.get_thread(thread_id) or self.create_thread(thread_id=thread_id)
        raw_path = str(workspace_path or "").strip()
        if not raw_path:
            raise ValueError("workspace path must not be empty")
        try:
            resolved = canonical_host_path(raw_path).resolve(strict=True)
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

    def start(
        self,
        thread_id: str,
        task: str,
        *,
        kind: str = "desktop_user_event",
        priority: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> tuple[tuple[WorkThread, list[WorkMessage]], AgentEvent]:
        normalized_task = str(task or "").strip()
        if not normalized_task:
            raise ValueError("work start requires task")

        thread = self.create_thread(thread_id=thread_id)
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
            event_payload["workspace_path"] = workspace.path
            event_payload["workdir"] = workspace.path
            event_payload["workspace_name"] = workspace.name

        try:
            event = self.resident.enqueue(
                normalized_task,
                kind=str(kind or "desktop_user_event").strip() or "desktop_user_event",
                priority=int(priority),
                payload=event_payload,
            )
            self._save_run(
                WorkRun(
                    event_id=event.event_id,
                    thread_id=thread.thread_id,
                    message_id=user_message.message_id,
                    task=normalized_task,
                )
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

        return self._snapshot_without_finalize(thread.thread_id), event

    def submit(
        self,
        thread_id: str,
        task: str,
        *,
        kind: str = "desktop_user_event",
        priority: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> tuple[tuple[WorkThread, list[WorkMessage]], ResidentRunResult]:
        _, event = self.start(
            thread_id,
            task,
            kind=kind,
            priority=priority,
            payload=payload,
        )
        while True:
            completed = self.resident.result_for(event.event_id)
            if completed is not None:
                run = completed
                break

            result = self.resident.live_once()
            if result is not None and result.event.event_id == event.event_id:
                run = result
                break

            completed = self.resident.result_for(event.event_id)
            if completed is not None:
                run = completed
                break

            persisted = self.resident.store.get_event(event.event_id)
            if persisted is not None and persisted.status in {
                EventStatus.COMPLETED,
                EventStatus.FAILED,
            }:
                raise RuntimeError(
                    "resident event reached a terminal state without a durable outcome"
                )

        self._finalize_run(event.event_id, run=run)
        return self.get_snapshot(thread_id), run

    def reset_response_stream(self, event_id: str) -> None:
        normalized_event = str(event_id or "").strip()
        if not normalized_event:
            return
        with self._lock:
            previous = self._response_streams.get(normalized_event)
            sequence = previous[1] + 1 if previous else 0
            self._response_streams[normalized_event] = ([], sequence)

    def publish_response_delta(self, event_id: str, delta: str) -> None:
        normalized_event = str(event_id or "").strip()
        text = str(delta or "")
        if not normalized_event or not text:
            return
        with self._lock:
            chunks, sequence = self._response_streams.setdefault(normalized_event, ([], 0))
            chunks.append(text)
            self._response_streams[normalized_event] = (chunks, sequence + 1)

    def progress(self, thread_id: str, event_id: str) -> dict[str, Any]:
        normalized_thread = self._normalize_thread_id(thread_id)
        normalized_event = str(event_id or "").strip()
        if not normalized_event:
            raise ValueError("work progress requires event_id")
        work_run = self.get_run(normalized_event)
        if work_run is None or work_run.thread_id != normalized_thread:
            raise ValueError("unknown work event for thread")

        completed = self.resident.result_for(normalized_event)
        if completed is not None and work_run.ledger_state != "finalized":
            self._finalize_run(normalized_event, run=completed)
            work_run = self.get_run(normalized_event) or work_run

        event = self.resident.store.get_event(normalized_event)
        if event is None:
            raise ValueError("resident work event is unavailable")
        terminal = event.status in {EventStatus.COMPLETED, EventStatus.FAILED}
        finalized = work_run.ledger_state == "finalized"
        working = self.resident.store.get_working_state()
        active = working.current_event_id == normalized_event and not terminal
        blocked_by = str(working.blocked_by or "").strip() if active else ""
        if terminal:
            stage = "complete" if event.status == EventStatus.COMPLETED else "failed"
            next_action = "complete"
        elif active:
            stage = (
                "waiting_for_user"
                if blocked_by == "user_presence_required"
                else str(working.stage or "processing")
            )
            next_action = str(working.next_action or "continue resident work")
        elif event.status == EventStatus.PENDING:
            stage = "queued"
            next_action = "await resident attention"
        else:
            stage = "processing"
            next_action = "continue resident work"

        recovery_data = None
        if active and stage == "side_effect_recovery":
            recovery_data = self._public_recovery(
                working.data.get("side_effect_recovery")
                if isinstance(working.data, dict)
                else None
            )

        thought_data: dict[str, Any] | None = None
        try:
            thought = self.resident.life.snapshot().current_thought
        except Exception:
            thought = None
        if thought is not None and thought.action_target == normalized_event:
            thought_data = {
                "at": thought.at,
                "focus": thought.focus,
                "action": thought.chosen_action,
                "action_kind": thought.action_kind,
                "reason": str(thought.reason or "")[:600],
                "confidence": thought.confidence,
            }

        investigation_data: dict[str, Any] | None = None
        try:
            investigations = self.resident.investigator.recent(16)
        except Exception:
            investigations = []
        for investigation in investigations:
            if investigation.event_id != normalized_event:
                continue
            investigation_data = {
                "rounds": investigation.rounds,
                "status": investigation.status,
                "unresolved": str(investigation.unresolved or "")[:500],
                "next_probe": str(investigation.next_probe or "")[:500],
                "evidence_count": len(investigation.evidence),
            }
            break

        body_actions: list[dict[str, Any]] = []
        body = getattr(self.resident, "body", None)
        if body is not None:
            try:
                matches = [
                    item
                    for item in reversed(body.recent_actions(120))
                    if item.event_id == normalized_event
                ][-6:]
            except Exception:
                matches = []
            for action in matches:
                summary = str(action.output or action.error or "").strip()
                summary = " ".join(summary.split())[:320]
                body_actions.append(
                    {
                        "kind": action.kind,
                        "success": action.success,
                        "at": action.completed_at,
                        "summary": summary,
                    }
                )

        result: dict[str, Any] = {
            "event_id": normalized_event,
            "thread_id": normalized_thread,
            "status": event.status.value,
            "stage": stage,
            "next_action": next_action,
            "blocked_by": blocked_by or None,
            "terminal": terminal,
            "finalized": finalized,
            "updated_at": event.updated_at,
            "recovery": recovery_data,
            "thought": thought_data,
            "investigation": investigation_data,
            "body_actions": body_actions,
        }
        if completed is not None:
            result["execution_path"] = completed.execution_path.value
            result["model_invocations"] = max(0, int(completed.model_invocations))
        if terminal and not finalized:
            result["error"] = "resident event is terminal but no durable work outcome is available"
        if active:
            with self._lock:
                streamed = self._response_streams.get(normalized_event)
                chunks = list(streamed[0]) if streamed is not None else []
                sequence = streamed[1] if streamed is not None else 0
            if chunks:
                result["assistant_response"] = "".join(chunks)
                result["response_sequence"] = sequence
        return result

    def get_run(self, event_id: str) -> WorkRun | None:
        normalized = str(event_id or "").strip()
        if not normalized:
            return None
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM work_runs WHERE event_id=?", (normalized,)
            ).fetchone()
        return self._run_from_row(row) if row else None

    def _active_run_for_thread(self, thread_id: str) -> WorkRun | None:
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT work_runs.*
                FROM work_runs
                JOIN events ON events.event_id=work_runs.event_id
                WHERE work_runs.thread_id=? AND work_runs.ledger_state='active'
                ORDER BY
                    CASE events.status
                        WHEN 'processing' THEN 0
                        WHEN 'pending' THEN 1
                        ELSE 2
                    END,
                    work_runs.created_at ASC
                LIMIT 1
                """,
                (thread_id,),
            ).fetchone()
        return self._run_from_row(row) if row else None

    def _save_run(self, run: WorkRun) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO work_runs(
                    event_id,thread_id,message_id,task,ledger_state,created_at,updated_at,finalized_at
                ) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(event_id) DO UPDATE SET
                    ledger_state=excluded.ledger_state,
                    updated_at=excluded.updated_at,
                    finalized_at=excluded.finalized_at
                """,
                (
                    run.event_id,
                    run.thread_id,
                    run.message_id,
                    run.task,
                    run.ledger_state,
                    run.created_at,
                    run.updated_at,
                    run.finalized_at,
                ),
            )
            conn.commit()

    def _finalize_completed_runs(self, *, thread_id: str | None = None) -> None:
        sql = "SELECT * FROM work_runs WHERE ledger_state='active'"
        params: list[Any] = []
        if thread_id is not None:
            sql += " AND thread_id=?"
            params.append(thread_id)
        sql += " ORDER BY created_at ASC LIMIT 64"
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()
        for row in rows:
            run = self._run_from_row(row)
            completed = self.resident.result_for(run.event_id)
            if completed is not None:
                self._finalize_run(run.event_id, run=completed)

    def _finalize_run(self, event_id: str, *, run: ResidentRunResult) -> None:
        with self._lock:
            work_run = self.get_run(event_id)
            if work_run is None:
                raise ValueError(f"unknown work run: {event_id}")
            if work_run.ledger_state == "finalized":
                return
            thread = self.get_thread(work_run.thread_id)
            if thread is None:
                raise ValueError(f"unknown work thread: {work_run.thread_id}")

            response_text = str(run.response or "").strip() or str(run.reason or "").strip()
            if not response_text:
                response_text = "Completed." if run.success else "The resident could not complete this event."
            self._append(
                thread,
                WorkMessage(
                    message_id=_event_message_id(event_id, "zn"),
                    thread_id=thread.thread_id,
                    role="zn",
                    text=response_text,
                    detail={} if run.success else {"failed": True},
                ),
            )

            workspace = self._workspace_from_event(run.event)
            new_artifacts = self._collect_artifacts(
                thread,
                run,
                task=work_run.task,
                workspace=workspace,
            )
            activity: dict[str, Any] = {
                "event_id": run.event.event_id,
                "execution_path": run.execution_path.value,
                "model_invocations": run.model_invocations,
            }
            if workspace is not None:
                activity["workspace"] = workspace.to_dict()
            if new_artifacts:
                activity["artifacts"] = [
                    {
                        "id": artifact.artifact_id,
                        "kind": artifact.kind,
                        "name": artifact.name,
                        "path": artifact.path,
                    }
                    for artifact in new_artifacts
                ]
            if run.capability_name:
                activity["capability_name"] = run.capability_name
            if run.reason:
                activity["reason"] = run.reason
            self._append(
                thread,
                WorkMessage(
                    message_id=_event_message_id(event_id, "activity"),
                    thread_id=thread.thread_id,
                    role="activity",
                    text="Resident activity",
                    detail=activity,
                ),
            )

            now = utc_now()
            work_run.ledger_state = "finalized"
            work_run.updated_at = now
            work_run.finalized_at = now
            self._save_run(work_run)
            self._response_streams.pop(event_id, None)

    def _collect_artifacts(
        self,
        thread: WorkThread,
        run: ResidentRunResult,
        *,
        task: str,
        workspace: WorkspaceAssociation | None,
    ) -> list[WorkArtifact]:
        body = getattr(self.resident, "body", None)
        if body is None:
            return []

        created: dict[str, WorkArtifact] = {}
        event_actions = [
            item
            for item in reversed(body.recent_actions(160))
            if item.event_id == run.event.event_id
        ]
        for artifact in self._collect_terminal_artifacts(
            thread,
            run.event.event_id,
            event_actions,
        ):
            created[artifact.artifact_id] = artifact

        if workspace is None:
            return list(created.values())

        for action in event_actions:
            if not action.success or action.kind not in {
                "read_text",
                "read_file",
                "write_text",
                "write_file",
            }:
                continue
            raw_path = str(action.data.get("path") or "").strip()
            if not raw_path:
                continue
            resolved = resolved_within(workspace.path, raw_path)
            if resolved is None or not resolved.is_file():
                continue

            relative = resolved.relative_to(Path(workspace.path).resolve()).as_posix()
            content = action.output
            truncated = bool(action.data.get("truncated", False))
            chars = int(action.data.get("chars") or len(content))
            mode = "read"
            source_action_id = action.action_id
            if action.kind in {"write_text", "write_file"}:
                observed = body.act(
                    "read_text",
                    event_id=run.event.event_id,
                    path=str(resolved),
                    max_chars=_ARTIFACT_CONTENT_LIMIT,
                )
                if not observed.success:
                    continue
                content = observed.output
                truncated = bool(observed.data.get("truncated", False))
                chars = int(observed.data.get("chars") or len(content))
                mode = "write"
                source_action_id = observed.action_id

            artifact = WorkArtifact(
                artifact_id=_artifact_id(run.event.event_id, "file", str(resolved)),
                thread_id=thread.thread_id,
                event_id=run.event.event_id,
                kind="file",
                name=relative,
                path=str(resolved),
                content=content[:_ARTIFACT_CONTENT_LIMIT],
                metadata={
                    "workspace_relative_path": relative,
                    "mode": mode,
                    "chars": chars,
                    "truncated": truncated or len(content) > _ARTIFACT_CONTENT_LIMIT,
                    "source_action_id": source_action_id,
                },
            )
            self._save_artifact(artifact)
            created[artifact.artifact_id] = artifact

        if self._workspace_context_relevant(task, event_actions):
            for artifact in self._collect_workspace_git_context(
                thread,
                run.event.event_id,
                workspace,
                body,
            ):
                created[artifact.artifact_id] = artifact
        return list(created.values())

    def _collect_terminal_artifacts(
        self,
        thread: WorkThread,
        event_id: str,
        event_actions: list[Any],
    ) -> list[WorkArtifact]:
        created: list[WorkArtifact] = []
        for action in event_actions:
            if action.kind not in _TERMINAL_ACTION_KINDS:
                continue
            data = action.data if isinstance(action.data, dict) else {}
            command = str(data.get("command") or "").strip()
            status = str(data.get("status") or ("completed" if action.success else "failed")).strip()
            error = str(action.error or data.get("error") or "").strip()
            parts: list[str] = []
            if command:
                parts.append(f"$ {command}")
            if action.output:
                parts.append(action.output.rstrip())
            if error and error not in action.output:
                parts.append(f"[error] {error}")
            if not parts:
                parts.append(f"[{status or 'terminal'}]")
            content = "\n".join(parts)
            name_command = command if command else action.kind.replace("_", " ")
            name = f"Terminal · {name_command[:72]}"
            artifact = WorkArtifact(
                artifact_id=_artifact_id(event_id, "terminal", action.action_id),
                thread_id=thread.thread_id,
                event_id=event_id,
                kind="terminal",
                name=name,
                content=content[:_ARTIFACT_CONTENT_LIMIT],
                metadata={
                    "operation": action.kind,
                    "status": status,
                    "success": bool(action.success),
                    "command": command,
                    "cwd": data.get("cwd"),
                    "exit_code": data.get("exit_code"),
                    "pid": data.get("pid"),
                    "session_id": data.get("session_id"),
                    "timed_out": bool(data.get("timed_out", False)),
                    "truncated": bool(data.get("truncated", False))
                    or len(content) > _ARTIFACT_CONTENT_LIMIT,
                    "source_action_id": action.action_id,
                },
            )
            self._save_artifact(artifact)
            created.append(artifact)
        return created

    @staticmethod
    def _workspace_context_relevant(task: str, event_actions: list[Any]) -> bool:
        if any(
            action.kind in {"read_text", "read_file", "write_text", "write_file", "git_state", "git"}
            for action in event_actions
        ):
            return True
        text = str(task or "").lower()
        return any(
            token in text
            for token in (
                "file", "code", "git", "diff", "change", "changed", "workspace",
                "project", "repo", "read", "write", "create", "modify", "patch",
                "文件", "代码", "差异", "修改", "工作区", "项目", "仓库", "读取", "写",
            )
        )

    def _collect_workspace_git_context(
        self,
        thread: WorkThread,
        event_id: str,
        workspace: WorkspaceAssociation,
        body,
    ) -> list[WorkArtifact]:
        git = body.act(
            "git_state",
            event_id=event_id,
            path=workspace.path,
            timeout=8,
        )
        if not git.success or not bool(git.data.get("dirty")):
            return []

        created: list[WorkArtifact] = []
        seen_paths: set[str] = set()
        for raw_relative in list(git.data.get("changed_paths") or ())[:12]:
            relative = str(raw_relative or "").strip()
            if not relative or relative in seen_paths:
                continue
            seen_paths.add(relative)
            candidate = resolved_within(workspace.path, Path(workspace.path) / relative)
            if candidate is None or not candidate.is_file():
                continue
            observed = body.act(
                "read_text",
                event_id=event_id,
                path=str(candidate),
                max_chars=_ARTIFACT_CONTENT_LIMIT,
            )
            if not observed.success:
                continue
            artifact = WorkArtifact(
                artifact_id=_artifact_id(event_id, "file", str(candidate)),
                thread_id=thread.thread_id,
                event_id=event_id,
                kind="file",
                name=relative,
                path=str(candidate),
                content=observed.output[:_ARTIFACT_CONTENT_LIMIT],
                metadata={
                    "workspace_relative_path": relative,
                    "mode": "workspace_change",
                    "chars": int(observed.data.get("chars") or len(observed.output)),
                    "truncated": bool(observed.data.get("truncated", False))
                    or len(observed.output) > _ARTIFACT_CONTENT_LIMIT,
                    "source_action_id": observed.action_id,
                },
            )
            self._save_artifact(artifact)
            created.append(artifact)
            if len(created) >= 4:
                break

        diff = body.act(
            "git_diff",
            event_id=event_id,
            path=workspace.path,
            timeout=10,
            max_output_chars=_ARTIFACT_CONTENT_LIMIT,
        )
        if not diff.success:
            return created

        diff_parts: list[str] = []
        truncated = bool(diff.data.get("truncated", False))
        for label, key in (("Working tree", "worktree"), ("Staged", "staged")):
            scope = diff.data.get(key) if isinstance(diff.data.get(key), dict) else {}
            patch = str(scope.get("patch") or "")
            if patch.strip():
                diff_parts.append(f"## {label}\n{patch.rstrip()}")
            truncated = truncated or bool(scope.get("truncated", False))
        diff_content = "\n\n".join(diff_parts)
        if diff_content:
            artifact = WorkArtifact(
                artifact_id=_artifact_id(event_id, "diff", workspace.path),
                thread_id=thread.thread_id,
                event_id=event_id,
                kind="diff",
                name="Current workspace diff",
                path=workspace.path,
                content=diff_content[:_ARTIFACT_CONTENT_LIMIT],
                metadata={
                    "workspace": workspace.to_dict(),
                    "scope": "current_workspace_after_event",
                    "source": "git_diff",
                    "source_action_id": diff.action_id,
                    "state_sha256": diff.data.get("state_sha256"),
                    "head": diff.data.get("head"),
                    "truncated": truncated or len(diff_content) > _ARTIFACT_CONTENT_LIMIT,
                },
            )
            self._save_artifact(artifact)
            created.append(artifact)
        return created

    def _save_artifact(self, artifact: WorkArtifact) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO work_artifacts(
                    artifact_id,thread_id,event_id,kind,name,path,content,metadata_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    event_id=excluded.event_id,
                    kind=excluded.kind,
                    name=excluded.name,
                    path=excluded.path,
                    content=excluded.content,
                    metadata_json=excluded.metadata_json,
                    created_at=excluded.created_at
                """,
                (
                    artifact.artifact_id,
                    artifact.thread_id,
                    artifact.event_id,
                    artifact.kind,
                    artifact.name,
                    artifact.path,
                    artifact.content,
                    json.dumps(artifact.metadata, ensure_ascii=False, separators=(",", ":")),
                    artifact.created_at,
                ),
            )
            conn.execute(
                "DELETE FROM work_artifacts WHERE artifact_id IN ("
                "SELECT artifact_id FROM work_artifacts WHERE thread_id=? "
                "ORDER BY created_at DESC LIMIT -1 OFFSET ?) ",
                (artifact.thread_id, _MAX_ARTIFACTS_PER_THREAD),
            )
            conn.commit()

    def _append(self, thread: WorkThread, message: WorkMessage) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO work_messages(
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
            conn.commit()
        thread.updated_at = message.created_at
        self._save_thread(thread)
