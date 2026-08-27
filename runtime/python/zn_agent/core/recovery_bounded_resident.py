from __future__ import annotations

"""Bound synchronous driving at durable recovery-control checkpoints."""

import threading
from contextlib import contextmanager
from typing import Any, Iterator

from .capability_recovery_resident import CapabilityRecoveryResidentRuntime
from .recovery_control import raise_if_synchronous_recovery_blocked


class RecoveryBoundedResidentRuntime(CapabilityRecoveryResidentRuntime):
    """Keep asynchronous resident life alive while bounding synchronous callers.

    Synchronous call policy is deliberately layered around the same resident
    main loop rather than copied into a second loop. A thread-local marker lets
    direct ``run_once()`` and ``submit()`` yield at explicit recovery-control
    boundaries, while ordinary one-step life pulses keep the resident alive.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._sync_recovery_context = threading.local()

    @contextmanager
    def synchronous_recovery_control(self) -> Iterator[None]:
        previous = bool(getattr(self._sync_recovery_context, "enabled", False))
        self._sync_recovery_context.enabled = True
        try:
            yield
        finally:
            self._sync_recovery_context.enabled = previous

    def submit(
        self,
        task: str,
        *,
        kind: str = "user_task",
        priority: int = 0,
        payload: dict[str, Any] | None = None,
    ):
        current = self.store.get_working_state()
        if current.current_event_id:
            raise_if_synchronous_recovery_blocked(current.current_event_id, current)
        with self.synchronous_recovery_control():
            return super().submit(
                task,
                kind=kind,
                priority=priority,
                payload=payload,
            )

    def run_once(
        self,
        *,
        thought=None,
        target_event_id: str | None = None,
        readiness=None,
        learning_evidence=None,
    ):
        if thought is not None or bool(
            getattr(self._sync_recovery_context, "enabled", False)
        ):
            return super().run_once(
                thought=thought,
                target_event_id=target_event_id,
                readiness=readiness,
                learning_evidence=learning_evidence,
            )
        with self.synchronous_recovery_control():
            return super().run_once(
                thought=thought,
                target_event_id=target_event_id,
                readiness=readiness,
                learning_evidence=learning_evidence,
            )

    def _advance_event_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        result = super()._advance_event_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )
        if result is None and bool(
            getattr(self._sync_recovery_context, "enabled", False)
        ):
            raise_if_synchronous_recovery_blocked(
                event.event_id,
                self.store.get_working_state(),
            )
        return result
