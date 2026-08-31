from __future__ import annotations

"""Maintainer-side bounded intake for privacy-safe ZN defect reports.

This is intentionally a storage/protocol primitive rather than a repository
mutation service. Receiving a report never grants source checkout, push, PR,
merge, release, signing, updater, or production credential authority.
"""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping

from .models import utc_now

_REPORT_SCHEMA = "zn-upstream-bug-report-v2"
_ACK_SCHEMA = "zn-upstream-bug-report-ack-v1"
_RECONCILIATION_SCHEMA = "zn-upstream-bug-report-reconciliation-v1"
_PRODUCT = "ZN"
_ALLOWED_KEYS = {
    "schema",
    "product",
    "report_key",
    "component_token",
    "failure_class",
    "exception_type",
    "incident_token",
    "occurrences",
}


class MaintainerBugReportIntake:
    """Durably deduplicate bounded reports by installation-private report key."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def accept(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        report = self._validated_payload(payload)
        now = utc_now()
        with closing(self._connect()) as conn:
            # The HTTP adapter is intentionally threaded. Serialize the short
            # read/insert-or-update transaction so two concurrent deliveries of
            # the same idempotency key cannot both observe an absent row.
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT report_key,component_token,failure_class,exception_type,"
                "incident_token,occurrences FROM maintainer_bug_report_intake "
                "WHERE report_key=?",
                (report["report_key"],),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO maintainer_bug_report_intake(
                        report_key,component_token,failure_class,exception_type,
                        incident_token,occurrences,received_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (
                        report["report_key"],
                        report["component_token"],
                        report["failure_class"],
                        report["exception_type"],
                        report["incident_token"],
                        report["occurrences"],
                        now,
                        now,
                    ),
                )
            else:
                expected = (
                    report["report_key"],
                    report["component_token"],
                    report["failure_class"],
                    report["exception_type"],
                    report["incident_token"],
                )
                observed = (
                    str(existing["report_key"]),
                    str(existing["component_token"]),
                    str(existing["failure_class"]),
                    str(existing["exception_type"]),
                    str(existing["incident_token"]),
                )
                if observed != expected:
                    raise RuntimeError("upstream bug report key was reused with different evidence")
                if report["occurrences"] > int(existing["occurrences"]):
                    conn.execute(
                        "UPDATE maintainer_bug_report_intake "
                        "SET occurrences=?,updated_at=? WHERE report_key=?",
                        (report["occurrences"], now, report["report_key"]),
                    )
            conn.commit()
        return self._ack(report["report_key"])

    def lookup(self, report_key: str) -> dict[str, Any] | None:
        key = self._digest(report_key, name="report_key")
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT report_key FROM maintainer_bug_report_intake WHERE report_key=?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return self._ack(key)

    def reconciliation(self, report_key: str) -> dict[str, Any]:
        """Return explicit receiver evidence for uncertain-dispatch reconciliation."""

        key = self._digest(report_key, name="report_key")
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT report_key FROM maintainer_bug_report_intake WHERE report_key=?",
                (key,),
            ).fetchone()
        return {
            "schema": _RECONCILIATION_SCHEMA,
            "report_key": key,
            "present": row is not None,
        }

    def snapshot(self, *, limit: int = 128) -> dict[str, Any]:
        bounded = max(1, min(512, int(limit)))
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT report_key,component_token,failure_class,exception_type,"
                "incident_token,occurrences,received_at,updated_at "
                "FROM maintainer_bug_report_intake "
                "ORDER BY received_at DESC,report_key ASC LIMIT ?",
                (bounded,),
            ).fetchall()
            total = int(conn.execute("SELECT COUNT(*) FROM maintainer_bug_report_intake").fetchone()[0])
        return {
            "report_count": total,
            "returned_count": len(rows),
            "truncated": total > len(rows),
            "reports": [dict(row) for row in rows],
        }

    @classmethod
    def _validated_payload(cls, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValueError("upstream bug report payload must be a mapping")
        if set(payload) != _ALLOWED_KEYS:
            raise ValueError("upstream bug report payload contains unsupported fields")
        if str(payload.get("schema") or "") != _REPORT_SCHEMA:
            raise ValueError("upstream bug report schema is unsupported")
        if str(payload.get("product") or "") != _PRODUCT:
            raise ValueError("upstream bug report product is invalid")

        failure_class = str(payload.get("failure_class") or "").strip()
        exception_type = str(payload.get("exception_type") or "").strip()
        occurrences = int(payload.get("occurrences") or 0)
        if failure_class != "probable_zn_defect":
            raise ValueError("upstream bug report failure class is invalid")
        if not exception_type or len(exception_type) > 128:
            raise ValueError("upstream bug report exception type is invalid")
        if occurrences < 3:
            raise ValueError("upstream bug report occurrence count is invalid")

        return {
            "schema": _REPORT_SCHEMA,
            "product": _PRODUCT,
            "report_key": cls._digest(payload.get("report_key"), name="report_key"),
            "component_token": cls._digest(payload.get("component_token"), name="component_token"),
            "failure_class": failure_class,
            "exception_type": exception_type,
            "incident_token": cls._digest(payload.get("incident_token"), name="incident_token"),
            "occurrences": occurrences,
        }

    @staticmethod
    def _digest(value: Any, *, name: str) -> str:
        digest = str(value or "").strip().lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"upstream bug report {name} is invalid")
        return digest

    @staticmethod
    def _ack(report_key: str) -> dict[str, Any]:
        return {
            "schema": _ACK_SCHEMA,
            "report_key": report_key,
            "accepted": True,
        }

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS maintainer_bug_report_intake(
                    report_key TEXT PRIMARY KEY,
                    component_token TEXT NOT NULL,
                    failure_class TEXT NOT NULL,
                    exception_type TEXT NOT NULL,
                    incident_token TEXT NOT NULL,
                    occurrences INTEGER NOT NULL,
                    received_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
