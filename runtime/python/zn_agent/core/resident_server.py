from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import secrets
import signal
import socketserver
import stat
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Mapping

from .channel_runtime import ResidentChannelSupervisor, build_zn_channel_adapters
from .models import utc_now
from .visual_region_sense import NativeVisualRegionSense, VisualRegionProbeFn
from .visual_sense import NativeVisualSense, VisualCaptureFn


_RESIDENT_ENDPOINT_VERSION = 2
_RESIDENT_AUTH_SCHEME = "session-secret-v1"


def _process_runtime_id(
    *,
    environ: Mapping[str, str] | None = None,
    python_executable: str | Path | None = None,
) -> str | None:
    env = environ if environ is not None else os.environ
    explicit = str(env.get("ZN_RUNTIME_ID") or "").strip()
    if explicit:
        return explicit

    executable = Path(python_executable or sys.executable).expanduser().resolve()
    for parent in executable.parents[:8]:
        manifest_path = parent / "runtime.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict):
            continue
        runtime_id = str(manifest.get("runtime_id") or "").strip()
        if manifest.get("product") == "ZN" and runtime_id:
            return runtime_id
    return None


def _loopback_bind_host(value: str | None) -> str:
    """Return the canonical TCP loopback host or fail closed.

    The local Resident control plane is never a network service. Normalizing
    ``localhost`` to the literal IPv4 loopback avoids DNS/hosts-file ambiguity,
    while rejecting wildcard/LAN addresses at the transport boundary means a
    caller cannot accidentally expose privileged RPC by changing configuration.
    A future Windows Named Pipe transport can replace this transport without
    changing the authentication/authority contract above it.
    """

    host = str(value or "127.0.0.1").strip().lower() or "127.0.0.1"
    if host in {"127.0.0.1", "localhost"}:
        return "127.0.0.1"
    raise ValueError("ZN Resident TCP control plane requires a loopback bind host")


def _windows_current_user_sid() -> str:
    """Resolve the SID of the actual process token, including service accounts."""

    completed = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        return ""
    match = re.search(r"\bS-\d+(?:-\d+)+\b", completed.stdout or "", flags=re.IGNORECASE)
    return match.group(0) if match else ""


