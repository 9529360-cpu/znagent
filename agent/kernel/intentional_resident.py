from __future__ import annotations

from typing import Any

from .embodied_resident import EmbodiedResidentRuntime
from .models import EventStatus, ResidentRunResult
from .will import NativeWill, ResidentIntention


class IntentionalResidentRuntime(EmbodiedResidentRuntime):
    """Embodied resident that keeps and advances its own durable intentions.

    Will is not a prompt queue. An intention may persist for days while many
    concrete events come and go. When an intention has a concrete next step,
    native Thought can turn that step into an internal event which then travels
    through the exact same cognition/body/outcome loop as any other work.
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
        return self.will.intend(
            description,
            source=source,
            priority=priority,
            next_task=next_task,
            next_payload=next_payload,
            complete_on_step_success=complete_on_step_success,
        )

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

    def _complete_result(self, event, result):
        completed = super()._complete_result(event, result)
        intention_id = str(event.payload.get("intention_id") or "").strip()
        if intention_id:
            summary = (
                completed.response
                or completed.reason
                or ("step succeeded" if completed.success else "step failed")
            )
            try:
                self.will.observe_event_outcome(
                    intention_id,
                    event_id=completed.event.event_id,
                    success=completed.success,
                    summary=summary,
                )
            except KeyError:
                # The event remains a valid resident event even if an imported
                # or manually-created payload references an unknown intention.
                pass
        return completed

    def status(self) -> dict[str, Any]:
        data = super().status()
        primary = self.will.primary()
        data["will"] = {
            "primary": self._intention_data(primary) if primary is not None else None,
            "active": [self._intention_data(item) for item in self.will.active(20)],
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
