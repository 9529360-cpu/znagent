from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import threading
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .models import AgentEvent, utc_now
from .self_model import TaskReadiness

if TYPE_CHECKING:
    from .resident import ZNResidentRuntime


@dataclass(slots=True)
class InvestigationState:
    """Durable record of ZN checking its own world before borrowing cognition."""

    investigation_id: str
    event_id: str
    task: str
    domains: tuple[str, ...]
    started_at: str
    updated_at: str
    hypotheses: tuple[str, ...] = ()
    probes: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)
    unresolved: str | None = None
    rounds: int = 0
    status: str = "open"
    resolution: str | None = None


@dataclass(slots=True)
class InvestigationResult:
    state: InvestigationState
    resolved: bool = False
    response: str = ""


class NativeInvestigator:
    """ZN's first native observe-check-update loop.

    This is not a planner and it does not call a model. It lets the resident use
    facts available from its own body and computer environment to test simple
    hypotheses before declaring an impasse. The first probes are intentionally
    small and generic; more body abilities can be added without changing the
    cognitive loop.
    """

    def __init__(self, resident: ZNResidentRuntime):
        self.resident = resident
        self.store = resident.store
        self._lock = threading.RLock()
        self._init_schema()

    def investigate(
        self,
        event: AgentEvent,
        readiness: TaskReadiness,
        *,
        learning_evidence: list[dict[str, Any]] | None = None,
        local_failure: str | None = None,
    ) -> InvestigationResult:
        previous = self._load_for_event(event.event_id)
        now = utc_now()
        hypotheses = list(previous.hypotheses if previous else ())
        probes = list(previous.probes if previous else ())
        evidence = list(previous.evidence if previous else ())
        facts = dict(previous.facts if previous else {})

        def add_hypothesis(text: str) -> None:
            value = str(text or "").strip()
            if value and value not in hypotheses:
                hypotheses.append(value)

        def add_probe(text: str) -> None:
            value = str(text or "").strip()
            if value and value not in probes:
                probes.append(value)

        def add_evidence(text: str) -> None:
            value = str(text or "").strip()
            if value and value not in evidence:
                evidence.append(value)

        if local_failure:
            add_hypothesis("the observed local failure identifies the immediate blocking condition")
        elif learning_evidence:
            add_hypothesis("a related prior resolution may contain a reusable pattern")
        elif readiness.posture == "familiar":
            add_hypothesis("retained domain knowledge may be enough once the current environment is inspected")
        elif readiness.posture == "partial":
            add_hypothesis("partial domain knowledge can narrow the problem after checking concrete state")
        else:
            add_hypothesis("the first useful step is to acquire concrete facts from the current environment")

        body = self.resident.life.snapshot().body
        if body is not None:
            add_probe("inspect resident body state")
            facts["body"] = {
                "hostname": body.hostname,
                "pid": body.pid,
                "cwd": body.cwd,
                "system": body.system,
                "architecture": body.architecture,
                "disk_free_ratio": body.disk_free_ratio,
            }
            add_evidence(
                f"body: host={body.hostname}; pid={body.pid}; cwd={body.cwd}; "
                f"system={body.system}; disk_free={body.disk_free_ratio:.3f}"
            )

        path_facts = self._inspect_paths(event)
        if path_facts:
            add_probe("inspect referenced filesystem paths")
            facts["paths"] = path_facts
            for item in path_facts:
                add_evidence(
                    "path: "
                    f"{item['path']} exists={item['exists']} type={item.get('type', 'missing')} "
                    f"size={item.get('size_bytes', 0)}"
                )

        git_fact = self._inspect_git(event, readiness)
        if git_fact is not None:
            add_probe("inspect current git workspace")
            facts["git"] = git_fact
            add_evidence(
                "git: "
                f"root={git_fact.get('root')}; branch={git_fact.get('branch')}; "
                f"dirty={git_fact.get('dirty')}; changed_files={git_fact.get('changed_files')}"
            )

        process_facts = self._inspect_processes(event)
        if process_facts:
            add_probe("inspect referenced process state")
            facts["processes"] = process_facts
            for item in process_facts:
                add_evidence(f"process: pid={item['pid']} alive={item['alive']}")

        if learning_evidence:
            add_probe("compare with related resident-side experience")
            add_evidence(f"related experience records available: {len(learning_evidence)}")

        response = self._answer_from_native_facts(event, facts)
        resolved = bool(response)
        unresolved = None if resolved else self._remaining_unknown(
            readiness,
            local_failure=local_failure,
            learning_evidence=learning_evidence or [],
            evidence=evidence,
        )

        state = InvestigationState(
            investigation_id=(
                previous.investigation_id
                if previous is not None
                else f"inv-{uuid.uuid4().hex[:12]}"
            ),
            event_id=event.event_id,
            task=event.task,
            domains=tuple(readiness.domains),
            started_at=previous.started_at if previous is not None else now,
            updated_at=now,
            hypotheses=tuple(hypotheses[-16:]),
            probes=tuple(probes[-32:]),
            evidence=tuple(evidence[-64:]),
            facts=facts,
            unresolved=unresolved,
            rounds=(previous.rounds if previous else 0) + 1,
            status="resolved" if resolved else "open",
            resolution=response or None,
        )
        self._save(state)
        return InvestigationResult(state=state, resolved=resolved, response=response)

    def resolve_from_external(self, event_id: str, summary: str) -> None:
        state = self._load_for_event(event_id)
        if state is None:
            return
        state.updated_at = utc_now()
        state.status = "resolved_external"
        state.resolution = str(summary or "external cognition resolved the remaining gap")[:1000]
        state.unresolved = None
        state.evidence = (*state.evidence, "remaining gap resolved with external cognition")[-64:]
        self._save(state)

    def recent(self, limit: int = 20) -> list[InvestigationState]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT data FROM native_investigations ORDER BY updated_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [self._from_raw(json.loads(row["data"])) for row in rows]

    @staticmethod
    def bounded_evidence(result: InvestigationResult, limit: int = 6) -> list[str]:
        """Return compact observations that can help resolve the remaining gap."""
        if result.resolved:
            return []
        return list(result.state.evidence[-max(1, int(limit)):])

    def _load_for_event(self, event_id: str) -> InvestigationState | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT data FROM native_investigations WHERE event_id=? "
                "ORDER BY updated_at DESC LIMIT 1",
                (event_id,),
            ).fetchone()
        if not row:
            return None
        return self._from_raw(json.loads(row["data"]))

    def _save(self, state: InvestigationState) -> None:
        payload = asdict(state)
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO native_investigations"
                "(investigation_id,event_id,status,updated_at,data) VALUES(?,?,?,?,?)",
                (
                    state.investigation_id,
                    state.event_id,
                    state.status,
                    state.updated_at,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            conn.commit()

    def _init_schema(self) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS native_investigations(
                    investigation_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_native_investigations_event
                    ON native_investigations(event_id, updated_at DESC);
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @staticmethod
    def _from_raw(raw: dict[str, Any]) -> InvestigationState:
        data = dict(raw)
        for key in ("domains", "hypotheses", "probes", "evidence"):
            data[key] = tuple(data.get(key) or ())
        data["facts"] = dict(data.get("facts") or {})
        return InvestigationState(**data)

    def _inspect_paths(self, event: AgentEvent) -> list[dict[str, Any]]:
        candidates: list[str] = []
        for key in ("path", "file", "directory", "workspace_path", "project_path", "repo_path"):
            value = event.payload.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
        paths_value = event.payload.get("paths")
        if isinstance(paths_value, (list, tuple)):
            candidates.extend(str(item).strip() for item in paths_value if str(item).strip())

        for token in re.findall(r"(?:[A-Za-z]:[\\/][^\s'\"]+|(?:\.{0,2}/|/)[^\s'\"]+)", event.task):
            candidates.append(token.rstrip(".,;:!?)]}"))

        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for raw in candidates:
            if raw in seen or len(result) >= 6:
                continue
            seen.add(raw)
            path = Path(raw).expanduser()
            try:
                stat = path.stat()
                if path.is_file():
                    kind = "file"
                elif path.is_dir():
                    kind = "directory"
                else:
                    kind = "other"
                result.append(
                    {
                        "path": str(path),
                        "exists": True,
                        "type": kind,
                        "size_bytes": int(stat.st_size),
                        "mtime": float(stat.st_mtime),
                    }
                )
            except OSError:
                result.append({"path": str(path), "exists": False, "type": "missing"})
        return result

    def _inspect_git(
        self,
        event: AgentEvent,
        readiness: TaskReadiness,
    ) -> dict[str, Any] | None:
        text = event.task.lower()
        domain_relevant = any(domain.startswith("it/") or domain == "it" for domain in readiness.domains)
        task_relevant = any(
            word in text
            for word in ("git", "repo", "repository", "workspace", "project", "code", "debug", "build", "test")
        )
        if not domain_relevant and not task_relevant:
            return None

        raw_workspace = (
            event.payload.get("workspace_path")
            or event.payload.get("project_path")
            or event.payload.get("repo_path")
        )
        body = self.resident.life.snapshot().body
        workspace = Path(str(raw_workspace)).expanduser() if raw_workspace else Path(body.cwd if body else os.getcwd())
        try:
            root_proc = subprocess.run(
                ["git", "-C", str(workspace), "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if root_proc.returncode != 0:
            return None
        root = root_proc.stdout.strip()
        if not root:
            return None

        branch = ""
        status_lines: list[str] = []
        try:
            branch_proc = subprocess.run(
                ["git", "-C", root, "branch", "--show-current"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if branch_proc.returncode == 0:
                branch = branch_proc.stdout.strip()
            status_proc = subprocess.run(
                ["git", "-C", root, "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if status_proc.returncode == 0:
                status_lines = [line for line in status_proc.stdout.splitlines() if line.strip()]
        except (OSError, subprocess.SubprocessError):
            pass
        return {
            "root": root,
            "branch": branch,
            "dirty": bool(status_lines),
            "changed_files": len(status_lines),
        }

    def _inspect_processes(self, event: AgentEvent) -> list[dict[str, Any]]:
        candidates: list[int] = []
        for key in ("pid", "process_pid"):
            value = event.payload.get(key)
            try:
                if value is not None:
                    candidates.append(int(value))
            except (TypeError, ValueError):
                pass
        for raw in re.findall(r"\bpid\s*[:=#]?\s*(\d+)\b", event.task, flags=re.IGNORECASE):
            try:
                candidates.append(int(raw))
            except ValueError:
                pass

        result: list[dict[str, Any]] = []
        for pid in dict.fromkeys(candidates):
            if pid <= 0 or len(result) >= 4:
                continue
            alive = True
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                alive = False
            except PermissionError:
                alive = True
            except OSError:
                alive = False
            result.append({"pid": pid, "alive": alive})
        return result

    @staticmethod
    def _answer_from_native_facts(event: AgentEvent, facts: dict[str, Any]) -> str:
        text = event.task.strip().lower()
        body = facts.get("body") if isinstance(facts.get("body"), dict) else {}
        git = facts.get("git") if isinstance(facts.get("git"), dict) else {}
        paths = facts.get("paths") if isinstance(facts.get("paths"), list) else []
        processes = facts.get("processes") if isinstance(facts.get("processes"), list) else []

        if any(phrase in text for phrase in ("current working directory", "what is my cwd", "what's my cwd", "当前工作目录", "当前目录")):
            value = body.get("cwd")
            if value:
                return str(value)

        if any(phrase in text for phrase in ("my current pid", "my pid", "resident pid", "当前 pid", "进程 id")):
            value = body.get("pid")
            if value is not None:
                return str(value)

        if any(phrase in text for phrase in ("hostname", "host name", "主机名")):
            value = body.get("hostname")
            if value:
                return str(value)

        if any(phrase in text for phrase in ("current git branch", "what branch", "git branch", "当前分支")):
            value = git.get("branch")
            if value:
                return str(value)

        if paths and any(phrase in text for phrase in ("exist", "exists", "存在", "有没有")):
            if len(paths) == 1:
                item = paths[0]
                return f"{item['path']}: {'exists' if item['exists'] else 'does not exist'}"

        if processes and any(phrase in text for phrase in ("alive", "running", "还在运行", "存活")):
            if len(processes) == 1:
                item = processes[0]
                return f"pid {item['pid']}: {'alive' if item['alive'] else 'not running'}"
        return ""

    @staticmethod
    def _remaining_unknown(
        readiness: TaskReadiness,
        *,
        local_failure: str | None,
        learning_evidence: list[dict[str, Any]],
        evidence: list[str],
    ) -> str:
        if local_failure:
            return (
                "I observed the environment and still need to determine the smallest "
                f"cause or procedure that resolves this local failure: {local_failure}"
            )
        if learning_evidence and readiness.posture in {"familiar", "partial"}:
            return (
                "I inspected my current environment and related experience, but the "
                "remaining difference for this case is not yet explained by my native knowledge"
            )
        if readiness.posture == "familiar":
            return (
                "I know this domain and inspected concrete local state, but I still lack "
                "the native procedure needed to complete this specific task"
            )
        if readiness.posture == "partial":
            return (
                "I acquired concrete local evidence, but my retained understanding is "
                "still insufficient to derive the next reliable action"
            )
        if evidence:
            return (
                "I acquired concrete facts from my environment, but I still need the "
                "first missing concept or procedure that connects them to the task"
            )
        return "I still lack the first concrete fact or procedure needed to make progress"
