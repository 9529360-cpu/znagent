from __future__ import annotations

"""Synchronous caller boundary for durable resident recovery states."""

from .models import WorkingState


class ResidentRecoveryRequired(RuntimeError):
    """A synchronous caller must yield while durable Work awaits explicit control.

    This is not a task failure. The resident event remains active and its durable
    recovery checkpoint remains authoritative until action-specific evidence or
    an explicit lifecycle decision resolves it.
    """

    def __init__(
        self,
        *,
        event_id: str,
        stage: str,
        blocked_by: str,
        decision: str,
        next_action: str | None,
    ) -> None:
        self.event_id = event_id
        self.stage = stage
        self.blocked_by = blocked_by
        self.decision = decision
        self.next_action = next_action
        decision_text = decision or "unspecified"
        super().__init__(
            f"resident event {event_id} requires explicit recovery control; "
            "the outside-world effect is uncertain and replay is blocked "
            f"(decision={decision_text}). The event remains active; inspect durable "
            "progress or cancel it explicitly instead of driving synchronously."
        )


def raise_if_synchronous_recovery_blocked(
    event_id: str,
    state: WorkingState,
) -> None:
    """Yield a synchronous caller without changing durable event truth.

    Exact append recovery is intentionally excluded while its decision remains
    ``reverify_effect`` because that path can make progress using read-only
    evidence. Once recovery falls back to a replay-blocked explicit decision,
    synchronous driving must return control rather than spin forever.
    """

    normalized_event = str(event_id or "").strip()
    if not normalized_event or str(state.current_event_id or "").strip() != normalized_event:
        return

    stage = str(state.stage or "").strip().lower()
    blocked_by = str(state.blocked_by or "").strip().lower()
    if stage != "side_effect_recovery" or blocked_by != "outside_world_effect_uncertain":
        return

    recovery = (
        state.data.get("side_effect_recovery")
        if isinstance(state.data, dict)
        else None
    )
    if not isinstance(recovery, dict) or recovery.get("replay_blocked") is not True:
        return

    decision = str(recovery.get("decision") or "").strip().lower()
    if decision == "reverify_effect":
        return

    raise ResidentRecoveryRequired(
        event_id=normalized_event,
        stage=stage,
        blocked_by=blocked_by,
        decision=decision,
        next_action=state.next_action,
    )
