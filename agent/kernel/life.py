from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import sqlite3
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

    @property
    def disk_free_ratio(self) -> float:
        if self.disk_total_bytes <= 0:
            return 0.0
        return max(0.0, min(1.0, self.disk_free_bytes / self.disk_total_bytes))


@dataclass(slots=True)
class ThoughtFrame:
    """One model-independent frame of ZN's current internal reasoning.

    It is deliberately structured rather than prose.  The frame records what
    the resident currently knows, what is unresolved, which actions it can see,
    and the next move selected by its own control loop.  A model can later be
    consulted for a specific unresolved part, but it does not create or own the
    frame itself.
    """

    sequence: int
    at: str
    focus: str
    known: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    possible_actions: tuple[str, ...] = ()
    chosen_action: str = "observe"
    reason: str = "maintain continuity"
    confidence: float = 1.0


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
    drives: tuple[str, ...] = ()
    observations: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    external_brains: tuple[str, ...] = ()
    body: BodyState | None = None
    current_thought: ThoughtFrame | None = None
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
    thought: ThoughtFrame | None = None


class ZNLifeCore:
    """The minimal continuous self-loop of ZN.

    This layer does not need an LLM.  It maintains continuity, senses the host,
    notices changes, forms an internal thought frame, keeps an active intention,
    and records what ZN just did.  Models are cognitive resources that may be
    consulted later; they do not own this state and are not required for it to
    continue.
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

        material_observations = list(
            self._notice_changes(previous, body, capabilities, external_brains)
        )
        drives = self._derive_drives(previous, body, pending)
        thought = self._form_thought(
            previous=previous,
            body=body,
            pending=pending,
            capabilities=capabilities,
            external_brains=external_brains,
            drives=drives,
        )

        mode = "engaged" if pending else ("recovering" if "recover" in thought.chosen_action else "observing")
        attention = None if thought.focus == "environment" else thought.focus
        intention = thought.chosen_action

        if pending:
            material_observations.append(f"unfinished event available: {pending[0].event_id}")
        elif previous.mode == "engaged":
            material_observations.append("no unfinished event remains")

        pulse_observations = tuple(material_observations) or ("no material change detected",)
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
            drives=drives,
            observations=self._merge_observations(
                previous.observations,
                tuple(material_observations),
            ),
            open_questions=previous.open_questions,
            capabilities=capabilities,
            external_brains=external_brains,
            body=body,
            current_thought=thought,
            last_event_id=previous.last_event_id,
            last_action_summary=previous.last_action_summary,
        )
        self._save_state(state)
        self._append_thought(thought)

        pulse = LifePulse(
            sequence=state.pulse_count,
            at=state.last_pulse_at or utc_now(),
            mode=state.mode,
            attention=state.attention,
            intention=state.intention,
            observations=pulse_observations,
            thought=thought,
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
            "observe for the next meaningful change"
            if run.success
            else f"recover from event {run.event.event_id}"
        )
        observation = (
            f"completed {run.event.event_id} via {run.execution_path.value}"
            if run.success
            else f"failed {run.event.event_id}: {run.reason or 'unknown reason'}"
        )
        state.observations = self._merge_observations(state.observations, (observation,))
        if not run.success:
            question = f"why did {run.event.event_id} fail"
            if question not in state.open_questions:
                state.open_questions = (*state.open_questions, question)[-16:]
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
        if state.body is not None:
            data["body"]["disk_free_ratio"] = state.body.disk_free_ratio
        return data

    def recent_pulses(self, limit: int = 20) -> list[LifePulse]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM life_pulses ORDER BY sequence DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        pulses: list[LifePulse] = []
        for row in rows:
            raw = json.loads(row["data"])
            raw["observations"] = tuple(raw.get("observations") or ())
            thought = raw.get("thought")
            raw["thought"] = self._thought_from_raw(thought) if isinstance(thought, dict) else None
            pulses.append(LifePulse(**raw))
        return pulses

    def recent_thoughts(self, limit: int = 20) -> list[ThoughtFrame]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM life_thoughts ORDER BY sequence DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [self._thought_from_raw(json.loads(row["data"])) for row in rows]

    def _load_or_birth(self) -> LivingState:
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM living_self WHERE id=1").fetchone()
        if row:
            raw = json.loads(row["data"])
            body = raw.get("body")
            thought = raw.get("current_thought")
            raw["body"] = BodyState(**body) if isinstance(body, dict) else None
            raw["current_thought"] = (
                self._thought_from_raw(thought) if isinstance(thought, dict) else None
            )
            for key in (
                "drives",
                "observations",
                "open_questions",
                "capabilities",
                "external_brains",
            ):
                raw[key] = tuple(raw.get(key) or ())
            return LivingState(**raw)

        identity = self.resident.identity
        state = LivingState(
            name=identity.name,
            version=identity.version,
            born_at=identity.created_at,
            intention="observe for the next meaningful change",
            drives=("maintain continuity",),
        )
        self._save_state(state)
        return state

    @staticmethod
    def _thought_from_raw(raw: dict[str, Any]) -> ThoughtFrame:
        data = dict(raw)
        for key in ("known", "unknown", "possible_actions"):
            data[key] = tuple(data.get(key) or ())
        return ThoughtFrame(**data)

    def _save_state(self, state: LivingState) -> None:
        payload = asdict(state)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO living_self(id,data,updated_at) VALUES(1,?,?)",
                (json.dumps(payload, ensure_ascii=False, separators=(",", ":")), utc_now()),
            )
            conn.commit()

    def _append_pulse(self, pulse: LifePulse) -> None:
        payload = asdict(pulse)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO life_pulses(sequence,created_at,data) VALUES(?,?,?)",
                (
                    pulse.sequence,
                    pulse.at,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            conn.execute(
                "DELETE FROM life_pulses WHERE sequence < (SELECT COALESCE(MAX(sequence),0)-2048 FROM life_pulses)"
            )
            conn.commit()

    def _append_thought(self, thought: ThoughtFrame) -> None:
        payload = asdict(thought)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO life_thoughts(sequence,created_at,data) VALUES(?,?,?)",
                (
                    thought.sequence,
                    thought.at,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            conn.execute(
                "DELETE FROM life_thoughts WHERE sequence < (SELECT COALESCE(MAX(sequence),0)-2048 FROM life_thoughts)"
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
                CREATE TABLE IF NOT EXISTS life_thoughts(
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
    def _derive_drives(
        previous: LivingState,
        body: BodyState,
        pending: list,
    ) -> tuple[str, ...]:
        drives: list[str] = ["maintain continuity"]
        if pending:
            drives.append("make progress on unfinished work")
        if previous.mode == "recovering" or previous.open_questions:
            drives.append("reduce unresolved uncertainty")
        if body.disk_total_bytes > 0 and body.disk_free_ratio < 0.10:
            drives.append("preserve body resources")
        return tuple(drives)

    def _form_thought(
        self,
        *,
        previous: LivingState,
        body: BodyState,
        pending: list,
        capabilities: tuple[str, ...],
        external_brains: tuple[str, ...],
        drives: tuple[str, ...],
    ) -> ThoughtFrame:
        known = [
            f"I am {previous.name} {previous.version}",
            f"I am running on {body.hostname} ({body.system} {body.architecture})",
            f"I have {len(capabilities)} compiled local capabilities",
            f"I have {len(external_brains)} external cognitive routes available",
        ]
        unknown = list(previous.open_questions[-8:])
        possible_actions = ["observe for meaningful change"]

        if pending:
            next_event = pending[0]
            focus = next_event.task
            possible_actions.insert(0, f"work on event {next_event.event_id}")
            chosen = f"work on event {next_event.event_id}"
            reason = "unfinished work is present and progress is currently possible"
            confidence = 0.95
        elif previous.mode == "recovering" and previous.last_event_id:
            focus = previous.attention or previous.last_event_id
            possible_actions.insert(0, f"recover from event {previous.last_event_id}")
            chosen = f"recover from event {previous.last_event_id}"
            reason = "the most recent action failed and remains unresolved"
            confidence = 0.85
        elif unknown:
            focus = unknown[0]
            possible_actions.insert(0, "inspect unresolved question")
            chosen = "inspect unresolved question"
            reason = "an unresolved question remains in my own state"
            confidence = 0.75
        elif body.disk_total_bytes > 0 and body.disk_free_ratio < 0.10:
            focus = "body resources"
            possible_actions.insert(0, "inspect low disk space")
            chosen = "inspect low disk space"
            reason = "free disk space is below ten percent"
            confidence = 0.95
        else:
            focus = "environment"
            chosen = "observe for meaningful change"
            reason = "no unfinished work or unresolved internal issue currently dominates attention"
            confidence = 1.0

        return ThoughtFrame(
            sequence=previous.pulse_count + 1,
            at=utc_now(),
            focus=focus,
            known=tuple(known),
            unknown=tuple(unknown),
            possible_actions=tuple(possible_actions),
            chosen_action=chosen,
            reason=reason,
            confidence=confidence,
        )

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
