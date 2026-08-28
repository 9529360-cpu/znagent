from __future__ import annotations

"""Durable protocol ledger for Windows staged overwrite namespace commits."""

import json
import sqlite3
from typing import Any

from .models import utc_now

TABLE = "resident_atomic_overwrite_protocols"
PROTOCOL_VERSION = 1


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE}(
            event_id TEXT NOT NULL,
            signature_hash TEXT NOT NULL,
            version INTEGER NOT NULL,
            intent_id TEXT NOT NULL,
            attempt_id TEXT,
            staging_path TEXT NOT NULL,
            backup_path TEXT NOT NULL,
            stage_ready INTEGER NOT NULL DEFAULT 0,
            stage_identity_json TEXT,
            namespace_commit_started INTEGER NOT NULL DEFAULT 0,
            write_strategy TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(event_id, signature_hash)
        );
        """
    )


def protocol(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    signature_hash: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT * FROM {TABLE} WHERE event_id=? AND signature_hash=?",
        (event_id, signature_hash),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    raw_identity = result.pop("stage_identity_json", None)
    result["stage_identity"] = json.loads(raw_identity) if raw_identity else None
    result["stage_ready"] = bool(result.get("stage_ready"))
    result["namespace_commit_started"] = bool(
        result.get("namespace_commit_started")
    )
    return result


def prepare_protocol(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    signature_hash: str,
    intent_id: str,
    staging_path: str,
    backup_path: str,
) -> dict[str, Any]:
    existing = protocol(conn, event_id=event_id, signature_hash=signature_hash)
    if existing is not None:
        if (
            int(existing.get("version") or 0) != PROTOCOL_VERSION
            or str(existing.get("intent_id") or "") != intent_id
            or str(existing.get("staging_path") or "") != staging_path
            or str(existing.get("backup_path") or "") != backup_path
        ):
            raise RuntimeError("conflicting durable atomic overwrite protocol already exists")
        return existing
    conn.execute(
        f"INSERT INTO {TABLE}(event_id,signature_hash,version,intent_id,attempt_id,"
        "staging_path,backup_path,stage_ready,stage_identity_json,"
        "namespace_commit_started,write_strategy,updated_at) "
        "VALUES(?,?,?,?,NULL,?,?,0,NULL,0,NULL,?)",
        (
            event_id,
            signature_hash,
            PROTOCOL_VERSION,
            intent_id,
            staging_path,
            backup_path,
            utc_now(),
        ),
    )
    return protocol(conn, event_id=event_id, signature_hash=signature_hash) or {}


def record_stage_ready(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    signature_hash: str,
    intent_id: str,
    attempt_id: str,
    staging_path: str,
    stage_identity: dict[str, Any],
) -> None:
    current = protocol(conn, event_id=event_id, signature_hash=signature_hash)
    if current is None:
        raise RuntimeError("atomic overwrite stage has no durable protocol")
    if (
        int(current.get("version") or 0) != PROTOCOL_VERSION
        or str(current.get("intent_id") or "") != intent_id
        or str(current.get("staging_path") or "") != staging_path
        or current.get("namespace_commit_started") is True
    ):
        raise RuntimeError("atomic overwrite stage does not match durable protocol")
    prior_attempt = str(current.get("attempt_id") or "")
    if prior_attempt and prior_attempt != attempt_id:
        raise RuntimeError("atomic overwrite protocol belongs to another side-effect attempt")
    conn.execute(
        f"UPDATE {TABLE} SET attempt_id=?,stage_ready=1,stage_identity_json=?,updated_at=? "
        "WHERE event_id=? AND signature_hash=?",
        (
            attempt_id,
            json.dumps(stage_identity, ensure_ascii=False, separators=(",", ":")),
            utc_now(),
            event_id,
            signature_hash,
        ),
    )


def record_commit_started(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    signature_hash: str,
    intent_id: str,
    attempt_id: str,
    staging_path: str,
    backup_path: str | None,
    strategy: str,
) -> None:
    current = protocol(conn, event_id=event_id, signature_hash=signature_hash)
    if current is None:
        raise RuntimeError("atomic overwrite commit has no durable protocol")
    if (
        int(current.get("version") or 0) != PROTOCOL_VERSION
        or str(current.get("intent_id") or "") != intent_id
        or str(current.get("attempt_id") or "") != attempt_id
        or current.get("stage_ready") is not True
        or not isinstance(current.get("stage_identity"), dict)
        or str(current.get("staging_path") or "") != staging_path
        or current.get("namespace_commit_started") is True
    ):
        raise RuntimeError("atomic overwrite commit does not match durable staged protocol")
    expected_backup = str(current.get("backup_path") or "")
    actual_backup = str(backup_path or "")
    if strategy == "replace_file_with_backup":
        if not actual_backup or actual_backup != expected_backup:
            raise RuntimeError("atomic overwrite backup path changed before commit")
    elif strategy == "move_new_no_replace":
        if actual_backup:
            raise RuntimeError("atomic create unexpectedly supplied a backup path")
    else:
        raise RuntimeError("unsupported atomic overwrite commit strategy")
    conn.execute(
        f"UPDATE {TABLE} SET namespace_commit_started=1,write_strategy=?,updated_at=? "
        "WHERE event_id=? AND signature_hash=?",
        (strategy, utc_now(), event_id, signature_hash),
    )


def delete_protocol(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    signature_hash: str,
    attempt_id: str | None = None,
) -> bool:
    if attempt_id:
        cursor = conn.execute(
            f"DELETE FROM {TABLE} WHERE event_id=? AND signature_hash=? AND "
            "(attempt_id=? OR attempt_id IS NULL)",
            (event_id, signature_hash, attempt_id),
        )
    else:
        cursor = conn.execute(
            f"DELETE FROM {TABLE} WHERE event_id=? AND signature_hash=?",
            (event_id, signature_hash),
        )
    return bool(cursor.rowcount)
