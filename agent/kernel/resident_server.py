from __future__ import annotations

import json
import os
import socketserver
import threading
from pathlib import Path
from typing import Any

from .models import utc_now


class _ResidentTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, handler_class, *, rpc):
        self.rpc = rpc
        super().__init__(server_address, handler_class)


class _ResidentTcpHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        rpc = self.server.rpc  # type: ignore[attr-defined]
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            request: dict[str, Any] | None = None
            try:
                request = json.loads(raw.decode("utf-8"))
                if not isinstance(request, dict):
                    raise ValueError("request must be an object")
                response = rpc.handle(request)
            except Exception as exc:
                request_id = request.get("id") if isinstance(request, dict) else None
                response = {
                    "id": request_id,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            self.wfile.write(
                (json.dumps(response, ensure_ascii=False, default=str) + "\n").encode(
                    "utf-8"
                )
            )
            self.wfile.flush()
            if getattr(rpc, "_shutdown", False):
                threading.Thread(
                    target=self.server.shutdown,  # type: ignore[attr-defined]
                    name="zn-resident-shutdown",
                    daemon=True,
                ).start()
                return


class ResidentSocketService:
    """Reconnectable local transport for a resident that outlives its UI.

    The resident runtime owns the lease, heartbeat, state, and endpoint. Desktop
    windows are clients. Closing a client connection therefore does not end the
    resident; another Electron process can later reconnect to the same subject.
    """

    def __init__(
        self,
        rpc,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        endpoint_path: str | Path | None = None,
    ):
        self.rpc = rpc
        self.host = str(host or "127.0.0.1")
        self.port = max(0, int(port))
        self.endpoint_path = (
            Path(endpoint_path).expanduser()
            if endpoint_path is not None
            else Path(self.rpc.resident.store.path).parent / "resident-endpoint.json"
        )
        self._server: _ResidentTcpServer | None = None

    def serve_forever(self) -> int:
        self.rpc.service.acquire()
        try:
            self.rpc.resident.live_once()
            self.rpc._start_life_loop()
            with _ResidentTcpServer(
                (self.host, self.port),
                _ResidentTcpHandler,
                rpc=self.rpc,
            ) as server:
                self._server = server
                host, port = server.server_address[:2]
                self._write_endpoint(str(host), int(port))
                server.serve_forever(poll_interval=0.25)
        finally:
            self._server = None
            self._remove_owned_endpoint()
            self.rpc._stop_life_loop()
            self.rpc.service.release()
            try:
                self.rpc.resident.store.close()
            except Exception:
                pass
        return 0

    def _write_endpoint(self, host: str, port: int) -> None:
        path = self.endpoint_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "transport": "tcp",
            "host": host,
            "port": port,
            "pid": os.getpid(),
            "instance_id": self.rpc.service.instance_id,
            "started_at": utc_now(),
        }
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, path)

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
