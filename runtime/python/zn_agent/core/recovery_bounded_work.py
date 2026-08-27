from __future__ import annotations

"""Recovery-aware synchronous facade over the resident-owned Work ledger."""

from contextlib import nullcontext
from typing import Any

from .recovery_control import raise_if_synchronous_recovery_blocked
from .work import ResidentWorkLedger


class RecoveryBoundedWorkLedger(ResidentWorkLedger):
    """Reuse Work durability while bounding its legacy synchronous submit face."""

    def submit(
        self,
        thread_id: str,
        task: str,
        *,
        kind: str = "desktop_user_event",
        priority: int = 0,
        payload: dict[str, Any] | None = None,
    ):
        current = self.resident.store.get_working_state()
        if current.current_event_id:
            raise_if_synchronous_recovery_blocked(current.current_event_id, current)

        scope = getattr(self.resident, "synchronous_recovery_control", None)
        context = scope() if callable(scope) else nullcontext()
        with context:
            return super().submit(
                thread_id,
                task,
                kind=kind,
                priority=priority,
                payload=payload,
            )
