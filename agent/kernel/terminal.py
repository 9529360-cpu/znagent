from __future__ import annotations

"""ZN-owned local terminal body.

This module is a source-level extraction of the mature local execution ideas in
``tools/environments/base.py``, ``tools/environments/local.py`` and the mature
PTY bridges. ZN keeps the hard-won mechanics -- safe working directories,
cross-platform shell selection, process-group cleanup, bounded output,
background sessions, interactive PTY I/O and child-environment isolation --
without keeping the old product's gateway/session/approval/config control plane.

Container, SSH and cloud backends are deliberately not imported here. They can
be extracted behind this ZN-owned interface when ZN has a concrete consumer.
"""

import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .pty import ZNPty, spawn_zn_pty


_IS_WINDOWS = os.name == "nt"
_COMPATIBLE_POSIX_SHELLS = frozenset({"bash", "zsh", "sh", "dash", "ksh", "mksh"})

_ZN_INHERITED_SECRET_KEYS = frozenset(
    {
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_TOKEN",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "XAI_API_KEY",
        "TOGETHER_API_KEY",
        "PERPLEXITY_API_KEY",
        "COHERE_API_KEY",
        "FIREWORKS_API_KEY",
        "TAVILY_API_KEY",
        "EXA_API_KEY",
        "FIRECRAWL_API_KEY",
        "PARALLEL_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "DISCORD_BOT_TOKEN",
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
        "SLACK_SIGNING_SECRET",
        "WHATSAPP_ACCESS_TOKEN",
        "SIGNAL_AUTH_TOKEN",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "ZN_UPDATE_S3_ACCESS_KEY_ID",
        "ZN_UPDATE_S3_SECRET_ACCESS_KEY",
    }
)
_ZN_RUNTIME_MARKERS = frozenset({"PYTHONHOME", "VIRTUAL_ENV", "CONDA_PREFIX"})


@dataclass(slots=True)
class TerminalRequest:
    command: str
    context_id: str = "zn-resident"
    workdir: str | None = None
    timeout: float = 60.0
    background: bool = False
    pty: bool = False
    env: dict[str, str] = field(default_factory=dict)
    max_output_chars: int = 50_000
    cols: int = 80
    rows: int = 24


@dataclass(slots=True)
class TerminalResult:
    status: str
    command: str
    success: bool
    output: str = ""
    exit_code: int | None = None
    cwd: str | None = None
    pid: int | None = None
    session_id: str | None = None
    truncated: bool = False
    timed_out: bool = False
    error: str | None = None


@dataclass(slots=True)
class _BackgroundProcess:
    handle: str
    context_id: str
    command: str
    process: subprocess.Popen[str]
    output_path: Path
    marker: str
    started_cwd: str
    max_output_chars: int
    started_at: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class _PtySession:
    handle: str
    context_id: str
    command: str
    pty: ZNPty
    marker: str
    started_cwd: str
    max_output_chars: int
    output: bytearray = field(default_factory=bytearray)
    truncated: bool = False
    started_at: float = field(default_factory=time.monotonic)


PtyFactory = Callable[..., ZNPty]


