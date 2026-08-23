from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .embodied_investigation import EmbodiedInvestigator
from .intention_formation import NativeIntentionFormation
from .investigation import NativeInvestigator
from .reconsolidation import SchemaReconsolidator
from .schema_structure import SchemaStructurePlasticity
from .transfer_incubation import TransferAwareSituatedResidentRuntime
from .world_sense import NativeWorldSense, WorldFocus, WorldObservation


@dataclass(frozen=True, slots=True)
class WorldSamplingRhythm:
    """Current resident-derived sampling tendency for one durable world focus."""

    interval_seconds: float
    mode: str = "baseline"
    reasons: tuple[str, ...] = ()


@dataclass(slots=True)
class WorldRhythmState:
    """Small persistent sensory history used to pace one world focus."""

    focus_id: str
    observation_count: int = 0
    change_count: int = 0
    unchanged_observation_streak: int = 0
    last_change_at: str | None = None


class AdaptiveWorldSense(NativeWorldSense):
    """Native world sense whose cadence follows lived stability and attention.

    The existing world sensor already owns durable focuses, source fingerprints,
    and an independent service thread. This extension only lets the organ pace
    itself from its own lived history plus current Thought/Will. It is not a
    scheduler agent and it never asks a model when to look again.
    """

    _STABLE_BACKOFF_AFTER = 3
    _DEEP_STABLE_BACKOFF_AFTER = 8
    _WORLD_RELATION_FAMILIES = frozenset({"world_change"})

    def __init__(self, resident):
        super().__init__(resident)
        self._init_rhythm_schema()

    def follow(
        self,
        topic: str,
        *,
        priority: int = 0,
        interval_seconds: int = 1800,
        source: str = "self",
    ) -> WorldFocus:
        focus = super().follow(
            topic,
            priority=priority,
            interval_seconds=interval_seconds,
            source=source,
        )
        if self._load_rhythm_state(focus.focus_id) is None:
            self._save_rhythm_state(WorldRhythmState(focus_id=focus.focus_id))
        return focus

    def observe(
        self,
        focus_id: str,
        *,
        search_fn=None,
        limit: int = 5,
    ) -> WorldObservation:
        observation = super().observe(
            focus_id,
            search_fn=search_fn,
            limit=limit,
        )
        self._record_observation(observation)
        return observation

    def rhythm(self, focus_id: str) -> WorldSamplingRhythm:
        focus = self._require(focus_id)
        state = self.rhythm_state(focus.focus_id)
        return self._sampling_rhythm(focus, state)

    def rhythm_state(self, focus_id: str) -> WorldRhythmState:
        state = self._load_rhythm_state(focus_id)
        if state is None:
            self._require(focus_id)
            state = WorldRhythmState(focus_id=str(focus_id))
            self._save_rhythm_state(state)
        return state

    def due_focus(self, *, now: datetime | None = None) -> WorldFocus | None:
        current = now or datetime.now(timezone.utc)
        for focus in self.focuses(enabled_only=True, limit=100):
            if focus.last_observed_at is None:
                return focus
            last = self._parse_time(focus.last_observed_at)
            if last is None:
                return focus
            interval = self._sampling_rhythm(
                focus,
                self.rhythm_state(focus.focus_id),
            ).interval_seconds
            if current >= last + timedelta(seconds=interval):
                return focus
        return None

    def _sampling_rhythm(
        self,
        focus: WorldFocus,
        state: WorldRhythmState,
    ) -> WorldSamplingRhythm:
        base = float(max(60, int(focus.interval_seconds)))
        pressure = self._world_attention_pressure(focus)
        if pressure is not None:
            mode, factor, reason = pressure
            return WorldSamplingRhythm(
                interval_seconds=round(max(60.0, base * factor), 3),
                mode=mode,
                reasons=(reason,),
            )

        streak = max(0, int(state.unchanged_observation_streak))
        if streak >= self._DEEP_STABLE_BACKOFF_AFTER:
            return WorldSamplingRhythm(
                interval_seconds=round(base * 4.0, 3),
                mode="settled",
                reasons=(
                    f"world focus sources stayed unchanged for {streak} observations",
                ),
            )
        if streak >= self._STABLE_BACKOFF_AFTER:
            return WorldSamplingRhythm(
                interval_seconds=round(base * 2.0, 3),
                mode="stable",
                reasons=(
                    f"world focus sources stayed unchanged for {streak} observations",
                ),
            )
        return WorldSamplingRhythm(interval_seconds=round(base, 3))

    def _world_attention_pressure(
        self,
        focus: WorldFocus,
    ) -> tuple[str, float, str] | None:
        primary = self.resident.will.primary()
        if primary is not None:
            for payload in (primary.candidate_payload, primary.next_payload):
                pressure = self._world_payload_pressure(payload, focus.focus_id)
                if pressure is not None:
                    return pressure

        try:
            thought = self.resident.life.snapshot().current_thought
        except Exception:
            thought = None
        if thought is None or str(thought.action_kind or "") != "observe":
            return None
        thought_focus = self._norm_focus(thought.focus)
        topic = self._norm_focus(focus.topic)
        if topic and (thought_focus == topic or topic in thought_focus):
            return (
                "thought_attention",
                0.75,
                "current Thought is holding this durable world focus in attention",
            )

        try:
            traces = self.resident.nervous.recent_traces(32)
        except Exception:
            traces = ()
        for trace in traces:
            if str(getattr(trace, "channel", "")) != "world":
                continue
            if str(getattr(trace, "metadata", {}).get("focus_id") or "") != focus.focus_id:
                continue
            if self._norm_focus(getattr(trace, "summary", "")) != thought_focus:
                continue
            return (
                "thought_attention",
                0.75,
                "current Thought is still attending to a lived observation from this focus",
            )
        return None

    @classmethod
    def _world_payload_pressure(
        cls,
        payload,
        focus_id: str,
    ) -> tuple[str, float, str] | None:
        if not isinstance(payload, dict):
            return None
        if str(payload.get("world_focus_id") or "") != str(focus_id):
            return None
        expectation = payload.get("schema_expectation")
        if not isinstance(expectation, dict):
            return None
        family = str(expectation.get("family") or "").strip().lower().replace(" ", "_")
        if family not in cls._WORLD_RELATION_FAMILIES:
            return None

        attention = payload.get("transfer_attention")
        evidence_state = ""
        if isinstance(attention, dict):
            evidence_state = str(attention.get("evidence_state") or "").strip().lower()
        if bool(expectation.get("recheck")) or evidence_state == "prediction_error":
            return (
                "prediction_error",
                0.25,
                f"world prediction error keeps {family} under closer native observation",
            )
        if evidence_state == "conflicted":
            return (
                "conflicted",
                0.50,
                f"conflicting world evidence keeps {family} under closer native observation",
            )
        if evidence_state == "mixed":
            return (
                "mixed",
                0.75,
                f"mixed world evidence keeps {family} somewhat closer to attention",
            )
        return None

    def _record_observation(self, observation: WorldObservation) -> None:
        state = self.rhythm_state(observation.focus_id)
        state.observation_count += 1
        if observation.changed:
            state.change_count += 1
            state.unchanged_observation_streak = 0
            state.last_change_at = observation.captured_at
        else:
            state.unchanged_observation_streak += 1
        self._save_rhythm_state(state)

        if state.unchanged_observation_streak in {
            self._STABLE_BACKOFF_AFTER,
            self._DEEP_STABLE_BACKOFF_AFTER,
        }:
            focus = self._require(observation.focus_id)
            self._remember_stability(
                focus,
                observation,
                state.unchanged_observation_streak,
            )

    def _remember_stability(
        self,
        focus: WorldFocus,
        observation: WorldObservation,
        streak: int,
    ) -> None:
        self.resident.nervous.perceive(
            "world",
            f"World focus {focus.topic} remained source-stable across {streak} observations.",
            features=(focus.topic, "world_stability", "world_change:stable"),
            source="world_sense",
            salience=0.58 if streak < self._DEEP_STABLE_BACKOFF_AFTER else 0.64,
            valence=0.0,
            arousal=0.26,
            metadata={
                "focus_id": focus.focus_id,
                "observation_id": observation.observation_id,
                "world_change_relation": "stable",
                "stable_observation_streak": streak,
            },
        )

    def _remember_delta(
        self,
        focus: WorldFocus,
        observation: WorldObservation,
        current: dict[str, dict[str, str]],
        previous: dict[str, dict[str, str]],
    ) -> None:
        features = ["world_delta", "world_change:changed"]
        parts: list[str] = []
        if observation.new_sources:
            features.append("new_source")
            parts.append("new: " + ", ".join(observation.new_sources[:4]))
        if observation.updated_sources:
            features.append("updated_source")
            parts.append("updated: " + ", ".join(observation.updated_sources[:4]))
        if observation.removed_sources:
            features.append("removed_source")
            parts.append("removed: " + ", ".join(observation.removed_sources[:4]))

        involved = {
            *observation.new_sources,
            *observation.updated_sources,
            *observation.removed_sources,
        }
        for source_state in (current, previous):
            for item in source_state.values():
                label = self._source_label(item, "")
                domain = str(item.get("domain") or "").strip().lower()
                if label in involved and domain:
                    features.append(f"source_domain:{domain}")

        summary = (
            f"World change about {focus.topic}: "
            + ("; ".join(parts) if parts else "structured sources changed")
        )[:2200]
        self.resident.nervous.perceive(
            "world",
            summary,
            features=(focus.topic, *tuple(dict.fromkeys(features))[:20]),
            source="world_sense",
            salience=0.78,
            valence=0.0,
            arousal=0.58,
            metadata={
                "focus_id": focus.focus_id,
                "observation_id": observation.observation_id,
                "world_change": True,
                "world_change_relation": "changed",
                "new_sources": list(observation.new_sources),
                "updated_sources": list(observation.updated_sources),
                "removed_sources": list(observation.removed_sources),
            },
        )

    @staticmethod
    def _norm_focus(value) -> str:
        return " ".join(str(value or "").strip().lower().split())[:1000]

    def _init_rhythm_schema(self) -> None:
        with closing(self._rhythm_connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS world_sense_rhythm(
                    focus_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _load_rhythm_state(self, focus_id: str) -> WorldRhythmState | None:
        with closing(self._rhythm_connect()) as conn:
            row = conn.execute(
                "SELECT data FROM world_sense_rhythm WHERE focus_id=?",
                (str(focus_id),),
            ).fetchone()
        if row is None:
            return None
        raw = json.loads(row["data"])
        raw.setdefault("observation_count", 0)
        raw.setdefault("change_count", 0)
        raw.setdefault("unchanged_observation_streak", 0)
        raw.setdefault("last_change_at", None)
        return WorldRhythmState(**raw)

    def _save_rhythm_state(self, state: WorldRhythmState) -> None:
        with closing(self._rhythm_connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO world_sense_rhythm(focus_id,data) VALUES(?,?)",
                (
                    state.focus_id,
                    json.dumps(asdict(state), ensure_ascii=False, separators=(",", ":")),
                ),
            )
            conn.commit()

    def _rhythm_connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn


class WorldAwareIntentionFormation(NativeIntentionFormation):
    """Let structured world relations become one native Will observation."""

    _PROBE_BY_FAMILY = {
        **NativeIntentionFormation._PROBE_BY_FAMILY,
        "world_change": "world",
    }
    _FAMILY_BONUS = {
        **NativeIntentionFormation._FAMILY_BONUS,
        "world_change": 0.11,
    }

    def form(self, intention, activation, *, situation, body):
        candidate = super().form(
            intention,
            activation,
            situation=situation,
            body=body,
        )
        if candidate is not None and candidate.probe_key == "world":
            candidate.payload["schema_probe_observation"] = "world"
        return candidate

    def _probe_target(
        self,
        probe_key: str,
        intention_text: str,
        *,
        body,
    ) -> dict[str, Any] | None:
        if probe_key != "world":
            return super()._probe_target(probe_key, intention_text, body=body)
        world = getattr(self.resident, "world", None) if self.resident is not None else None
        if world is None:
            return None
        try:
            focuses = world.focuses(enabled_only=True, limit=100)
        except Exception:
            return None
        if not focuses:
            return None
        text = self._norm_world_text(intention_text)
        matched = [
            focus
            for focus in focuses
            if self._norm_world_text(focus.topic)
            and self._norm_world_text(focus.topic) in text
        ]
        if len(matched) == 1:
            focus = matched[0]
        elif len(focuses) == 1:
            focus = focuses[0]
        else:
            return None
        return {
            "world_focus_id": focus.focus_id,
            "world_topic": focus.topic,
        }

    @staticmethod
    def _step_text(
        probe_key: str,
        family: str,
        value: str,
        signature: str,
        target: dict[str, Any],
        *,
        recheck: bool = False,
        attempt: int = 1,
    ) -> str:
        if probe_key == "world":
            prefix = f"recheck {attempt} " if recheck else "inspect "
            topic = str(target.get("world_topic") or "outside world")[:220]
            return (
                f"{prefix}current world focus '{topic}' relation {family}:{value} "
                f"for my current intention (schema expectation {signature})"
            )
        return NativeIntentionFormation._step_text(
            probe_key,
            family,
            value,
            signature,
            target,
            recheck=recheck,
            attempt=attempt,
        )

    @staticmethod
    def _reason_text(
        probe_key: str,
        family: str,
        *,
        situation,
        body,
        recheck: bool = False,
    ) -> str:
        if probe_key == "world":
            if recheck:
                return (
                    f"the last reality check produced prediction error for structured {family}; "
                    "one confirming resident world observation can determine whether the "
                    "relation should restructure instead of being repeated indefinitely"
                )
            return (
                f"the activated schema carries a structured {family} expectation and an "
                "existing durable world focus provides a concrete resident-native observation path"
            )
        return NativeIntentionFormation._reason_text(
            probe_key,
            family,
            situation=situation,
            body=body,
            recheck=recheck,
        )

    @staticmethod
    def _norm_world_text(value) -> str:
        return " ".join(str(value or "").strip().lower().split())[:1200]


class WorldSchemaReconsolidator(SchemaReconsolidator):
    """Read current world probe facts as relation-level reality evidence."""

    _EXCLUSIVE = {*SchemaReconsolidator._EXCLUSIVE, "world_change"}

    @classmethod
    def _observation(cls, facts: dict[str, Any]) -> dict[str, Any]:
        observation = super()._observation(facts)
        world = facts.get("world") if isinstance(facts.get("world"), dict) else None
        if not world or world.get("available") is False:
            return observation

        observation["channels"].add("world")

        def add(raw: Any) -> None:
            feature = cls._norm(raw)
            if not feature:
                return
            observation["features"].add(feature)
            relation = cls._relation(feature)
            if relation:
                observation["relations"].setdefault(relation[0], set()).add(relation[1])

        add(f"world_change:{'changed' if world.get('changed') else 'stable'}")
        delta_present = False
        for name, key in (
            ("new", "new_sources"),
            ("updated", "updated_sources"),
            ("removed", "removed_sources"),
        ):
            if world.get(key):
                delta_present = True
                add(f"source_delta:{name}")
        if not delta_present and world.get("stable_sources"):
            add("source_delta:stable")
        for domain in (world.get("source_domains") or ())[:12]:
            add(f"source_domain:{domain}")
        return observation


class WorldAwareEmbodiedInvestigator(EmbodiedInvestigator):
    """Embodied investigation with one native outside-world observation probe."""

    _PROBE_LABELS = {
        **EmbodiedInvestigator._PROBE_LABELS,
        "world": "sample current resident world focus",
    }

    def investigate(
        self,
        event,
        readiness,
        *,
        learning_evidence: list[dict[str, Any]] | None = None,
        local_failure: str | None = None,
    ):
        # Call the native probe loop directly so world relation feedback is
        # evaluated once with the world-aware reconsolidator below.
        result = NativeInvestigator.investigate(
            self,
            event,
            readiness,
            learning_evidence=learning_evidence,
            local_failure=local_failure,
        )
        self._surface_procedural_applicability(event, readiness, result)
        predictions = result.state.facts.get("schema_predictions")
        nervous = getattr(self.resident, "nervous", None)
        if not isinstance(predictions, list) or not predictions or nervous is None:
            return result

        feedback = WorldSchemaReconsolidator(nervous).evaluate(
            predictions,
            result.state.facts,
            event_id=event.event_id,
        )
        if not feedback:
            return result

        self._bind_prediction_feedback_to_event(
            nervous,
            feedback,
            event.event_id,
        )
        structural_merges = SchemaStructurePlasticity(nervous).compact(
            seed_ids=[item.schema_trace_id for item in feedback],
        )
        existing = result.state.facts.get("schema_prediction_feedback")
        records = list(existing) if isinstance(existing, list) else []
        known_keys = {
            str(item.get("reconsolidation_key") or "")
            for item in records
            if isinstance(item, dict)
        }
        evidence = list(result.state.evidence)
        for item in feedback:
            if item.reconsolidation_key not in known_keys:
                records.append(item.to_dict())
                known_keys.add(item.reconsolidation_key)
            if item.status == "supported":
                note = (
                    f"prediction error {item.prediction_error:.3f}: current evidence "
                    f"supports schema {item.schema_trace_id}; the schema was reinforced"
                )
            elif item.status == "refined":
                note = (
                    f"prediction error {item.prediction_error:.3f}: current evidence "
                    f"partly contradicts schema {item.schema_trace_id}; the schema was "
                    "reconsolidated and the exception was preserved"
                )
            elif item.status == "contradicted":
                note = (
                    f"prediction error {item.prediction_error:.3f}: current evidence "
                    f"contradicts schema {item.schema_trace_id}; the schema was weakened "
                    "and the exception was preserved"
                )
            else:
                note = (
                    f"current {', '.join(item.observation_channels) or 'body'} evidence "
                    f"did not directly test schema {item.schema_trace_id}; no neural "
                    "prediction strength was changed"
                )
            self._append_unique(evidence, note)

        merge_records = [item.to_dict() for item in structural_merges]
        for item in structural_merges:
            self._append_unique(
                evidence,
                "structural neural plasticity merged redundant schema "
                f"{item.absorbed_schema_id} into {item.canonical_schema_id} "
                f"(shared lived support={item.source_overlap:.3f}, "
                f"shared structure={item.feature_overlap:.3f})",
            )

        result.state.facts["schema_prediction_feedback"] = records[-16:]
        if merge_records:
            prior_merges = result.state.facts.get("schema_structural_merges")
            merged_history = list(prior_merges) if isinstance(prior_merges, list) else []
            merged_history.extend(merge_records)
            result.state.facts["schema_structural_merges"] = merged_history[-16:]
        result.state.evidence = tuple(evidence[-64:])
        result.state.updated_at = (
            structural_merges[-1].at if structural_merges else feedback[-1].at
        )

        if event.kind == "intention_probe" and result.resolved:
            changed = [item for item in feedback if item.status != "untested"]
            if changed:
                latest = changed[-1]
                suffix = (
                    f" Reality feedback {latest.status} the activated pattern "
                    f"(prediction error={latest.prediction_error:.3f}); the result was "
                    "written back into my persistent neural state."
                )
            else:
                suffix = (
                    " The current observation did not test a structured expectation "
                    "inside the schema, so I left its neural strength unchanged."
                )
            if structural_merges:
                suffix += (
                    f" I also collapsed {len(structural_merges)} redundant schema "
                    "representation(s) into the surviving lived pattern."
                )
            result.response = f"{result.response}{suffix}"
            result.state.resolution = result.response

        self._save(result.state)
        return result

    def _run_probe(
        self,
        key: str,
        event,
        readiness,
        *,
        facts: dict[str, Any],
        learning_evidence: list[dict[str, Any]],
    ) -> list[str]:
        if key == "world":
            world = getattr(self.resident, "world", None)
            focus_id = str(event.payload.get("world_focus_id") or "").strip()
            if world is None or not focus_id:
                facts["world"] = {"available": False}
                return ["resident world focus is currently unavailable"]
            try:
                observation = world.observe(focus_id)
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                facts["world"] = {
                    "available": False,
                    "focus_id": focus_id,
                    "error": message,
                }
                return [f"resident world probe failed: {message}"]

            focus = next(
                (
                    item
                    for item in world.focuses(enabled_only=False, limit=200)
                    if item.focus_id == focus_id
                ),
                None,
            )
            source_domains = sorted(
                {
                    str(item.get("domain") or "").strip().lower()
                    for item in (
                        (focus.last_source_state or {}).values()
                        if focus is not None
                        else ()
                    )
                    if str(item.get("domain") or "").strip()
                }
            )
            facts["world"] = {
                "available": True,
                "focus_id": focus_id,
                "topic": observation.topic,
                "changed": bool(observation.changed),
                "source_count": int(observation.source_count),
                "new_sources": list(observation.new_sources),
                "updated_sources": list(observation.updated_sources),
                "removed_sources": list(observation.removed_sources),
                "stable_sources": list(observation.stable_sources),
                "source_domains": source_domains,
                "captured_at": observation.captured_at,
            }
            return [
                "world: "
                f"focus={observation.topic}; changed={observation.changed}; "
                f"sources={observation.source_count}; new={len(observation.new_sources)}; "
                f"updated={len(observation.updated_sources)}; "
                f"removed={len(observation.removed_sources)}"
            ]

        return super()._run_probe(
            key,
            event,
            readiness,
            facts=facts,
            learning_evidence=learning_evidence,
        )


class WorldAwareTransferResidentRuntime(TransferAwareSituatedResidentRuntime):
    """Current resident with world sensing inside the same closed learning loop."""

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.world = AdaptiveWorldSense(self)
        self.intention_formation = WorldAwareIntentionFormation(
            self.nervous,
            resident=self,
        )
        self.investigator = WorldAwareEmbodiedInvestigator(self)
