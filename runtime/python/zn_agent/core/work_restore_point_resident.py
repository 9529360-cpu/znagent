from __future__ import annotations

"""Resident-owned exact-file restore-point foundation for Work overwrites.

This layer captures restorable pre-mutation bytes only for a real durable Work
run and only while an exact overwrite is still before Body dispatch. A retained
restore point is evidence/content ownership, not rollback authority: nothing in
this module writes the captured bytes back to the target.
"""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .action import NativeActionIntent
from .atomic_overwrite_namespace_recovery_resident import (
    AtomicOverwriteNamespaceRecoveryResidentRuntime,
)
from .file_identity import (
    DEFAULT_MAX_HASH_BYTES,
    compare_file_identities,
    observe_file_identity,
)
from .models import utc_now


_TABLE = "work_restore_points"
_VERSION = 1
_MAX_CONTENT_BYTES = DEFAULT_MAX_HASH_BYTES
_MAX_POINTS_PER_EVENT = 32
_MAX_FINALIZED_POINTS = 96


class _RestoreCaptureChanged(RuntimeError):
    pass


class WorkRestorePointResidentRuntime(AtomicOverwriteNamespaceRecoveryResidentRuntime):
    """Retain exact pre-mutation file content for durable Work-owned overwrites.

    The record is bound to the ordinary ``work_runs`` identity (event, thread and
    accepted user message), the exact resident intent/signature and the canonical
    pre-mutation file identity. Existing behavior is intentionally unchanged for
    non-Work events, missing targets, non-regular files and files whose exact
    identity is outside the current bounded hash/capture limit.

    Retained content survives resident reconstruction. It is never interpreted
    as permission to restore automatically; actual rollback remains a separate,
    future user-visible authority boundary.
    """

    _WORK_RESTORE_STATE_KEY = "work_restore_point"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._init_work_restore_schema()

    def _restore_connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_work_restore_schema(self) -> None:
        with closing(self._restore_connect()) as conn:
            conn.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {_TABLE}(
                    restore_point_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    intent_id TEXT NOT NULL,
                    action_signature TEXT NOT NULL,
                    target_path TEXT NOT NULL,
                    pre_identity_json TEXT NOT NULL,
                    content BLOB NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(event_id, action_signature, target_path)
                );
                CREATE INDEX IF NOT EXISTS idx_work_restore_event
                    ON {_TABLE}(event_id, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_work_restore_thread
                    ON {_TABLE}(thread_id, created_at DESC);
                """
            )
            conn.commit()

    @staticmethod
    def _capturable_identity(identity: Any) -> bool:
        if not isinstance(identity, dict):
            return False
        size = identity.get("size_bytes")
        digest = str(identity.get("content_sha256") or "")
        return bool(
            identity.get("observable") is True
            and identity.get("stable") is True
            and identity.get("exists") is True
            and str(identity.get("type") or "") == "file"
            and identity.get("digest_complete") is True
            and isinstance(size, int)
            and not isinstance(size, bool)
            and 0 <= size <= _MAX_CONTENT_BYTES
            and len(digest) == 64
            and all(char in "0123456789abcdef" for char in digest)
            and str(identity.get("path") or "").strip()
        )

    @staticmethod
    def _restore_point_id(
        *, event_id: str, action_signature: str, target_path: str
    ) -> str:
        digest = hashlib.sha256(
            f"{event_id}\0{action_signature}\0{target_path}".encode(
                "utf-8", errors="replace"
            )
        ).hexdigest()[:24]
        return f"restore-{digest}"

    @staticmethod
    def _work_ids(event) -> tuple[str, str] | None:
        payload = event.payload if isinstance(event.payload, dict) else {}
        thread_id = str(payload.get("work_thread_id") or "").strip()
        message_id = str(payload.get("work_message_id") or "").strip()
        if not thread_id and not message_id:
            return None
        if not thread_id or not message_id:
            raise RuntimeError("Work restore ownership has incomplete event linkage")
        return thread_id, message_id

    def _verified_work_linkage(
        self,
        conn: sqlite3.Connection,
        event,
    ) -> tuple[str, str] | None:
        work_ids = self._work_ids(event)
        if work_ids is None:
            return None
        thread_id, message_id = work_ids
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='work_runs'"
        ).fetchone()
        if table is None:
            raise RuntimeError("Work restore ownership requires the durable Work ledger")
        row = conn.execute(
            "SELECT event_id,thread_id,message_id,task FROM work_runs WHERE event_id=?",
            (event.event_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Work restore ownership cannot find its durable Work run")
        if (
            str(row["event_id"]) != event.event_id
            or str(row["thread_id"]) != thread_id
            or str(row["message_id"]) != message_id
            or str(row["task"]) != event.task
        ):
            raise RuntimeError("Work restore ownership conflicts with durable Work linkage")
        return thread_id, message_id

    @staticmethod
    def _row_public(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "restore_point_id": str(row["restore_point_id"]),
            "version": int(row["version"]),
            "event_id": str(row["event_id"]),
            "thread_id": str(row["thread_id"]),
            "message_id": str(row["message_id"]),
            "intent_id": str(row["intent_id"]),
            "action_signature": str(row["action_signature"]),
            "target_path": str(row["target_path"]),
            "content_sha256": str(row["content_sha256"]),
            "size_bytes": int(row["size_bytes"]),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def _verify_existing_restore_point(
        self,
        row: sqlite3.Row,
        *,
        event,
        thread_id: str,
        message_id: str,
        intent: NativeActionIntent,
        action_signature: str,
        identity: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            stored_identity = json.loads(row["pre_identity_json"] or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError("durable Work restore identity is malformed") from exc
        expected = {
            "version": _VERSION,
            "event_id": event.event_id,
            "thread_id": thread_id,
            "message_id": message_id,
            "intent_id": intent.intent_id,
            "action_signature": action_signature,
            "target_path": str(identity.get("path") or ""),
            "content_sha256": str(identity.get("content_sha256") or ""),
            "size_bytes": int(identity.get("size_bytes") or 0),
            "status": "retained",
        }
        for key, value in expected.items():
            if row[key] != value:
                raise RuntimeError(f"durable Work restore point conflicts on {key}")
        if stored_identity != identity:
            raise RuntimeError("durable Work restore point conflicts with pre-mutation identity")
        content = bytes(row["content"])
        if len(content) != expected["size_bytes"]:
            raise RuntimeError("durable Work restore content size is inconsistent")
        if hashlib.sha256(content).hexdigest() != expected["content_sha256"]:
            raise RuntimeError("durable Work restore content digest is inconsistent")
        return self._row_public(row)

    def _prune_finalized_restore_points(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            f"""
            DELETE FROM {_TABLE}
            WHERE restore_point_id IN (
                SELECT rp.restore_point_id
                FROM {_TABLE} AS rp
                JOIN work_runs AS wr ON wr.event_id=rp.event_id
                WHERE wr.ledger_state='finalized'
                ORDER BY rp.created_at DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (_MAX_FINALIZED_POINTS,),
        )

    def _capture_work_restore_point(
        self,
        event,
        intent: NativeActionIntent,
        identity: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not self._capturable_identity(identity):
            return None
        action_signature = self._intent_signature(intent)
        target_path = str(identity.get("path") or "")
        restore_point_id = self._restore_point_id(
            event_id=event.event_id,
            action_signature=action_signature,
            target_path=target_path,
        )

        with closing(self._restore_connect()) as conn:
            work_linkage = self._verified_work_linkage(conn, event)
            if work_linkage is None:
                return None
            thread_id, message_id = work_linkage
            existing = conn.execute(
                f"SELECT * FROM {_TABLE} WHERE restore_point_id=?",
                (restore_point_id,),
            ).fetchone()
            if existing is not None:
                return self._verify_existing_restore_point(
                    existing,
                    event=event,
                    thread_id=thread_id,
                    message_id=message_id,
                    intent=intent,
                    action_signature=action_signature,
                    identity=identity,
                )
            count_row = conn.execute(
                f"SELECT COUNT(*) AS n FROM {_TABLE} WHERE event_id=?",
                (event.event_id,),
            ).fetchone()
            if int(count_row["n"] if count_row is not None else 0) >= _MAX_POINTS_PER_EVENT:
                return None

        path = Path(target_path)
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise _RestoreCaptureChanged(
                f"could not retain exact pre-mutation file content: {type(exc).__name__}"
            ) from exc
        expected_size = int(identity["size_bytes"])
        expected_digest = str(identity["content_sha256"])
        if len(content) != expected_size or hashlib.sha256(content).hexdigest() != expected_digest:
            raise _RestoreCaptureChanged(
                "file changed while ZN was retaining its pre-mutation restore content"
            )
        current = observe_file_identity(path, max_hash_bytes=_MAX_CONTENT_BYTES)
        comparison = compare_file_identities(identity, current)
        if comparison.get("exact") is not True:
            raise _RestoreCaptureChanged(
                "file identity changed while ZN was retaining its pre-mutation restore content"
            )

        now = utc_now()
        with closing(self._restore_connect()) as conn:
            work_linkage = self._verified_work_linkage(conn, event)
            if work_linkage is None:
                return None
            thread_id, message_id = work_linkage
            conn.execute(
                f"""
                INSERT OR IGNORE INTO {_TABLE}(
                    restore_point_id,version,event_id,thread_id,message_id,intent_id,
                    action_signature,target_path,pre_identity_json,content,content_sha256,
                    size_bytes,status,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    restore_point_id,
                    _VERSION,
                    event.event_id,
                    thread_id,
                    message_id,
                    intent.intent_id,
                    action_signature,
                    target_path,
                    json.dumps(identity, ensure_ascii=False, separators=(",", ":")),
                    sqlite3.Binary(content),
                    expected_digest,
                    expected_size,
                    "retained",
                    now,
                    now,
                ),
            )
            row = conn.execute(
                f"SELECT * FROM {_TABLE} WHERE restore_point_id=?",
                (restore_point_id,),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise RuntimeError("durable Work restore point was not persisted")
            public = self._verify_existing_restore_point(
                row,
                event=event,
                thread_id=thread_id,
                message_id=message_id,
                intent=intent,
                action_signature=action_signature,
                identity=identity,
            )
            self._prune_finalized_restore_points(conn)
            conn.commit()
            return public

    def retained_work_restore_points(self, event_id: str) -> list[dict[str, Any]]:
        normalized = str(event_id or "").strip()
        if not normalized:
            return []
        with closing(self._restore_connect()) as conn:
            rows = conn.execute(
                f"SELECT * FROM {_TABLE} WHERE event_id=? ORDER BY created_at ASC",
                (normalized,),
            ).fetchall()
        return [self._row_public(row) for row in rows]

    def _hold_restore_capture(
        self,
        event,
        state,
        intent: NativeActionIntent,
        exc: _RestoreCaptureChanged,
        *,
        thought=None,
    ) -> bool:
        failure = (
            "Work restore-point capture lost exact pre-mutation file reality; "
            "ZN will refresh Investigation before allowing the overwrite"
        )
        state.data["local_failure"] = failure
        state.data["work_restore_point_capture"] = {
            "status": "identity_changed",
            "reason": str(exc)[:240],
        }
        self._record_failed_action(
            event,
            state,
            intent,
            source="precondition",
            failure=failure,
        )
        state.stage = "native_investigation"
        state.next_action = "refresh exact file evidence before another overwrite"
        state.blocked_by = None
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        if thought is not None:
            if failure not in thought.unknown:
                thought.unknown = (*thought.unknown, failure)
            thought.reason = (
                f"{thought.reason}; the Work restore checkpoint could not be bound to "
                "stable current file reality, so mutation authority was withdrawn"
            )
            self._persist_enriched_thought(thought)
        return False

    def _prepare_overwrite_prestate(
        self,
        event,
        state,
        intent: NativeActionIntent,
        *,
        thought=None,
    ) -> bool:
        if not super()._prepare_overwrite_prestate(
            event,
            state,
            intent,
            thought=thought,
        ):
            return False
        raw = state.data.get(self._OVERWRITE_PRESTATE_KEY)
        identity = (
            raw.get("identity")
            if isinstance(raw, dict)
            and str(raw.get("intent_id") or "") == intent.intent_id
            and str(raw.get("action_signature") or "") == self._intent_signature(intent)
            else None
        )
        if not isinstance(identity, dict):
            return True
        try:
            restore_point = self._capture_work_restore_point(event, intent, identity)
        except _RestoreCaptureChanged as exc:
            return self._hold_restore_capture(
                event,
                state,
                intent,
                exc,
                thought=thought,
            )
        if restore_point is None:
            return True
        state.data[self._WORK_RESTORE_STATE_KEY] = {
            "restore_point_id": restore_point["restore_point_id"],
            "event_id": restore_point["event_id"],
            "intent_id": restore_point["intent_id"],
            "target_path": restore_point["target_path"],
            "content_sha256": restore_point["content_sha256"],
            "size_bytes": restore_point["size_bytes"],
            "status": restore_point["status"],
            "automatic_restore_authority": False,
        }
        state.data.pop("work_restore_point_capture", None)
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return True
