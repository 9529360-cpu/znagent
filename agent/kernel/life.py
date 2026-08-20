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
    from .models import AgentEvent
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
class SituationModel:
    """ZN's compact model of what is true and relevant right now."""

    sequence: int
    at: str
    active_event_id: str | None = None
    active_task: str | None = None
    active_priority: int | None = None
    active_impasse_id: str | None = None
    body_health: str = "nominal"
    body_signals: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    local_capabilities: tuple[str, ...] = ()
    external_brains: tuple[str, ...] = ()
    recent_outcome: str | None = None
    changes: tuple[str, ...] = ()


@dataclass(slots=True)
class ImpasseState:
    """A concrete gap ZN could not resolve with its current native knowledge."""

    impasse_id: str
    event_id: str
    task: str
    opened_at: str
    updated_at: str
    reason: str
    required_capabilities: tuple[str, ...] = ()
    local_failure: str | None = None
    attempts: int = 1
    status: str = "open"
    resolution_source: str | None = None
    resolution_summary: str | None = None
    resolved_at: str | None = None


@dataclass(slots=True)
class LearningCandidate:
    """A resolved impasse that may be compiled into reusable native ability."""

    candidate_id: str
    source_impasse_id: str
    event_id: str
    task: str
    created_at: str
    resolution_source: str
    resolution_summary: str
    required_capabilities: tuple[str, ...] = ()
    status: str = "candidate"


