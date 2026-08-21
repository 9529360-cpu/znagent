from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

from .embodied_resident import EmbodiedResidentRuntime
from .models import EventStatus, ResidentRunResult
from .nervous_system import PersistentNervousSystem
from .will import NativeWill, ResidentIntention
from .world_sense import NativeWorldSense, WorldObservation


class IntentionalResidentRuntime(EmbodiedResidentRuntime):
    """Embodied resident with persistent Will and a lived nervous system.

    Will is not a prompt queue. Neural memory is not a transcript store. The
    resident keeps durable intentions while perception, thought, action, and
    outcomes continuously reshape an associative nervous substrate that remains
    present across restarts.
    """

    _ACTIVE_THOUGHT_KINDS = {
        *EmbodiedResidentRuntime._ACTIVE_THOUGHT_KINDS,
        "intention",
    }
    _REFLECTION_PERIOD_PULSES = 30
    _REFLECTION_CHANNELS = ("will", "outcome", "world", "vision", "action")

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(
            kernel=kernel,
            capabilities=capabilities,
            budget=budget,
        )
        self.will = NativeWill(self.store)
        self.will.reconcile_outcomes()
        self.nervous = PersistentNervousSystem(self.store)
        self.nervous.heartbeat(body=self.body.sense())
        self.world = NativeWorldSense(self)

    def intend(
        self,
        description: str,
        *,
        source: str = "self",
        priority: int = 0,
        next_task: str | None = None,
        next_payload: dict[str, Any] | None = None,
        complete_on_step_success: bool = False,
    ) -> ResidentIntention:
        intention = self.will.intend(
            description,
            source=source,
            priority=priority,
            next_task=next_task,
            next_payload=next_payload,
            complete_on_step_success=complete_on_step_success,
        )
        self.nervous.perceive(
            "will",
            f"I formed an intention: {intention.description}",
            features=("intention", intention.source),
            source="will",
            salience=min(1.0, 0.55 + max(0, intention.priority) * 0.03),
            valence=0.25,
            arousal=0.35,
            metadata={"intention_id": intention.intention_id},
        )
        return intention

    def follow_world(
        self,
        topic: str,
        *,
        priority: int = 0,
        interval_seconds: int = 1800,
        source: str = "self",
    ):
        """Keep noticing a topic in the outside world without repeated prompts."""
        return self.world.follow(
            topic,
            priority=priority,
            interval_seconds=interval_seconds,
            source=source,
        )

    def observe_world_once(
        self,
        focus_id: str,
        *,
        search_fn=None,
        limit: int = 5,
    ) -> WorldObservation:
        return self.world.observe(focus_id, search_fn=search_fn, limit=limit)

    def perceive_visual(
        self,
        summary: str,
        *,
        features: Iterable[str] = (),
        source: str = "vision",
        salience: float = 0.55,
        valence: float = 0.0,
        arousal: float = 0.35,
        metadata: dict[str, Any] | None = None,
    ):
        """Let screen/camera/vision adapters feed ZN's native nervous system."""
        return self.nervous.remember_visual(
            summary,
            features=features,
            source=source,
            salience=salience,
            valence=valence,
            arousal=arousal,
            metadata=metadata,
        )

    def perceive_world(
        self,
        summary: str,
        *,
        features: Iterable[str] = (),
        source: str = "world/web",
        salience: float = 0.5,
        valence: float = 0.0,
        arousal: float = 0.3,
        metadata: dict[str, Any] | None = None,
    ):
        """Let autonomous web/world sensors feed the same persistent memory."""
        return self.nervous.remember_world(
            summary,
            features=features,
            source=source,
            salience=salience,
            valence=valence,
            arousal=arousal,
            metadata=metadata,
        )

    def pulse(self):
        """Advance body homeostasis, neural continuity, then form one Thought."""
        self.nervous.heartbeat(body=self.body.sense())
        working = self.store.get_working_state()
        self.nervous.observe_working_state(working.data)

        pulse = super().pulse()
        thought = pulse.thought
        if thought is not None:
            unknown_pressure = min(1.0, len(thought.unknown) / 4.0)
            action_pressure = 0.15 if thought.action_kind == "observe" else 0.45
            features = [thought.action_kind]
            if thought.unknown:
                features.append("uncertain")
            self.nervous.perceive(
                "thought",
                f"{thought.focus} -> {thought.chosen_action}",
                features=tuple(features),
                source="thought",
                salience=min(1.0, 0.30 + action_pressure + 0.20 * unknown_pressure),
                valence=-0.18 * unknown_pressure,
                arousal=min(1.0, 0.22 + action_pressure + 0.28 * unknown_pressure),
                metadata={
                    "sequence": thought.sequence,
                    "action_target": thought.action_target,
                    "confidence": thought.confidence,
                },
            )
        return pulse

    def live_once(self) -> ResidentRunResult | None:
        """Form one Thought and advance one event, intention, or native reflection."""
        with self._cycle_lock:
            pulse = self.pulse()
            thought = pulse.thought
            if thought is None:
                return None

            if thought.action_kind == "intention" and thought.action_target:
                self._advance_intention(thought.action_target)
                return None

            if thought.action_kind == "observe" and self._native_reflect_if_due(thought):
                return None

            if thought.action_kind not in self._ACTIVE_THOUGHT_KINDS:
                return None
            if not thought.action_target:
                return None

            event = self.store.get_event(thought.action_target)
            if event is None or event.status in {EventStatus.COMPLETED, EventStatus.FAILED}:
                return None

            required = self._required_capabilities(event)
            readiness = self.kernel.self_model.assess_task(event.task, required)
            learning_evidence = self._related_learning_evidence(event, readiness)
            self._enrich_thought_with_readiness(
                thought,
                readiness,
                learning_evidence,
            )
            self._enrich_thought_with_working_stage(thought, event)
            self._persist_enriched_thought(thought)
            return self.run_once(
                thought=thought,
                target_event_id=event.event_id,
                readiness=readiness,
                learning_evidence=learning_evidence,
            )

    def _native_reflect_if_due(self, thought) -> bool:
        """Perform one low-frequency association entirely inside the resident.

        Reflection is not a planning request and does not create an event. It
        lets Will, affect, and salient lived traces co-activate periodically so
        later Thoughts can be changed by the resident's own accumulated life.
        """
        sequence = max(0, int(getattr(thought, "sequence", 0) or 0))
        if sequence <= 0 or sequence % self._REFLECTION_PERIOD_PULSES:
            return False

        situation = self.life.snapshot().current_situation
        if situation is not None and (
            situation.active_event_id or situation.active_impasse_id
        ):
            return False

        primary = self.will.primary()
        affect = self.nervous.snapshot()
        activations = []
        focus = None
        if primary is not None:
            focus = primary.description
            activations = self.nervous.activate(
                primary.description,
                channels=self._REFLECTION_CHANNELS,
                limit=5,
            )
        else:
            candidates = [
                trace
                for trace in self.nervous.recent_traces(64)
                if trace.channel in self._REFLECTION_CHANNELS
            ]
            candidates.sort(
                key=lambda trace: (
                    0.50 * trace.salience
                    + 0.30 * trace.strength
                    + 0.12 * abs(trace.valence)
                    + 0.08 * trace.arousal
                ),
                reverse=True,
            )
            if candidates:
                top = candidates[0]
                score = (
                    0.50 * top.salience
                    + 0.30 * top.strength
                    + 0.12 * abs(top.valence)
                    + 0.08 * top.arousal
                )
                if score >= 0.58 and (
                    affect.curiosity >= 0.40
                    or affect.tension >= 0.40
                    or abs(affect.valence) >= 0.30
                ):
                    focus = top.summary
                    activations = self.nervous.activate(
                        top.summary,
                        channels=self._REFLECTION_CHANNELS,
                        limit=5,
                    )

        if not focus or not activations:
            return False

        traces = [item.trace for item in activations[:3]]
        top = traces[0]
        if len(traces) >= 2:
            summary = (
                f"While thinking about {focus[:220]}, I associated "
                f"{top.summary[:260]} with {traces[1].summary[:260]}."
            )
        else:
            summary = (
                f"While thinking about {focus[:220]}, the lived trace "
                f"{top.summary[:360]} remained salient."
            )
        average_valence = sum(trace.valence for trace in traces) / len(traces)
        self.nervous.perceive(
            "reflection",
            summary,
            features=(
                "native_reflection",
                *(f"source:{trace.channel}" for trace in traces),
            ),
            source="self",
            salience=min(
                0.82,
                0.42
                + 0.20 * max(item.activation for item in activations[:3])
                + 0.12 * affect.curiosity
                + 0.08 * affect.tension,
            ),
            valence=max(-1.0, min(1.0, average_valence)),
            arousal=min(0.78, 0.24 + 0.20 * affect.curiosity + 0.20 * affect.tension),
            metadata={
                "thought_sequence": sequence,
                "intention_id": primary.intention_id if primary is not None else None,
                "source_trace_ids": [trace.trace_id for trace in traces],
                "model_invocations": 0,
            },
        )
        return True

    def _related_learning_evidence(
        self,
        event,
        readiness,
        *,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Blend explicit learning evidence with bounded associative lived memory.

        Neural traces stay resident-side. They can change deliberation and help
        ZN recognize a familiar situation, but this method does not put them
        into an external-model prompt.
        """
        bounded_limit = max(1, int(limit))
        merged = list(
            super()._related_learning_evidence(
                event,
                readiness,
                limit=bounded_limit,
            )
        )
        allowed_channels = {"outcome", "world", "vision", "action", "will"}
        for activation in self.nervous.activate(event.task, limit=bounded_limit * 3):
            trace = activation.trace
            if trace.channel not in allowed_channels:
                continue
            if str(trace.metadata.get("event_id") or "") == event.event_id:
                continue
            merged.append(
                {
                    "candidate_id": f"neural:{trace.trace_id}",
                    "similarity": round(activation.activation, 4),
                    "domains": list(readiness.domains),
                    "task": trace.summary[:240],
                    "resolution_summary": trace.summary[:320],
                    "resolution_source": f"neural:{trace.channel}",
                    "neural_trace_id": trace.trace_id,
                    "salience": round(trace.salience, 4),
                    "valence": round(trace.valence, 4),
                }
            )

        deduped: dict[str, dict[str, Any]] = {}
        for item in merged:
            key = str(item.get("candidate_id") or item.get("neural_trace_id") or "")
            if not key:
                continue
            prior = deduped.get(key)
            if prior is None or float(item.get("similarity") or 0.0) > float(
                prior.get("similarity") or 0.0
            ):
                deduped[key] = item
        ranked = sorted(
            deduped.values(),
            key=lambda item: float(item.get("similarity") or 0.0),
            reverse=True,
        )
        return ranked[:bounded_limit]

    def _advance_intention(self, intention_id: str) -> None:
        intention = self.will.get(intention_id)
        if intention is None:
            return
        if intention.status != "active":
            return
        if intention.related_event_id:
            return
        if not intention.next_task:
            return

        task = intention.next_task
        payload = dict(intention.next_payload)
        payload.setdefault("intention_id", intention.intention_id)
        payload.setdefault("intention_description", intention.description)
        payload.setdefault("intention_source", intention.source)
        event = self.enqueue(
            task,
            kind="intention_step",
            priority=intention.priority,
            payload=payload,
        )
        self.will.engage(intention.intention_id, event.event_id)
        self.nervous.perceive(
            "will",
            f"I began the next step of intention {intention.intention_id}: {task}",
            features=("intention_step", "engaged"),
            source="will",
            salience=0.62,
            valence=0.12,
            arousal=0.45,
            metadata={
                "intention_id": intention.intention_id,
                "event_id": event.event_id,
            },
        )

    def _complete_result(self, event, result):
        completed = super()._complete_result(event, result)
        summary = (
            completed.response
            or completed.reason
            or ("event succeeded" if completed.success else "event failed")
        )
        self.nervous.perceive(
            "outcome",
            f"{event.task}: {summary[:1000]}",
            features=(
                event.kind,
                completed.execution_path.value,
                "success" if completed.success else "failure",
            ),
            source="self",
            salience=min(1.0, 0.58 + (0.18 if not completed.success else 0.0)),
            valence=0.52 if completed.success else -0.78,
            arousal=0.42 if completed.success else 0.82,
            metadata={
                "event_id": completed.event.event_id,
                "model_invocations": completed.model_invocations,
            },
        )

        intention_id = str(event.payload.get("intention_id") or "").strip()
        if intention_id:
            try:
                self.will.observe_event_outcome(
                    intention_id,
                    event_id=completed.event.event_id,
                    success=completed.success,
                    summary=summary,
                )
            except KeyError:
                # The event remains valid if an imported/manual payload points
                # at an intention that is not present in this resident.
                pass
        return completed

    def status(self) -> dict[str, Any]:
        data = super().status()
        primary = self.will.primary()
        affect = self.nervous.snapshot()
        data["will"] = {
            "primary": self._intention_data(primary) if primary is not None else None,
            "active": [self._intention_data(item) for item in self.will.active(20)],
        }
        data["nervous_system"] = {
            "tone": self.nervous.describe_state(),
            "affect": asdict(affect),
            "recent_trace_count": len(self.nervous.recent_traces(50)),
        }
        data["world_sense"] = {
            "focuses": [asdict(item) for item in self.world.focuses(enabled_only=True, limit=20)],
            "due_focus": (
                asdict(due) if (due := self.world.due_focus()) is not None else None
            ),
        }
        return data

    @staticmethod
    def _intention_data(intention: ResidentIntention) -> dict[str, Any]:
        return {
            "intention_id": intention.intention_id,
            "description": intention.description,
            "source": intention.source,
            "priority": intention.priority,
            "status": intention.status,
            "current_step": intention.current_step,
            "next_task": intention.next_task,
            "related_event_id": intention.related_event_id,
            "last_outcome": intention.last_outcome,
            "complete_on_step_success": intention.complete_on_step_success,
            "updated_at": intention.updated_at,
        }
