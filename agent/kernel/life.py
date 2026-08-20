from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .models import EventStatus, ResidentRunResult, utc_now

if TYPE_CHECKING:
    from .resident import ZNResidentRuntime


@dataclass(slots=True)
class BodyState:
    """What ZN can directly sense about the body it is currently inhabiting."""

    hostname: str
    system: str
    release: str
    architecture: str
    python_version: str
    pid: int
    cwd: str
    cpu_count: int | None
    disk_total_bytes: int
    disk_free_bytes: int
    process_uptime_seconds: float
    captured_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class LivingState:
    """Durable first-person state owned by ZN itself, not by a model context."""

    name: str
    version: str
    born_at: str
    pulse_count: int = 0
    wake_count: int = 0
    last_wake_at: str | None = None
    last_pulse_at: str | None = None
    mode: str = "waking"
    attention: str | None = None
    intention: str | None = None
    observations: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    external_brains: tuple[str, ...] = ()
    body: BodyState | None = None
    last_event_id: str | None = None
    last_action_summary: str | None = None

    @property
    def age_seconds(self) -> float:
        try:
            born = datetime.fromisoformat(self.born_at)
            if born.tzinfo is None:
                born = born.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - born).total_seconds())
        except Exception:
            return 0.0


@dataclass(slots=True)
class LifePulse:
    sequence: int
    at: str
    mode: str
    attention: str | None
    intention: str | None
    observations: tuple[str, ...]


