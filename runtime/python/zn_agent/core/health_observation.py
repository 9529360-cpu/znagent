from __future__ import annotations

"""Durable, privacy-safe resident health observations.

The journal keeps one bounded row per resident organ so restarts do not erase
useful health evidence. Raw error messages are never persisted: only the
exception type and a one-way fingerprint are retained, together with occurrence
counters, a conservative failure class, and timestamps.

Health evidence is diagnostic state only. It does not create repair tasks,
source-write authority, repository authority, update authority, or any other
side-effect permission.
"""

import hashlib
import sqlite3
from contextlib import closing
from typing import Any

from .models import utc_now

_DOMAIN = b"zn-resident-health-v1\x00"
_MAX_ORGAN_LENGTH = 128
_PROBABLE_ZN_DEFECT_TYPES = frozenset({"AssertionError", "NotImplementedError"})
_PROGRAMMING_OR_DATA_CONTRACT_TYPES = frozenset(
    {"AttributeError", "IndexError", "KeyError", "TypeError"}
)


class ResidentHealthJournal:
    def __init__(self, store):
        self.store = store
        self._init_schema()

    # Bounded recent-outcome window ("1" = success, "0" = failure). Catches
    # flapping routes that keep resetting the consecutive counter with an
    # occasional success but fail most of the time.
    _RECENT_WINDOW = 10
    _MIN_WINDOW_SAMPLES = 5

    def record_failure(
        self,
        organ: str,
        error: BaseException,
        *,
        failure_class: str | None = None,
        terminal: bool = False,
    ) -> dict[str, Any]:
        organ_name = self._organ(organ)
        exception_type = type(error).__name__[:128]
        fingerprint = self._fingerprint(exception_type, str(error))
        resolved_failure_class = (
            str(failure_class or "").strip().lower()[:128]
            or self._classify(error)
        )
        now = utc_now()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO resident_health_observations(
                    organ,total_failures,consecutive_failures,repeat_fingerprint_failures,
                    first_failure_at,last_failure_at,last_success_at,last_exception_type,
                    last_fingerprint,last_failure_class,terminal_failure_class,recent_results
                ) VALUES(?,1,1,1,?,?,NULL,?,?,?,?, '0')
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
                    last_failure_class=excluded.last_failure_class,
                    terminal_failure_class=CASE
                        WHEN ? THEN excluded.last_failure_class
                        ELSE resident_health_observations.terminal_failure_class
                    END,
                    recent_results=substr(
                        resident_health_observations.recent_results || '0',
                        -?
                    )
                """,
                (
                    organ_name,
                    now,
                    now,
                    exception_type,
                    fingerprint,
                    resolved_failure_class,
                    resolved_failure_class if terminal else None,
                    1 if terminal else 0,
                    self._RECENT_WINDOW,
                ),
            )
            row = conn.execute(
                "SELECT organ,total_failures,consecutive_failures,repeat_fingerprint_failures,"
                "first_failure_at,last_failure_at,last_success_at,last_exception_type,"
                "last_fingerprint,last_failure_class,terminal_failure_class,recent_results "
                "FROM resident_health_observations WHERE organ=?",
                (organ_name,),
            ).fetchone()
            snapshot = self._snapshot(row)
            conn.commit()
        return snapshot

    def record_success(self, organ: str) -> dict[str, Any] | None:
        organ_name = self._organ(organ)
        now = utc_now()
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "UPDATE resident_health_observations "
                "SET consecutive_failures=0,repeat_fingerprint_failures=0,"
                "last_success_at=?,terminal_failure_class=NULL,"
                "recent_results=substr(recent_results || '1', -?) "
                "WHERE organ=?",
                (now, self._RECENT_WINDOW, organ_name),
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
                "last_fingerprint,last_failure_class,terminal_failure_class,recent_results "
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
                "last_fingerprint,last_failure_class,terminal_failure_class,recent_results "
                "FROM resident_health_observations "
                "ORDER BY consecutive_failures DESC,last_failure_at DESC,organ ASC LIMIT ?",
                (bounded,),
            ).fetchall()
            total = int(
                conn.execute("SELECT COUNT(*) FROM resident_health_observations").fetchone()[0]
            )
        organs = [self._snapshot(row) for row in rows]
        unhealthy = sum(1 for item in organs if not item["healthy"])
        return {
            "healthy": unhealthy == 0,
            "organ_count": total,
            "returned_count": len(organs),
            "unhealthy_count": unhealthy,
            "truncated": total > len(organs),
            "organs": organs,
        }

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> dict[str, Any]:
        keys = set(row.keys())
        consecutive = max(0, int(row["consecutive_failures"] or 0))
        recent = str(row["recent_results"] or "") if "recent_results" in keys else ""
        recent = "".join(c for c in recent if c in "01")
        success_rate: float | None = None
        if len(recent) >= ResidentHealthJournal._MIN_WINDOW_SAMPLES:
            success_rate = recent.count("1") / len(recent)
        terminal_class = row["terminal_failure_class"] if "terminal_failure_class" in keys else None
        return {
            "organ": str(row["organ"]),
            "healthy": consecutive == 0 and not terminal_class,
            "total_failures": max(0, int(row["total_failures"] or 0)),
            "consecutive_failures": consecutive,
            "repeat_fingerprint_failures": max(
                0, int(row["repeat_fingerprint_failures"] or 0)
            ),
            "first_failure_at": row["first_failure_at"],
            "last_failure_at": row["last_failure_at"],
            "last_success_at": row["last_success_at"],
            "last_exception_type": row["last_exception_type"],
            "last_fingerprint": row["last_fingerprint"],
            "last_failure_class": str(row["last_failure_class"] or "unknown"),
            "terminal_failure_class": (
                str(terminal_class) if terminal_class else None
            ),
            "recent_success_rate": success_rate,
            "recent_window_samples": len(recent),
        }

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
            if "terminal_failure_class" not in columns:
                conn.execute(
                    "ALTER TABLE resident_health_observations "
                    "ADD COLUMN terminal_failure_class TEXT"
                )
            if "recent_results" not in columns:
                conn.execute(
                    "ALTER TABLE resident_health_observations "
                    "ADD COLUMN recent_results TEXT NOT NULL DEFAULT ''"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_resident_health_unhealthy "
                "ON resident_health_observations(consecutive_failures,last_failure_at)"
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
