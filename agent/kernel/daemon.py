from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from .provider_bridge import build_resident_runtime_from_existing_stack
from .service import ResidentService


class ResidentRpcServer:
    """Newline-delimited JSON-RPC over stdio for the Electron host.

    No TCP listener is opened. Electron owns the child process and communicates
    through its private stdin/stdout pipes, keeping resident control local to
    the desktop process tree.
    """

    def __init__(
        self,
        resident=None,
        *,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
    ):
        self.resident = resident or build_resident_runtime_from_existing_stack()
        self.service = ResidentService(self.resident)
        self.input = input_stream or sys.stdin
        self.output = output_stream or sys.stdout
        self._shutdown = False

    def serve_forever(self) -> int:
        self.service.acquire()
        self._write({"type": "ready", "status": self.resident.status()})
        try:
            for line in self.input:
                if self._shutdown:
                    break
                line = line.strip()
                if not line:
                    continue
                self.service.heartbeat()
                request: dict[str, Any] | None = None
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ValueError("request must be an object")
                    response = self.handle(request)
                except Exception as exc:
                    request_id = request.get("id") if isinstance(request, dict) else None
                    response = {
                        "id": request_id,
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                self._write(response)
        finally:
            self.service.release()
            try:
                self.resident.store.close()
            except Exception:
                pass
        return 0

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("id")
        method = str(request.get("method") or "").strip()
        params = request.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("params must be an object")

        if method == "ping":
            result: Any = {"alive": True}
        elif method == "status":
            result = self.resident.status()
        elif method == "submit":
            task = str(params.get("task") or "").strip()
            if not task:
                raise ValueError("submit requires task")
            run = self.resident.submit(
                task,
                kind=str(params.get("kind") or "user_task"),
                priority=int(params.get("priority") or 0),
                payload=(
                    params.get("payload")
                    if isinstance(params.get("payload"), dict)
                    else None
                ),
            )
            result = self._run_result(run)
        elif method == "remember":
            key = str(params.get("key") or "").strip()
            if not key:
                raise ValueError("remember requires key")
            aliases = params.get("aliases") or []
            if not isinstance(aliases, list):
                raise ValueError("aliases must be a list")
            self.resident.memory.remember(
                key,
                params.get("value"),
                aliases=tuple(str(value) for value in aliases),
            )
            result = {"saved": True, "key": key}
        elif method == "forget":
            key = str(params.get("key") or "").strip()
            if not key:
                raise ValueError("forget requires key")
            self.resident.memory.forget(key)
            result = {"forgotten": True, "key": key}
        elif method == "shutdown":
            self._shutdown = True
            result = {"shutting_down": True}
        else:
            raise ValueError(f"unknown method: {method}")

        return {"id": request_id, "ok": True, "result": result}

    @staticmethod
    def _run_result(run) -> dict[str, Any]:
        return {
            "event_id": run.event.event_id,
            "execution_path": run.execution_path.value,
            "success": run.success,
            "response": run.response,
            "model_invocations": run.model_invocations,
            "capability_name": run.capability_name,
            "reason": run.reason,
        }

    def _write(self, payload: dict[str, Any]) -> None:
        self.output.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        self.output.flush()


def main() -> int:
    return ResidentRpcServer().serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
