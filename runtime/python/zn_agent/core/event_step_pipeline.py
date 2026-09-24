from __future__ import annotations

"""Explicit ordered Resident event-step pipeline.

Behavior modules register bounded handlers here instead of repeatedly replacing
Resident._advance_event_step. The pipeline owns the single method interception
point and preserves the original Resident implementation as the terminal
fallback.
"""

from dataclasses import dataclass
from typing import Any, Callable


_PIPELINE_MARKER = "_event_step_pipeline_v1_installed"
_PIPELINE_HANDLERS = "_event_step_pipeline_v1_handlers"
_PIPELINE_SEQUENCE = "_event_step_pipeline_v1_sequence"


@dataclass(frozen=True, slots=True)
class EventStepDecision:
    handled: bool
    result: Any = None

    @classmethod
    def claim(cls, result: Any = None) -> "EventStepDecision":
        return cls(handled=True, result=result)


EventStepHandler = Callable[..., EventStepDecision | None]


def ensure_event_step_pipeline(resident) -> None:
    """Install the one pipeline interception point for this Resident."""
    if getattr(resident, _PIPELINE_MARKER, False):
        return

    original_advance = resident._advance_event_step
    setattr(resident, _PIPELINE_HANDLERS, [])
    setattr(resident, _PIPELINE_SEQUENCE, 0)

    def advance_event_step(
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        handlers = tuple(getattr(resident, _PIPELINE_HANDLERS, ()))
        for _priority, _sequence, _name, handler in handlers:
            decision = handler(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )
            if decision is not None and decision.handled:
                return decision.result

        return original_advance(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    resident._advance_event_step = advance_event_step
    setattr(resident, _PIPELINE_MARKER, True)


def register_event_step_handler(
    resident,
    *,
    name: str,
    handler: EventStepHandler,
    priority: int = 100,
) -> None:
    """Register one named handler with stable, explicit ordering."""
    ensure_event_step_pipeline(resident)

    handlers = list(getattr(resident, _PIPELINE_HANDLERS, ()))
    if any(existing_name == name for _, _, existing_name, _ in handlers):
        return

    sequence = int(getattr(resident, _PIPELINE_SEQUENCE, 0))
    handlers.append((int(priority), sequence, str(name), handler))
    handlers.sort(key=lambda item: (item[0], item[1]))
    setattr(resident, _PIPELINE_HANDLERS, handlers)
    setattr(resident, _PIPELINE_SEQUENCE, sequence + 1)


def event_step_handler_names(resident) -> tuple[str, ...]:
    """Expose stable registration order for focused composition tests."""
    return tuple(
        name
        for _priority, _sequence, name, _handler in getattr(
            resident,
            _PIPELINE_HANDLERS,
            (),
        )
    )