class ZNLifeCore:
    """The minimal continuous self-loop of ZN.

    This layer does not need an LLM. It maintains continuity, senses the host,
    notices changes, keeps an active intention, and records what ZN just did.
    Models may later be consulted by the resident runtime, but they do not own
    this state and they are not required for the heartbeat to continue.
    """

    def __init__(self, resident: ZNResidentRuntime):
        self.resident = resident
        self.store = resident.store
        self._started_monotonic = time.monotonic()
        self._init_schema()
        self._state = self._load_or_birth()

    def wake(self) -> LivingState:
        state = self._load_or_birth()
        state.wake_count += 1
        state.last_wake_at = utc_now()
        state.mode = "awake"
        state.observations = self._merge_observations(
            state.observations,
            ("runtime awakened",),
        )
        self._save_state(state)
        self._state = state
        return state

    def pulse(self) -> LifePulse:
        previous = self._load_or_birth()
        body = self._sense_body()
        pending = self.store.list_events(EventStatus.PENDING, limit=100)
        capabilities = tuple(self.resident.capabilities.names())
        external_brains = self._sense_external_brains()

        observations = list(self._notice_changes(previous, body, capabilities, external_brains))
        mode = "engaged" if pending else "observing"
        attention = previous.attention
        intention = previous.intention

        if pending:
            next_event = pending[-1]
            attention = next_event.task
            intention = f"continue event {next_event.event_id}"
            observations.append(f"unfinished event available: {next_event.event_id}")
        elif previous.mode == "engaged":
            attention = None
            intention = "remain available and observe"
            observations.append("no unfinished event remains")
        elif not intention:
            intention = "remain available and observe"

        if not observations:
            observations.append("no material change detected")

        state = LivingState(
            name=previous.name,
            version=previous.version,
            born_at=previous.born_at,
            pulse_count=previous.pulse_count + 1,
            wake_count=previous.wake_count,
            last_wake_at=previous.last_wake_at,
            last_pulse_at=utc_now(),
            mode=mode,
            attention=attention,
            intention=intention,
            observations=self._merge_observations(previous.observations, tuple(observations)),
            open_questions=previous.open_questions,
            capabilities=capabilities,
            external_brains=external_brains,
            body=body,
            last_event_id=previous.last_event_id,
            last_action_summary=previous.last_action_summary,
        )
        self._save_state(state)
        pulse = LifePulse(
            sequence=state.pulse_count,
            at=state.last_pulse_at or utc_now(),
            mode=state.mode,
            attention=state.attention,
            intention=state.intention,
            observations=tuple(observations),
        )
        self._append_pulse(pulse)
        self._state = state
        return pulse

    def observe_action(self, run: ResidentRunResult) -> LivingState:
        state = self._load_or_birth()
        state.last_event_id = run.event.event_id
        state.last_action_summary = self._summarize_run(run)
        state.mode = "observing" if run.success else "recovering"
        state.attention = None if run.success else run.event.task
        state.intention = (
            "remain available and observe"
            if run.success
            else f"understand failure of {run.event.event_id}"
        )
        observation = (
            f"completed {run.event.event_id} via {run.execution_path.value}"
            if run.success
            else f"failed {run.event.event_id}: {run.reason or 'unknown reason'}"
        )
        state.observations = self._merge_observations(state.observations, (observation,))
        self._save_state(state)
        self._state = state
        return state

    def set_open_questions(self, questions: list[str] | tuple[str, ...]) -> LivingState:
        state = self._load_or_birth()
        state.open_questions = tuple(
            text for text in (str(item).strip() for item in questions) if text
        )
        self._save_state(state)
        self._state = state
        return state

    def snapshot(self) -> LivingState:
        self._state = self._load_or_birth()
        return self._state

    def snapshot_dict(self) -> dict[str, Any]:
        state = self.snapshot()
        data = asdict(state)
        data["age_seconds"] = state.age_seconds
        return data

    def recent_pulses(self, limit: int = 20) -> list[LifePulse]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM life_pulses ORDER BY sequence DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [LifePulse(**json.loads(row["data"])) for row in rows]

    def _load_or_birth(self) -> LivingState:
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM living_self WHERE id=1").fetchone()
        if row:
            raw = json.loads(row["data"])
            body = raw.get("body")
            raw["body"] = BodyState(**body) if isinstance(body, dict) else None
            for key in ("observations", "open_questions", "capabilities", "external_brains"):
                raw[key] = tuple(raw.get(key) or ())
            return LivingState(**raw)

        identity = self.resident.identity
        state = LivingState(
            name=identity.name,
            version=identity.version,
            born_at=identity.created_at,
            intention="remain available and observe",
        )
        self._save_state(state)
        return state

    def _save_state(self, state: LivingState) -> None:
        payload = asdict(state)
        payload.pop("age_seconds", None)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO living_self(id,data,updated_at) VALUES(1,?,?)",
                (json.dumps(payload, ensure_ascii=False, separators=(",", ":")), utc_now()),
            )
            conn.commit()

    def _append_pulse(self, pulse: LifePulse) -> None:
        payload = asdict(pulse)
        payload["observations"] = list(pulse.observations)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO life_pulses(sequence,created_at,data) VALUES(?,?,?)",
                (
                    pulse.sequence,
                    pulse.at,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            # Heartbeats are evidence of continuity, not an infinite transcript.
            conn.execute(
                "DELETE FROM life_pulses WHERE sequence < (SELECT COALESCE(MAX(sequence),0)-2048 FROM life_pulses)"
            )
            conn.commit()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS living_self(
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS life_pulses(
                    sequence INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _sense_body(self) -> BodyState:
        try:
            disk = shutil.disk_usage(self.store.path.parent)
            disk_total, disk_free = int(disk.total), int(disk.free)
        except OSError:
            disk_total, disk_free = 0, 0
        return BodyState(
            hostname=socket.gethostname(),
            system=platform.system(),
            release=platform.release(),
            architecture=platform.machine(),
            python_version=platform.python_version(),
            pid=os.getpid(),
            cwd=os.getcwd(),
            cpu_count=os.cpu_count(),
            disk_total_bytes=disk_total,
            disk_free_bytes=disk_free,
            process_uptime_seconds=max(0.0, time.monotonic() - self._started_monotonic),
        )

    def _sense_external_brains(self) -> tuple[str, ...]:
        routes = getattr(getattr(self.resident.kernel, "router", None), "routes", ())
        available: list[str] = []
        for route in routes:
            metadata = getattr(route, "metadata", {}) or {}
            if metadata.get("model_available", True) is False:
                continue
            provider = str(getattr(route, "provider", "") or "")
            model = str(getattr(route, "model", "") or "")
            if provider == "none" or model == "none":
                continue
            route_id = str(getattr(route, "route_id", "") or "external")
            available.append(route_id)
        return tuple(sorted(set(available)))

    @staticmethod
    def _notice_changes(
        previous: LivingState,
        body: BodyState,
        capabilities: tuple[str, ...],
        external_brains: tuple[str, ...],
    ) -> tuple[str, ...]:
        changes: list[str] = []
        old = previous.body
        if old is None:
            changes.append("body state acquired")
        else:
            if old.hostname != body.hostname:
                changes.append(f"host changed: {old.hostname} -> {body.hostname}")
            if old.cwd != body.cwd:
                changes.append(f"working directory changed: {old.cwd} -> {body.cwd}")
            if old.pid != body.pid:
                changes.append(f"process changed: {old.pid} -> {body.pid}")
            if old.disk_free_bytes and body.disk_free_bytes:
                delta = body.disk_free_bytes - old.disk_free_bytes
                if abs(delta) >= 512 * 1024 * 1024:
                    changes.append(f"disk free space changed by {delta} bytes")
        if previous.capabilities != capabilities:
            changes.append("available capabilities changed")
        if previous.external_brains != external_brains:
            changes.append("external brain connections changed")
        return tuple(changes)

    @staticmethod
    def _merge_observations(
        previous: tuple[str, ...],
        new: tuple[str, ...],
        *,
        limit: int = 32,
    ) -> tuple[str, ...]:
        merged = list(previous)
        for item in new:
            text = str(item).strip()
            if text:
                merged.append(text)
        return tuple(merged[-max(1, int(limit)):])

    @staticmethod
    def _summarize_run(run: ResidentRunResult) -> str:
        if run.success:
            response = str(run.response or "").strip().replace("\n", " ")
            return (
                f"success via {run.execution_path.value}: {response[:240]}"
                if response
                else f"success via {run.execution_path.value}"
            )
        return f"failure via {run.execution_path.value}: {run.reason or 'unknown reason'}"
