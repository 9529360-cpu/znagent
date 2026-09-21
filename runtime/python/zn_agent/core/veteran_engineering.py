from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

VETERAN_PROTOCOL_VERSION = "2025-11-25"
VETERAN_RUNTIME_NAME = "veteran-engineer"
_ZN_MANAGED_OPERATOR_CONTRACT = "zn-veteran-operator-v1"
VETERAN_ALLOWED_TOOLS = frozenset(
    {
        "runtime_health",
        "runtime_integrity",
        "project_open",
        "project_snapshot",
        "mission_plan",
        "mission_execute",
        "mission_status",
        "mission_advance",
        "mission_readiness",
        "mission_timeline",
        "mission_cancel",
        "mission_resume",
        "evidence_query",
        "handoff_export",
    }
)


class VeteranSidecarError(RuntimeError):
    """Bounded Veteran sidecar protocol/runtime failure."""


@dataclass(frozen=True, slots=True)
class VeteranRuntimeCommand:
    argv: tuple[str, ...]
    env: Mapping[str, str]
    runtime_root: Path


def _is_veteran_runtime_root(candidate: Path) -> bool:
    return (
        (candidate / "mcp" / "server.mjs").is_file()
        and (candidate / "VENDOR.json").is_file()
    )


def vendored_veteran_root(env: Mapping[str, str] | None = None) -> Path:
    effective_env = os.environ if env is None else env
    explicit = str(effective_env.get("ZN_VETERAN_RUNTIME_ROOT") or "").strip()
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if _is_veteran_runtime_root(candidate):
            return candidate
        raise VeteranSidecarError(
            f"ZN_VETERAN_RUNTIME_ROOT is not a valid Veteran runtime: {candidate}"
        )

    for ancestor in Path(__file__).resolve().parents:
        for candidate in (
            ancestor / "vendor" / "veteran-engineer",
            ancestor / "veteran-engineer",
        ):
            if _is_veteran_runtime_root(candidate):
                return candidate.resolve()
    raise VeteranSidecarError("vendored Veteran runtime could not be located")


def default_veteran_state_root(agent_home: str | os.PathLike[str]) -> Path:
    return Path(agent_home).expanduser().resolve() / "engineering" / "veteran"


def stable_veteran_request_id(
    namespace: str,
    operation: str,
    payload: Mapping[str, Any],
) -> str:
    normalized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
    safe_namespace = "".join(ch for ch in namespace if ch.isalnum() or ch in "-_")[:48]
    safe_operation = "".join(ch for ch in operation if ch.isalnum() or ch in "-_")[:32]
    return f"zn-{safe_namespace or 'work'}-{safe_operation or 'call'}-{digest}"


def resolve_veteran_runtime_command(
    *,
    runtime_root: Path | None = None,
    node_executable: str | None = None,
    desktop_executable: str | None = None,
) -> VeteranRuntimeCommand:
    root = (runtime_root or vendored_veteran_root()).resolve()
    server = root / "mcp" / "server.mjs"
    if not server.is_file():
        raise VeteranSidecarError(f"vendored Veteran server missing: {server}")

    explicit_node = str(node_executable or os.getenv("ZN_VETERAN_NODE") or "").strip()
    if explicit_node:
        return VeteranRuntimeCommand(
            argv=(explicit_node, str(server)),
            env={},
            runtime_root=root,
        )

    explicit_desktop = str(
        desktop_executable
        or os.getenv("ZN_DESKTOP_EXECUTABLE")
        or os.getenv("ZN_VETERAN_ELECTRON_HOST")
        or ""
    ).strip()
    if explicit_desktop and Path(explicit_desktop).is_file():
        return VeteranRuntimeCommand(
            argv=(explicit_desktop, str(server)),
            env={"ELECTRON_RUN_AS_NODE": "1"},
            runtime_root=root,
        )

    resolved_node = shutil.which("node")
    if resolved_node:
        return VeteranRuntimeCommand(
            argv=(str(resolved_node), str(server)),
            env={},
            runtime_root=root,
        )

    raise VeteranSidecarError(
        "Veteran sidecar needs Node 20+ or a ZN/Electron executable host; "
        "set ZN_VETERAN_NODE or ZN_DESKTOP_EXECUTABLE"
    )


