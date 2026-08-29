from __future__ import annotations

"""Durable, privacy-safe resident health observations.

Self-maintenance cannot reason about repeated resident failures if every restart
forgets them. This journal keeps one bounded row per resident organ. Raw error
messages are never persisted: only the exception type and a one-way fingerprint
are retained, together with occurrence counters, a conservative failure class,
and timestamps.

A repeated high-confidence ZN defect can form exactly one durable maintenance
task for that organ. The task is evidence only: it does not grant source-write,
merge, updater, replacement, or release authority. Recovery closes the task, and
a later qualifying defect can reopen the same organ task with fresh evidence.
"""

import hashlib
import sqlite3
from contextlib import closing
from typing import Any

from .models import utc_now

_DOMAIN = b"zn-resident-health-v1\x00"
_TASK_DOMAIN = b"zn-maintenance-task-v1\x00"
_MAX_ORGAN_LENGTH = 128
_MAINTENANCE_REPEAT_THRESHOLD = 3
_PROBABLE_ZN_DEFECT_TYPES = frozenset({"AssertionError", "NotImplementedError"})
_PROGRAMMING_OR_DATA_CONTRACT_TYPES = frozenset(
    {"AttributeError", "IndexError", "KeyError", "TypeError"}
)


class ResidentHealthJournal:
    def __init__(self, store):
        self.store = store
        self._init_schema()

    def record_failure(self, organ: str, error: BaseException) -> dict[str, Any]:
        organ_name = self._organ(organ)
        exception_type = type(error).__name__[:128]
        fingerprint = self._fingerprint(exception_type, str(error))
        failure_class = self._classify(error)
        now = utc_now()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO resident_health_observations(
                    organ,total_failures,consecutive_failures,repeat_fingerprint_failures,
                    first_failure_at,last_failure_at,last_success_at,last_exception_type,
                    last_fingerprint,last_failure_class
                ) VALUES(?,1,1,1,?,?,NULL,?,?,?)
                ON CONFLICT(organ) DO UPDATE SET
                    total_failures=total_failures+1,
                    consecutive_failures=consecutive_failures+1,
                    repeat_fingerprint_failures=CASE
                        WHEN resident_health_observations.last_fingerprint=excluded.last_fingerprint
                        THEN resident_health_observations.repeat_fingerprint_failures+1
                        ELSE 1
                    END,
                    last_failure_at=excluded.last_failure_at,
                    last_exception_type=excluded.last_exception_type,
                    last_fingerprint=excluded.last_fingerprint,
                    last_failure_class=excluded.last_failure_class
                """,
                (
                    organ_name,
                    now,
                    now,
                    exception_type,
                    fingerprint,
                    failure_class,
                ),
            )
            row = conn.execute(
                "SELECT organ,total_failures,consecutive_failures,repeat_fingerprint_failures,"
                "first_failure_at,last_failure_at,last_success_at,last_exception_type,"
                "last_fingerprint,last_failure_class "
                "FROM resident_health_observations WHERE organ=?",
                (organ_name,),
            ).fetchone()
            snapshot = self._snapshot(row)
            if snapshot["maintenance_candidate"]:
                self._upsert_maintenance_task(conn, snapshot, now=now)
            conn.commit()
        return snapshot

    def record_success(self, organ: str) -> dict[str, Any] | None:
        organ_name = self._organ(organ)
        now = utc_now()
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "UPDATE resident_health_observations "
                "SET consecutive_failures=0,repeat_fingerprint_failures=0,last_success_at=? "
                "WHERE organ=?",
                (now, organ_name),
            )
            if cursor.rowcount > 0:
                conn.execute(
                    "UPDATE resident_maintenance_tasks "
                    "SET status='closed',closed_at=?,close_reason='organ_recovered',updated_at=? "
                    "WHERE organ=? AND status='open'",
                    (now, now, organ_name),
                )
            conn.commit()
        if cursor.rowcount <= 0:
            return None
        return self.get(organ_name)

    def get(self, organ: str) -> dict[str, Any] | None:
        organ_name = self._organ(organ)
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT organ,total_failures,consecutive_failures,repeat_fingerprint_failures,"
                "first_failure_at,last_failure_at,last_success_at,last_exception_type,"
                "last_fingerprint,last_failure_class "
                "FROM resident_health_observations WHERE organ=?",
                (organ_name,),
            ).fetchone()
        return self._snapshot(row) if row else None

    def snapshot(self, *, limit: int = 128) -> dict[str, Any]:
        bounded = max(1, min(512, int(limit)))
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT organ,total_failures,consecutive_failures,repeat_fingerprint_failures,"
                "first_failure_at,last_failure_at,last_success_at,last_exception_type,"
                "last_fingerprint,last_failure_class "
                "FROM resident_health_observations "
                "ORDER BY consecutive_failures DESC,last_failure_at DESC,organ ASC LIMIT ?",
                (bounded,),
            ).fetchall()
            total = int(
                conn.execute("SELECT COUNT(*) FROM resident_health_observations").fetchone()[0]
            )
        organs = [self._snapshot(row) for row in rows]
        unhealthy = sum(1 for item in organs if not item["healthy"])
        candidates = sum(1 for item in organs if item["maintenance_candidate"])
        return {
            "healthy": unhealthy == 0,
            "organ_count": total,
            "returned_count": len(organs),
            "unhealthy_count": unhealthy,
            "maintenance_candidate_count": candidates,
            "truncated": total > len(organs),
            "organs": organs,
        }

    def maintenance_task(self, organ: str) -> dict[str, Any] | None:
        organ_name = self._organ(organ)
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT task_id,organ,status,failure_class,fingerprint,exception_type,"
                "first_seen_at,last_seen_at,updated_at,closed_at,close_reason,occurrences "
                "FROM resident_maintenance_tasks WHERE organ=?",
                (organ_name,),
            ).fetchone()
        return self._task_snapshot(row) if row else None

    def maintenance_tasks(self, *, limit: int = 128) -> dict[str, Any]:
        bounded = max(1, min(512, int(limit)))
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT task_id,organ,status,failure_class,fingerprint,exception_type,"
                "first_seen_at,last_seen_at,updated_at,closed_at,close_reason,occurrences "
                "FROM resident_maintenance_tasks "
                "ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END,updated_at DESC,organ ASC "
                "LIMIT ?",
                (bounded,),
            ).fetchall()
            total = int(
                conn.execute("SELECT COUNT(*) FROM resident_maintenance_tasks").fetchone()[0]
            )
            open_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM resident_maintenance_tasks WHERE status='open'"
                ).fetchone()[0]
            )
        return {
            "task_count": total,
            "open_count": open_count,
            "returned_count": len(rows),
            "truncated": total > len(rows),
            "tasks": [self._task_snapshot(row) for row in rows],
        }

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> dict[str, Any]:
        consecutive = max(0, int(row["consecutive_failures"] or 0))
        repeated = max(0, int(row["repeat_fingerprint_failures"] or 0))
        failure_class = str(row["last_failure_class"] or "unknown")
        maintenance_candidate = bool(
            failure_class == "probable_zn_defect"
            and consecutive >= _MAINTENANCE_REPEAT_THRESHOLD
            and repeated >= _MAINTENANCE_REPEAT_THRESHOLD
        )
        return {
            "organ": str(row["organ"]),
            "healthy": consecutive == 0,
            "total_failures": max(0, int(row["total_failures"] or 0)),
            "consecutive_failures": consecutive,
            "repeat_fingerprint_failures": repeated,
            "first_failure_at": row["first_failure_at"],
            "last_failure_at": row["last_failure_at"],
            "last_success_at": row["last_success_at"],
            "last_exception_type": row["last_exception_type"],
            "last_fingerprint": row["last_fingerprint"],
            "last_failure_class": failure_class,
            "maintenance_candidate": maintenance_candidate,
        }

    @staticmethod
    def _task_snapshot(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "task_id": str(row["task_id"]),
            "organ": str(row["organ"]),
            "status": str(row["status"]),
            "failure_class": str(row["failure_class"]),
            "fingerprint": str(row["fingerprint"]),
            "exception_type": str(row["exception_type"]),
            "first_seen_at": row["first_seen_at"],
            "last_seen_at": row["last_seen_at"],
            "updated_at": row["updated_at"],
            "closed_at": row["closed_at"],
            "close_reason": row["close_reason"],
            "occurrences": max(0, int(row["occurrences"] or 0)),
        }

    def _upsert_maintenance_task(
        self,
        conn: sqlite3.Connection,
        health: dict[str, Any],
        *,
        now: str,
    ) -> None:
        organ = str(health["organ"])
        fingerprint = str(health["last_fingerprint"] or "")
        exception_type = str(health["last_exception_type"] or "unknown")
        failure_class = str(health["last_failure_class"] or "unknown")
        repeated = max(1, int(health["repeat_fingerprint_failures"] or 1))
        task_id = self._task_id(organ)
        existing = conn.execute(
            "SELECT fingerprint,occurrences,status FROM resident_maintenance_tasks WHERE organ=?",
            (organ,),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO resident_maintenance_tasks(
                    task_id,organ,status,failure_class,fingerprint,exception_type,
                    first_seen_at,last_seen_at,updated_at,closed_at,close_reason,occurrences
                ) VALUES(?,?,'open',?,?,?,?,?,?,NULL,NULL,?)
                """,
                (
                    task_id,
                    organ,
                    failure_class,
                    fingerprint,
                    exception_type,
                    now,
                    now,
                    now,
                    repeated,
                ),
            )
            return

        same_fingerprint = str(existing["fingerprint"] or "") == fingerprint
        previous_occurrences = max(0, int(existing["occurrences"] or 0))
        occurrences = max(previous_occurrences, repeated) if same_fingerprint else repeated
        conn.execute(
            """
            UPDATE resident_maintenance_tasks SET
                status='open',failure_class=?,fingerprint=?,exception_type=?,
                first_seen_at=CASE WHEN fingerprint=? THEN first_seen_at ELSE ? END,
                last_seen_at=?,updated_at=?,closed_at=NULL,close_reason=NULL,occurrences=?
            WHERE organ=?
            """,
            (
                failure_class,
                fingerprint,
                exception_type,
                fingerprint,
                now,
                now,
                now,
                occurrences,
                organ,
            ),
        )

    @staticmethod
    def _classify(error: BaseException) -> str:
        exception_type = type(error).__name__
        if exception_type in _PROBABLE_ZN_DEFECT_TYPES:
            return "probable_zn_defect"
        if exception_type in _PROGRAMMING_OR_DATA_CONTRACT_TYPES:
            return "programming_or_data_contract"
        if isinstance(error, (TimeoutError, ConnectionError)):
            return "network_or_service"
        if isinstance(error, PermissionError):
            return "permission_or_environment"
        if isinstance(error, FileNotFoundError):
            return "configuration_or_environment"
        if isinstance(error, ValueError):
            return "configuration_or_input"
        if isinstance(error, OSError):
            return "environment_or_service"
        return "unknown"

    @staticmethod
    def _fingerprint(exception_type: str, message: str) -> str:
        digest = hashlib.sha256()
        digest.update(_DOMAIN)
        digest.update(exception_type.encode("utf-8", errors="replace"))
        digest.update(b"\x00")
        digest.update(str(message or "").encode("utf-8", errors="replace"))
        return digest.hexdigest()

    @staticmethod
    def _task_id(organ: str) -> str:
        digest = hashlib.sha256()
        digest.update(_TASK_DOMAIN)
        digest.update(str(organ or "").encode("utf-8", errors="replace"))
        return f"maintenance-{digest.hexdigest()[:24]}"

    @staticmethod
    def _organ(value: str) -> str:
        organ = str(value or "").strip().lower()
        if not organ:
            raise ValueError("resident health organ must not be empty")
        if len(organ) > _MAX_ORGAN_LENGTH:
            raise ValueError("resident health organ is too long")
        return organ

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS resident_health_observations(
                    organ TEXT PRIMARY KEY,
                    total_failures INTEGER NOT NULL DEFAULT 0,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    repeat_fingerprint_failures INTEGER NOT NULL DEFAULT 0,
                    first_failure_at TEXT NOT NULL,
                    last_failure_at TEXT NOT NULL,
                    last_success_at TEXT,
                    last_exception_type TEXT,
                    last_fingerprint TEXT,
                    last_failure_class TEXT NOT NULL DEFAULT 'unknown'
                )
                """
            )
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(resident_health_observations)")
            }
            if "repeat_fingerprint_failures" not in columns:
                conn.execute(
                    "ALTER TABLE resident_health_observations "
                    "ADD COLUMN repeat_fingerprint_failures INTEGER NOT NULL DEFAULT 0"
                )
            if "last_failure_class" not in columns:
                conn.execute(
                    "ALTER TABLE resident_health_observations "
                    "ADD COLUMN last_failure_class TEXT NOT NULL DEFAULT 'unknown'"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_resident_health_unhealthy "
                "ON resident_health_observations(consecutive_failures,last_failure_at)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS resident_maintenance_tasks(
                    task_id TEXT NOT NULL UNIQUE,
                    organ TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    failure_class TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    exception_type TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    closed_at TEXT,
                    close_reason TEXT,
                    occurrences INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_resident_maintenance_tasks_status "
                "ON resident_maintenance_tasks(status,updated_at)"
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
