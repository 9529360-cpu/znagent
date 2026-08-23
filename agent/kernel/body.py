from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import sqlite3
import subprocess
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from .models import utc_now
from .terminal import TerminalRequest, TerminalResult, get_zn_local_terminal

if TYPE_CHECKING:
    from .resident import ZNResidentRuntime
    from .store import KernelStore


@dataclass(slots=True)
class BodyAction:
    """One concrete action ZN intends to perform through its computer body."""

    action_id: str
    kind: str
    args: dict[str, Any] = field(default_factory=dict)
    event_id: str | None = None
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class BodyActionResult:
    """Observed result of a body action, owned by ZN rather than by a model call."""

    action_id: str
    kind: str
    success: bool
    output: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    event_id: str | None = None
    started_at: str = field(default_factory=utc_now)
    completed_at: str = field(default_factory=utc_now)


class NativeBody:
    """ZN's unified interface for sensing and acting on its computer environment.

    Files, processes, Git and the terminal are different movements of the same
    body. This class contains no planning/model logic: Thought chooses an action;
    Body executes it and returns evidence.

    Local terminal execution, including interactive PTY sessions, is owned by ZN
    rather than delegated to the old product terminal control plane.
    """

    def __init__(
        self,
        *,
        resident: ZNResidentRuntime | None = None,
        store: KernelStore | None = None,
    ):
        self.resident = resident
        self.store = store or (resident.store if resident is not None else None)
        if self.store is not None:
            self._init_schema()

    def sense(self) -> dict[str, Any]:
        disk = shutil.disk_usage(Path.cwd())
        return {
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
            "cwd": os.getcwd(),
            "system": platform.system(),
            "release": platform.release(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "disk_total_bytes": int(disk.total),
            "disk_free_bytes": int(disk.free),
            "captured_at": utc_now(),
        }

    def act(
        self,
        kind: str,
        *,
        event_id: str | None = None,
        **args: Any,
    ) -> BodyActionResult:
        action = BodyAction(
            action_id=f"body-{uuid.uuid4().hex[:12]}",
            kind=str(kind or "").strip().lower(),
            args=dict(args),
            event_id=event_id,
        )
        started = utc_now()
        try:
            result = self._dispatch(action, started)
        except Exception as exc:
            result = BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                event_id=event_id,
                started_at=started,
                completed_at=utc_now(),
            )
        self._record(action, result)
        return result

    def recent_actions(self, limit: int = 50) -> list[BodyActionResult]:
        if self.store is None:
            return []
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT result_json FROM native_body_actions "
                "ORDER BY completed_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [self._result_from_dict(json.loads(row["result_json"])) for row in rows]

    def _dispatch(self, action: BodyAction, started: str) -> BodyActionResult:
        kind = action.kind
        if kind == "sense":
            return self._ok(action, started, data=self.sense())
        if kind in {"inspect_path", "path"}:
            return self._inspect_path(action, started)
        if kind in {"read_text", "read_file"}:
            return self._read_text(action, started)
        if kind in {"write_text", "write_file"}:
            return self._write_text(action, started)
        if kind in {"list_directory", "list_dir"}:
            return self._list_directory(action, started)
        if kind in {"process_state", "process"}:
            return self._process_state(action, started)
        if kind in {"git_state", "git"}:
            return self._git_state(action, started)
        if kind == "git_diff":
            return self._git_diff(action, started)
        if kind in {"command", "terminal", "shell"}:
            return self._command(action, started)
        if kind in {"terminal_poll", "command_poll"}:
            return self._terminal_session(action, started, operation="poll")
        if kind in {"terminal_stop", "command_stop"}:
            return self._terminal_session(action, started, operation="stop")
        if kind in {"terminal_input", "terminal_write", "command_input"}:
            return self._terminal_session(action, started, operation="input")
        if kind in {"terminal_resize", "command_resize"}:
            return self._terminal_session(action, started, operation="resize")
        raise ValueError(f"unknown body action kind: {kind or '<empty>'}")

    def _inspect_path(self, action: BodyAction, started: str) -> BodyActionResult:
        path = self._path_arg(action.args)
        try:
            stat = path.stat()
            if path.is_file():
                path_type = "file"
            elif path.is_dir():
                path_type = "directory"
            else:
                path_type = "other"
            data = {
                "path": str(path),
                "exists": True,
                "type": path_type,
                "size_bytes": int(stat.st_size),
                "mtime": float(stat.st_mtime),
                "mode": int(stat.st_mode),
            }
        except FileNotFoundError:
            data = {"path": str(path), "exists": False, "type": "missing"}
        return self._ok(action, started, data=data)

    def _read_text(self, action: BodyAction, started: str) -> BodyActionResult:
        path = self._path_arg(action.args)
        max_chars = max(1, int(action.args.get("max_chars", 20000)))
        encoding = str(action.args.get("encoding") or "utf-8")
        text = path.read_text(encoding=encoding, errors="replace")
        truncated = len(text) > max_chars
        output = text[:max_chars]
        return self._ok(
            action,
            started,
            output=output,
            data={
                "path": str(path),
                "chars": len(text),
                "returned_chars": len(output),
                "truncated": truncated,
                "encoding": encoding,
            },
        )

    def _write_text(self, action: BodyAction, started: str) -> BodyActionResult:
        path = self._path_arg(action.args)
        content = str(action.args.get("content") or "")
        encoding = str(action.args.get("encoding") or "utf-8")
        append = bool(action.args.get("append", False))
        if bool(action.args.get("create_parents", True)):
            path.parent.mkdir(parents=True, exist_ok=True)
        if append:
            with path.open("a", encoding=encoding) as handle:
                written = handle.write(content)
        else:
            written = path.write_text(content, encoding=encoding)
        return self._ok(
            action,
            started,
            output=str(path),
            data={
                "path": str(path),
                "written_chars": int(written),
                "append": append,
                "encoding": encoding,
            },
        )

    def _list_directory(self, action: BodyAction, started: str) -> BodyActionResult:
        path = self._path_arg(action.args, default=".")
        limit = max(1, int(action.args.get("limit", 200)))
        entries: list[dict[str, Any]] = []
        for child in sorted(path.iterdir(), key=lambda item: item.name.lower())[:limit]:
            try:
                stat = child.stat()
                size = int(stat.st_size)
            except OSError:
                size = 0
            entries.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "type": (
                        "directory"
                        if child.is_dir()
                        else "file"
                        if child.is_file()
                        else "other"
                    ),
                    "size_bytes": size,
                }
            )
        return self._ok(
            action,
            started,
            data={"path": str(path), "entries": entries, "count": len(entries)},
        )

    def _process_state(self, action: BodyAction, started: str) -> BodyActionResult:
        pid = int(action.args.get("pid", os.getpid()))
        alive = True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            alive = False
        except PermissionError:
            alive = True
        except OSError:
            alive = False
        data: dict[str, Any] = {"pid": pid, "alive": alive}
        if alive:
            try:
                import psutil

                proc = psutil.Process(pid)
                data.update(
                    {
                        "name": proc.name(),
                        "status": proc.status(),
                        "create_time": proc.create_time(),
                        "memory_rss": int(proc.memory_info().rss),
                        "cpu_percent": float(proc.cpu_percent(interval=None)),
                    }
                )
            except Exception:
                pass
        return self._ok(action, started, data=data)

    def _git_state(self, action: BodyAction, started: str) -> BodyActionResult:
        workspace = self._path_arg(action.args, default=os.getcwd())
        limit = max(1, min(1000, int(action.args.get("limit", 200))))

        def run(*parts: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["git", "-C", str(workspace), *parts],
                capture_output=True,
                text=True,
                timeout=max(1.0, float(action.args.get("timeout", 5.0))),
                check=False,
            )

        def nul_paths(proc: subprocess.CompletedProcess[str]) -> list[str]:
            if proc.returncode != 0:
                return []
            return [item for item in proc.stdout.split("\0") if item][:limit]

        root_proc = run("rev-parse", "--show-toplevel")
        if root_proc.returncode != 0:
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=False,
                error=(root_proc.stderr or root_proc.stdout or "not a git workspace").strip(),
                data={"workspace": str(workspace), "exit_code": root_proc.returncode},
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )

        branch_proc = run("branch", "--show-current")
        head_proc = run("rev-parse", "--verify", "HEAD")
        status_proc = run("status", "--porcelain")
        staged_proc = run(
            "diff", "--cached", "--name-only", "-z", "--diff-filter=ACDMRTUXB"
        )
        unstaged_proc = run("diff", "--name-only", "-z", "--diff-filter=ACDMRTUXB")
        untracked_proc = run("ls-files", "--others", "--exclude-standard", "-z")
        conflicted_proc = run("diff", "--name-only", "-z", "--diff-filter=U")
        upstream_proc = run(
            "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"
        )

        branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else ""
        head = head_proc.stdout.strip() if head_proc.returncode == 0 else None
        upstream = (
            upstream_proc.stdout.strip()
            if upstream_proc.returncode == 0 and upstream_proc.stdout.strip()
            else None
        )
        ahead: int | None = None
        behind: int | None = None
        if head and upstream:
            divergence_proc = run("rev-list", "--left-right", "--count", "HEAD...@{u}")
            if divergence_proc.returncode == 0:
                fields = divergence_proc.stdout.strip().split()
                if len(fields) == 2:
                    try:
                        ahead = int(fields[0])
                        behind = int(fields[1])
                    except ValueError:
                        ahead = None
                        behind = None

        staged_paths = nul_paths(staged_proc)
        unstaged_paths = nul_paths(unstaged_proc)
        untracked_paths = nul_paths(untracked_proc)
        conflicted_paths = nul_paths(conflicted_proc)
        changed_paths = list(
            dict.fromkeys(
                [
                    *staged_paths,
                    *unstaged_paths,
                    *untracked_paths,
                    *conflicted_paths,
                ]
            )
        )[:limit]
        changes = (
            [line for line in status_proc.stdout.splitlines() if line.strip()][:limit]
            if status_proc.returncode == 0
            else []
        )

        return self._ok(
            action,
            started,
            data={
                "root": root_proc.stdout.strip(),
                "branch": branch,
                "head": head,
                "head_short": head[:12] if head else None,
                "detached": bool(head and not branch),
                "upstream": upstream,
                "ahead": ahead,
                "behind": behind,
                "dirty": bool(changed_paths),
                "changed_files": len(changed_paths),
                "changed_paths": changed_paths,
                "staged_files": len(staged_paths),
                "staged_paths": staged_paths,
                "unstaged_files": len(unstaged_paths),
                "unstaged_paths": unstaged_paths,
                "untracked_files": len(untracked_paths),
                "untracked_paths": untracked_paths,
                "conflicted_files": len(conflicted_paths),
                "conflicted_paths": conflicted_paths,
                # Retain the bounded porcelain lines for existing callers that
                # need compact status evidence, but make structured paths the
                # primary resident-owned repository contract.
                "changes": changes,
            },
        )

    @staticmethod
    def _git_diff_scope(value: Any) -> str:
        text = str(value or "").strip().replace("\\", "/")
        while text.startswith("./"):
            text = text[2:]
        if not text:
            raise ValueError("git_diff relative_path must not be empty")
        if text.startswith("/") or (
            len(text) >= 3 and text[0].isalpha() and text[1] == ":" and text[2] == "/"
        ):
            raise ValueError("git_diff relative_path must be repository-relative")
        candidate = PurePosixPath(text)
        if not candidate.parts or any(part == ".." for part in candidate.parts):
            raise ValueError("git_diff relative_path must not escape the repository")
        normalized = candidate.as_posix().rstrip("/")
        if normalized in {"", ".", ".."}:
            raise ValueError("git_diff relative_path must name one repository path")
        return normalized

    def _git_diff(self, action: BodyAction, started: str) -> BodyActionResult:
        """Observe bounded repository diffs without routing through a shell command."""

        workspace = self._path_arg(action.args, default=os.getcwd())
        limit = max(1, min(1000, int(action.args.get("limit", 200))))
        timeout = max(1.0, float(action.args.get("timeout", 8.0)))
        max_output_chars = max(
            512,
            min(200_000, int(action.args.get("max_output_chars", 50_000))),
        )
        raw_scope = action.args.get("relative_path")
        scope_relative = (
            self._git_diff_scope(raw_scope) if raw_scope is not None else None
        )
        pathspec = f":(literal){scope_relative}" if scope_relative else "."

        def run(*parts: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["git", "-C", str(workspace), *parts],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )

        def nul_paths(proc: subprocess.CompletedProcess[str]) -> list[str]:
            if proc.returncode != 0:
                return []
            return [item for item in proc.stdout.split("\0") if item][:limit]

        root_proc = run("rev-parse", "--show-toplevel")
        if root_proc.returncode != 0:
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=False,
                error=(root_proc.stderr or root_proc.stdout or "not a git workspace").strip(),
                data={"workspace": str(workspace), "exit_code": root_proc.returncode},
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )

        worktree_patch_proc = run(
            "diff", "--no-ext-diff", "--no-textconv", "--no-color", "--", pathspec
        )
        staged_patch_proc = run(
            "diff", "--cached", "--no-ext-diff", "--no-textconv", "--no-color", "--", pathspec
        )
        worktree_paths_proc = run(
            "diff", "--name-only", "-z", "--diff-filter=ACDMRTUXB", "--", pathspec
        )
        staged_paths_proc = run(
            "diff", "--cached", "--name-only", "-z", "--diff-filter=ACDMRTUXB", "--", pathspec
        )
        untracked_proc = run(
            "ls-files", "--others", "--exclude-standard", "-z", "--", pathspec
        )
        scope_tracked_proc = (
            run("ls-files", "--error-unmatch", "--", pathspec)
            if scope_relative
            else None
        )
        for proc in (
            worktree_patch_proc,
            staged_patch_proc,
            worktree_paths_proc,
            staged_paths_proc,
            untracked_proc,
        ):
            if proc.returncode != 0:
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    error=(proc.stderr or proc.stdout or "git diff observation failed").strip(),
                    data={"workspace": str(workspace), "exit_code": proc.returncode},
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )
        if scope_tracked_proc is not None and scope_tracked_proc.returncode not in {0, 1}:
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=False,
                error=(
                    scope_tracked_proc.stderr
                    or scope_tracked_proc.stdout
                    or "git tracked-path observation failed"
                ).strip(),
                data={"workspace": str(workspace), "exit_code": scope_tracked_proc.returncode},
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )

        worktree_raw = worktree_patch_proc.stdout
        staged_raw = staged_patch_proc.stdout
        worktree_paths = nul_paths(worktree_paths_proc)
        staged_paths = nul_paths(staged_paths_proc)
        untracked_paths = nul_paths(untracked_proc)
        changed_paths = list(
            dict.fromkeys([*worktree_paths, *staged_paths, *untracked_paths])
        )[:limit]

        scope_limit = max(256, max_output_chars // 2)
        worktree_patch = worktree_raw[:scope_limit]
        staged_patch = staged_raw[:scope_limit]
        worktree_truncated = len(worktree_raw) > len(worktree_patch)
        staged_truncated = len(staged_raw) > len(staged_patch)

        parts: list[str] = []
        if worktree_patch.strip():
            parts.append(f"## Working tree\n{worktree_patch.rstrip()}")
        if staged_patch.strip():
            parts.append(f"## Staged\n{staged_patch.rstrip()}")
        if untracked_paths:
            parts.append("## Untracked paths\n" + "\n".join(untracked_paths))
        combined = "\n\n".join(parts)
        output = combined[:max_output_chars]
        output_truncated = len(combined) > len(output)

        head_proc = run("rev-parse", "--verify", "HEAD")
        head = head_proc.stdout.strip() if head_proc.returncode == 0 else None
        state_value: dict[str, Any] = {
            "worktree": worktree_raw,
            "staged": staged_raw,
            "untracked": untracked_paths,
        }
        if scope_relative:
            state_value["scope"] = scope_relative
        state_fingerprint = hashlib.sha256(
            json.dumps(
                state_value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        return self._ok(
            action,
            started,
            output=output,
            data={
                "root": root_proc.stdout.strip(),
                "head": head,
                "head_short": head[:12] if head else None,
                "dirty": bool(changed_paths),
                "changed_files": len(changed_paths),
                "changed_paths": changed_paths,
                "scope_relative_path": scope_relative,
                "scope_tracked": (
                    bool(scope_tracked_proc.returncode == 0)
                    if scope_tracked_proc is not None
                    else None
                ),
                "worktree": {
                    "paths": worktree_paths,
                    "files": len(worktree_paths),
                    "patch": worktree_patch,
                    "patch_chars": len(worktree_raw),
                    "patch_sha256": hashlib.sha256(
                        worktree_raw.encode("utf-8")
                    ).hexdigest(),
                    "truncated": worktree_truncated,
                },
                "staged": {
                    "paths": staged_paths,
                    "files": len(staged_paths),
                    "patch": staged_patch,
                    "patch_chars": len(staged_raw),
                    "patch_sha256": hashlib.sha256(
                        staged_raw.encode("utf-8")
                    ).hexdigest(),
                    "truncated": staged_truncated,
                },
                "untracked_paths": untracked_paths,
                "state_sha256": state_fingerprint,
                "truncated": worktree_truncated or staged_truncated or output_truncated,
                "max_output_chars": max_output_chars,
            },
        )

    def _command(self, action: BodyAction, started: str) -> BodyActionResult:
        command = str(action.args.get("command") or "").strip()
        if not command:
            raise ValueError("command body action requires command")

        context_id = str(
            action.args.get("session_id")
            or action.args.get("task_id")
            or action.event_id
            or "zn-resident"
        )
        explicit_env = action.args.get("env")
        env = (
            {str(key): str(value) for key, value in explicit_env.items()}
            if isinstance(explicit_env, dict)
            else {}
        )
        result = get_zn_local_terminal().execute(
            TerminalRequest(
                command=command,
                context_id=context_id,
                workdir=(
                    str(action.args["workdir"])
                    if action.args.get("workdir") is not None
                    else None
                ),
                timeout=float(action.args.get("timeout", 60.0)),
                background=bool(action.args.get("background", False)),
                pty=bool(action.args.get("pty", False)),
                env=env,
                max_output_chars=max(128, int(action.args.get("max_output_chars", 50_000))),
                cols=max(1, int(action.args.get("cols", 80))),
                rows=max(1, int(action.args.get("rows", 24))),
            )
        )
        return self._terminal_body_result(action, started, result)

    def _terminal_session(
        self,
        action: BodyAction,
        started: str,
        *,
        operation: str,
    ) -> BodyActionResult:
        session_id = str(action.args.get("session_id") or "").strip()
        if not session_id:
            raise ValueError(f"{action.kind} body action requires session_id")
        terminal = get_zn_local_terminal()
        if operation == "poll":
            return self._terminal_body_result(action, started, terminal.poll(session_id))
        if operation == "input":
            if "data" in action.args:
                data = action.args["data"]
            elif "input" in action.args:
                data = action.args["input"]
            else:
                raise ValueError(f"{action.kind} body action requires data/input")
            return self._terminal_body_result(
                action,
                started,
                terminal.write_stdin(session_id, str(data)),
            )
        if operation == "resize":
            result = terminal.resize(
                session_id,
                cols=max(1, int(action.args.get("cols", 80))),
                rows=max(1, int(action.args.get("rows", 24))),
            )
            return self._terminal_body_result(action, started, result)
        if operation == "stop":
            result = terminal.stop(session_id)
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=True,
                output=result.output,
                data=asdict(result),
                error=None,
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )
        raise ValueError(f"unknown terminal session operation: {operation}")

    @staticmethod
    def _terminal_body_result(
        action: BodyAction,
        started: str,
        result: TerminalResult,
    ) -> BodyActionResult:
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=result.success,
            output=result.output,
            data=asdict(result),
            error=result.error,
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    @staticmethod
    def _path_arg(args: dict[str, Any], default: str | None = None) -> Path:
        raw = args.get("path") or args.get("target") or args.get("workspace") or default
        if raw is None or not str(raw).strip():
            raise ValueError("body action requires path/target")
        return Path(str(raw)).expanduser()

    @staticmethod
    def _ok(
        action: BodyAction,
        started: str,
        *,
        output: str = "",
        data: dict[str, Any] | None = None,
    ) -> BodyActionResult:
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=output,
            data=dict(data or {}),
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS native_body_actions(
                    action_id TEXT PRIMARY KEY,
                    event_id TEXT,
                    kind TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    completed_at TEXT NOT NULL,
                    action_json TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_native_body_actions_event
                    ON native_body_actions(event_id, completed_at DESC);
                """
            )
            conn.commit()

    def _record(self, action: BodyAction, result: BodyActionResult) -> None:
        if self.store is None:
            return
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO native_body_actions"
                "(action_id,event_id,kind,success,completed_at,action_json,result_json) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    action.action_id,
                    action.event_id,
                    action.kind,
                    1 if result.success else 0,
                    result.completed_at,
                    json.dumps(asdict(action), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(asdict(result), ensure_ascii=False, separators=(",", ":")),
                ),
            )
            conn.execute(
                "DELETE FROM native_body_actions WHERE action_id IN ("
                "SELECT action_id FROM native_body_actions ORDER BY completed_at DESC "
                "LIMIT -1 OFFSET 4096)"
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        if self.store is None:
            raise RuntimeError("NativeBody requires a KernelStore for persistence")
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @staticmethod
    def _result_from_dict(raw: dict[str, Any]) -> BodyActionResult:
        return BodyActionResult(**dict(raw))
