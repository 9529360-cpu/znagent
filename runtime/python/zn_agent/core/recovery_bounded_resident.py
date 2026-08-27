from __future__ import annotations

"""Bound direct synchronous driving at durable recovery-control checkpoints."""

from .capability_recovery_resident import CapabilityRecoveryResidentRuntime
from .models import EventStatus
from .recovery_control import raise_if_synchronous_recovery_blocked


class RecoveryBoundedResidentRuntime(CapabilityRecoveryResidentRuntime):
    """Keep asynchronous resident life alive while bounding synchronous callers.

    The desktop's normal Work path starts durable work and polls progress while
    the resident life loop continues independently. Legacy/direct synchronous
    callers cannot do that. If one reaches a replay-blocked side-effect recovery
    that needs explicit control, return control by raising
    ``ResidentRecoveryRequired`` while leaving the event, WorkingState, and
    side-effect attempt active and recoverable.
    """

    def submit(
        self,
        task: str,
        *,
        kind: str = "user_task",
        priority: int = 0,
        payload: dict | None = None,
    ):
        current = self.store.get_working_state()
        if current.current_event_id:
            raise_if_synchronous_recovery_blocked(current.current_event_id, current)

        event = self.enqueue(task, kind=kind, priority=priority, payload=payload)
        while True:
            completed = self.result_for(event.event_id)
            if completed is not None:
                return completed

            result = self.live_once()
            if result is not None and result.event.event_id == event.event_id:
                return result

            completed = self.result_for(event.event_id)
            if completed is not None:
                return completed

            current = self.store.get_working_state()
            raise_if_synchronous_recovery_blocked(
                str(current.current_event_id or event.event_id),
                current,
            )

            persisted = self.store.get_event(event.event_id)
            if persisted is not None and persisted.status in {
                EventStatus.COMPLETED,
                EventStatus.FAILED,
            }:
                raise RuntimeError(
                    "resident event reached a terminal state without a durable outcome"
                )

    def run_once(
        self,
        *,
        thought=None,
        target_event_id: str | None = None,
        readiness=None,
        learning_evidence=None,
    ):
        event = (
            self.store.claim_event(target_event_id)
            if target_event_id
            else self.store.claim_next_event()
        )
        if event is None:
            return None

        drive_to_terminal = thought is None
        required = self._required_capabilities(event)
        if readiness is None:
            readiness = self.kernel.self_model.assess_task(event.task, required)
        if learning_evidence is None:
            learning_evidence = self._related_learning_evidence(event, readiness)

        state = self._state_for_event(
            event,
            thought=thought,
            readiness=readiness,
            learning_evidence=learning_evidence,
        )

        try:
            while True:
                result = self._advance_event_step(
                    event,
                    state,
                    readiness=readiness,
                    learning_evidence=learning_evidence,
                    thought=thought,
                )
                if result is not None:
                    return self._complete_result(event, result)

                if drive_to_terminal:
                    current = self.store.get_working_state()
                    raise_if_synchronous_recovery_blocked(event.event_id, current)
                else:
                    return None

                pulse = self.pulse()
                thought = pulse.thought
                required = self._required_capabilities(event)
                readiness = self.kernel.self_model.assess_task(event.task, required)
                learning_evidence = self._related_learning_evidence(event, readiness)
                if thought is not None:
                    self._enrich_thought_with_readiness(
                        thought,
                        readiness,
                        learning_evidence,
                    )
                    self._enrich_thought_with_working_stage(thought, event)
                    self._persist_enriched_thought(thought)
                state = self.store.get_working_state()
                self._update_state_context(
                    state,
                    event,
                    thought=thought,
                    readiness=readiness,
                    learning_evidence=learning_evidence,
                )
                self.store.save_working_state(state)
        except Exception as exc:
            completed = self.result_for(event.event_id)
            if completed is not None:
                return completed
            current = self.store.get_working_state()
            if self._preserve_working_truth_on_exception(event, current):
                raise
            message = f"{type(exc).__name__}: {exc}"
            self.life.mark_impasse_unresolved(event, message)
            failure = self._checkpoint_terminal_failure(
                event,
                current,
                reason=message,
            )
            return self._complete_result(event, failure)