@dataclass(slots=True)
class ThoughtFrame:
    """One model-independent frame of ZN's current internal reasoning."""

    sequence: int
    at: str
    focus: str
    known: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    possible_actions: tuple[str, ...] = ()
    chosen_action: str = "observe"
    action_kind: str = "observe"
    action_target: str | None = None
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
    current_situation: SituationModel | None = None
    current_thought: ThoughtFrame | None = None
    current_impasse: ImpasseState | None = None
    learning_candidates: tuple[str, ...] = ()
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
    """The continuous native self-loop of ZN.

    The sequence is intentionally explicit: sense -> situation -> thought ->
    action -> outcome -> learning. This loop does not require an LLM. External
    models are only relevant after ZN identifies a concrete impasse that its
    own memory and compiled capabilities could not resolve.
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
        next_event = self.store.peek_next_event()
        capabilities = tuple(self.resident.capabilities.names())
        external_brains = self._sense_external_brains()
        material_observations = list(
            self._notice_changes(previous, body, capabilities, external_brains)
        )

        situation = self._build_situation(
            previous=previous,
            body=body,
            next_event=next_event,
            capabilities=capabilities,
            external_brains=external_brains,
            changes=tuple(material_observations),
        )
        drives = self._derive_drives(situation)
        thought = self._form_thought(
            previous=previous,
            situation=situation,
            drives=drives,
        )

        if situation.active_event_id:
            mode = "engaged"
        elif situation.active_impasse_id:
            mode = "recovering"
        elif thought.action_kind == "recover":
            mode = "recovering"
        else:
            mode = "observing"
        attention = None if thought.focus == "environment" else thought.focus
        intention = thought.chosen_action

        if situation.active_event_id:
            material_observations.append(
                f"unfinished event available: {situation.active_event_id}"
            )
        elif previous.mode == "engaged":
            material_observations.append("no unfinished event remains")

        pulse_observations = tuple(material_observations) or (
            "no material change detected",
        )
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
            current_situation=situation,
            current_thought=thought,
            current_impasse=previous.current_impasse,
            learning_candidates=previous.learning_candidates,
            last_event_id=previous.last_event_id,
            last_action_summary=previous.last_action_summary,
        )
        self._save_state(state)
        self._append_situation(situation)
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

    def begin_impasse(
        self,
        event: AgentEvent,
        *,
        reason: str,
        required_capabilities: tuple[str, ...] = (),
        local_failure: str | None = None,
    ) -> ImpasseState:
        """Record the exact point where native resolution stopped being enough."""
        state = self._load_or_birth()
        current = state.current_impasse
        now = utc_now()
        if current and current.event_id == event.event_id and current.status == "open":
            current.updated_at = now
            current.reason = str(reason or current.reason)
            current.local_failure = local_failure or current.local_failure
            current.required_capabilities = tuple(required_capabilities)
            current.attempts += 1
            impasse = current
        else:
            impasse = ImpasseState(
                impasse_id=f"imp-{event.event_id}",
                event_id=event.event_id,
                task=event.task,
                opened_at=now,
                updated_at=now,
                reason=str(reason or "native resolution path is unknown"),
                required_capabilities=tuple(required_capabilities),
                local_failure=local_failure,
            )
        state.current_impasse = impasse
        state.mode = "recovering"
        state.attention = event.task
        state.intention = f"resolve impasse {impasse.impasse_id}"
        state.observations = self._merge_observations(
            state.observations,
            (f"impasse opened: {impasse.impasse_id}",),
        )
        self._save_impasse(impasse)
        self._save_state(state)
        self._state = state
        return impasse

    def mark_impasse_unresolved(self, event: AgentEvent, reason: str) -> None:
        state = self._load_or_birth()
        impasse = state.current_impasse
        if not impasse or impasse.event_id != event.event_id:
            return
        impasse.updated_at = utc_now()
        impasse.reason = str(reason or impasse.reason)
        impasse.status = "open"
        self._save_impasse(impasse)
        state.current_impasse = impasse
        self._save_state(state)
        self._state = state

    def resolve_impasse(
        self,
        event: AgentEvent,
        run: ResidentRunResult,
        *,
        resolution_source: str,
    ) -> LearningCandidate | None:
        """Close an impasse and stage its solution as a reusable learning candidate."""
        state = self._load_or_birth()
        impasse = state.current_impasse
        if not impasse or impasse.event_id != event.event_id or not run.success:
            return None

        now = utc_now()
        summary = self._summarize_run(run)
        impasse.status = "resolved"
        impasse.updated_at = now
        impasse.resolved_at = now
        impasse.resolution_source = str(resolution_source or run.execution_path.value)
        impasse.resolution_summary = summary
        self._save_impasse(impasse)

        candidate = LearningCandidate(
            candidate_id=f"learn-{impasse.impasse_id}",
            source_impasse_id=impasse.impasse_id,
            event_id=event.event_id,
            task=event.task,
            created_at=now,
            resolution_source=impasse.resolution_source,
            resolution_summary=summary,
            required_capabilities=impasse.required_capabilities,
        )
        self._save_learning_candidate(candidate)
        state.current_impasse = None
        if candidate.candidate_id not in state.learning_candidates:
            state.learning_candidates = (
                *state.learning_candidates,
                candidate.candidate_id,
            )[-128:]
        state.observations = self._merge_observations(
            state.observations,
            (
                f"impasse resolved: {impasse.impasse_id}",
                f"learning candidate staged: {candidate.candidate_id}",
            ),
        )
        self._save_state(state)
        self._state = state
        return candidate

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
        state.observations = self._merge_observations(
            state.observations,
            (observation,),
        )
        current_impasse = state.current_impasse
        if not run.success and not (
            current_impasse and current_impasse.event_id == run.event.event_id
        ):
            question = f"why did {run.event.event_id} fail"
            if question not in state.open_questions:
                state.open_questions = (*state.open_questions, question)[-16:]
        self._save_state(state)
        self._state = state
        return state

    def set_open_questions(
        self,
        questions: list[str] | tuple[str, ...],
    ) -> LivingState:
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
            raw["thought"] = (
                self._thought_from_raw(thought)
                if isinstance(thought, dict)
                else None
            )
            pulses.append(LifePulse(**raw))
        return pulses

    def recent_situations(self, limit: int = 20) -> list[SituationModel]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM life_situations ORDER BY sequence DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [self._situation_from_raw(json.loads(row["data"])) for row in rows]

    def recent_thoughts(self, limit: int = 20) -> list[ThoughtFrame]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM life_thoughts ORDER BY sequence DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [self._thought_from_raw(json.loads(row["data"])) for row in rows]

    def recent_impasses(self, limit: int = 20) -> list[ImpasseState]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM life_impasses ORDER BY updated_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [self._impasse_from_raw(json.loads(row["data"])) for row in rows]

    def recent_learning_candidates(self, limit: int = 20) -> list[LearningCandidate]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM life_learning_candidates ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [self._learning_from_raw(json.loads(row["data"])) for row in rows]

    def _load_or_birth(self) -> LivingState:
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM living_self WHERE id=1").fetchone()
        if row:
            raw = json.loads(row["data"])
            body = raw.get("body")
            situation = raw.get("current_situation")
            thought = raw.get("current_thought")
            impasse = raw.get("current_impasse")
            raw["body"] = BodyState(**body) if isinstance(body, dict) else None
            raw["current_situation"] = (
                self._situation_from_raw(situation)
                if isinstance(situation, dict)
                else None
            )
            raw["current_thought"] = (
                self._thought_from_raw(thought)
                if isinstance(thought, dict)
                else None
            )
            raw["current_impasse"] = (
                self._impasse_from_raw(impasse)
                if isinstance(impasse, dict)
                else None
            )
            for key in (
                "drives",
                "observations",
                "open_questions",
                "capabilities",
                "external_brains",
                "learning_candidates",
            ):
                raw[key] = tuple(raw.get(key) or ())
            raw.setdefault("current_situation", None)
            raw.setdefault("current_impasse", None)
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
    def _situation_from_raw(raw: dict[str, Any]) -> SituationModel:
        data = dict(raw)
        for key in (
            "body_signals",
            "unresolved_questions",
            "local_capabilities",
            "external_brains",
            "changes",
        ):
            data[key] = tuple(data.get(key) or ())
        return SituationModel(**data)

    @staticmethod
    def _thought_from_raw(raw: dict[str, Any]) -> ThoughtFrame:
        data = dict(raw)
        for key in ("known", "unknown", "possible_actions"):
            data[key] = tuple(data.get(key) or ())
        data.setdefault("action_kind", "observe")
        data.setdefault("action_target", None)
        return ThoughtFrame(**data)

    @staticmethod
    def _impasse_from_raw(raw: dict[str, Any]) -> ImpasseState:
        data = dict(raw)
        data["required_capabilities"] = tuple(
            data.get("required_capabilities") or ()
        )
        return ImpasseState(**data)

    @staticmethod
    def _learning_from_raw(raw: dict[str, Any]) -> LearningCandidate:
        data = dict(raw)
        data["required_capabilities"] = tuple(
            data.get("required_capabilities") or ()
        )
        return LearningCandidate(**data)

    def _save_state(self, state: LivingState) -> None:
        payload = asdict(state)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO living_self(id,data,updated_at) VALUES(1,?,?)",
                (
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    utc_now(),
                ),
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
                "DELETE FROM life_pulses WHERE sequence < "
                "(SELECT COALESCE(MAX(sequence),0)-2048 FROM life_pulses)"
            )
            conn.commit()

    def _append_situation(self, situation: SituationModel) -> None:
        payload = asdict(situation)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO life_situations(sequence,created_at,data) "
                "VALUES(?,?,?)",
                (
                    situation.sequence,
                    situation.at,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            conn.execute(
                "DELETE FROM life_situations WHERE sequence < "
                "(SELECT COALESCE(MAX(sequence),0)-2048 FROM life_situations)"
            )
            conn.commit()

    def _append_thought(self, thought: ThoughtFrame) -> None:
        payload = asdict(thought)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO life_thoughts(sequence,created_at,data) "
                "VALUES(?,?,?)",
                (
                    thought.sequence,
                    thought.at,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            conn.execute(
                "DELETE FROM life_thoughts WHERE sequence < "
                "(SELECT COALESCE(MAX(sequence),0)-2048 FROM life_thoughts)"
            )
            conn.commit()

    def _save_impasse(self, impasse: ImpasseState) -> None:
        payload = asdict(impasse)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO life_impasses"
                "(impasse_id,event_id,status,updated_at,data) VALUES(?,?,?,?,?)",
                (
                    impasse.impasse_id,
                    impasse.event_id,
                    impasse.status,
                    impasse.updated_at,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            conn.commit()

    def _save_learning_candidate(self, candidate: LearningCandidate) -> None:
        payload = asdict(candidate)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO life_learning_candidates"
                "(candidate_id,source_impasse_id,created_at,status,data) "
                "VALUES(?,?,?,?,?)",
                (
                    candidate.candidate_id,
                    candidate.source_impasse_id,
                    candidate.created_at,
                    candidate.status,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                ),
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
                CREATE TABLE IF NOT EXISTS life_situations(
                    sequence INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS life_thoughts(
                    sequence INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS life_impasses(
                    impasse_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS life_learning_candidates(
                    candidate_id TEXT PRIMARY KEY,
                    source_impasse_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
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
            process_uptime_seconds=max(
                0.0,
                time.monotonic() - self._started_monotonic,
            ),
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

    def _build_situation(
        self,
        *,
        previous: LivingState,
        body: BodyState,
        next_event: AgentEvent | None,
        capabilities: tuple[str, ...],
        external_brains: tuple[str, ...],
        changes: tuple[str, ...],
    ) -> SituationModel:
        body_signals: list[str] = []
        body_health = "nominal"
        if body.disk_total_bytes > 0 and body.disk_free_ratio < 0.10:
            body_health = "constrained"
            body_signals.append("disk free space below ten percent")
        if previous.body and previous.body.pid != body.pid:
            body_signals.append("resident process identity changed")

        current_impasse = previous.current_impasse
        active_impasse_id = (
            current_impasse.impasse_id
            if current_impasse and current_impasse.status == "open"
            else None
        )
        return SituationModel(
            sequence=previous.pulse_count + 1,
            at=utc_now(),
            active_event_id=next_event.event_id if next_event else None,
            active_task=next_event.task if next_event else None,
            active_priority=next_event.priority if next_event else None,
            active_impasse_id=active_impasse_id,
            body_health=body_health,
            body_signals=tuple(body_signals),
            unresolved_questions=tuple(previous.open_questions[-8:]),
            local_capabilities=capabilities,
            external_brains=external_brains,
            recent_outcome=previous.last_action_summary,
            changes=changes,
        )

    @staticmethod
    def _derive_drives(situation: SituationModel) -> tuple[str, ...]:
        drives: list[str] = ["maintain continuity"]
        if situation.active_event_id:
            drives.append("make progress on unfinished work")
        if situation.active_impasse_id:
            drives.append("resolve current cognitive impasse")
        if situation.unresolved_questions:
            drives.append("reduce unresolved uncertainty")
        if situation.body_health != "nominal":
            drives.append("preserve body resources")
        return tuple(drives)

    def _form_thought(
        self,
        *,
        previous: LivingState,
        situation: SituationModel,
        drives: tuple[str, ...],
    ) -> ThoughtFrame:
        known = [
            f"I am {previous.name} {previous.version}",
            f"my body health is {situation.body_health}",
            f"I have {len(situation.local_capabilities)} compiled local capabilities",
            f"I have {len(situation.external_brains)} external cognitive routes available",
        ]
        if situation.active_event_id:
            known.append(
                f"event {situation.active_event_id} is the highest priority unfinished work"
            )
        if situation.recent_outcome:
            known.append(f"my recent outcome was: {situation.recent_outcome[:240]}")

        unknown = list(situation.unresolved_questions)
        current_impasse = previous.current_impasse
        if (
            situation.active_impasse_id
            and current_impasse
            and current_impasse.status == "open"
        ):
            unknown.insert(0, current_impasse.reason)

        possible_actions = ["observe for meaningful change"]
        action_kind = "observe"
        action_target = None

        if situation.active_event_id:
            focus = situation.active_task or situation.active_event_id
            possible_actions.insert(
                0,
                f"work on event {situation.active_event_id}",
            )
            chosen = f"work on event {situation.active_event_id}"
            action_kind = "event"
            action_target = situation.active_event_id
            reason = "unfinished work is present and progress is currently possible"
            confidence = 0.95
        elif situation.active_impasse_id and current_impasse:
            focus = current_impasse.task
            possible_actions.insert(
                0,
                f"inspect impasse {current_impasse.impasse_id}",
            )
            chosen = f"inspect impasse {current_impasse.impasse_id}"
            action_kind = "impasse"
            action_target = current_impasse.impasse_id
            reason = "my native resolution path stopped at a concrete knowledge gap"
            confidence = 0.85
        elif previous.mode == "recovering" and previous.last_event_id:
            focus = previous.attention or previous.last_event_id
            possible_actions.insert(
                0,
                f"recover from event {previous.last_event_id}",
            )
            chosen = f"recover from event {previous.last_event_id}"
            action_kind = "recover"
            action_target = previous.last_event_id
            reason = "the most recent action failed and remains unresolved"
            confidence = 0.80
        elif unknown:
            focus = unknown[0]
            possible_actions.insert(0, "inspect unresolved question")
            chosen = "inspect unresolved question"
            action_kind = "reflect"
            action_target = unknown[0]
            reason = "an unresolved question remains in my own state"
            confidence = 0.75
        elif situation.body_health != "nominal":
            focus = "body resources"
            possible_actions.insert(0, "inspect body constraint")
            chosen = "inspect body constraint"
            action_kind = "body"
            action_target = "body_health"
            reason = "my body reports a resource constraint"
            confidence = 0.95
        else:
            focus = "environment"
            chosen = "observe for meaningful change"
            reason = (
                "no unfinished work, cognitive impasse, or unresolved internal "
                "issue currently dominates attention"
            )
            confidence = 1.0

        return ThoughtFrame(
            sequence=situation.sequence,
            at=utc_now(),
            focus=focus,
            known=tuple(known),
            unknown=tuple(unknown),
            possible_actions=tuple(possible_actions),
            chosen_action=chosen,
            action_kind=action_kind,
            action_target=action_target,
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
        return (
            f"failure via {run.execution_path.value}: "
            f"{run.reason or 'unknown reason'}"
        )