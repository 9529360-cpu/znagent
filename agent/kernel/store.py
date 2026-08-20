from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from .models import (
    AgentEvent, AgentIdentity, Assessment, CapabilityEstimate, EventStatus,
    Experience, Goal, GoalStatus, ImprovementProposal, ProposalStatus,
    RuntimeMetrics, WorkingState, utc_now,
)


class KernelStore:
    """Compact durable store for the resident agent's actual state."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS identity(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS goals(goal_id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS experiences(experience_id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS capabilities(name TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS proposals(proposal_id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY, status TEXT NOT NULL, priority INTEGER NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_events_queue ON events(status, priority DESC, created_at ASC);
            CREATE TABLE IF NOT EXISTS working_state(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS facts(fact_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, aliases_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runtime_metrics(id INTEGER PRIMARY KEY CHECK(id=1), tasks_total INTEGER NOT NULL DEFAULT 0, tasks_model INTEGER NOT NULL DEFAULT 0, model_invocations INTEGER NOT NULL DEFAULT 0, prompt_tokens INTEGER NOT NULL DEFAULT 0, completion_tokens INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS resident_lease(id INTEGER PRIMARY KEY CHECK(id=1), instance_id TEXT NOT NULL, pid INTEGER NOT NULL, hostname TEXT NOT NULL, started_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL);
            """)
            self._conn.execute(
                "INSERT OR IGNORE INTO runtime_metrics VALUES(1,0,0,0,0,0,?)",
                (utc_now(),),
            )

    @staticmethod
    def _dump(data: dict[str, Any]) -> str:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    def get_or_create_identity(self, default: AgentIdentity | None = None) -> AgentIdentity:
        with self._lock:
            row = self._conn.execute("SELECT data FROM identity WHERE id=1").fetchone()
        if row:
            d = json.loads(row["data"])
            d["principles"] = tuple(d.get("principles") or ())
            return AgentIdentity(**d)
        identity = default or AgentIdentity()
        self._save_identity(identity)
        return identity

    def _save_identity(self, identity: AgentIdentity) -> None:
        data = {
            "name": identity.name, "version": identity.version, "purpose": identity.purpose,
            "principles": list(identity.principles), "created_at": identity.created_at,
            "updated_at": identity.updated_at,
        }
        with self._lock, self._conn:
            self._conn.execute("INSERT OR REPLACE INTO identity(id,data) VALUES(1,?)", (self._dump(data),))

    def save_goal(self, goal: Goal) -> None:
        goal.updated_at = utc_now()
        data = {
            "goal_id": goal.goal_id, "task": goal.task,
            "required_capabilities": list(goal.required_capabilities), "priority": goal.priority,
            "status": goal.status.value, "attempts": goal.attempts, "route_id": goal.route_id,
            "metadata": goal.metadata, "created_at": goal.created_at, "updated_at": goal.updated_at,
        }
        with self._lock, self._conn:
            self._conn.execute("INSERT OR REPLACE INTO goals(goal_id,data) VALUES(?,?)", (goal.goal_id, self._dump(data)))

    def get_goal(self, goal_id: str) -> Goal | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM goals WHERE goal_id=?", (goal_id,)).fetchone()
        if not row:
            return None
        d = json.loads(row["data"])
        d["required_capabilities"] = tuple(d.get("required_capabilities") or ("general",))
        d["status"] = GoalStatus(d["status"])
        return Goal(**d)

    def add_experience(self, exp: Experience) -> None:
        data = {
            "experience_id": exp.experience_id, "goal_id": exp.goal_id, "route_id": exp.route_id,
            "task": exp.task, "required_capabilities": list(exp.required_capabilities),
            "assessment": {"success": exp.assessment.success, "quality": exp.assessment.quality,
                           "confidence": exp.assessment.confidence, "reasons": list(exp.assessment.reasons)},
            "response_excerpt": exp.response_excerpt, "error": exp.error,
            "metrics": exp.metrics, "created_at": exp.created_at,
        }
        with self._lock, self._conn:
            self._conn.execute("INSERT OR REPLACE INTO experiences(experience_id,goal_id,data) VALUES(?,?,?)", (exp.experience_id, exp.goal_id, self._dump(data)))

    def save_capability(self, cap: CapabilityEstimate) -> None:
        cap.updated_at = utc_now()
        data = {"name": cap.name, "score": cap.score, "evidence_count": cap.evidence_count,
                "confidence": cap.confidence, "updated_at": cap.updated_at}
        with self._lock, self._conn:
            self._conn.execute("INSERT OR REPLACE INTO capabilities(name,data) VALUES(?,?)", (cap.name, self._dump(data)))

    def get_capability(self, name: str) -> CapabilityEstimate | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM capabilities WHERE name=?", (name,)).fetchone()
        return CapabilityEstimate(**json.loads(row["data"])) if row else None

    def list_capabilities(self) -> list[CapabilityEstimate]:
        with self._lock:
            rows = self._conn.execute("SELECT data FROM capabilities ORDER BY name").fetchall()
        return [CapabilityEstimate(**json.loads(r["data"])) for r in rows]

    def add_proposal(self, p: ImprovementProposal) -> None:
        data = {"proposal_id": p.proposal_id, "goal_id": p.goal_id, "capability": p.capability,
                "hypothesis": p.hypothesis, "experiment": p.experiment, "scope": p.scope,
                "benchmark_required": p.benchmark_required, "status": p.status.value,
                "created_at": p.created_at}
        with self._lock, self._conn:
            self._conn.execute("INSERT OR REPLACE INTO proposals(proposal_id,goal_id,data) VALUES(?,?,?)", (p.proposal_id, p.goal_id, self._dump(data)))

    def list_proposals(self, statuses: Iterable[ProposalStatus] | None = None) -> list[ImprovementProposal]:
        wanted = {s.value if isinstance(s, ProposalStatus) else str(s) for s in statuses or ()}
        with self._lock:
            rows = self._conn.execute("SELECT data FROM proposals ORDER BY rowid DESC").fetchall()
        out = []
        for row in rows:
            d = json.loads(row["data"])
            if wanted and d["status"] not in wanted:
                continue
            d["status"] = ProposalStatus(d["status"])
            out.append(ImprovementProposal(**d))
        return out

    def enqueue_event(self, event: AgentEvent) -> None:
        self._save_event(event)

    def _save_event(self, event: AgentEvent) -> None:
        event.updated_at = utc_now()
        data = {"event_id": event.event_id, "task": event.task, "kind": event.kind,
                "priority": event.priority, "payload": event.payload, "status": event.status.value,
                "attempts": event.attempts, "last_error": event.last_error,
                "created_at": event.created_at, "updated_at": event.updated_at}
        with self._lock, self._conn:
            self._conn.execute("INSERT OR REPLACE INTO events(event_id,status,priority,created_at,data) VALUES(?,?,?,?,?)", (event.event_id, event.status.value, event.priority, event.created_at, self._dump(data)))

    def get_event(self, event_id: str) -> AgentEvent | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM events WHERE event_id=?", (event_id,)).fetchone()
        return self._event_from_data(row["data"]) if row else None

    @staticmethod
    def _event_from_data(raw: str) -> AgentEvent:
        d = json.loads(raw)
        d["status"] = EventStatus(d["status"])
        return AgentEvent(**d)

    def peek_next_event(self) -> AgentEvent | None:
        """Return the event ZN would act on next without claiming it."""
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM events WHERE status=? ORDER BY priority DESC, created_at ASC LIMIT 1",
                (EventStatus.PENDING.value,),
            ).fetchone()
        return self._event_from_data(row["data"]) if row else None

    def claim_event(self, event_id: str) -> AgentEvent | None:
        """Claim one exact pending event selected by the resident's ThoughtFrame."""
        event_id = str(event_id or "").strip()
        if not event_id:
            return None
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT data FROM events WHERE event_id=? AND status=?",
                (event_id, EventStatus.PENDING.value),
            ).fetchone()
            if not row:
                return None
            event = self._event_from_data(row["data"])
            event.status = EventStatus.PROCESSING
            event.attempts += 1
            self._save_event(event)
            return event

    def claim_next_event(self) -> AgentEvent | None:
        next_event = self.peek_next_event()
        if next_event is None:
            return None
        return self.claim_event(next_event.event_id)

    def finish_event(self, event_id: str, *, success: bool, error: str | None = None) -> None:
        event = self.get_event(event_id)
        if not event:
            return
        event.status = EventStatus.COMPLETED if success else EventStatus.FAILED
        event.last_error = error
        self._save_event(event)

    def recover_interrupted_events(self) -> int:
        with self._lock:
            rows = self._conn.execute("SELECT data FROM events WHERE status=?", (EventStatus.PROCESSING.value,)).fetchall()
        for row in rows:
            event = self._event_from_data(row["data"])
            event.status = EventStatus.PENDING
            event.last_error = event.last_error or "resident runtime restarted during processing"
            self._save_event(event)
        return len(rows)

    def list_events(self, status: EventStatus | None = None, limit: int = 100) -> list[AgentEvent]:
        sql, params = "SELECT data FROM events", []
        if status is not None:
            sql += " WHERE status=?"
            params.append(status.value)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._event_from_data(r["data"]) for r in rows]

    def save_working_state(self, state: WorkingState) -> None:
        state.updated_at = utc_now()
        data = {"current_event_id": state.current_event_id, "current_goal_id": state.current_goal_id,
                "stage": state.stage, "next_action": state.next_action, "blocked_by": state.blocked_by,
                "data": state.data, "updated_at": state.updated_at}
        with self._lock, self._conn:
            self._conn.execute("INSERT OR REPLACE INTO working_state(id,data) VALUES(1,?)", (self._dump(data),))

    def get_working_state(self) -> WorkingState:
        with self._lock:
            row = self._conn.execute("SELECT data FROM working_state WHERE id=1").fetchone()
        if row:
            return WorkingState(**json.loads(row["data"]))
        state = WorkingState()
        self.save_working_state(state)
        return state

    def put_fact(self, key: str, value: Any, *, aliases: tuple[str, ...] = ()) -> None:
        key = str(key or "").strip()
        if not key:
            raise ValueError("fact key must not be empty")
        now = utc_now()
        with self._lock, self._conn:
            existing = self._conn.execute("SELECT created_at FROM facts WHERE fact_key=?", (key,)).fetchone()
            created = existing["created_at"] if existing else now
            self._conn.execute("INSERT OR REPLACE INTO facts VALUES(?,?,?,?,?)", (key, json.dumps(value, ensure_ascii=False), json.dumps(list(aliases), ensure_ascii=False), created, now))

    def get_fact(self, key: str) -> Any | None:
        with self._lock:
            row = self._conn.execute("SELECT value_json FROM facts WHERE fact_key=?", (key,)).fetchone()
        return json.loads(row["value_json"]) if row else None

    def list_facts(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM facts ORDER BY fact_key").fetchall()
        return [{"key": r["fact_key"], "value": json.loads(r["value_json"]),
                 "aliases": tuple(json.loads(r["aliases_json"])), "created_at": r["created_at"],
                 "updated_at": r["updated_at"]} for r in rows]

    def delete_fact(self, key: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM facts WHERE fact_key=?", (key,))

    def record_runtime_task(self, *, model_invocations: int, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        inv = max(0, int(model_invocations))
        with self._lock, self._conn:
            self._conn.execute("""UPDATE runtime_metrics SET tasks_total=tasks_total+1,
                tasks_model=tasks_model+?, model_invocations=model_invocations+?,
                prompt_tokens=prompt_tokens+?, completion_tokens=completion_tokens+?, updated_at=? WHERE id=1""",
                (1 if inv else 0, inv, max(0, int(prompt_tokens)), max(0, int(completion_tokens)), utc_now()))

    def get_runtime_metrics(self) -> RuntimeMetrics:
        with self._lock:
            r = self._conn.execute("SELECT * FROM runtime_metrics WHERE id=1").fetchone()
        return RuntimeMetrics(tasks_total=r["tasks_total"], tasks_model=r["tasks_model"],
            model_invocations=r["model_invocations"], prompt_tokens=r["prompt_tokens"],
            completion_tokens=r["completion_tokens"], updated_at=r["updated_at"])

    def claim_resident_lease(self, *, instance_id: str, pid: int, hostname: str, stale_after_seconds: float = 30.0) -> bool:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        with self._lock, self._conn:
            row = self._conn.execute("SELECT * FROM resident_lease WHERE id=1").fetchone()
            if row and row["instance_id"] != instance_id:
                try:
                    heartbeat = datetime.fromisoformat(row["heartbeat_at"])
                    if heartbeat.tzinfo is None:
                        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
                    if (now - heartbeat).total_seconds() <= max(1.0, float(stale_after_seconds)):
                        return False
                except Exception:
                    pass
            text = now.isoformat()
            self._conn.execute("INSERT OR REPLACE INTO resident_lease VALUES(1,?,?,?,?,?)", (instance_id, int(pid), hostname, text, text))
            return True

    def heartbeat_resident_lease(self, instance_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("UPDATE resident_lease SET heartbeat_at=? WHERE id=1 AND instance_id=?", (utc_now(), instance_id))
            return bool(cur.rowcount)

    def release_resident_lease(self, instance_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM resident_lease WHERE id=1 AND instance_id=?", (instance_id,))

    def get_resident_lease(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM resident_lease WHERE id=1").fetchone()
        return dict(row) if row else None