class VeteranMcpClient:
    """Single-flight newline-delimited MCP client for the vendored sidecar."""

    def __init__(
        self,
        *,
        state_root: Path,
        command: VeteranRuntimeCommand | None = None,
        timeout_seconds: float = 30.0,
        max_response_chars: int = 4_000_000,
        max_stderr_chars: int = 32_000,
    ) -> None:
        self.state_root = Path(state_root).resolve()
        self.command = command or resolve_veteran_runtime_command()
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 300.0))
        self.max_response_chars = max(4_096, int(max_response_chars))
        self.max_stderr_chars = max(1_024, int(max_stderr_chars))
        self._process: subprocess.Popen[str] | None = None
        self._stdout_queue: queue.Queue[str | None] = queue.Queue()
        self._stderr_parts: deque[str] = deque()
        self._stderr_chars = 0
        self._next_id = 1
        self._tool_names: frozenset[str] = frozenset()
        self._request_lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def tool_names(self) -> frozenset[str]:
        return self._tool_names

    def start(self) -> "VeteranMcpClient":
        if self.running:
            return self
        self.state_root.mkdir(parents=True, exist_ok=True)
        ensure_veteran_operator_policy(self.state_root)
        env = dict(os.environ)
        env.update(self.command.env)
        env["VETERAN_MCP_FORCE_FALLBACK"] = "1"
        env["VETERAN_ENGINEER_STATE_DIR"] = str(self.state_root)
        env.pop("VETERAN_MCP_REQUIRE_SDK", None)
        try:
            process = subprocess.Popen(
                list(self.command.argv),
                cwd=str(self.command.runtime_root),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if os.name == "nt"
                    else 0
                ),
            )
        except OSError as exc:
            raise VeteranSidecarError(f"failed to start Veteran sidecar: {exc}") from exc
        if process.stdin is None or process.stdout is None or process.stderr is None:
            process.kill()
            raise VeteranSidecarError("Veteran sidecar pipes were not created")
        self._process = process
        threading.Thread(
            target=self._read_stdout,
            args=(process.stdout,),
            daemon=True,
            name="zn-veteran-stdout",
        ).start()
        threading.Thread(
            target=self._read_stderr,
            args=(process.stderr,),
            daemon=True,
            name="zn-veteran-stderr",
        ).start()

        initialized = self._request_raw("initialize", {})
        server_info = initialized.get("serverInfo")
        if (
            initialized.get("protocolVersion") != VETERAN_PROTOCOL_VERSION
            or not isinstance(server_info, dict)
            or server_info.get("name") != VETERAN_RUNTIME_NAME
        ):
            self.close()
            raise VeteranSidecarError(
                f"unexpected Veteran handshake: {initialized!r}"
            )
        listed = self._request_raw("tools/list", {})
        tools = listed.get("tools")
        if not isinstance(tools, list):
            self.close()
            raise VeteranSidecarError("Veteran tools/list returned no tool list")
        names = frozenset(
            str(item.get("name"))
            for item in tools
            if isinstance(item, dict) and item.get("name")
        )
        missing = VETERAN_ALLOWED_TOOLS.difference(names)
        if missing:
            self.close()
            raise VeteranSidecarError(
                "Veteran sidecar is missing required tools: "
                + ", ".join(sorted(missing))
            )
        self._tool_names = names
        return self

    def close(self) -> None:
        process = self._process
        self._process = None
        self._tool_names = frozenset()
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        for stream in (process.stdout, process.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass

    def __enter__(self) -> "VeteranMcpClient":
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if name not in VETERAN_ALLOWED_TOOLS:
            raise VeteranSidecarError(f"Veteran tool is not authorized by ZN V1: {name}")
        self.start()
        envelope = self._request_raw(
            "tools/call",
            {"name": name, "arguments": dict(arguments or {})},
        )
        if envelope.get("isError") is True:
            raise VeteranSidecarError(self._tool_error_message(envelope))
        structured = envelope.get("structuredContent")
        if isinstance(structured, dict):
            return dict(structured)
        content = envelope.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict) and first.get("type") == "text":
                try:
                    parsed = json.loads(str(first.get("text") or ""))
                except json.JSONDecodeError as exc:
                    raise VeteranSidecarError(
                        "Veteran tool returned non-JSON text content"
                    ) from exc
                if isinstance(parsed, dict):
                    return parsed
        raise VeteranSidecarError(f"Veteran tool returned no structured object: {name}")

    def _request_raw(
        self,
        method: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._request_lock:
            process = self._process
            if process is None or process.poll() is not None or process.stdin is None:
                raise VeteranSidecarError(
                    "Veteran sidecar is not running" + self._stderr_suffix()
                )
            request_id = self._next_id
            self._next_id += 1
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params),
            }
            try:
                process.stdin.write(
                    json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
                    + "\n"
                )
                process.stdin.flush()
            except OSError as exc:
                raise VeteranSidecarError(
                    f"failed writing to Veteran sidecar: {exc}"
                    + self._stderr_suffix()
                ) from exc

            try:
                line = self._stdout_queue.get(timeout=self.timeout_seconds)
            except queue.Empty as exc:
                raise VeteranSidecarError(
                    f"Veteran sidecar timed out waiting for {method}"
                    + self._stderr_suffix()
                ) from exc
            if line is None:
                raise VeteranSidecarError(
                    "Veteran sidecar closed stdout" + self._stderr_suffix()
                )
            if len(line) > self.max_response_chars:
                raise VeteranSidecarError(
                    f"Veteran response exceeded {self.max_response_chars} characters"
                )
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                raise VeteranSidecarError("Veteran returned invalid JSON") from exc
            if not isinstance(response, dict) or response.get("id") != request_id:
                raise VeteranSidecarError(
                    f"Veteran response id mismatch for {method}: {response!r}"
                )
            error = response.get("error")
            if isinstance(error, dict):
                raise VeteranSidecarError(
                    f"Veteran protocol error {error.get('code')}: "
                    f"{error.get('message')}"
                )
            result = response.get("result")
            if not isinstance(result, dict):
                raise VeteranSidecarError(
                    f"Veteran response has no object result for {method}"
                )
            return result

    def _read_stdout(self, stream) -> None:
        try:
            for raw in stream:
                self._stdout_queue.put(raw.rstrip("\r\n"))
        finally:
            self._stdout_queue.put(None)

    def _read_stderr(self, stream) -> None:
        for raw in stream:
            text = raw.rstrip("\r\n")
            if not text:
                continue
            self._stderr_parts.append(text)
            self._stderr_chars += len(text)
            while self._stderr_parts and self._stderr_chars > self.max_stderr_chars:
                removed = self._stderr_parts.popleft()
                self._stderr_chars -= len(removed)

    def _stderr_suffix(self) -> str:
        if not self._stderr_parts:
            return ""
        return "; stderr=" + " | ".join(self._stderr_parts)[-self.max_stderr_chars :]

    @staticmethod
    def _tool_error_message(envelope: Mapping[str, Any]) -> str:
        content = envelope.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                text = str(first.get("text") or "").strip()
                if text:
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError:
                        return "Veteran tool failed: " + text[:2000]
                    if isinstance(parsed, dict):
                        code = str(parsed.get("code") or "ERROR")
                        message = str(parsed.get("message") or "")
                        return f"Veteran tool failed [{code}]: {message}"
        return "Veteran tool failed"