class ZNLocalTerminal:
    """Local shell/PTY execution owned by the resident body.

    Non-interactive commands get a fresh shell process. Interactive commands get
    a PTY session with the same context/cwd semantics and can receive stdin and
    resize events through their session id. Environment mutations are never
    silently promoted to the resident process.
    """

    def __init__(self, *, pty_factory: PtyFactory = spawn_zn_pty) -> None:
        self._lock = threading.RLock()
        self._cwd_by_context: dict[str, str] = {}
        self._background: dict[str, _BackgroundProcess] = {}
        self._pty_sessions: dict[str, _PtySession] = {}
        self._pty_factory = pty_factory

    def execute(self, request: TerminalRequest) -> TerminalResult:
        command = str(request.command or "").strip()
        if not command:
            raise ValueError("terminal command must not be empty")

        context_id = str(request.context_id or "zn-resident").strip() or "zn-resident"
        cwd = self._resolve_request_cwd(context_id, request.workdir)
        marker = f"__ZN_CWD_{uuid.uuid4().hex}__"
        script = self._wrap_command(command, marker)
        env = self._child_env(request.env)
        shell = self._find_shell()
        args = self._shell_args(shell, script)

        if request.pty:
            return self._execute_pty(
                request=request,
                command=command,
                context_id=context_id,
                cwd=cwd,
                marker=marker,
                args=args,
                env=env,
            )

        if request.background:
            return self._start_background(
                request=request,
                command=command,
                context_id=context_id,
                cwd=cwd,
                marker=marker,
                args=args,
                env=env,
            )

        proc = self._spawn(args, cwd=cwd, env=env, stdout=subprocess.PIPE)
        try:
            stdout, _ = proc.communicate(timeout=max(0.05, float(request.timeout)))
            timed_out = False
        except subprocess.TimeoutExpired:
            self._terminate_tree(proc)
            stdout, _ = proc.communicate()
            timed_out = True

        clean_output, observed_cwd = self._extract_cwd(stdout or "", marker)
        if observed_cwd:
            self._remember_cwd(context_id, observed_cwd)
        rendered, truncated = _bounded_output(clean_output, request.max_output_chars)
        code = proc.returncode
        success = code == 0 and not timed_out
        return TerminalResult(
            status="timeout" if timed_out else "completed",
            command=command,
            success=success,
            output=rendered,
            exit_code=code,
            cwd=observed_cwd or cwd,
            pid=proc.pid,
            truncated=truncated,
            timed_out=timed_out,
            error=(
                f"command timed out after {float(request.timeout):g}s"
                if timed_out
                else None if success else f"command exited with code {code}"
            ),
        )

    def poll(self, session_id: str) -> TerminalResult:
        key = str(session_id or "").strip()
        with self._lock:
            pty_item = self._pty_sessions.get(key)
        if pty_item is not None:
            return self._poll_pty(pty_item)

        item = self._background_item(key)
        code = item.process.poll()
        output = _read_text_best_effort(item.output_path)
        clean_output, observed_cwd = self._extract_cwd(output, item.marker)
        if code is None:
            rendered, truncated = _bounded_output(clean_output, item.max_output_chars)
            return TerminalResult(
                status="running",
                command=item.command,
                success=True,
                output=rendered,
                cwd=observed_cwd or item.started_cwd,
                pid=item.process.pid,
                session_id=item.handle,
                truncated=truncated,
            )

        if observed_cwd:
            self._remember_cwd(item.context_id, observed_cwd)
        rendered, truncated = _bounded_output(clean_output, item.max_output_chars)
        self._forget_background(item.handle)
        return TerminalResult(
            status="completed",
            command=item.command,
            success=code == 0,
            output=rendered,
            exit_code=code,
            cwd=observed_cwd or item.started_cwd,
            pid=item.process.pid,
            session_id=item.handle,
            truncated=truncated,
            error=None if code == 0 else f"command exited with code {code}",
        )

    def write_stdin(self, session_id: str, data: str | bytes) -> TerminalResult:
        item = self._pty_item(session_id)
        if not item.pty.is_alive():
            return self._poll_pty(item)

        payload = data if isinstance(data, bytes) else str(data).encode("utf-8")
        try:
            item.pty.write(payload)
        except Exception:
            if not item.pty.is_alive():
                return self._poll_pty(item)
            raise

        self._drain_pty(item, timeout=0.01)
        if not item.pty.is_alive():
            return self._poll_pty(item)

        rendered, truncated, observed_cwd = self._pty_output(item)
        return TerminalResult(
            status="running",
            command=item.command,
            success=True,
            output=rendered,
            cwd=observed_cwd or item.started_cwd,
            pid=item.pty.pid,
            session_id=item.handle,
            truncated=truncated,
        )

    def resize(self, session_id: str, *, cols: int, rows: int) -> TerminalResult:
        item = self._pty_item(session_id)
        if not item.pty.is_alive():
            return self._poll_pty(item)

        try:
            item.pty.resize(int(cols), int(rows))
        except Exception:
            if not item.pty.is_alive():
                return self._poll_pty(item)
            raise

        if not item.pty.is_alive():
            return self._poll_pty(item)

        return TerminalResult(
            status="running",
            command=item.command,
            success=True,
            cwd=item.started_cwd,
            pid=item.pty.pid,
            session_id=item.handle,
        )

    def stop(self, session_id: str) -> TerminalResult:
        key = str(session_id or "").strip()
        with self._lock:
            pty_item = self._pty_sessions.get(key)
        if pty_item is not None:
            return self._stop_pty(pty_item)

        item = self._background_item(key)
        if item.process.poll() is None:
            self._terminate_tree(item.process)
        output = _read_text_best_effort(item.output_path)
        clean_output, observed_cwd = self._extract_cwd(output, item.marker)
        if observed_cwd:
            self._remember_cwd(item.context_id, observed_cwd)
        rendered, truncated = _bounded_output(clean_output, item.max_output_chars)
        code = item.process.poll()
        self._forget_background(item.handle)
        return TerminalResult(
            status="stopped",
            command=item.command,
            success=False,
            output=rendered,
            exit_code=code,
            cwd=observed_cwd or item.started_cwd,
            pid=item.process.pid,
            session_id=item.handle,
            truncated=truncated,
            error="background command stopped",
        )

    def context_cwd(self, context_id: str) -> str | None:
        with self._lock:
            return self._cwd_by_context.get(str(context_id or "zn-resident"))

    def _execute_pty(
        self,
        *,
        request: TerminalRequest,
        command: str,
        context_id: str,
        cwd: str,
        marker: str,
        args: list[str],
        env: dict[str, str],
    ) -> TerminalResult:
        pty = self._pty_factory(
            args,
            cwd=cwd,
            env=env,
            cols=int(request.cols),
            rows=int(request.rows),
        )
        handle = f"pty-{uuid.uuid4().hex[:12]}"
        item = _PtySession(
            handle=handle,
            context_id=context_id,
            command=command,
            pty=pty,
            marker=marker,
            started_cwd=cwd,
            max_output_chars=max(128, int(request.max_output_chars)),
        )
        if request.background:
            with self._lock:
                self._pty_sessions[handle] = item
            self._drain_pty(item, timeout=0.01)
            return TerminalResult(
                status="running",
                command=command,
                success=True,
                cwd=cwd,
                pid=pty.pid,
                session_id=handle,
            )

        deadline = time.monotonic() + max(0.05, float(request.timeout))
        timed_out = False
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            data = pty.read(timeout=min(0.1, remaining))
            if data is None:
                break
            if data:
                self._append_pty_output(item, data)
                continue
            if not pty.is_alive():
                break

        if timed_out and pty.is_alive():
            pty.close()
        else:
            self._drain_pty(item, timeout=0.0)
        code = pty.exit_code()
        rendered, truncated, observed_cwd = self._pty_output(item)
        if observed_cwd:
            self._remember_cwd(context_id, observed_cwd)
        if pty.is_alive():
            pty.close()
        else:
            pty.close()
        success = not timed_out and (code == 0 or code is None)
        return TerminalResult(
            status="timeout" if timed_out else "completed",
            command=command,
            success=success,
            output=rendered,
            exit_code=code,
            cwd=observed_cwd or cwd,
            pid=pty.pid,
            session_id=handle,
            truncated=truncated,
            timed_out=timed_out,
            error=(
                f"command timed out after {float(request.timeout):g}s"
                if timed_out
                else None if success else f"command exited with code {code}"
            ),
        )

    def _poll_pty(self, item: _PtySession) -> TerminalResult:
        self._drain_pty(item, timeout=0.01)
        alive = item.pty.is_alive()
        rendered, truncated, observed_cwd = self._pty_output(item)
        if alive:
            return TerminalResult(
                status="running",
                command=item.command,
                success=True,
                output=rendered,
                cwd=observed_cwd or item.started_cwd,
                pid=item.pty.pid,
                session_id=item.handle,
                truncated=truncated,
            )

        code = item.pty.exit_code()
        if observed_cwd:
            self._remember_cwd(item.context_id, observed_cwd)
        self._forget_pty(item.handle)
        success = code == 0 or code is None
        return TerminalResult(
            status="completed",
            command=item.command,
            success=success,
            output=rendered,
            exit_code=code,
            cwd=observed_cwd or item.started_cwd,
            pid=item.pty.pid,
            session_id=item.handle,
            truncated=truncated,
            error=None if success else f"command exited with code {code}",
        )

    def _stop_pty(self, item: _PtySession) -> TerminalResult:
        self._drain_pty(item, timeout=0.01)
        item.pty.close()
        code = item.pty.exit_code()
        rendered, truncated, observed_cwd = self._pty_output(item)
        if observed_cwd:
            self._remember_cwd(item.context_id, observed_cwd)
        with self._lock:
            self._pty_sessions.pop(item.handle, None)
        return TerminalResult(
            status="stopped",
            command=item.command,
            success=False,
            output=rendered,
            exit_code=code,
            cwd=observed_cwd or item.started_cwd,
            pid=item.pty.pid,
            session_id=item.handle,
            truncated=truncated,
            error="interactive command stopped",
        )

    def _pty_item(self, session_id: str) -> _PtySession:
        key = str(session_id or "").strip()
        with self._lock:
            item = self._pty_sessions.get(key)
        if item is None:
            raise KeyError(f"unknown ZN interactive terminal session: {key or '<empty>'}")
        return item

    def _drain_pty(self, item: _PtySession, *, timeout: float) -> None:
        first = True
        while True:
            data = item.pty.read(timeout=timeout if first else 0.0)
            first = False
            if data is None or data == b"":
                return
            self._append_pty_output(item, data)

    @staticmethod
    def _append_pty_output(item: _PtySession, data: bytes) -> None:
        item.output.extend(data)
        max_bytes = max(4096, item.max_output_chars * 4)
        if len(item.output) <= max_bytes:
            return
        payload = max_bytes - 128
        head = max(0, int(payload * 0.35))
        tail = max(0, payload - head)
        compact = (
            bytes(item.output[:head])
            + b"\n... [ZN PTY stream buffer truncated] ...\n"
            + bytes(item.output[-tail:])
        )
        item.output = bytearray(compact)
        item.truncated = True

    def _pty_output(self, item: _PtySession) -> tuple[str, bool, str | None]:
        text = bytes(item.output).decode("utf-8", errors="replace")
        clean_output, observed_cwd = self._extract_cwd(text, item.marker)
        rendered, bounded = _bounded_output(clean_output, item.max_output_chars)
        return rendered, item.truncated or bounded, observed_cwd

    def _forget_pty(self, handle: str) -> None:
        with self._lock:
            item = self._pty_sessions.pop(handle, None)
        if item is not None:
            item.pty.close()

    def _start_background(
        self,
        *,
        request: TerminalRequest,
        command: str,
        context_id: str,
        cwd: str,
        marker: str,
        args: list[str],
        env: dict[str, str],
    ) -> TerminalResult:
        handle = f"term-{uuid.uuid4().hex[:12]}"
        output_dir = Path(tempfile.gettempdir()) / "zn-terminal"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{handle}.log"
        output_handle = output_path.open("w", encoding="utf-8", errors="replace")
        try:
            proc = self._spawn(args, cwd=cwd, env=env, stdout=output_handle)
        finally:
            output_handle.close()

        item = _BackgroundProcess(
            handle=handle,
            context_id=context_id,
            command=command,
            process=proc,
            output_path=output_path,
            marker=marker,
            started_cwd=cwd,
            max_output_chars=max(1, int(request.max_output_chars)),
        )
        with self._lock:
            self._background[handle] = item
        return TerminalResult(
            status="running",
            command=command,
            success=True,
            cwd=cwd,
            pid=proc.pid,
            session_id=handle,
        )

    def _background_item(self, session_id: str) -> _BackgroundProcess:
        key = str(session_id or "").strip()
        with self._lock:
            item = self._background.get(key)
        if item is None:
            raise KeyError(f"unknown ZN terminal session: {key or '<empty>'}")
        return item

    def _forget_background(self, handle: str) -> None:
        with self._lock:
            item = self._background.pop(handle, None)
        if item is not None:
            try:
                item.output_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _resolve_request_cwd(self, context_id: str, workdir: str | None) -> str:
        requested = str(workdir or "").strip()
        if requested:
            candidate = _normalize_host_path(requested)
        else:
            with self._lock:
                remembered = self._cwd_by_context.get(context_id)
            candidate = remembered or os.getcwd()
        return _resolve_safe_cwd(candidate)

    def _remember_cwd(self, context_id: str, cwd: str) -> None:
        normalized = _normalize_host_path(cwd)
        if _cwd_usable(normalized):
            with self._lock:
                self._cwd_by_context[context_id] = normalized

    @staticmethod
    def _wrap_command(command: str, marker: str) -> str:
        marker_literal = marker.replace("'", "")
        return (
            "trap '__zn_status=$?; printf \"\\n"
            + marker_literal
            + "%s\\n\" \"$PWD\"; exit $__zn_status' EXIT\n"
            + command
        )

    @staticmethod
    def _extract_cwd(output: str, marker: str) -> tuple[str, str | None]:
        pattern = re.compile(r"(?:\r?\n)?" + re.escape(marker) + r"([^\r\n]*)\r?\n?")
        matches = list(pattern.finditer(output))
        if not matches:
            return output, None
        observed = matches[-1].group(1).strip()
        cleaned = pattern.sub("", output)
        normalized = _normalize_host_path(observed) if observed else None
        return cleaned, normalized

    @staticmethod
    def _child_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
        env = {str(key): str(value) for key, value in os.environ.items()}
        for key in _ZN_INHERITED_SECRET_KEYS:
            env.pop(key, None)
        for key in list(env):
            if key.startswith("ZN_CREDENTIAL_") or key.startswith("ZN_SECRET_"):
                env.pop(key, None)
        for key in _ZN_RUNTIME_MARKERS:
            env.pop(key, None)
        env.pop("PYTHONPATH", None)
        env.setdefault("PYTHONUTF8", "1")
        if _IS_WINDOWS:
            env.setdefault("MSYS_NO_PATHCONV", "1")
            env.setdefault("MSYS2_ARG_CONV_EXCL", "*")
        if extra:
            env.update({str(key): str(value) for key, value in extra.items()})
        return env

    @staticmethod
    def _find_shell() -> str:
        if not _IS_WINDOWS:
            configured = str(os.environ.get("SHELL") or "").strip()
            if (
                configured
                and Path(configured).name in _COMPATIBLE_POSIX_SHELLS
                and os.path.isfile(configured)
                and os.access(configured, os.X_OK)
            ):
                return configured
            return shutil.which("bash") or shutil.which("sh") or "/bin/sh"

        candidates = [str(os.environ.get("ZN_GIT_BASH_PATH") or "").strip()]
        which = shutil.which("bash")
        if which:
            candidates.append(which)
        program_files = [
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        for root in program_files:
            if not root:
                continue
            candidates.extend(
                [
                    os.path.join(root, "Git", "bin", "bash.exe"),
                    os.path.join(root, "Programs", "Git", "bin", "bash.exe"),
                ]
            )
        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate
        raise RuntimeError("ZN local terminal requires Git Bash on Windows")

    @staticmethod
    def _shell_args(shell: str, script: str) -> list[str]:
        return [shell, "-c", script]

    @staticmethod
    def _spawn(
        args: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        stdout,
    ) -> subprocess.Popen[str]:
        kwargs: dict[str, object] = {}
        if _IS_WINDOWS:
            kwargs["creationflags"] = int(
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kwargs,
        )

    @staticmethod
    def _terminate_tree(proc: subprocess.Popen[str]) -> None:
        if proc.poll() is not None:
            return
        if _IS_WINDOWS:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=3,
                )
            except Exception:
                try:
                    proc.kill()
                except OSError:
                    pass
            try:
                proc.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                pass
            return

        try:
            pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            return
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                break
            except PermissionError:
                pass
            proc.poll()
            time.sleep(0.05)
        else:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            proc.wait(timeout=1)
        except (subprocess.TimeoutExpired, OSError):
            pass


