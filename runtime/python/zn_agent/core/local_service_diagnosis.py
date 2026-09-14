from __future__ import annotations

"""Bounded local-service diagnosis and repair verification.

This module composes existing terminal/process capabilities into one ordinary
user task: inspect a local listener, correlate it with the owning process, read a
bounded log tail, probe an optional health URL, run an explicitly supplied repair
command when it is safe to do so, and then verify the real service condition.

It is deliberately not a service manager. Unknown processes are never killed,
restart commands are never invented, and command success is not treated as
service recovery.
"""

import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import psutil

from .terminal import TerminalRequest, TerminalResult, ZNLocalTerminal


@dataclass(frozen=True, slots=True)
class LocalServiceTarget:
    port: int
    host: str = "127.0.0.1"
    expected_process_name: str | None = None
    health_url: str | None = None
    log_path: str | None = None

    def __post_init__(self) -> None:
        port = int(self.port)
        if not 1 <= port <= 65535:
            raise ValueError("local service port must be between 1 and 65535")
        if not str(self.host or "").strip():
            raise ValueError("local service host must not be empty")


@dataclass(frozen=True, slots=True)
class LocalListenerObservation:
    host: str
    port: int
    pid: int | None
    process_name: str | None
    executable_path: str | None
    command_line: tuple[str, ...]
    created_at_epoch: float | None
    status: str


@dataclass(frozen=True, slots=True)
class LocalHealthObservation:
    url: str
    ok: bool
    status_code: int | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class LocalLogObservation:
    path: str
    exists: bool
    tail: str = ""
    truncated: bool = False
    error: str | None = None


@dataclass(frozen=True, slots=True)
class LocalServiceSnapshot:
    target: LocalServiceTarget
    listeners: tuple[LocalListenerObservation, ...]
    health: LocalHealthObservation | None
    log: LocalLogObservation | None
    healthy: bool
    reason: str
    inspection_errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LocalServiceDiagnosisResult:
    before: LocalServiceSnapshot
    after: LocalServiceSnapshot
    repair_attempted: bool
    repair_result: TerminalResult | None
    repair_blocked_reason: str | None

    @property
    def restored(self) -> bool:
        return not self.before.healthy and self.after.healthy

    @property
    def success(self) -> bool:
        return self.after.healthy


ConnectionProvider = Callable[[], Iterable[object]]
UrlOpen = Callable[..., object]
Sleep = Callable[[float], None]


