from __future__ import annotations

"""Bounded read-only local-service diagnosis and verification.

This module observes one local listener, correlates it with its owning process,
reads a bounded log tail and probes an optional same-service HTTP health URL. It
deliberately does not execute repair commands or kill processes. Repairs stay on
ZN's existing ``command`` Body action so the established authority, replay and
durable side-effect journal remain the only mutation boundary.
"""

import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlsplit

import psutil


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", "*"})
_MAX_HEALTH_URL_CHARS = 2048


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_without_redirects(url: str, *, timeout: float):
    opener = urllib.request.build_opener(_NoRedirectHandler())
    return opener.open(url, timeout=timeout)


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
        host = str(self.host or "").strip()
        if not host:
            raise ValueError("local service host must not be empty")
        if len(host) > 255:
            raise ValueError("local service host is too long")
        if self.health_url:
            _validate_health_url(str(self.health_url), host=host, port=port)


@dataclass(frozen=True, slots=True)
class LocalListenerObservation:
    host: str
    port: int
    pid: int | None
    process_name: str | None
    executable_path: str | None
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
    repair_blocked_reason: str | None = None
    inspection_errors: tuple[str, ...] = ()


ConnectionProvider = Callable[[], Iterable[object]]
UrlOpen = Callable[..., object]
Sleep = Callable[[float], None]


class LocalServiceDiagnoser:
    """Observe and re-observe one local service without mutation authority."""

    def __init__(
        self,
        *,
        connection_provider: ConnectionProvider | None = None,
        urlopen: UrlOpen | None = None,
        sleep: Sleep = time.sleep,
        max_log_bytes: int = 24_000,
        max_log_lines: int = 160,
    ) -> None:
        self._connection_provider = connection_provider or (
            lambda: psutil.net_connections(kind="inet")
        )
        self._urlopen = urlopen or _open_without_redirects
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
            repair_blocked_reason=self.repair_block_reason(target, tuple(listeners)),
            inspection_errors=tuple(listener_errors),
        )

    def wait_until_healthy(
        self,
        target: LocalServiceTarget,
        *,
        timeout: float = 8.0,
        interval: float = 0.2,
        health_timeout: float = 2.0,
    ) -> LocalServiceSnapshot:
        deadline = time.monotonic() + max(0.0, float(timeout))
        last = self.inspect(target, health_timeout=health_timeout)
        while not last.healthy and time.monotonic() < deadline:
            self._sleep(min(max(0.01, float(interval)), max(0.0, deadline - time.monotonic())))
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
            created_at: float | None = None
            if pid is not None:
                try:
                    process = psutil.Process(pid)
                    with process.oneshot():
                        process_name = _best_effort(process.name)
                        executable = _best_effort(process.exe)
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
                raw_status = getattr(response, "status", None)
                if raw_status is None:
                    raw_status = response.getcode()
                code = int(raw_status)
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
            return LocalHealthObservation(url=url, ok=200 <= code < 300, status_code=code)
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
    def repair_block_reason(
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


def _validate_health_url(value: str, *, host: str, port: int) -> None:
    url = str(value or "").strip()
    if not url or len(url) > _MAX_HEALTH_URL_CHARS:
        raise ValueError("local service health URL is empty or too long")
    try:
        parsed = urlsplit(url)
        parsed_port = parsed.port
    except ValueError as exc:
        raise ValueError("local service health URL is invalid") from exc
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise ValueError("local service health URL must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("local service health URL must not contain credentials")
    if not parsed.hostname:
        raise ValueError("local service health URL requires a hostname")
    if parsed.fragment:
        raise ValueError("local service health URL must not contain a fragment")
    effective_port = parsed_port or (443 if scheme == "https" else 80)
    if int(effective_port) != int(port):
        raise ValueError("local service health URL must use the target listener port")
    if not _health_host_matches_target(host, parsed.hostname):
        raise ValueError("local service health URL must address the target local host")


def _health_host_matches_target(target: str, url_host: str) -> bool:
    wanted = str(target or "").strip().casefold().strip("[]")
    actual = str(url_host or "").strip().casefold().strip("[]")
    if wanted in _LOOPBACK_HOSTS:
        return actual in _LOOPBACK_HOSTS
    if wanted in _WILDCARD_HOSTS:
        return actual in _LOOPBACK_HOSTS
    return wanted == actual


def _address_parts(address: object) -> tuple[str, int]:
    host = str(getattr(address, "ip", "") or "")
    port = _positive_int(getattr(address, "port", None))
    if port is None and isinstance(address, (tuple, list)) and len(address) >= 2:
        host = str(address[0] or "")
        port = _positive_int(address[1])
    return host, int(port or 0)


def _host_matches(target: str, observed: str) -> bool:
    wanted = str(target).strip().casefold().strip("[]")
    actual = str(observed).strip().casefold().strip("[]")
    if wanted in _LOOPBACK_HOSTS:
        return actual in _LOOPBACK_HOSTS | frozenset({"0.0.0.0", "::"})
    if wanted in _WILDCARD_HOSTS:
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