@dataclass(frozen=True, slots=True)
class VeteranMissionRef:
    project_id: str
    mission_id: str
    base_head: str | None


class VeteranEngineeringCapability:
    """ZN-owned facade over the narrow Veteran engineering Mission surface."""

    def __init__(self, client: VeteranMcpClient, *, namespace: str) -> None:
        self.client = client
        self.namespace = namespace

    def open_project(
        self,
        repo_path: str | os.PathLike[str],
        *,
        name: str = "",
        request_scope: str = "project_open",
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"repoPath": str(Path(repo_path).resolve())}
        if name.strip():
            args["name"] = name.strip()
        scope = str(request_scope or "project_open").strip()[:64] or "project_open"
        return self.client.call_tool(
            "project_open",
            {
                "requestId": stable_veteran_request_id(
                    self.namespace, scope, args
                ),
                **args,
            },
        )

    def plan_mission(
        self,
        *,
        project_id: str,
        goal: str,
        done_definition: str,
        tasks: Sequence[Mapping[str, Any]] | None = None,
        risk_envelope: str = "medium",
        non_goals: Sequence[str] = (),
    ) -> tuple[VeteranMissionRef, dict[str, Any]]:
        args: dict[str, Any] = {
            "projectId": project_id,
            "goal": goal,
            "doneDefinition": done_definition,
            "nonGoals": list(non_goals),
            "riskEnvelope": risk_envelope,
        }
        if tasks is not None:
            if not tasks:
                raise VeteranSidecarError("explicit Veteran task list must not be empty")
            args["tasks"] = [dict(task) for task in tasks]
        result = self.client.call_tool(
            "mission_plan",
            {
                "requestId": stable_veteran_request_id(
                    self.namespace, "mission_plan", args
                ),
                **args,
            },
        )
        mission = result.get("mission")
        if not isinstance(mission, dict):
            raise VeteranSidecarError("Veteran mission_plan returned no mission object")
        mission_id = str(mission.get("id") or "").strip()
        result_project_id = str(mission.get("projectId") or "").strip()
        if not mission_id or result_project_id != project_id:
            raise VeteranSidecarError(
                "Veteran mission_plan returned inconsistent mission identity"
            )
        source = mission.get("baseSourceIdentity")
        base_head = (
            str(source.get("head") or "").strip() or None
            if isinstance(source, dict)
            else None
        )
        return (
            VeteranMissionRef(
                project_id=project_id,
                mission_id=mission_id,
                base_head=base_head,
            ),
            result,
        )

    def mission_status(self, mission_id: str) -> dict[str, Any]:
        return self.client.call_tool(
            "mission_status",
            {"missionId": mission_id},
        )

    def execute(
        self,
        mission_id: str,
        *,
        run_workers: bool,
        bootstrap_authorization: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {
            "missionId": mission_id,
            "runWorkers": bool(run_workers),
        }
        if bootstrap_authorization is not None:
            args["bootstrapAuthorization"] = dict(bootstrap_authorization)
        return self.client.call_tool(
            "mission_execute",
            {
                "requestId": self._transition_request_id(
                    "mission_execute", mission_id, args
                ),
                **args,
            },
        )

    def advance(self, mission_id: str, *, run_workers: bool) -> dict[str, Any]:
        args = {
            "missionId": mission_id,
            "runWorkers": bool(run_workers),
        }
        return self.client.call_tool(
            "mission_advance",
            {
                "requestId": self._transition_request_id(
                    "mission_advance", mission_id, args
                ),
                **args,
            },
        )

    def _transition_request_id(
        self,
        operation: str,
        mission_id: str,
        args: Mapping[str, Any],
    ) -> str:
        status = self.mission_status(mission_id)
        mission = status.get("mission")
        if not isinstance(mission, dict):
            raise VeteranSidecarError(
                f"Veteran mission status lost transition identity for {mission_id}"
            )

        def proof_identity(value: Any) -> dict[str, Any] | None:
            if not isinstance(value, dict):
                return None
            return {
                "status": value.get("status"),
                "commitSha": value.get("commitSha"),
                "candidateId": value.get("candidateId"),
            }

        transition = {
            "missionId": mission_id,
            "phase": mission.get("phase"),
            "status": mission.get("status"),
            "updatedAt": mission.get("updatedAt"),
            "waveIndex": mission.get("waveIndex"),
            "activeCandidateId": mission.get("activeCandidateId"),
            "activeMergeProposalId": mission.get("activeMergeProposalId"),
            "validation": proof_identity(mission.get("validation")),
            "review": proof_identity(mission.get("review")),
            "semanticReview": proof_identity(mission.get("semanticReview")),
        }
        identity = {
            **dict(args),
            "_znTransition": transition,
        }
        return stable_veteran_request_id(
            self.namespace,
            operation,
            identity,
        )

    def cancel(self, mission_id: str, *, reason: str) -> dict[str, Any]:
        args = {"missionId": mission_id, "reason": reason}
        return self.client.call_tool(
            "mission_cancel",
            {
                "requestId": stable_veteran_request_id(
                    self.namespace, "mission_cancel", args
                ),
                **args,
            },
        )

    def evidence(
        self,
        *,
        mission_id: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self.client.call_tool(
            "evidence_query",
            {
                "missionId": mission_id,
                "limit": max(1, min(int(limit), 200)),
            },
        )

    def evidence_items(
        self,
        *,
        mission_id: str,
        limit: int = 50,
    ) -> tuple[dict[str, Any], ...]:
        result = self.evidence(mission_id=mission_id, limit=limit)
        rows = result.get("result")
        if not isinstance(rows, list):
            raise VeteranSidecarError(
                "Veteran evidence_query returned no result list"
            )
        return tuple(dict(item) for item in rows if isinstance(item, dict))


@dataclass(frozen=True, slots=True)
class VeteranCodexWorker:
    command: Path
    codex_home: Path | None
    windows_sandbox: str | None


def discover_veteran_codex_worker(
    env: Mapping[str, str] | None = None,
    *,
    platform_name: str | None = None,
) -> VeteranCodexWorker | None:
    effective_env = os.environ if env is None else env
    platform_value = platform_name or os.name
    is_windows = platform_value in {"nt", "win32", "windows"}

    candidates: list[Path] = []
    explicit = str(effective_env.get("ZN_VETERAN_CODEX") or "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())

    on_path = shutil.which("codex")
    if on_path:
        candidates.append(Path(on_path))

    raw_home = str(effective_env.get("CODEX_HOME") or "").strip()
    codex_home = (
        Path(os.path.abspath(os.path.expanduser(raw_home)))
        if raw_home
        else None
    )
    if codex_home is not None:
        if is_windows:
            candidates.extend(
                [
                    codex_home / "bin" / "codex.exe",
                    codex_home / "packages" / "standalone" / "current" / "bin" / "codex.exe",
                    codex_home / "packages" / "standalone" / "current" / "codex.exe",
                ]
            )
        else:
            candidates.extend(
                [
                    codex_home / "bin" / "codex",
                    codex_home / "packages" / "standalone" / "current" / "bin" / "codex",
                    codex_home / "packages" / "standalone" / "current" / "codex",
                ]
            )

    if is_windows:
        local_appdata = str(effective_env.get("LOCALAPPDATA") or "").strip()
        if local_appdata:
            candidates.append(
                Path(local_appdata) / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe"
            )

    seen: set[str] = set()
    for candidate in candidates:
        stable_path = Path(
            os.path.abspath(os.path.expanduser(str(candidate)))
        )
        key = os.path.normcase(str(stable_path))
        if key in seen:
            continue
        seen.add(key)
        if stable_path.is_file():
            sandbox = "unelevated" if is_windows else None
            return VeteranCodexWorker(
                command=stable_path,
                codex_home=codex_home,
                windows_sandbox=sandbox,
            )
    return None


def veteran_operator_policy_for_codex(
    worker: VeteranCodexWorker,
    *,
    max_workers: int = 1,
    planner_command: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    extra_args = ["--ignore-user-config", "--ignore-rules"]
    planner = str(Path(planner_command or sys.executable).resolve())
    if worker.windows_sandbox:
        extra_args[:0] = ["-c", f'windows.sandbox="{worker.windows_sandbox}"']
    return {
        "znManaged": {
            "contract": _ZN_MANAGED_OPERATOR_CONTRACT,
            "version": 1,
        },
        "defaults": {
            "requireValidation": False,
            "requireSemanticReview": False,
            "plannerProvider": {
                "command": planner,
                "args": ["-m", "zn_agent.core.veteran_codex_planner"],
                "envAllowlist": ["CODEX_HOME", "ZN_VETERAN_CODEX"],
                "timeoutMs": 180_000,
            },
            "workerPolicy": {
                "enabled": True,
                "maxWorkers": max(1, min(int(max_workers), 4)),
                "defaultWorker": "codex",
                "allowUnconfinedCustomWorkers": False,
                "allowRawValidation": False,
                "codex": {
                    "command": str(worker.command),
                    "envAllowlist": ["CODEX_HOME"],
                    "timeoutMs": 900_000,
                    "extraArgs": extra_args,
                },
            },
        }
    }


def ensure_veteran_operator_policy(
    state_root: str | os.PathLike[str],
    *,
    env: Mapping[str, str] | None = None,
) -> Path | None:
    root = Path(state_root).expanduser().resolve()
    target = root / "operator.json"
    existing_managed = False
    existing: dict[str, Any] | None = None
    if target.exists():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return target
        marker = loaded.get("znManaged") if isinstance(loaded, dict) else None
        if (
            not isinstance(marker, dict)
            or marker.get("contract") != _ZN_MANAGED_OPERATOR_CONTRACT
        ):
            return target
        existing = dict(loaded)
        existing_managed = True

    worker = discover_veteran_codex_worker(env)
    if worker is None:
        return target if existing_managed else None

    root.mkdir(parents=True, exist_ok=True)
    payload = veteran_operator_policy_for_codex(worker)
    if existing_managed and existing is not None:
        projects = existing.get("projects")
        if isinstance(projects, dict) and projects:
            # Project validation is a ZN-managed override layer derived from
            # observed repository truth. Refresh bounded defaults without
            # erasing those per-project bindings on every Resident pulse.
            payload["projects"] = dict(projects)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if existing_managed:
        try:
            if target.read_text(encoding="utf-8") == serialized:
                return target
        except OSError:
            pass

    temp = root / f".operator.json.tmp-{os.getpid()}-{threading.get_ident()}"
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        if existing_managed:
            os.replace(temp, target)
        else:
            try:
                os.link(temp, target)
            except FileExistsError:
                pass
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
    return target if target.exists() else None


@dataclass(frozen=True, slots=True)
class VeteranWorkerOutcome:
    project_id: str
    mission_id: str
    base_head: str | None
    integration_sha: str | None
    status: str
    phase: str
    task_states: tuple[tuple[str, str], ...]
    evidence_ids: tuple[str, ...]
    raw_status: Mapping[str, Any]


class VeteranWorkerRunExecutor:
    """Bind one ZN coding WorkerRun to one durable Veteran Mission.

    ZN remains the lifecycle authority. Veteran mission identity is checkpointed
    into WorkerRun.metrics before any worker execution so restart attaches to the
    same mission instead of planning or executing a duplicate.
    """

    _METRIC_KEY = "veteran_engineering"

    def __init__(self, *, ledger: Any, capability: VeteranEngineeringCapability) -> None:
        self.ledger = ledger
        self.capability = capability

    def prepare(
        self,
        *,
        worker_run_id: str,
        repo_path: str | os.PathLike[str],
        goal: str,
        done_definition: str,
        tasks: Sequence[Mapping[str, Any]] | None = None,
        risk_envelope: str = "medium",
        non_goals: Sequence[str] = (),
    ) -> VeteranMissionRef:
        run = self._coding_run(worker_run_id)
        checkpoint = self._checkpoint(run)
        if checkpoint:
            return VeteranMissionRef(
                project_id=str(checkpoint["project_id"]),
                mission_id=str(checkpoint["mission_id"]),
                base_head=(
                    str(checkpoint.get("base_head") or "").strip() or None
                ),
            )

        project = self.capability.open_project(
            repo_path,
            name=f"zn-{worker_run_id}",
        )
        project_id = str(project.get("id") or "").strip()
        if not project_id:
            raise VeteranSidecarError("Veteran project_open returned no project id")
        ref, _planned = self.capability.plan_mission(
            project_id=project_id,
            goal=goal,
            done_definition=done_definition,
            tasks=tasks,
            risk_envelope=risk_envelope,
            non_goals=non_goals,
        )
        self.ledger.update_worker_run_metrics(
            worker_run_id,
            metrics={
                self._METRIC_KEY: {
                    "contract": "zn-veteran-worker-v1",
                    "project_id": ref.project_id,
                    "mission_id": ref.mission_id,
                    "base_head": ref.base_head,
                    "state": "planned",
                    "planner_model_invocations": 1 if tasks is None else 0,
                    "model_invocations": 1 if tasks is None else 0,
                }
            },
        )
        return ref

    def execute(
        self,
        *,
        worker_run_id: str,
        run_workers: bool,
    ) -> VeteranWorkerOutcome:
        run = self._coding_run(worker_run_id)
        checkpoint = self._checkpoint(run)
        if not checkpoint:
            raise VeteranSidecarError(
                "Veteran WorkerRun must be prepared before execution"
            )
        mission_id = str(checkpoint["mission_id"])
        self.capability.execute(mission_id, run_workers=run_workers)
        return self.refresh(worker_run_id=worker_run_id)

    def refresh(self, *, worker_run_id: str) -> VeteranWorkerOutcome:
        run = self._coding_run(worker_run_id)
        checkpoint = self._checkpoint(run)
        if not checkpoint:
            raise VeteranSidecarError("Veteran WorkerRun has no mission checkpoint")
        mission_id = str(checkpoint["mission_id"])
        result = self.capability.mission_status(mission_id)
        mission = result.get("mission")
        if not isinstance(mission, dict):
            raise VeteranSidecarError("Veteran mission_status returned no mission")
        tasks = result.get("tasks")
        task_rows = tasks if isinstance(tasks, list) else []
        task_states = tuple(
            (
                str(task.get("id") or ""),
                str(task.get("status") or ""),
            )
            for task in task_rows
            if isinstance(task, dict) and task.get("id")
        )
        integration_sha = next(
            (
                str(task.get("integrationSha") or "").strip()
                for task in reversed(task_rows)
                if isinstance(task, dict)
                and str(task.get("integrationSha") or "").strip()
            ),
            None,
        )
        status = str(mission.get("status") or "").strip()
        phase = str(mission.get("phase") or "").strip()
        evidence_items = self.capability.evidence_items(
            mission_id=mission_id,
            limit=50,
        )
        evidence_ids = tuple(
            str(item.get("id") or "").strip()
            for item in evidence_items
            if str(item.get("id") or "").strip()
        )
        dispatch_count = sum(
            len(task.get("dispatches") or [])
            for task in task_rows
            if isinstance(task, dict) and isinstance(task.get("dispatches") or [], list)
        )
        planner_model_invocations = max(
            0,
            int(checkpoint.get("planner_model_invocations") or 0),
        )
        model_invocations = planner_model_invocations + dispatch_count
        self.ledger.update_worker_run_metrics(
            worker_run_id,
            metrics={
                self._METRIC_KEY: {
                    **dict(checkpoint),
                    "state": status or "unknown",
                    "phase": phase or "unknown",
                    "integration_sha": integration_sha,
                    "tasks": [
                        {"id": task_id, "status": task_status}
                        for task_id, task_status in task_states
                    ],
                    "evidence_ids": list(evidence_ids),
                    "worker_dispatches": dispatch_count,
                    "model_invocations": model_invocations,
                }
            },
        )
        return VeteranWorkerOutcome(
            project_id=str(checkpoint["project_id"]),
            mission_id=mission_id,
            base_head=str(checkpoint.get("base_head") or "").strip() or None,
            integration_sha=integration_sha,
            status=status,
            phase=phase,
            task_states=task_states,
            evidence_ids=evidence_ids,
            raw_status=result,
        )

    def _coding_run(self, worker_run_id: str) -> Any:
        run = self.ledger.worker_run(worker_run_id)
        if run is None:
            raise VeteranSidecarError("unknown ZN WorkerRun")
        if str(getattr(run, "executor_kind", "")) != "coding":
            raise VeteranSidecarError(
                "Veteran engineering execution requires a coding WorkerRun"
            )
        if str(getattr(run, "state", "")) not in {"queued", "running"}:
            raise VeteranSidecarError(
                "Veteran engineering execution requires a live WorkerRun"
            )
        checkpoint = getattr(self.ledger, "update_worker_run_metrics", None)
        if callable(checkpoint):
            run = checkpoint(worker_run_id, metrics={})
            if str(getattr(run, "state", "")) not in {"queued", "running"}:
                raise VeteranSidecarError(
                    "Veteran engineering execution belongs to a stale Work plan"
                )
        return run

    @classmethod
    def _checkpoint(cls, run: Any) -> dict[str, Any] | None:
        metrics = getattr(run, "metrics", None)
        if not isinstance(metrics, dict):
            return None
        value = metrics.get(cls._METRIC_KEY)
        if not isinstance(value, dict):
            return None
        project_id = str(value.get("project_id") or "").strip()
        mission_id = str(value.get("mission_id") or "").strip()
        if not project_id or not mission_id:
            raise VeteranSidecarError(
                "Veteran WorkerRun checkpoint is incomplete"
            )
        return dict(value)


_NODE_VALIDATION_PRIORITY = (
    "test",
    "check",
    "verify",
    "typecheck",
    "build",
    "lint",
)
_SAFE_NODE_SCRIPT = re.compile(r"^[A-Za-z0-9_.:-]+$")


def veteran_node_validation_policy(
    project: Mapping[str, Any],
    *,
    platform_name: str | None = None,
) -> dict[str, Any] | None:
    profile = project.get("environmentProfile")
    if not isinstance(profile, dict):
        return None
    node = profile.get("node")
    managers = profile.get("packageManagers")
    if not isinstance(node, dict) or not isinstance(managers, dict):
        return None
    manager_info = managers.get("node")
    if not isinstance(manager_info, dict) or manager_info.get("ambiguous") is True:
        return None
    manager = str(manager_info.get("selected") or "").strip().lower()
    if not manager:
        manifests = profile.get("manifests")
        manifest_rows = manifests if isinstance(manifests, list) else []
        has_node_package = any(
            isinstance(item, dict)
            and str(item.get("kind") or "").strip() == "node-package"
            and str(item.get("path") or "").replace("\\", "/") == "package.json"
            for item in manifest_rows
        )
        lockfiles = manager_info.get("lockfileCandidates")
        if (
            has_node_package
            and manager_info.get("ambiguous") is not True
            and isinstance(lockfiles, list)
            and not lockfiles
        ):
            manager = "npm"
    if manager not in {"npm", "pnpm", "yarn", "bun"}:
        return None
    scripts = [
        str(value).strip()
        for value in node.get("validationScriptNames") or ()
        if isinstance(value, str) and str(value).strip()
    ]
    if not scripts:
        return None
    script_set = set(scripts)
    selected = next((name for name in _NODE_VALIDATION_PRIORITY if name in script_set), None)
    if selected is None:
        selected = next(
            (
                value
                for prefix in _NODE_VALIDATION_PRIORITY
                for value in scripts
                if value.startswith(prefix + ":")
            ),
            None,
        )
    if selected is None or _SAFE_NODE_SCRIPT.fullmatch(selected) is None:
        return None

    windows = (platform_name or os.name).strip().lower() in {"nt", "windows", "win32"}
    if windows and manager in {"npm", "pnpm", "yarn"}:
        # Node documents that .cmd/.bat launchers are not directly executable
        # on Windows. Spawn cmd.exe explicitly rather than shell=True, and only
        # after restricting the repository-derived script name to a safe token.
        command = [
            "cmd.exe",
            "/d",
            "/s",
            "/c",
            manager + ".cmd",
            "run",
            selected,
        ]
    else:
        command = [manager, "run", selected]
    capability_name = f"node-{selected.replace(':', '-')}"[:120]
    return {
        "requireValidation": True,
        "requiredValidationCapabilities": [capability_name],
        "validationCapabilities": [
            {
                "name": capability_name,
                "description": f"Repository-declared {manager} script: {selected}",
                "command": command,
                "cwd": ".",
                "timeoutMs": 600_000,
            }
        ],
        "validationPolicy": {"maxParallel": 1},
    }


def configure_veteran_project_validation(
    state_root: Path,
    *,
    workspace: str | os.PathLike[str],
    project: Mapping[str, Any],
    platform_name: str | None = None,
) -> str | None:
    policy = veteran_node_validation_policy(project, platform_name=platform_name)
    if policy is None:
        return None
    target = Path(state_root).resolve() / "operator.json"
    if not target.is_file():
        raise VeteranSidecarError("Veteran operator policy must exist before project validation binding")
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VeteranSidecarError(f"Veteran operator policy is unreadable: {exc}") from exc
    if not isinstance(raw, dict):
        raise VeteranSidecarError("Veteran operator policy must be a JSON object")
    marker = raw.get("znManaged")
    if (
        not isinstance(marker, dict)
        or marker.get("contract") != _ZN_MANAGED_OPERATOR_CONTRACT
    ):
        return None

    # Veteran canonicalizes local repository paths to forward-slash form
    # before projectPolicy lookup, including on Windows. Store the managed
    # project override under that same identity so validation cannot silently
    # fall back to defaults.
    workspace_key = str(Path(workspace).expanduser().resolve()).replace("\\", "/")
    projects = raw.get("projects")
    if projects is None:
        projects = {}
    if not isinstance(projects, dict):
        raise VeteranSidecarError("Veteran operator projects policy must be an object")
    current = projects.get(workspace_key)
    current = dict(current) if isinstance(current, dict) else {}
    updated_project = {**current, **policy}
    if current == updated_project:
        required = policy["requiredValidationCapabilities"]
        return str(required[0]) if required else None

    updated = dict(raw)
    updated["projects"] = {**projects, workspace_key: updated_project}
    encoded = json.dumps(updated, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    temp = target.with_name(target.name + f".tmp-{os.getpid()}-{threading.get_ident()}")
    try:
        temp.write_text(encoded, encoding="utf-8")
        os.replace(temp, target)
    except OSError as exc:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise VeteranSidecarError(f"could not update Veteran project validation policy: {exc}") from exc
    required = policy["requiredValidationCapabilities"]
    return str(required[0]) if required else None
