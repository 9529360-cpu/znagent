from __future__ import annotations

"""Durable, authority-free investigation state derived from maintenance tasks.

A maintenance task is evidence that ZN may need source investigation; it is not
source-write authority. This ledger gives an open task a bounded incident record
with an explicit baseline, regression oracle, isolated-branch attempts and an
acceptance state before any future source-maintenance caller is allowed to act.

The task projection in :mod:`health_observation` remains authoritative. This
module deliberately does *not* install SQLite triggers on that table: a damaged
or unavailable investigation projection must never make health/task writes fail.
Instead every investigation read/write reconciles from task truth first. That
also observes tasks formed by channel supervisors using separate health-journal
instances against the same resident database, without polling error strings.
"""

import sqlite3
from contextlib import closing
from typing import Any

from .models import utc_now

_MAX_REF = 1000
_MAX_REASON = 128


class MaintenanceInvestigationLedger:
    """Bound one evidence-only investigation/attempt lifecycle to each task."""

    def __init__(self, store):
        self.store = store
        self._init_schema()
        self.reconcile()

    def get(self, task_id: str) -> dict[str, Any] | None:
        normalized = self._task_id(task_id)
        self.reconcile(task_id=normalized)
        return self._get_without_reconcile(normalized)

    def snapshot(self, *, limit: int = 128) -> dict[str, Any]:
        self.reconcile()
        bounded = max(1, min(512, int(limit)))
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT task_id,organ,task_fingerprint,failure_class,exception_type,"
                "source_task_status,status,authority,incident_started_at,last_seen_at,"
                "observed_occurrences,updated_at,closed_at,close_reason,baseline_ref,"
                "regression_oracle,attempt_count,acceptance_state,accepted_attempt_key "
                "FROM resident_maintenance_investigations "
                "ORDER BY CASE status WHEN 'closed' THEN 1 ELSE 0 END,updated_at DESC "
                "LIMIT ?",
                (bounded,),
            ).fetchall()
            total = int(
                conn.execute(
                    "SELECT COUNT(*) FROM resident_maintenance_investigations"
                ).fetchone()[0]
            )
            active = int(
                conn.execute(
                    "SELECT COUNT(*) FROM resident_maintenance_investigations "
                    "WHERE source_task_status='open'"
                ).fetchone()[0]
            )
        return {
            "investigation_count": total,
            "active_count": active,
            "returned_count": len(rows),
            "truncated": total > len(rows),
            "investigations": [self._snapshot(row) for row in rows],
        }

    def begin(
        self,
        task_id: str,
        *,
        baseline_ref: str,
        regression_oracle: str,
    ) -> dict[str, Any]:
        """Admit attempt-oriented investigation only after its contract is explicit."""

        normalized = self._task_id(task_id)
        baseline = self._required_ref(baseline_ref, "baseline_ref")
        oracle = self._required_ref(regression_oracle, "regression_oracle")
        self.reconcile(task_id=normalized)
        now = utc_now()
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT source_task_status,status,baseline_ref,regression_oracle "
                "FROM resident_maintenance_investigations WHERE task_id=?",
                (normalized,),
            ).fetchone()
            if row is None:
                raise ValueError("maintenance investigation does not exist")
            if str(row["source_task_status"] or "") != "open":
                raise RuntimeError("closed maintenance task cannot begin investigation")
            status = str(row["status"] or "")
            if status not in {"pending", "investigating", "rejected"}:
                raise RuntimeError(
                    f"maintenance investigation cannot begin from status {status!r}"
                )

            # Rejected evidence is not silently reusable. Restarting a rejected
            # investigation, or changing its baseline/oracle contract, requires
            # fresh attempts even when the task fingerprint itself is unchanged.
            reset_attempts = bool(
                status == "rejected"
                or str(row["baseline_ref"] or "") not in {"", baseline}
                or str(row["regression_oracle"] or "") not in {"", oracle}
            )
            if reset_attempts:
                conn.execute(
                    "DELETE FROM resident_maintenance_attempts WHERE task_id=?",
                    (normalized,),
                )
            conn.execute(
                "UPDATE resident_maintenance_investigations SET "
                "status='investigating',baseline_ref=?,regression_oracle=?,"
                "attempt_count=CASE WHEN ? THEN 0 ELSE attempt_count END,"
                "acceptance_state='unreviewed',accepted_attempt_key=NULL,updated_at=? "
                "WHERE task_id=?",
                (baseline, oracle, 1 if reset_attempts else 0, now, normalized),
            )
            conn.commit()
        result = self._get_without_reconcile(normalized)
        assert result is not None
        return result

    def record_attempt(
        self,
        task_id: str,
        *,
        attempt_key: str,
        branch_ref: str,
        regression_passed: bool,
        evidence_ref: str,
    ) -> dict[str, Any]:
        """Record one deduped isolated attempt; never grant merge/update authority."""

        normalized = self._task_id(task_id)
        key = self._required_ref(attempt_key, "attempt_key")
        branch = self._required_ref(branch_ref, "branch_ref")
        evidence = self._required_ref(evidence_ref, "evidence_ref")
        if not branch.startswith("work/"):
            raise ValueError("maintenance attempt branch_ref must be an isolated work/* branch")
        self.reconcile(task_id=normalized)
        now = utc_now()
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT source_task_status,status,baseline_ref,regression_oracle "
                "FROM resident_maintenance_investigations WHERE task_id=?",
                (normalized,),
            ).fetchone()
            if row is None:
                raise ValueError("maintenance investigation does not exist")
            if str(row["source_task_status"] or "") != "open":
                raise RuntimeError("closed maintenance task cannot record attempts")
            if str(row["status"] or "") != "investigating":
                raise RuntimeError("maintenance investigation must begin before attempts")
            if not str(row["baseline_ref"] or "").strip() or not str(
                row["regression_oracle"] or ""
            ).strip():
                raise RuntimeError(
                    "maintenance attempt requires durable baseline and regression oracle"
                )

            conn.execute(
                "INSERT INTO resident_maintenance_attempts("
                "task_id,attempt_key,branch_ref,regression_passed,evidence_ref,created_at"
                ") VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(task_id,attempt_key) DO NOTHING",
                (
                    normalized,
                    key,
                    branch,
                    1 if bool(regression_passed) else 0,
                    evidence,
                    now,
                ),
            )
            attempt_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM resident_maintenance_attempts WHERE task_id=?",
                    (normalized,),
                ).fetchone()[0]
            )
            conn.execute(
                "UPDATE resident_maintenance_investigations SET attempt_count=?,"
                "acceptance_state='unreviewed',accepted_attempt_key=NULL,updated_at=? "
                "WHERE task_id=?",
                (attempt_count, now, normalized),
            )
            conn.commit()
        result = self._get_without_reconcile(normalized)
        assert result is not None
        return result

    def accept(self, task_id: str, *, attempt_key: str) -> dict[str, Any]:
        """Accept evidence only when the named isolated attempt passed its oracle."""

        normalized = self._task_id(task_id)
        key = self._required_ref(attempt_key, "attempt_key")
        self.reconcile(task_id=normalized)
        now = utc_now()
        with closing(self._connect()) as conn:
            investigation = conn.execute(
                "SELECT source_task_status,status FROM resident_maintenance_investigations "
                "WHERE task_id=?",
                (normalized,),
            ).fetchone()
            if investigation is None:
                raise ValueError("maintenance investigation does not exist")
            if str(investigation["source_task_status"] or "") != "open":
                raise RuntimeError("closed maintenance task cannot accept an attempt")
            if str(investigation["status"] or "") != "investigating":
                raise RuntimeError("only an active investigation can accept an attempt")
            attempt = conn.execute(
                "SELECT regression_passed FROM resident_maintenance_attempts "
                "WHERE task_id=? AND attempt_key=?",
                (normalized, key),
            ).fetchone()
            if attempt is None:
                raise ValueError("maintenance attempt does not exist")
            if int(attempt["regression_passed"] or 0) != 1:
                raise RuntimeError("failed regression attempt cannot be accepted")
            conn.execute(
                "UPDATE resident_maintenance_investigations SET status='accepted',"
                "acceptance_state='accepted',accepted_attempt_key=?,updated_at=? "
                "WHERE task_id=?",
                (key, now, normalized),
            )
            conn.commit()
        result = self._get_without_reconcile(normalized)
        assert result is not None
        return result

    def reject(self, task_id: str, *, reason: str = "evidence_rejected") -> dict[str, Any]:
        normalized = self._task_id(task_id)
        reason_code = str(reason or "evidence_rejected").strip()[:_MAX_REASON]
        self.reconcile(task_id=normalized)
        now = utc_now()
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT source_task_status FROM resident_maintenance_investigations "
                "WHERE task_id=?",
                (normalized,),
            ).fetchone()
            if row is None:
                raise ValueError("maintenance investigation does not exist")
            if str(row["source_task_status"] or "") != "open":
                raise RuntimeError("closed maintenance task cannot be rejected")
            conn.execute(
                "UPDATE resident_maintenance_investigations SET status='rejected',"
                "acceptance_state=?,accepted_attempt_key=NULL,updated_at=? WHERE task_id=?",
                (reason_code or "evidence_rejected", now, normalized),
            )
            conn.commit()
        result = self._get_without_reconcile(normalized)
        assert result is not None
        return result

    def reconcile(self, *, task_id: str | None = None) -> int:
        """Repair the secondary lifecycle projection from maintenance-task truth."""

        normalized = self._task_id(task_id) if task_id is not None else None
        repaired = 0
        with closing(self._connect()) as conn:
            if normalized is None:
                tasks = conn.execute(
                    "SELECT task_id,organ,status,failure_class,fingerprint,exception_type,"
                    "first_seen_at,last_seen_at,updated_at,closed_at,close_reason,occurrences "
                    "FROM resident_maintenance_tasks"
                ).fetchall()
            else:
                tasks = conn.execute(
                    "SELECT task_id,organ,status,failure_class,fingerprint,exception_type,"
                    "first_seen_at,last_seen_at,updated_at,closed_at,close_reason,occurrences "
                    "FROM resident_maintenance_tasks WHERE task_id=?",
                    (normalized,),
                ).fetchall()

            task_ids: set[str] = set()
            for task in tasks:
                current_task_id = str(task["task_id"])
                task_ids.add(current_task_id)
                before = conn.execute(
                    "SELECT task_fingerprint,source_task_status,status,observed_occurrences "
                    "FROM resident_maintenance_investigations WHERE task_id=?",
                    (current_task_id,),
                ).fetchone()
                self._reconcile_task(conn, task)
                after = conn.execute(
                    "SELECT task_fingerprint,source_task_status,status,observed_occurrences "
                    "FROM resident_maintenance_investigations WHERE task_id=?",
                    (current_task_id,),
                ).fetchone()
                if before is None or tuple(before) != tuple(after):
                    repaired += 1

            if normalized is None:
                stale = conn.execute(
                    "SELECT task_id FROM resident_maintenance_investigations "
                    "WHERE source_task_status='open'"
                ).fetchall()
            elif not task_ids:
                stale = conn.execute(
                    "SELECT task_id FROM resident_maintenance_investigations "
                    "WHERE task_id=? AND source_task_status='open'",
                    (normalized,),
                ).fetchall()
            else:
                stale = []

            now = utc_now()
            for row in stale:
                stale_task_id = str(row["task_id"])
                if stale_task_id in task_ids:
                    continue
                conn.execute(
                    "UPDATE resident_maintenance_investigations SET "
                    "source_task_status='missing',status='closed',closed_at=?,"
                    "close_reason='maintenance_task_missing',updated_at=? WHERE task_id=?",
                    (now, now, stale_task_id),
                )
                repaired += 1
            conn.commit()
        return repaired

    def _get_without_reconcile(self, task_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT task_id,organ,task_fingerprint,failure_class,exception_type,"
                "source_task_status,status,authority,incident_started_at,last_seen_at,"
                "observed_occurrences,updated_at,closed_at,close_reason,baseline_ref,"
                "regression_oracle,attempt_count,acceptance_state,accepted_attempt_key "
                "FROM resident_maintenance_investigations WHERE task_id=?",
                (task_id,),
            ).fetchone()
        return self._snapshot(row) if row else None

    def _reconcile_task(self, conn: sqlite3.Connection, task: sqlite3.Row) -> None:
        task_id = str(task["task_id"])
        existing = conn.execute(
            "SELECT task_fingerprint,source_task_status,status FROM "
            "resident_maintenance_investigations WHERE task_id=?",
            (task_id,),
        ).fetchone()
        reset = bool(
            existing is None
            or str(existing["task_fingerprint"] or "") != str(task["fingerprint"] or "")
            or (
                str(task["status"] or "") == "open"
                and str(existing["source_task_status"] or "") != "open"
            )
        )
        if existing is None:
            conn.execute(
                "INSERT INTO resident_maintenance_investigations("
                "task_id,organ,task_fingerprint,failure_class,exception_type,"
                "source_task_status,status,authority,incident_started_at,last_seen_at,"
                "observed_occurrences,updated_at,closed_at,close_reason"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    str(task["organ"]),
                    str(task["fingerprint"]),
                    str(task["failure_class"]),
                    str(task["exception_type"]),
                    str(task["status"]),
                    "pending" if str(task["status"]) == "open" else "closed",
                    "evidence_only",
                    str(task["first_seen_at"]),
                    str(task["last_seen_at"]),
                    max(0, int(task["occurrences"] or 0)),
                    str(task["updated_at"]),
                    task["closed_at"],
                    task["close_reason"],
                ),
            )
            return

        if reset:
            conn.execute(
                "DELETE FROM resident_maintenance_attempts WHERE task_id=?",
                (task_id,),
            )
        conn.execute(
            "UPDATE resident_maintenance_investigations SET organ=?,task_fingerprint=?,"
            "failure_class=?,exception_type=?,source_task_status=?,"
            "status=CASE WHEN ?='open' THEN ? ELSE 'closed' END,"
            "incident_started_at=CASE WHEN ? THEN ? ELSE incident_started_at END,"
            "last_seen_at=?,observed_occurrences=?,updated_at=?,closed_at=?,close_reason=?,"
            "baseline_ref=CASE WHEN ? THEN NULL ELSE baseline_ref END,"
            "regression_oracle=CASE WHEN ? THEN NULL ELSE regression_oracle END,"
            "attempt_count=CASE WHEN ? THEN 0 ELSE attempt_count END,"
            "acceptance_state=CASE WHEN ? THEN 'unreviewed' ELSE acceptance_state END,"
            "accepted_attempt_key=CASE WHEN ? THEN NULL ELSE accepted_attempt_key END "
            "WHERE task_id=?",
            (
                str(task["organ"]),
                str(task["fingerprint"]),
                str(task["failure_class"]),
                str(task["exception_type"]),
                str(task["status"]),
                str(task["status"]),
                "pending" if reset else str(existing["status"]),
                1 if reset else 0,
                str(task["first_seen_at"]),
                str(task["last_seen_at"]),
                max(0, int(task["occurrences"] or 0)),
                str(task["updated_at"]),
                task["closed_at"],
                task["close_reason"],
                1 if reset else 0,
                1 if reset else 0,
                1 if reset else 0,
                1 if reset else 0,
                1 if reset else 0,
                task_id,
            ),
        )

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "task_id": str(row["task_id"]),
            "organ": str(row["organ"]),
            "task_fingerprint": str(row["task_fingerprint"]),
            "failure_class": str(row["failure_class"]),
            "exception_type": str(row["exception_type"]),
            "source_task_status": str(row["source_task_status"]),
            "status": str(row["status"]),
            "authority": str(row["authority"]),
            "incident_started_at": row["incident_started_at"],
            "last_seen_at": row["last_seen_at"],
            "observed_occurrences": max(0, int(row["observed_occurrences"] or 0)),
            "updated_at": row["updated_at"],
            "closed_at": row["closed_at"],
            "close_reason": row["close_reason"],
            "baseline_ref": row["baseline_ref"],
            "regression_oracle": row["regression_oracle"],
            "attempt_count": max(0, int(row["attempt_count"] or 0)),
            "acceptance_state": str(row["acceptance_state"]),
            "accepted_attempt_key": row["accepted_attempt_key"],
        }

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            # Development versions briefly used triggers for eager projection.
            # Remove them if a developer DB ever saw that schema: secondary
            # maintenance state must not participate in authoritative task writes.
            conn.executescript(
                """
                DROP TRIGGER IF EXISTS zn_maintenance_investigation_task_insert;
                DROP TRIGGER IF EXISTS zn_maintenance_investigation_attempt_reset;
                DROP TRIGGER IF EXISTS zn_maintenance_investigation_task_update;
                CREATE TABLE IF NOT EXISTS resident_maintenance_investigations(
                    task_id TEXT PRIMARY KEY,
                    organ TEXT NOT NULL,
                    task_fingerprint TEXT NOT NULL,
                    failure_class TEXT NOT NULL,
                    exception_type TEXT NOT NULL,
                    source_task_status TEXT NOT NULL,
                    status TEXT NOT NULL,
                    authority TEXT NOT NULL DEFAULT 'evidence_only',
                    incident_started_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    observed_occurrences INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    closed_at TEXT,
                    close_reason TEXT,
                    baseline_ref TEXT,
                    regression_oracle TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    acceptance_state TEXT NOT NULL DEFAULT 'unreviewed',
                    accepted_attempt_key TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_resident_maintenance_investigation_status
                    ON resident_maintenance_investigations(source_task_status,status,updated_at);
                CREATE TABLE IF NOT EXISTS resident_maintenance_attempts(
                    task_id TEXT NOT NULL,
                    attempt_key TEXT NOT NULL,
                    branch_ref TEXT NOT NULL,
                    regression_passed INTEGER NOT NULL,
                    evidence_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(task_id,attempt_key),
                    FOREIGN KEY(task_id) REFERENCES resident_maintenance_investigations(task_id)
                );
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _task_id(value: str) -> str:
        task_id = str(value or "").strip()
        if not task_id:
            raise ValueError("maintenance task_id must not be empty")
        return task_id[:256]

    @staticmethod
    def _required_ref(value: str, field: str) -> str:
        ref = str(value or "").strip()
        if not ref:
            raise ValueError(f"{field} must not be empty")
        if "\n" in ref or "\r" in ref:
            raise ValueError(f"{field} must be a single bounded reference")
        if len(ref) > _MAX_REF:
            raise ValueError(f"{field} is too long")
        return ref
