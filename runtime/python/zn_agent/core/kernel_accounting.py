from __future__ import annotations

"""Exactly-once accounting for durable external cognition attempts."""

import json
import sqlite3
from contextlib import closing

from .models import Assessment, utc_now
from .self_model import SelfModel


class KernelAttemptAccountingJournal:
    """Commit route-quality evidence once for one durable kernel attempt.

    External cognition may be resumed after a process crash from an already
    observed worker result. Route learning is therefore keyed by the durable
    goal/attempt identity instead of being applied as an in-memory side effect.
    """

    TABLE = "kernel_attempt_accounting"

    def __init__(self, store):
        self.store = store
        self._init_schema()

    def record_external_route_assessment(
        self,
        *,
        goal_id: str,
        attempt: int,
        route_id: str,
        task: str,
        required_capabilities: tuple[str, ...],
        assessment: Assessment,
    ) -> bool:
        normalized_goal = str(goal_id or "").strip()
        normalized_route = str(route_id or "").strip()
        normalized_attempt = int(attempt)
        if not normalized_goal:
            raise ValueError("kernel accounting requires goal_id")
        if normalized_attempt < 1:
            raise ValueError("kernel accounting requires a positive attempt number")
        if not normalized_route:
            raise ValueError("kernel accounting requires route_id")

        sample = max(0.0, min(1.0, float(assessment.quality)))
        if not assessment.success:
            sample = min(sample, 0.35)
        domains = SelfModel.infer_domains(task, required_capabilities)
        now = utc_now()
        accounting_kind = "external_route_assessment"

        with closing(self._connect()) as conn:
            inserted = conn.execute(
                f"INSERT OR IGNORE INTO {self.TABLE}"
                "(goal_id,attempt,kind,created_at) VALUES(?,?,?,?)",
                (normalized_goal, normalized_attempt, accounting_kind, now),
            )
            if inserted.rowcount == 1:
                for domain in domains:
                    self._update_capability_estimate(
                        conn,
                        SelfModel.route_capability_key(normalized_route, domain),
                        sample,
                        now,
                    )
            conn.commit()
        return inserted.rowcount == 1

    def has_record(self, goal_id: str, attempt: int, kind: str) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT 1 FROM {self.TABLE} WHERE goal_id=? AND attempt=? AND kind=?",
                (str(goal_id or "").strip(), int(attempt), str(kind or "").strip()),
            ).fetchone()
        return row is not None

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE}(
                    goal_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(goal_id,attempt,kind)
                )
                """
            )
            conn.commit()

    @staticmethod
    def _update_capability_estimate(
        conn: sqlite3.Connection,
        key: str,
        sample: float,
        now: str,
    ) -> None:
        row = conn.execute(
            "SELECT data FROM capabilities WHERE name=?",
            (key,),
        ).fetchone()
        if row is None:
            old_score = 0.0
            old_n = 0
        else:
            try:
                raw = json.loads(row["data"])
                old_score = float(raw.get("score", 0.0))
                old_n = max(0, int(raw.get("evidence_count", 0)))
            except (TypeError, ValueError, json.JSONDecodeError):
                old_score = 0.0
                old_n = 0

        evidence_count = old_n + 1
        score = ((old_score * old_n) + sample) / evidence_count
        data = {
            "name": key,
            "score": score,
            "evidence_count": evidence_count,
            "confidence": min(0.99, evidence_count / (evidence_count + 3.0)),
            "updated_at": now,
        }
        conn.execute(
            "INSERT OR REPLACE INTO capabilities(name,data) VALUES(?,?)",
            (key, json.dumps(data, ensure_ascii=False, separators=(",", ":"))),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