class LocalServiceDiagnoser:
    """Inspect one local service and optionally execute one explicit repair.

    A repair is blocked when the target port is owned by an unexpected process or
    by multiple distinct PIDs. This prevents a generic "restart" request from
    trampling an unrelated service that happens to occupy the same port.
    """

    def __init__(
        self,
        *,
        terminal: ZNLocalTerminal | None = None,
        connection_provider: ConnectionProvider | None = None,
        urlopen: UrlOpen | None = None,
        sleep: Sleep = time.sleep,
        max_log_bytes: int = 24_000,
        max_log_lines: int = 160,
    ) -> None:
        self.terminal = terminal or ZNLocalTerminal()
        self._connection_provider = connection_provider or (
            lambda: psutil.net_connections(kind="inet")
        )
        self._urlopen = urlopen or urllib.request.urlopen
        self._sleep = sleep
        self.max_log_bytes = max(1024, int(max_log_bytes))
        self.max_log_lines = max(1, int(max_log_lines))

    def inspect(
        self,
        target: LocalServiceTarget,
        *,
        health_timeout: float = 2.0,
    ) -> LocalServiceSnapshot:
        listeners, listener_errors = self._listeners(target)
        health = self._health(target, timeout=health_timeout)
        log = self._log_tail(target.log_path) if target.log_path else None
        healthy, reason = self._evaluate(target, listeners, health)
        return LocalServiceSnapshot(
            target=target,
            listeners=tuple(listeners),
            health=health,
            log=log,
            healthy=healthy,
            reason=reason,
            inspection_errors=tuple(listener_errors),
        )

    def diagnose_and_repair(
        self,
        target: LocalServiceTarget,
        *,
        repair_command: str | None = None,
        workdir: str | None = None,
        repair_timeout: float = 30.0,
        verification_timeout: float = 8.0,
        verification_interval: float = 0.2,
        health_timeout: float = 2.0,
    ) -> LocalServiceDiagnosisResult:
        before = self.inspect(target, health_timeout=health_timeout)
        if before.healthy or not str(repair_command or "").strip():
            return LocalServiceDiagnosisResult(
                before=before,
                after=before,
                repair_attempted=False,
                repair_result=None,
                repair_blocked_reason=None,
            )

        blocked = self._repair_block_reason(target, before.listeners)
        if blocked is not None:
            return LocalServiceDiagnosisResult(
                before=before,
                after=before,
                repair_attempted=False,
                repair_result=None,
                repair_blocked_reason=blocked,
            )

        repair = self.terminal.execute(
            TerminalRequest(
                command=str(repair_command).strip(),
                context_id="local-service-diagnosis",
                workdir=workdir,
                timeout=max(0.05, float(repair_timeout)),
                max_output_chars=20_000,
            )
        )
        after = self._verify(
            target,
            timeout=max(0.0, float(verification_timeout)),
            interval=max(0.01, float(verification_interval)),
            health_timeout=health_timeout,
        )
        return LocalServiceDiagnosisResult(
            before=before,
            after=after,
            repair_attempted=True,
            repair_result=repair,
            repair_blocked_reason=None,
        )

    def _verify(
        self,
        target: LocalServiceTarget,
        *,
        timeout: float,
        interval: float,
        health_timeout: float,
    ) -> LocalServiceSnapshot:
        deadline = time.monotonic() + timeout
        last = self.inspect(target, health_timeout=health_timeout)
        while not last.healthy and time.monotonic() < deadline:
            self._sleep(min(interval, max(0.0, deadline - time.monotonic())))
            last = self.inspect(target, health_timeout=health_timeout)
        return last

    def _listeners(
        self,
        target: LocalServiceTarget,
    ) -> tuple[list[LocalListenerObservation], list[str]]:
        rows: list[LocalListenerObservation] = []
        errors: list[str] = []
        try:
            connections = list(self._connection_provider())
        except Exception as exc:
            return [], [f"connection inspection failed: {type(exc).__name__}: {exc}"]

        for connection in connections:
            status = str(getattr(connection, "status", "") or "")
            if status.upper() != "LISTEN":
                continue
            local = getattr(connection, "laddr", None)
            local_host, local_port = _address_parts(local)
            if local_port != target.port or not _host_matches(target.host, local_host):
                continue
            pid = _positive_int(getattr(connection, "pid", None))
            process_name: str | None = None
            executable: str | None = None
            command_line: tuple[str, ...] = ()
            created_at: float | None = None
            if pid is not None:
                try:
                    process = psutil.Process(pid)
                    with process.oneshot():
                        process_name = _best_effort(process.name)
                        executable = _best_effort(process.exe)
                        raw_cmdline = _best_effort(process.cmdline)
                        if isinstance(raw_cmdline, (list, tuple)):
                            command_line = tuple(str(item) for item in raw_cmdline)
                        raw_created = _best_effort(process.create_time)
                        if raw_created is not None:
                            created_at = float(raw_created)
                except (psutil.NoSuchProcess, psutil.ZombieProcess):
                    errors.append(f"listener process disappeared during inspection: pid={pid}")
                except (psutil.AccessDenied, OSError) as exc:
                    errors.append(
                        f"listener process metadata unavailable: pid={pid}: "
                        f"{type(exc).__name__}"
                    )
            rows.append(
                LocalListenerObservation(
                    host=local_host,
                    port=local_port,
                    pid=pid,
                    process_name=process_name,
                    executable_path=executable,
                    command_line=command_line,
                    created_at_epoch=created_at,
                    status=status,
                )
            )
        rows.sort(key=lambda row: (row.pid is None, row.pid or 0, row.host))
        return rows, errors

    def _health(
        self,
        target: LocalServiceTarget,
        *,
        timeout: float,
    ) -> LocalHealthObservation | None:
        url = str(target.health_url or "").strip()
        if not url:
            return None
        try:
            response = self._urlopen(url, timeout=max(0.05, float(timeout)))
            try:
                code = int(getattr(response, "status", response.getcode()))
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
            return LocalHealthObservation(url=url, ok=200 <= code < 400, status_code=code)
        except urllib.error.HTTPError as exc:
            return LocalHealthObservation(
                url=url,
                ok=False,
                status_code=int(exc.code),
                error=f"HTTP {exc.code}",
            )
        except Exception as exc:
            return LocalHealthObservation(
                url=url,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _log_tail(self, value: str) -> LocalLogObservation:
        path = Path(os.path.expanduser(os.path.expandvars(str(value)))).resolve(strict=False)
        if not path.is_file():
            return LocalLogObservation(path=str(path), exists=False)
        try:
            size = path.stat().st_size
            with path.open("rb") as handle:
                if size > self.max_log_bytes:
                    handle.seek(-self.max_log_bytes, os.SEEK_END)
                payload = handle.read(self.max_log_bytes)
            text = payload.decode("utf-8", errors="replace")
            lines = text.splitlines()
            line_truncated = len(lines) > self.max_log_lines
            if line_truncated:
                lines = lines[-self.max_log_lines :]
            return LocalLogObservation(
                path=str(path),
                exists=True,
                tail="\n".join(lines),
                truncated=size > self.max_log_bytes or line_truncated,
            )
        except OSError as exc:
            return LocalLogObservation(
                path=str(path),
                exists=True,
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _evaluate(
        target: LocalServiceTarget,
        listeners: list[LocalListenerObservation],
        health: LocalHealthObservation | None,
    ) -> tuple[bool, str]:
        if not listeners:
            return False, "target port is not listening"
        expected = _normalized_process_name(target.expected_process_name)
        if expected and not any(
            _normalized_process_name(row.process_name) == expected for row in listeners
        ):
            return False, "target port is owned by an unexpected process"
        if health is not None and not health.ok:
            return False, health.error or f"health endpoint returned {health.status_code}"
        return True, "listener and health checks are satisfied"

    @staticmethod
    def _repair_block_reason(
        target: LocalServiceTarget,
        listeners: tuple[LocalListenerObservation, ...],
    ) -> str | None:
        pids = {row.pid for row in listeners if row.pid is not None}
        if len(pids) > 1:
            return "target port has multiple owning processes"
        expected = _normalized_process_name(target.expected_process_name)
        if expected and listeners and not any(
            _normalized_process_name(row.process_name) == expected for row in listeners
        ):
            return "target port is occupied by an unexpected process"
        return None


def _address_parts(address: object) -> tuple[str, int]:
    host = str(getattr(address, "ip", "") or "")
    port = _positive_int(getattr(address, "port", None))
    if port is None and isinstance(address, (tuple, list)) and len(address) >= 2:
        host = str(address[0] or "")
        port = _positive_int(address[1])
    return host, int(port or 0)


def _host_matches(target: str, observed: str) -> bool:
    wanted = str(target).strip().casefold()
    actual = str(observed).strip().casefold()
    if wanted in {"localhost", "127.0.0.1", "::1"}:
        return actual in {"localhost", "127.0.0.1", "::1", "0.0.0.0", "::"}
    if wanted in {"0.0.0.0", "::", "*"}:
        return True
    return wanted == actual


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _normalized_process_name(value: str | None) -> str:
    name = os.path.basename(str(value or "").strip()).casefold()
    return name[:-4] if name.endswith(".exe") else name


def _best_effort(callable_value: Callable[[], object]) -> object | None:
    try:
        return callable_value()
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
        return None
