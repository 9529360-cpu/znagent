from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

from .embodied_resident import EmbodiedResidentRuntime
from .models import EventStatus, ResidentRunResult
from .nervous_system import PersistentNervousSystem
from .will import NativeWill, ResidentIntention


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
            self.nervous.perceive(
                "thought",
                f"{thought.focus} -> {thought.chosen_action}",
                features=(
                    thought.action_kind,
                    *("uncertain",) if thought.unknown else (),
                ),
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
        """Form one Thought and advance one event or one intention step."""
        with self._cycle_lock:
            pulse = self.pulse()
            thought = pulse.thought
            if thought is None:
                return None

            if thought.action_kind == "intention" and thought.action_target:
                self._advance_intention(thought.action_target)
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