def _restrict_endpoint_file(path: Path) -> None:
    """Restrict the endpoint/auth material to the current OS user.

    POSIX uses a strict 0600 mode. On Windows the process-token SID is resolved
    numerically and passed to ``icacls``. Numeric SIDs avoid friendly-name
    localization/service-account ambiguity (for example NetworkService runners).
    Failure is fatal: publishing an unrestricted session secret is less safe
    than refusing to publish the endpoint.
    """

    if os.name != "nt":
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        return

    sid = _windows_current_user_sid()
    if not sid:
        raise RuntimeError("could not resolve the current Windows SID for endpoint ACL")
    completed = subprocess.run(
        [
            "icacls",
            str(path),
            "/inheritancelevel:r",
            "/grant:r",
            f"*{sid}:F",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        raise RuntimeError("failed to restrict ZN Resident endpoint permissions")


class _ResidentTerminationRequested(BaseException):
    """Internal control flow for an OS-requested graceful resident stop."""


class _ResidentTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, handler_class, *, rpc, auth_secret: str):
        self.rpc = rpc
        self._auth_secret = auth_secret
        super().__init__(server_address, handler_class)

    def verify_request(self, request, client_address) -> bool:  # noqa: ARG002
        try:
            return ipaddress.ip_address(str(client_address[0])).is_loopback
        except ValueError:
            return False

    def authenticate(self, candidate: object) -> bool:
        if not isinstance(candidate, str):
            return False
        return secrets.compare_digest(candidate, self._auth_secret)


class _ResidentTcpHandler(socketserver.StreamRequestHandler):
    @staticmethod
    def _write_response(handler: "_ResidentTcpHandler", response: dict[str, Any]) -> None:
        handler.wfile.write(
            (json.dumps(response, ensure_ascii=False, default=str) + "\n").encode("utf-8")
        )
        handler.wfile.flush()

    def handle(self) -> None:
        rpc = self.server.rpc  # type: ignore[attr-defined]
        authenticated = False
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            request: dict[str, Any] | None = None
            try:
                request = json.loads(raw.decode("utf-8"))
                if not isinstance(request, dict):
                    raise ValueError("request must be an object")
                request_id = request.get("id")
                method = str(request.get("method") or "").strip()

                if not authenticated:
                    if method != "authenticate":
                        self._write_response(
                            self,
                            {
                                "id": request_id,
                                "ok": False,
                                "error": "authentication required",
                            },
                        )
                        return
                    params = request.get("params")
                    candidate = params.get("secret") if isinstance(params, dict) else None
                    if not self.server.authenticate(candidate):  # type: ignore[attr-defined]
                        self._write_response(
                            self,
                            {
                                "id": request_id,
                                "ok": False,
                                "error": "authentication failed",
                            },
                        )
                        return
                    authenticated = True
                    self._write_response(
                        self,
                        {
                            "id": request_id,
                            "ok": True,
                            "result": {
                                "authenticated": True,
                                "scheme": _RESIDENT_AUTH_SCHEME,
                            },
                        },
                    )
                    continue

                if method == "authenticate":
                    response = {
                        "id": request_id,
                        "ok": False,
                        "error": "authentication already established",
                    }
                else:
                    response = rpc.handle(request)
            except Exception as exc:
                request_id = request.get("id") if isinstance(request, dict) else None
                response = {
                    "id": request_id,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            self._write_response(self, response)
            if getattr(rpc, "_shutdown", False):
                threading.Thread(
                    target=self.server.shutdown,  # type: ignore[attr-defined]
                    name="zn-resident-shutdown",
                    daemon=True,
                ).start()
                return


class ResidentSocketService:
    """Reconnectable authenticated local transport for the long-lived Resident.

    The resident runtime owns the lease, heartbeat, state, endpoint and enabled
    communication organs. Desktop windows are authenticated clients. Closing a
    client connection therefore does not end the resident; another authorized
    Electron process can later reconnect to the same subject.

    TCP is deliberately transitional: it is pinned to loopback, every connection
    must prove possession of a high-entropy per-process session secret before any
    Resident RPC is dispatched, and the endpoint carrying that secret is
    restricted to the current OS user. This keeps the control-plane semantics
    compatible with a later Windows Named Pipe + per-user SID ACL transport.

    The same service process owns ZN's low-level visual sampling, on-demand local
    visual region sensing and channel lifecycles. Visual evidence and authorized
    channel events therefore belong to the same resident while no Electron
    window is connected.
    """

    _VISUAL_CAPTURE_HEALTH_ORGAN = "sense:vision_capture"

    def __init__(
        self,
        rpc,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        endpoint_path: str | Path | None = None,
        visual_capture_fn: VisualCaptureFn | None = None,
        visual_interval: float = 5.0,
        visual_region_probe_fn: VisualRegionProbeFn | None = None,
        channel_adapters=(),
        channel_poll_timeout: float = 10.0,
    ):
        self.rpc = rpc
        self.host = _loopback_bind_host(host)
        self.port = max(0, int(port))
        self.endpoint_path = (
            Path(endpoint_path).expanduser()
            if endpoint_path is not None
            else Path(self.rpc.resident.store.path).parent / "resident-endpoint.json"
        )
        self._session_secret = secrets.token_urlsafe(48)
        capture = visual_capture_fn or NativeVisualSense._capture_primary_screen
        self.visual = NativeVisualSense(
            self.rpc.resident,
            capture_fn=self._health_aware_visual_capture(capture),
            interval_seconds=visual_interval,
        )
        self.visual_region = NativeVisualRegionSense(probe_fn=visual_region_probe_fn)
        self.channels = ResidentChannelSupervisor(
            self.rpc.resident,
            tuple(channel_adapters or ()),
            poll_timeout=channel_poll_timeout,
        )
        # Expose resident-owned senses on the subject while this persistent
        # service owns their lifecycle. Neither becomes an Electron/UI organ.
        self.rpc.resident.vision = self.visual
        self.rpc.resident.visual_region = self.visual_region
        self._server: _ResidentTcpServer | None = None
        self._visual_stop = threading.Event()
        self._visual_thread: threading.Thread | None = None

    def _health_aware_visual_capture(self, capture: VisualCaptureFn) -> VisualCaptureFn:
        """Observe actual capture attempts without polling persisted last_error.

        NativeVisualSense intentionally converts capture failures into local
        state and ``None`` observations so a missing display cannot kill ZN.
        Wrapping the capture function is therefore the narrow point where the
        original exception still exists and where one health observation maps to
        exactly one real capture attempt. Health persistence remains secondary:
        it may never replace a successful frame or mask the original failure.
        """

        def capture_with_health():
            try:
                frame = capture()
            except Exception as exc:
                self._record_visual_capture_failure(exc)
                raise
            self._record_visual_capture_success()
            return frame

        return capture_with_health

    def _record_visual_capture_failure(self, error: BaseException) -> None:
        health = getattr(self.rpc.resident, "health", None)
        record = getattr(health, "record_failure", None)
        if not callable(record):
            return
        try:
            record(self._VISUAL_CAPTURE_HEALTH_ORGAN, error)
        except Exception:
            pass

    def _record_visual_capture_success(self) -> None:
        health = getattr(self.rpc.resident, "health", None)
        record = getattr(health, "record_success", None)
        if not callable(record):
            return
        try:
            record(self._VISUAL_CAPTURE_HEALTH_ORGAN)
        except Exception:
            pass

    def serve_forever(self) -> int:
        try:
            self.rpc.service.acquire()
            self.rpc.resident.live_once()
            self.rpc._start_life_loop()
            self._start_visual_loop()
            self.channels.start()
            with _ResidentTcpServer(
                (self.host, self.port),
                _ResidentTcpHandler,
                rpc=self.rpc,
                auth_secret=self._session_secret,
            ) as server:
                self._server = server
                host, port = server.server_address[:2]
                self._write_endpoint(str(host), int(port))
                server.serve_forever(poll_interval=0.25)
        finally:
            self._server = None
            self._remove_owned_endpoint()
            self.channels.stop()
            self._stop_visual_loop()
            self.rpc._stop_life_loop()
            self._close_managed_browser()
            self.rpc.service.release()
            try:
                self.rpc.resident.store.close()
            except Exception:
                pass
        return 0

    def _close_managed_browser(self) -> None:
        """Release resident-owned browser processes before resident lease/store teardown."""

        browser = getattr(self.rpc.resident, "managed_browser", None)
        close = getattr(browser, "close", None)
        if not callable(close):
            return
        try:
            close()
        except Exception:
            # Browser cleanup failure must not strand the resident lease or
            # endpoint. Process shutdown remains the final resource boundary.
            pass

    def _start_visual_loop(self) -> None:
        self._visual_stop.clear()
        if self._visual_thread and self._visual_thread.is_alive():
            return
        self._visual_thread = threading.Thread(
            target=self._visual_loop,
            name="zn-visual-sense",
            daemon=True,
        )
        self._visual_thread.start()

    def _stop_visual_loop(self) -> None:
        self._visual_stop.set()
        thread = self._visual_thread
        if thread and thread.is_alive():
            thread.join(timeout=max(1.0, self.visual.interval_seconds * 2.0))
        self._visual_thread = None

    def _visual_loop(self) -> None:
        tick = max(0.1, min(1.0, self.visual.interval_seconds / 2.0))
        while not self._visual_stop.wait(tick):
            try:
                self.visual.maybe_sample()
            except Exception:
                # Missing OS screen permission, a locked session, or a headless
                # host may make this sense unavailable. Vision failure must not
                # stop the resident's life, Will, world sense, or other organs.
                continue

    def _write_endpoint(self, host: str, port: int) -> None:
        path = self.endpoint_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _RESIDENT_ENDPOINT_VERSION,
            "transport": "tcp",
            "host": host,
            "port": port,
            "pid": os.getpid(),
            "instance_id": self.rpc.service.instance_id,
            "started_at": utc_now(),
            "runtime_id": _process_runtime_id(),
            "python": sys.executable,
            "channels": list(self.channels.channels),
            "authentication": {
                "scheme": _RESIDENT_AUTH_SCHEME,
                "secret": self._session_secret,
            },
        }
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY
            descriptor = os.open(temporary, flags, stat.S_IRUSR | stat.S_IWUSR)
            os.close(descriptor)
            # Restrict the empty staging file before the session secret is ever
            # written. This makes the publish sequence fail closed even if ACL
            # hardening fails on Windows.
            _restrict_endpoint_file(temporary)
            with temporary.open("w", encoding="utf-8", newline="") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            _restrict_endpoint_file(path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _remove_owned_endpoint(self) -> None:
        path = self.endpoint_path
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if int(raw.get("pid") or -1) != os.getpid():
                return
            if str(raw.get("instance_id") or "") != self.rpc.service.instance_id:
                return
            path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return


def _serve_with_sigterm_cleanup(service: ResidentSocketService) -> int:
    """Convert service-manager SIGTERM into the resident's normal cleanup path.

    Python's default SIGTERM action exits immediately, bypassing the service
    ``finally`` block and leaving the durable resident lease behind. The first
    SIGTERM instead becomes internal control flow that unwinds ``serve_forever``.
    Further SIGTERMs during cleanup are ignored so endpoint retirement, organ
    shutdown and lease release cannot be interrupted halfway through.
    """

    sigterm = getattr(signal, "SIGTERM", None)
    if sigterm is None or threading.current_thread() is not threading.main_thread():
        return service.serve_forever()

    previous_handler = signal.getsignal(sigterm)
    termination_requested = False

    def request_termination(signum, frame) -> None:  # noqa: ARG001
        nonlocal termination_requested
        if termination_requested:
            return
        termination_requested = True
        raise _ResidentTerminationRequested(signum)

    signal.signal(sigterm, request_termination)
    try:
        try:
            return service.serve_forever()
        except _ResidentTerminationRequested:
            return 0
    finally:
        signal.signal(sigterm, previous_handler)


def main(argv: list[str] | None = None) -> int:
    # Import lazily so daemon.py remains the transport-agnostic JSON-RPC face
    # and this module can be launched directly as the long-lived local service.
    from .daemon import ResidentRpcServer

    parser = argparse.ArgumentParser(prog="zn-resident-server", add_help=True)
    parser.add_argument("--home", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    if args.home:
        # Autostart entries must not depend on whatever environment happens to
        # exist at the next login. Pin the whole resident process to the same ZN
        # home that was active when the startup entry was installed.
        os.environ["ZN_AGENT_HOME"] = str(Path(args.home).expanduser().resolve())

    host = (
        str(args.host or os.getenv("ZN_RESIDENT_HOST") or "127.0.0.1").strip()
        or "127.0.0.1"
    )
    if args.port is not None:
        port = max(0, int(args.port))
    else:
        try:
            port = max(0, int(os.getenv("ZN_RESIDENT_PORT") or "0"))
        except ValueError:
            port = 0
    service = ResidentSocketService(
        ResidentRpcServer(),
        host=host,
        port=port,
        channel_adapters=build_zn_channel_adapters(),
    )
    return _serve_with_sigterm_cleanup(service)


if __name__ == "__main__":
    raise SystemExit(main())
