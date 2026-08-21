from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import asdict
from typing import Any, TextIO

from .provider_bridge import build_resident_runtime_from_existing_stack
from .service import ResidentService


class ResidentRpcServer:
    """Newline-delimited JSON-RPC over stdio for the Electron host.

    The RPC pipe is only a face/control surface. ZN's life loop runs on its own
    background thread, so an idle UI does not mean an idle or recreated self.
    """

    def __init__(
        self,
        resident=None,
        *,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
        life_interval: float = 2.0,
    ):
        self.resident = resident or build_resident_runtime_from_existing_stack()
        self.service = ResidentService(self.resident)
        self.input = input_stream or sys.stdin
        self.output = output_stream or sys.stdout
        self.life_interval = max(0.25, float(life_interval))
        self._shutdown = False
        self._life_stop = threading.Event()
        self._life_thread: threading.Thread | None = None

    def serve_forever(self) -> int:
        self.service.acquire()
        self.resident.live_once()
        self._start_life_loop()
        self._write({"type": "ready", "status": self.resident.status()})
        try:
            for line in self.input:
                if self._shutdown:
                    break
                line = line.strip()
                if not line:
                    continue
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
            self._stop_life_loop()
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
            result: Any = {
                "alive": True,
                "pulse_count": self.resident.life.snapshot().pulse_count,
            }
        elif method == "status":
            result = self.resident.status()
        elif method == "self":
            result = self.resident.life.snapshot_dict()
        elif method == "pulses":
            limit = self._limit(params)
            result = [
                {
                    "sequence": pulse.sequence,
                    "at": pulse.at,
                    "mode": pulse.mode,
                    "attention": pulse.attention,
                    "intention": pulse.intention,
                    "observations": list(pulse.observations),
                    "thought": asdict(pulse.thought) if pulse.thought else None,
                }
                for pulse in self.resident.life.recent_pulses(limit)
            ]
        elif method == "situations":
            result = [
                asdict(item)
                for item in self.resident.life.recent_situations(self._limit(params))
            ]
        elif method == "thoughts":
            result = [
                asdict(item)
                for item in self.resident.life.recent_thoughts(self._limit(params))
            ]
        elif method == "impasses":
            result = [
                asdict(item)
                for item in self.resident.life.recent_impasses(self._limit(params))
            ]
        elif method == "learning":
            result = [
                asdict(item)
                for item in self.resident.life.recent_learning_candidates(
                    self._limit(params)
                )
            ]
        elif method == "neural":
            nervous = getattr(self.resident, "nervous", None)
            result = (
                [asdict(item) for item in nervous.recent_traces(self._limit(params))]
                if nervous is not None
                else []
            )
        elif method == "perceive":
            nervous = getattr(self.resident, "nervous", None)
            if nervous is None:
                raise ValueError("resident has no nervous system")
            summary = str(params.get("summary") or "").strip()
            if not summary:
                raise ValueError("perceive requires summary")
            features = params.get("features") or []
            if not isinstance(features, list):
                raise ValueError("features must be a list")
            metadata = params.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                raise ValueError("metadata must be an object")
            channel = str(params.get("channel") or "sense").strip().lower()
            kwargs = {
                "features": tuple(str(item) for item in features),
                "source": str(params.get("source") or channel or "sense"),
                "salience": float(params.get("salience", 0.5)),
                "valence": float(params.get("valence", 0.0)),
                "arousal": float(params.get("arousal", 0.3)),
                "metadata": metadata,
            }
            if channel == "vision" and hasattr(self.resident, "perceive_visual"):
                trace = self.resident.perceive_visual(summary, **kwargs)
            elif channel in {"world", "web", "world/web"} and hasattr(
                self.resident, "perceive_world"
            ):
                trace = self.resident.perceive_world(summary, **kwargs)
            else:
                trace = nervous.perceive(channel, summary, **kwargs)
            result = asdict(trace)
        elif method == "world_follow":
            world = getattr(self.resident, "world", None)
            if world is None:
                raise ValueError("resident has no world sensory organ")
            topic = str(params.get("topic") or "").strip()
            if not topic:
                raise ValueError("world_follow requires topic")
            result = asdict(
                world.follow(
                    topic,
                    priority=int(params.get("priority") or 0),
                    interval_seconds=int(params.get("interval_seconds") or 1800),
                    source=str(params.get("source") or "self"),
                )
            )
        elif method == "world_focuses":
            world = getattr(self.resident, "world", None)
            result = (
                [
                    asdict(item)
                    for item in world.focuses(
                        enabled_only=bool(params.get("enabled_only", True)),
                        limit=self._limit(params),
                    )
                ]
                if world is not None
                else []
            )
        elif method == "world_observe":
            world = getattr(self.resident, "world", None)
            if world is None:
                raise ValueError("resident has no world sensory organ")
            focus_id = str(params.get("focus_id") or "").strip()
            if not focus_id:
                raise ValueError("world_observe requires focus_id")
            result = asdict(
                world.observe(
                    focus_id,
                    limit=max(1, min(10, int(params.get("limit") or 5))),
                )
            )
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
            self._life_stop.set()
            result = {"shutting_down": True}
        else:
            raise ValueError(f"unknown method: {method}")

        return {"id": request_id, "ok": True, "result": result}

    @staticmethod
    def _limit(params: dict[str, Any]) -> int:
        return max(1, min(200, int(params.get("limit") or 20)))

    def _start_life_loop(self) -> None:
        if self._life_thread and self._life_thread.is_alive():
            return
        self._life_stop.clear()
        self._life_thread = threading.Thread(
            target=self._life_loop,
            name="zn-life",
            daemon=True,
        )
        self._life_thread.start()

    def _stop_life_loop(self) -> None:
        self._life_stop.set()
        thread = self._life_thread
        if thread and thread.is_alive():
            thread.join(timeout=max(1.0, self.life_interval * 2.0))
        self._life_thread = None

    def _life_loop(self) -> None:
        next_lease_heartbeat = 0.0
        while not self._life_stop.wait(self.life_interval):
            try:
                now = time.monotonic()
                if now >= next_lease_heartbeat:
                    self.service.heartbeat()
                    next_lease_heartbeat = now + self.service.heartbeat_interval
                self.resident.live_once()
                world = getattr(self.resident, "world", None)
                if world is not None:
                    world.maybe_observe()
            except Exception:
                # The foreground RPC path remains available to report state even
                # if one perception/action/sensory cycle fails. The next cycle
                # keeps the same resident alive and tries again.
                continue

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
