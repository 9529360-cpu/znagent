from __future__ import annotations

"""Durable privacy-safe outbox for upstream ZN defect reports.

This owner prepares bounded incident records from already-derived resident maintenance
Tasks. It intentionally has no network, repository, credential, push, PR, merge,
release, updater or signing authority. A later transport may consume the payload
only after deterministic endpoint policy is established.
"""

import hashlib
import sqlite3
from contextlib import closing
from typing import Any, Mapping

from .models import utc_now

_REPORT_KEY_DOMAIN = b"zn-upstream-bug-report-key-v1\x00"
_COMPONENT_DOMAIN = b"zn-upstream-bug-report-component-v1\x00"
_SCHEMA = "zn-upstream-bug-report-v1"
_PRODUCT = "ZN"
_MIN_OCCURRENCES = 3


class ResidentUpstreamBugReportOutbox:
    """Prepare one bounded upstream report per stable maintenance incident."""

    def __init__(self, store):
        self.store = store
        self._init_schema()

    def prepare(self, task: Mapping[str, Any]) -> dict[str, Any]:
        task_id = str(task.get("task_id") or "").strip()
        organ = str(task.get("organ") or "").strip().lower()
        status = str(task.get("status") or "").strip().lower()
        failure_class = str(task.get("failure_class") or "").strip()
        fingerprint = str(task.get("fingerprint") or "").strip().lower()
        exception_type = str(task.get("exception_type") or "").strip()
        occurrences = max(0, int(task.get("occurrences") or 0))

        if status != "open":
            raise ValueError("upstream bug report requires an open maintenance task")
        if failure_class != "probable_zn_defect":
            raise ValueError("upstream bug report requires a probable ZN defect")
        if not task_id.startswith("maintenance-") or len(task_id) > 64:
            raise ValueError("upstream bug report task id is invalid")
        if not organ or len(organ) > 128:
            raise ValueError("upstream bug report component identity is invalid")
        if not self._is_sha256(fingerprint):
            raise ValueError("upstream bug report incident fingerprint is invalid")
        if not exception_type or len(exception_type) > 128:
            raise ValueError("upstream bug report exception type is invalid")
        if occurrences < _MIN_OCCURRENCES:
            raise ValueError("upstream bug report evidence is below the repeat threshold")

        component_fingerprint = self._fingerprint(_COMPONENT_DOMAIN, organ)
        report_key = self._fingerprint(
            _REPORT_KEY_DOMAIN,
            "\x00".join((task_id, fingerprint)),
        )
        now = utc_now()

        with closing(self._connect()) as conn:
            existing = conn.execute(
                "SELECT report_key,task_id,incident_fingerprint,component_fingerprint,"
                "failure_class,exception_type,occurrences,state,dispatch_attempts,"
                "last_error_type,created_at,updated_at "
                "FROM resident_upstream_bug_reports WHERE report_key=?",
                (report_key,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO resident_upstream_bug_reports(
                        report_key,task_id,incident_fingerprint,component_fingerprint,
                        failure_class,exception_type,occurrences,state,dispatch_attempts,
                        last_error_type,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,'pending',0,NULL,?,?)
                    """,
                    (
                        report_key,
                        task_id,
                        fingerprint,
                        component_fingerprint,
                        failure_class,
                        exception_type,
                        occurrences,
                        now,
                        now,
                    ),
                )
            else:
                self._require_same_evidence(
                    existing,
                    task_id=task_id,
                    incident_fingerprint=fingerprint,
                    component_fingerprint=component_fingerprint,
                    failure_class=failure_class,
                    exception_type=exception_type,
                )
                if str(existing["state"]) == "pending" and occurrences > int(existing["occurrences"]):
                    conn.execute(
                        "UPDATE resident_upstream_bug_reports "
                        "SET occurrences=?,updated_at=? WHERE report_key=? AND state='pending'",
                        (occurrences, now, report_key),
                    )
            conn.commit()
            row = conn.execute(
                "SELECT report_key,task_id,incident_fingerprint,component_fingerprint,"
                "failure_class,exception_type,occurrences,state,dispatch_attempts,"
                "last_error_type,created_at,updated_at "
                "FROM resident_upstream_bug_reports WHERE report_key=?",
                (report_key,),
            ).fetchone()
        return self._snapshot(row)

    def payload(self, report_key: str) -> dict[str, Any]:
        row = self._row(report_key)
        if row is None:
            raise KeyError("upstream bug report does not exist")
        return self._payload(row)

    def reserve_dispatch(self, report_key: str) -> dict[str, Any]:
        key = self._report_key(report_key)
        now = utc_now()
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT state FROM resident_upstream_bug_reports WHERE report_key=?",
                (key,),
            ).fetchone()
            if row is None:
                raise KeyError("upstream bug report does not exist")
            if str(row["state"]) != "pending":
                raise RuntimeError("upstream bug report is not pending")
            cursor = conn.execute(
                "UPDATE resident_upstream_bug_reports "
                "SET state='dispatching',dispatch_attempts=dispatch_attempts+1,"
                "last_error_type=NULL,updated_at=? "
                "WHERE report_key=? AND state='pending'",
                (now, key),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("upstream bug report dispatch reservation raced")
            conn.commit()
            reserved = conn.execute(
                "SELECT report_key,task_id,incident_fingerprint,component_fingerprint,"
                "failure_class,exception_type,occurrences,state,dispatch_attempts,"
                "last_error_type,created_at,updated_at "
                "FROM resident_upstream_bug_reports WHERE report_key=?",
                (key,),
            ).fetchone()
        return self._payload(reserved)

    def mark_delivered(self, report_key: str) -> dict[str, Any]:
        return self._finish_dispatch(report_key, state="delivered", error_type=None)

    def mark_outcome_uncertain(self, report_key: str, error: BaseException) -> dict[str, Any]:
        return self._finish_dispatch(
            report_key,
            state="outcome_uncertain",
            error_type=type(error).__name__[:128],
        )

    def snapshot(self, *, limit: int = 128) -> dict[str, Any]:
        bounded = max(1, min(512, int(limit)))
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT report_key,task_id,incident_fingerprint,component_fingerprint,"
                "failure_class,exception_type,occurrences,state,dispatch_attempts,"
                "last_error_type,created_at,updated_at "
                "FROM resident_upstream_bug_reports "
                "ORDER BY created_at DESC,report_key ASC LIMIT ?",
                (bounded,),
            ).fetchall()
            total = int(conn.execute("SELECT COUNT(*) FROM resident_upstream_bug_reports").fetchone()[0])
            pending = int(
                conn.execute(
                    "SELECT COUNT(*) FROM resident_upstream_bug_reports WHERE state='pending'"
                ).fetchone()[0]
            )
            uncertain = int(
                conn.execute(
                    "SELECT COUNT(*) FROM resident_upstream_bug_reports "
                    "WHERE state='outcome_uncertain'"
                ).fetchone()[0]
            )
        return {
            "report_count": total,
            "pending_count": pending,
            "outcome_uncertain_count": uncertain,
            "returned_count": len(rows),
            "truncated": total > len(rows),
            "reports": [self._snapshot(row) for row in rows],
        }

    def _finish_dispatch(
        self,
        report_key: str,
        *,
        state: str,
        error_type: str | None,
    ) -> dict[str, Any]:
        if state not in {"delivered", "outcome_uncertain"}:
            raise ValueError("invalid upstream bug report terminal state")
        key = self._report_key(report_key)
        now = utc_now()
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT state FROM resident_upstream_bug_reports WHERE report_key=?",
                (key,),
            ).fetchone()
            if row is None:
                raise KeyError("upstream bug report does not exist")
            current = str(row["state"])
            if current == state:
                pass
            elif current != "dispatching":
                raise RuntimeError("upstream bug report has no active dispatch")
            else:
                conn.execute(
                    "UPDATE resident_upstream_bug_reports "
                    "SET state=?,last_error_type=?,updated_at=? WHERE report_key=?",
                    (state, error_type, now, key),
                )
            conn.commit()
            finished = conn.execute(
                "SELECT report_key,task_id,incident_fingerprint,component_fingerprint,"
                "failure_class,exception_type,occurrences,state,dispatch_attempts,"
                "last_error_type,created_at,updated_at "
                "FROM resident_upstream_bug_reports WHERE report_key=?",
                (key,),
            ).fetchone()
        return self._snapshot(finished)

    def _row(self, report_key: str):
        key = self._report_key(report_key)
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT report_key,task_id,incident_fingerprint,component_fingerprint,"
                "failure_class,exception_type,occurrences,state,dispatch_attempts,"
                "last_error_type,created_at,updated_at "
                "FROM resident_upstream_bug_reports WHERE report_key=?",
                (key,),
            ).fetchone()

    @staticmethod
    def _payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "product": _PRODUCT,
            "report_key": str(row["report_key"]),
            "component_fingerprint": str(row["component_fingerprint"]),
            "failure_class": str(row["failure_class"]),
            "exception_type": str(row["exception_type"]),
            "incident_fingerprint": str(row["incident_fingerprint"]),
            "occurrences": max(0, int(row["occurrences"] or 0)),
        }

    @classmethod
    def _snapshot(cls, row: sqlite3.Row) -> dict[str, Any]:
        return {
            **cls._payload(row),
            "state": str(row["state"]),
            "dispatch_attempts": max(0, int(row["dispatch_attempts"] or 0)),
            "last_error_type": row["last_error_type"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _require_same_evidence(
        row: sqlite3.Row,
        *,
        task_id: str,
        incident_fingerprint: str,
        component_fingerprint: str,
        failure_class: str,
        exception_type: str,
    ) -> None:
        expected = (
            task_id,
            incident_fingerprint,
            component_fingerprint,
            failure_class,
            exception_type,
        )
        observed = (
            str(row["task_id"]),
            str(row["incident_fingerprint"]),
            str(row["component_fingerprint"]),
            str(row["failure_class"]),
            str(row["exception_type"]),
        )
        if observed != expected:
            raise RuntimeError("upstream bug report evidence drifted for the same report key")

    @staticmethod
    def _fingerprint(domain: bytes, value: str) -> str:
        digest = hashlib.sha256()
        digest.update(domain)
        digest.update(str(value).encode("utf-8", errors="replace"))
        return digest.hexdigest()

    @staticmethod
    def _is_sha256(value: str) -> bool:
        return len(value) == 64 and all(char in "0123456789abcdef" for char in value)

    @staticmethod
    def _report_key(value: str) -> str:
        key = str(value or "").strip().lower()
        if not ResidentUpstreamBugReportOutbox._is_sha256(key):
            raise ValueError("upstream bug report key is invalid")
        return key

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS resident_upstream_bug_reports(
                    report_key TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    incident_fingerprint TEXT NOT NULL,
                    component_fingerprint TEXT NOT NULL,
                    failure_class TEXT NOT NULL,
                    exception_type TEXT NOT NULL,
                    occurrences INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    dispatch_attempts INTEGER NOT NULL DEFAULT 0,
                    last_error_type TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_resident_upstream_bug_reports_state "
                "ON resident_upstream_bug_reports(state,created_at)"
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
