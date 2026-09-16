from __future__ import annotations

"""Idempotent handoff from one durable Will step to the existing Event store.

The Resident already owns both sides of this boundary: ``NativeWill`` owns the
current durable intention step and ``KernelStore.events`` owns executable Event
truth. This behavior adds no queue, ledger, scheduler, retry loop, or execution
authority. It reuses ZN's existing idempotent Event ingress so a process death
after Event persistence but before ``will.engage()`` cannot create a second
Event on restart.

Only the exact internal intention handoff shape is eligible. Ordinary user,
Work, channel, and other ``enqueue`` calls keep the original random Event ID
behavior unchanged.
"""

from .event_ingress import enqueue_event_once, stable_external_event_id
from .models import AgentEvent


_INSTALL_MARKER = "_zn_intention_event_handoff_installed"


def _same_event_contract(
    event: AgentEvent,
    *,
    task: str,
    kind: str,
    priority: int,
    payload: dict,
) -> bool:
    return (
        event.task == task
        and event.kind == kind
        and int(event.priority) == int(priority)
        and event.payload == payload
    )


def install_intention_event_handoff_behavior(resident) -> None:
    """Reuse one durable Event identity for one still-active Will step."""

    if getattr(resident, _INSTALL_MARKER, False):
        return
    will = getattr(resident, "will", None)
    store = getattr(resident, "store", None)
    if will is None or store is None:
        raise ValueError("idempotent Will handoff requires existing Will and Event store")

    original_enqueue = resident.enqueue

    def enqueue(
        task: str,
        *,
        kind: str = "user_task",
        priority: int = 0,
        payload: dict | None = None,
    ) -> AgentEvent:
        normalized_task = str(task or "").strip()
        normalized_kind = str(kind or "user_task").strip() or "user_task"
        normalized_priority = int(priority)
        payload_data = dict(payload or {})
        intention_id = str(payload_data.get("intention_id") or "").strip()

        if not intention_id:
            return original_enqueue(
                task,
                kind=kind,
                priority=priority,
                payload=payload,
            )

        intention = will.get(intention_id)
        eligible = (
            intention is not None
            and intention.status == "active"
            and not intention.related_event_id
            and bool(intention.next_task)
            and intention.next_task == normalized_task
            and str(payload_data.get("intention_description") or "")
            == intention.description
            and str(payload_data.get("intention_source") or "")
            == intention.source
        )
        if not eligible:
            return original_enqueue(
                task,
                kind=kind,
                priority=priority,
                payload=payload,
            )

        # ``updated_at`` is the durable generation boundary for an active Will
        # step: set_next_step/intend establish it; engage replaces the step with
        # an Event; a later same-text step receives a later generation stamp.
        step_generation = str(intention.updated_at or "").strip()
        if not step_generation:
            raise RuntimeError("active Will step has no durable generation timestamp")

        event_id = stable_external_event_id(
            "will",
            f"{intention_id}\0{step_generation}",
        )
        ingress = enqueue_event_once(
            resident,
            event_id=event_id,
            task=normalized_task,
            kind=normalized_kind,
            priority=normalized_priority,
            payload=payload_data,
        )
        if not _same_event_contract(
            ingress.event,
            task=normalized_task,
            kind=normalized_kind,
            priority=normalized_priority,
            payload=payload_data,
        ):
            raise RuntimeError(
                "durable Will Event identity already exists with a different contract"
            )
        return ingress.event

    resident.enqueue = enqueue
    setattr(resident, _INSTALL_MARKER, True)
