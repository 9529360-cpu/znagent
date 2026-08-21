from __future__ import annotations

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
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .models import utc_now

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

    Files, processes, Git and the terminal are not separate cognitive skills.
    They are different movements of the same body. This class deliberately
    contains no planning or model logic: Thought chooses an action; Body
    executes it and returns evidence.

    The terminal path reuses Hermes' mature execution stack, including its
    local/container/SSH/cloud backends, instead of rebuilding shell plumbing.
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
        """Return a fresh native snapshot of the body and immediate host."""
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
        """Perform one concrete body action and durably record its outcome."""
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
            data = self.sense()
            return self._ok(action, started, data=data)
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
        if kind in {"command", "terminal", "shell"}:
            return self._command(action, started)
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

        def run(*parts: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["git", "-C", str(workspace), *parts],
                capture_output=True,
                text=True,
                timeout=max(1.0, float(action.args.get("timeout", 5.0))),
                check=False,
            )

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
        root = root_proc.stdout.strip()
        branch_proc = run("branch", "--show-current")
        status_proc = run("status", "--porcelain")
        changed = [line for line in status_proc.stdout.splitlines() if line.strip()]
        return self._ok(
            action,
            started,
            data={
                "root": root,
                "branch": branch_proc.stdout.strip() if branch_proc.returncode == 0 else "",
                "dirty": bool(changed),
                "changed_files": len(changed),
                "changes": changed[:200],
            },
        )

    def _command(self, action: BodyAction, started: str) -> BodyActionResult:
        command = str(action.args.get("command") or "").strip()
        if not command:
            raise ValueError("command body action requires command")

        # Reuse the mature Hermes terminal stack rather than implementing a
        # second shell/session/container subsystem in the resident kernel.
        from tools.terminal_tool import terminal_tool

        raw = terminal_tool(
            command=command,
            background=bool(action.args.get("background", False)),
            timeout=(
                int(action.args["timeout"])
                if action.args.get("timeout") is not None
                else None
            ),
            task_id=str(action.args.get("task_id") or action.event_id or "zn-resident"),
            session_id=str(action.args.get("session_id") or action.event_id or "zn-resident"),
            workdir=(
                str(action.args["workdir"])
                if action.args.get("workdir") is not None
                else None
            ),
            pty=bool(action.args.get("pty", False)),
            notify_on_complete=bool(action.args.get("notify_on_complete", False)),
        )
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            payload = {"output": str(raw), "exit_code": None}

        exit_code = payload.get("exit_code")
        status = str(payload.get("status") or "").lower()
        success = bool(
            status in {"running", "success", "completed"}
            or exit_code == 0
            or (bool(action.args.get("background")) and payload.get("session_id"))
        )
        output = str(payload.get("output") or payload.get("stdout") or "")
        error = payload.get("error")
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=success,
            output=output,
            data=payload,
            error=str(error) if error else None,
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
