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
    """Durable record of ZN testing hypotheses against its own world."""

    investigation_id: str
    event_id: str
    task: str
    domains: tuple[str, ...]
    started_at: str
    updated_at: str
    hypotheses: tuple[str, ...] = ()
    probes: tuple[str, ...] = ()
    probe_keys: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)
    unresolved: str | None = None
    next_probe: str | None = None
    rounds: int = 0
    status: str = "open"
    resolution: str | None = None


@dataclass(slots=True)
class InvestigationResult:
    state: InvestigationState
    resolved: bool = False
    response: str = ""
    can_continue: bool = False
    performed_probe: str | None = None


class NativeInvestigator:
    """Native hypothesis -> probe -> evidence loop.

    One call advances one concrete probe only. The resident life cycle decides
    whether to run another round on a later Thought pulse. There is no arbitrary
    fixed round count: investigation continues while ZN can derive another
    meaningful native observation from its body, environment, or retained
    experience.
    """

    _PROBE_LABELS = {
        "body": "inspect resident body state",
        "paths": "inspect referenced filesystem paths",
        "file_preview": "inspect referenced file content",
        "git": "inspect current git workspace",
        "processes": "inspect referenced process state",
        "experience": "compare with related resident-side experience",
    }

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
        if previous is not None and previous.status.startswith("resolved"):
            return InvestigationResult(
                state=previous,
                resolved=True,
                response=previous.resolution or "",
                can_continue=False,
            )

        now = utc_now()
        hypotheses = list(previous.hypotheses if previous else ())
        probes = list(previous.probes if previous else ())
        probe_keys = list(previous.probe_keys if previous else ())
        evidence = list(previous.evidence if previous else ())
        facts = dict(previous.facts if previous else {})

        self._seed_hypotheses(
            hypotheses,
            readiness,
            learning_evidence=learning_evidence or [],
            local_failure=local_failure,
        )

        next_probe = self._choose_next_probe(
            event,
            readiness,
            facts=facts,
            performed=set(probe_keys),
            learning_evidence=learning_evidence or [],
        )
        if next_probe is None:
            unresolved = self._remaining_unknown(
                readiness,
                local_failure=local_failure,
                learning_evidence=learning_evidence or [],
                evidence=evidence,
            )
            state = self._build_state(
                previous=previous,
                event=event,
                readiness=readiness,
                now=now,
                hypotheses=hypotheses,
                probes=probes,
                probe_keys=probe_keys,
                evidence=evidence,
                facts=facts,
                unresolved=unresolved,
                next_probe=None,
                resolved=False,
                response="",
                advance_round=False,
            )
            self._save(state)
            return InvestigationResult(state=state)

        label = self._PROBE_LABELS[next_probe]
        if label not in probes:
            probes.append(label)
        probe_keys.append(next_probe)
        new_evidence = self._run_probe(
            next_probe,
            event,
            readiness,
            facts=facts,
            learning_evidence=learning_evidence or [],
        )
        for item in new_evidence:
            value = str(item or "").strip()
            if value and value not in evidence:
                evidence.append(value)

        self._derive_hypotheses_from_facts(hypotheses, facts)
        response = self._answer_from_native_facts(event, facts)
        resolved = bool(response)
        following_probe = None
        if not resolved:
            following_probe = self._choose_next_probe(
                event,
                readiness,
                facts=facts,
                performed=set(probe_keys),
                learning_evidence=learning_evidence or [],
            )
        unresolved = None if resolved else self._remaining_unknown(
            readiness,
            local_failure=local_failure,
            learning_evidence=learning_evidence or [],
            evidence=evidence,
        )

        state = self._build_state(
            previous=previous,
            event=event,
            readiness=readiness,
            now=now,
            hypotheses=hypotheses,
            probes=probes,
            probe_keys=probe_keys,
            evidence=evidence,
            facts=facts,
            unresolved=unresolved,
            next_probe=following_probe,
            resolved=resolved,
            response=response,
            advance_round=True,
        )
        self._save(state)
        return InvestigationResult(
            state=state,
            resolved=resolved,
            response=response,
            can_continue=bool(following_probe) and not resolved,
            performed_probe=next_probe,
        )

    def current(self, event_id: str) -> InvestigationState | None:
        return self._load_for_event(event_id)

    def resolve_from_external(self, event_id: str, summary: str) -> None:
        state = self._load_for_event(event_id)
        if state is None:
            return
        state.updated_at = utc_now()
        state.status = "resolved_external"
        state.resolution = str(summary or "external cognition resolved the remaining gap")[:1000]
        state.unresolved = None
        state.next_probe = None
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
        if result.resolved:
            return []
        return list(result.state.evidence[-max(1, int(limit)):])

    def _build_state(
        self,
        *,
        previous: InvestigationState | None,
        event: AgentEvent,
        readiness: TaskReadiness,
        now: str,
        hypotheses: list[str],
        probes: list[str],
        probe_keys: list[str],
        evidence: list[str],
        facts: dict[str, Any],
        unresolved: str | None,
        next_probe: str | None,
        resolved: bool,
        response: str,
        advance_round: bool,
    ) -> InvestigationState:
        return InvestigationState(
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
            probe_keys=tuple(probe_keys[-32:]),
            evidence=tuple(evidence[-64:]),
            facts=facts,
            unresolved=unresolved,
            next_probe=next_probe,
            rounds=(previous.rounds if previous else 0) + (1 if advance_round else 0),
            status="resolved" if resolved else "open",
            resolution=response or None,
        )

    @staticmethod
    def _append_unique(values: list[str], text: str) -> None:
        value = str(text or "").strip()
        if value and value not in values:
            values.append(value)

    def _seed_hypotheses(
        self,
        hypotheses: list[str],
        readiness: TaskReadiness,
        *,
        learning_evidence: list[dict[str, Any]],
        local_failure: str | None,
    ) -> None:
        if local_failure:
            self._append_unique(
                hypotheses,
                "the observed local failure identifies the immediate blocking condition",
            )
        elif learning_evidence:
            self._append_unique(
                hypotheses,
                "a related prior resolution may contain a reusable pattern",
            )
        elif readiness.posture == "familiar":
            self._append_unique(
                hypotheses,
                "retained domain knowledge may be enough once current state is inspected",
            )
        elif readiness.posture == "partial":
            self._append_unique(
                hypotheses,
                "partial domain knowledge can narrow the problem after concrete observation",
            )
        else:
            self._append_unique(
                hypotheses,
                "the first useful step is to acquire concrete facts from the current environment",
            )

    def _derive_hypotheses_from_facts(
        self,
        hypotheses: list[str],
        facts: dict[str, Any],
    ) -> None:
        paths = facts.get("paths") if isinstance(facts.get("paths"), list) else []
        if any(not bool(item.get("exists")) for item in paths):
            self._append_unique(
                hypotheses,
                "a missing referenced filesystem target may explain the current problem",
            )
        git = facts.get("git") if isinstance(facts.get("git"), dict) else {}
        if git.get("dirty"):
            self._append_unique(
                hypotheses,
                "uncommitted workspace changes may explain a difference in current behavior",
            )
        processes = facts.get("processes") if isinstance(facts.get("processes"), list) else []
        if any(not bool(item.get("alive")) for item in processes):
            self._append_unique(
                hypotheses,
                "a referenced process is no longer running and may be the immediate cause",
            )
        body = facts.get("body") if isinstance(facts.get("body"), dict) else {}
        try:
            if float(body.get("disk_free_ratio", 1.0)) < 0.10:
                self._append_unique(
                    hypotheses,
                    "low free disk space may be constraining the current task",
                )
        except (TypeError, ValueError):
            pass

    def _choose_next_probe(
        self,
        event: AgentEvent,
        readiness: TaskReadiness,
        *,
        facts: dict[str, Any],
        performed: set[str],
        learning_evidence: list[dict[str, Any]],
    ) -> str | None:
        task = event.task.lower()
        candidates: list[str] = []

        path_candidates = self._path_candidates(event)
        process_relevant = bool(self._process_candidates(event))
        body_question = any(
            phrase in task
            for phrase in (
                "current working directory", "what is my cwd", "what's my cwd",
                "my current pid", "my pid", "resident pid", "hostname", "host name",
                "当前工作目录", "当前目录", "当前 pid", "进程 id", "主机名",
            )
        )
        content_question = any(
            phrase in task
            for phrase in (
                "read ", "show ", "contents", "content of", "inside the file",
                "打开", "读取", "内容", "看看文件",
            )
        )

        if path_candidates and "paths" not in performed:
            candidates.append("paths")
        if (
            "paths" in performed
            and content_question
            and self._previewable_paths(facts)
            and "file_preview" not in performed
        ):
            candidates.append("file_preview")
        if process_relevant and "processes" not in performed:
            candidates.append("processes")
        if body_question and "body" not in performed:
            candidates.append("body")

        git_relevant = self._git_relevant(event, readiness)
        if git_relevant and "git" not in performed:
            candidates.append("git")
        if learning_evidence and "experience" not in performed:
            candidates.append("experience")

        # Body state is the agent's most basic sensory anchor and remains useful
        # when no more specific probe is available.
        if "body" not in performed:
            candidates.append("body")

        # After a path probe discovers a readable file, evidence itself can
        # create the next probe. This is the first native evidence -> next action
        # transition rather than a pre-scripted fixed sequence.
        if (
            "paths" in performed
            and self._previewable_paths(facts)
            and self._file_context_relevant(event)
            and "file_preview" not in performed
            and "file_preview" not in candidates
        ):
            candidates.insert(0, "file_preview")

        for key in candidates:
            if key not in performed:
                return key
        return None

    def _run_probe(
        self,
        key: str,
        event: AgentEvent,
        readiness: TaskReadiness,
        *,
        facts: dict[str, Any],
        learning_evidence: list[dict[str, Any]],
    ) -> list[str]:
        if key == "body":
            body = self.resident.life.snapshot().body
            if body is None:
                return ["body state is currently unavailable"]
            facts["body"] = {
                "hostname": body.hostname,
                "pid": body.pid,
                "cwd": body.cwd,
                "system": body.system,
                "architecture": body.architecture,
                "disk_free_ratio": body.disk_free_ratio,
            }
            return [
                f"body: host={body.hostname}; pid={body.pid}; cwd={body.cwd}; "
                f"system={body.system}; disk_free={body.disk_free_ratio:.3f}"
            ]

        if key == "paths":
            path_facts = self._inspect_paths(event)
            facts["paths"] = path_facts
            if not path_facts:
                return ["path probe found no concrete referenced path"]
            return [
                "path: "
                f"{item['path']} exists={item['exists']} type={item.get('type', 'missing')} "
                f"size={item.get('size_bytes', 0)}"
                for item in path_facts
            ]

        if key == "file_preview":
            previews = self._inspect_file_previews(facts)
            facts["file_previews"] = previews
            if not previews:
                return ["referenced files did not yield readable text content"]
            return [
                f"file content observed locally: {item['path']} chars={item['chars']} "
                f"truncated={item['truncated']}"
                for item in previews
            ]

        if key == "git":
            git_fact = self._inspect_git(event, readiness)
            if git_fact is None:
                facts["git"] = {"available": False}
                return ["git workspace probe did not find a repository"]
            facts["git"] = git_fact
            return [
                "git: "
                f"root={git_fact.get('root')}; branch={git_fact.get('branch')}; "
                f"dirty={git_fact.get('dirty')}; changed_files={git_fact.get('changed_files')}"
            ]

        if key == "processes":
            process_facts = self._inspect_processes(event)
            facts["processes"] = process_facts
            if not process_facts:
                return ["process probe found no concrete referenced pid"]
            return [
                f"process: pid={item['pid']} alive={item['alive']}"
                for item in process_facts
            ]

        if key == "experience":
            facts["related_experience_count"] = len(learning_evidence)
            return [f"related experience records available: {len(learning_evidence)}"]

        return [f"unknown native probe: {key}"]

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
        for key in ("domains", "hypotheses", "probes", "probe_keys", "evidence"):
            data[key] = tuple(data.get(key) or ())
        data["facts"] = dict(data.get("facts") or {})
        data.setdefault("next_probe", None)
        return InvestigationState(**data)

    def _path_candidates(self, event: AgentEvent) -> list[str]:
        candidates: list[str] = []
        for key in ("path", "file", "directory", "workspace_path", "project_path", "repo_path"):
            value = event.payload.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
        paths_value = event.payload.get("paths")
        if isinstance(paths_value, (list, tuple)):
            candidates.extend(str(item).strip() for item in paths_value if str(item).strip())
        for token in re.findall(
            r"(?:[A-Za-z]:[\\/][^\s'\"]+|(?:\.{0,2}/|/)[^\s'\"]+)",
            event.task,
        ):
            candidates.append(token.rstrip(".,;:!?)]}"))
        return list(dict.fromkeys(item for item in candidates if item))[:6]

    def _inspect_paths(self, event: AgentEvent) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for raw in self._path_candidates(event):
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

    @staticmethod
    def _previewable_paths(facts: dict[str, Any]) -> list[dict[str, Any]]:
        paths = facts.get("paths") if isinstance(facts.get("paths"), list) else []
        return [
            item
            for item in paths
            if item.get("exists") and item.get("type") == "file"
        ][:2]

    def _inspect_file_previews(self, facts: dict[str, Any]) -> list[dict[str, Any]]:
        previews: list[dict[str, Any]] = []
        for item in self._previewable_paths(facts):
            path = Path(str(item.get("path") or ""))
            try:
                raw = path.read_bytes()[:16384]
            except OSError:
                continue
            text = raw.decode("utf-8", errors="replace")
            previews.append(
                {
                    "path": str(path),
                    "preview": text,
                    "chars": len(text),
                    "truncated": int(item.get("size_bytes") or 0) > len(raw),
                }
            )
        return previews

    @staticmethod
    def _file_context_relevant(event: AgentEvent) -> bool:
        text = event.task.lower()
        return any(
            word in text
            for word in (
                "file", "config", "log", "error", "debug", "code", "read",
                "content", "文件", "配置", "日志", "错误", "调试", "代码", "内容",
            )
        )

    @staticmethod
    def _git_relevant(event: AgentEvent, readiness: TaskReadiness) -> bool:
        text = event.task.lower()
        domain_relevant = any(
            domain.startswith("it/") or domain == "it"
            for domain in readiness.domains
        )
        task_relevant = any(
            word in text
            for word in (
                "git", "repo", "repository", "workspace", "project",
                "code", "debug", "build", "test", "分支", "仓库", "项目", "代码",
            )
        )
        return domain_relevant or task_relevant

    def _inspect_git(
        self,
        event: AgentEvent,
        readiness: TaskReadiness,
    ) -> dict[str, Any] | None:
        if not self._git_relevant(event, readiness):
            return None
        raw_workspace = (
            event.payload.get("workspace_path")
            or event.payload.get("project_path")
            or event.payload.get("repo_path")
        )
        body = self.resident.life.snapshot().body
        workspace = (
            Path(str(raw_workspace)).expanduser()
            if raw_workspace
            else Path(body.cwd if body else os.getcwd())
        )
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
        changed_paths = [line[3:].strip() for line in status_lines if len(line) > 3][:24]
        return {
            "available": True,
            "root": root,
            "branch": branch,
            "dirty": bool(status_lines),
            "changed_files": len(status_lines),
            "changed_paths": changed_paths,
        }

    def _process_candidates(self, event: AgentEvent) -> list[int]:
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
        return [pid for pid in dict.fromkeys(candidates) if pid > 0][:4]

    def _inspect_processes(self, event: AgentEvent) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for pid in self._process_candidates(event):
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
        previews = (
            facts.get("file_previews")
            if isinstance(facts.get("file_previews"), list)
            else []
        )
        processes = facts.get("processes") if isinstance(facts.get("processes"), list) else []

        if any(phrase in text for phrase in (
            "current working directory", "what is my cwd", "what's my cwd", "当前工作目录", "当前目录"
        )):
            value = body.get("cwd")
            if value:
                return str(value)

        if any(phrase in text for phrase in (
            "my current pid", "my pid", "resident pid", "当前 pid", "进程 id"
        )):
            value = body.get("pid")
            if value is not None:
                return str(value)

        if any(phrase in text for phrase in ("hostname", "host name", "主机名")):
            value = body.get("hostname")
            if value:
                return str(value)

        if any(phrase in text for phrase in (
            "current git branch", "what branch", "git branch", "当前分支"
        )):
            value = git.get("branch")
            if value:
                return str(value)

        if any(phrase in text for phrase in (
            "working tree dirty", "workspace dirty", "uncommitted", "工作区干净", "未提交"
        )) and git.get("available"):
            return "dirty" if git.get("dirty") else "clean"

        if any(phrase in text for phrase in (
            "changed files", "which files changed", "修改了哪些文件", "哪些文件改了"
        )) and git.get("available"):
            changed = git.get("changed_paths") or []
            return "\n".join(str(item) for item in changed) if changed else "no changed files"

        if paths and any(phrase in text for phrase in ("exist", "exists", "存在", "有没有")):
            if len(paths) == 1:
                item = paths[0]
                return f"{item['path']}: {'exists' if item['exists'] else 'does not exist'}"

        if previews and any(phrase in text for phrase in (
            "read ", "show ", "contents", "content of", "inside the file", "打开", "读取", "内容", "看看文件"
        )):
            if len(previews) == 1:
                return str(previews[0].get("preview") or "")

        if processes and any(phrase in text for phrase in (
            "alive", "running", "还在运行", "存活"
        )):
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
