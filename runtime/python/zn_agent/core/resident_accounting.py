from __future__ import annotations

"""Event-idempotent resident accounting for crash-recoverable native results."""

import json
import sqlite3
from contextlib import closing

from .models import utc_now
from .self_model import SelfModel


class ResidentAccountingJournal:
    """Commit self evidence once for one durable resident event fact.

    Crash-recoverable resident paths persist their semantic result before this
    accounting runs. If the process dies after an accounting transaction but
    before terminal publication or the next WorkingState checkpoint, restart may
    safely call the same method again: the event/kind key makes the second call a
    no-op rather than duplicating self-model evidence or task totals.
    """

    TABLE = "resident_event_accounting"

    def __init__(self, store):
        self.store = store
        self._init_schema()

    def record_native_capability_success(
        self,
        *,
        event_id: str,
        task: str,
        required_capabilities: tuple[str, ...],
        quality: float,
    ) -> tuple[str, ...]:
        normalized_event = str(event_id or "").strip()
        if not normalized_event:
            raise ValueError("resident accounting requires event_id")
        domains = SelfModel.infer_domains(task, required_capabilities)
        sample = max(0.0, min(1.0, float(quality)))
        accounting_kind = "native_capability_success"
        now = utc_now()

        with closing(self._connect()) as conn:
            inserted = conn.execute(
                f"INSERT OR IGNORE INTO {self.TABLE}(event_id,kind,created_at) VALUES(?,?,?)",
                (normalized_event, accounting_kind, now),
            )
            if inserted.rowcount == 1:
                for domain in domains:
                    self._update_capability_estimate(
                        conn,
                        SelfModel.agent_capability_key(domain),
                        sample,
                        now,
                    )
                    self._update_capability_estimate(
                        conn,
                        SelfModel.knowledge_key(domain),
                        sample,
                        now,
                    )
                conn.execute(
                    "UPDATE runtime_metrics SET tasks_total=tasks_total+1, updated_at=? WHERE id=1",
                    (now,),
                )
            conn.commit()
        return domains

    def record_native_capability_failure(
        self,
        *,
        event_id: str,
        task: str,
        required_capabilities: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Record one observed compiled-capability failure without ending the task.

        A compiled capability can fail and then hand the same event to native
        investigation. That failure is still evidence about independent ability,
        but it must not increment completed-task accounting and must not be
        learned twice when restart resumes an already observed durable result.
        """
        normalized_event = str(event_id or "").strip()
        if not normalized_event:
            raise ValueError("resident accounting requires event_id")
        domains = SelfModel.infer_domains(task, required_capabilities)
        accounting_kind = "native_capability_failure"
        now = utc_now()

        with closing(self._connect()) as conn:
            inserted = conn.execute(
                f"INSERT OR IGNORE INTO {self.TABLE}(event_id,kind,created_at) VALUES(?,?,?)",
                (normalized_event, accounting_kind, now),
            )
            if inserted.rowcount == 1:
                for domain in domains:
                    self._update_capability_estimate(
                        conn,
                        SelfModel.agent_capability_key(domain),
                        0.0,
                        now,
                    )
            conn.commit()
        return domains

    def record_terminal_failure(
        self,
        *,
        event_id: str,
        model_invocations: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> bool:
        """Count one durable terminal failure exactly once for the resident event.

        This preserves the existing terminal-failure semantics: a budget/exception
        failure counts as one attempted task but does not invent native ability or
        knowledge evidence. The caller must persist the failure checkpoint before
        invoking this method so a restart can reconstruct the same terminal fact.
        """
        normalized_event = str(event_id or "").strip()
        if not normalized_event:
            raise ValueError("resident accounting requires event_id")
        invocations = max(0, int(model_invocations))
        prompt = max(0, int(prompt_tokens))
        completion = max(0, int(completion_tokens))
        accounting_kind = "terminal_failure"
        now = utc_now()

        with closing(self._connect()) as conn:
            inserted = conn.execute(
                f"INSERT OR IGNORE INTO {self.TABLE}(event_id,kind,created_at) VALUES(?,?,?)",
                (normalized_event, accounting_kind, now),
            )
            if inserted.rowcount == 1:
                conn.execute(
                    "UPDATE runtime_metrics SET "
                    "tasks_total=tasks_total+1, "
                    "tasks_model=tasks_model+?, "
                    "model_invocations=model_invocations+?, "
                    "prompt_tokens=prompt_tokens+?, "
                    "completion_tokens=completion_tokens+?, "
                    "updated_at=? WHERE id=1",
                    (
                        1 if invocations else 0,
                        invocations,
                        prompt,
                        completion,
                        now,
                    ),
                )
            conn.commit()
        return inserted.rowcount == 1

    def has_record(self, event_id: str, kind: str) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT 1 FROM {self.TABLE} WHERE event_id=? AND kind=?",
                (str(event_id or "").strip(), str(kind or "").strip()),
            ).fetchone()
        return row is not None

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE}(
                    event_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(event_id,kind)
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