def _normalize_host_path(value: str) -> str:
    expanded = os.path.expanduser(str(value or "").strip())
    if not expanded:
        return os.getcwd()
    if _IS_WINDOWS:
        match = re.match(r"^/(?:(?:cygdrive|mnt)/)?([a-zA-Z])(?:/(.*))?$", expanded)
        if match:
            drive = match.group(1).upper()
            tail = (match.group(2) or "").replace("/", "\\")
            expanded = f"{drive}:\\{tail}" if tail else f"{drive}:\\"
    return os.path.abspath(expanded)


def _cwd_usable(value: str) -> bool:
    return bool(value) and os.path.isdir(value) and os.access(value, os.X_OK)


def _resolve_safe_cwd(value: str) -> str:
    candidate = _normalize_host_path(value)
    if _cwd_usable(candidate):
        return candidate
    current = Path(candidate)
    for parent in (current.parent, *current.parents):
        text = str(parent)
        if _cwd_usable(text):
            return text
    home = str(Path.home())
    if _cwd_usable(home):
        return home
    return tempfile.gettempdir()


def _bounded_output(value: str, max_chars: int) -> tuple[str, bool]:
    text = str(value or "")
    limit = max(128, int(max_chars))
    if len(text) <= limit:
        return text, False
    notice = f"\n... [ZN terminal output truncated; {len(text) - limit:,}+ chars omitted] ...\n"
    payload = max(0, limit - len(notice))
    head = int(payload * 0.4)
    tail = payload - head
    return text[:head] + notice + (text[-tail:] if tail else ""), True


def _read_text_best_effort(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


_default_terminal: ZNLocalTerminal | None = None
_default_terminal_lock = threading.Lock()


def get_zn_local_terminal() -> ZNLocalTerminal:
    global _default_terminal
    if _default_terminal is not None:
        return _default_terminal
    with _default_terminal_lock:
        if _default_terminal is None:
            _default_terminal = ZNLocalTerminal()
        return _default_terminal
