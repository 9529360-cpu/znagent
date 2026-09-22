from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.event_step_pipeline import (
    EventStepDecision,
    event_step_handler_names,
    register_event_step_handler,
)


class _Resident:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _advance_event_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        del event, state, readiness, learning_evidence, thought
        self.calls.append("fallback")
        return "fallback"


class EventStepPipelineTests(unittest.TestCase):
    def test_handlers_run_by_priority_then_registration_order(self) -> None:
        resident = _Resident()

        def late(*_args, **_kwargs):
            resident.calls.append("late")
            return None

        def first(*_args, **_kwargs):
            resident.calls.append("first")
            return None

        def second(*_args, **_kwargs):
            resident.calls.append("second")
            return EventStepDecision.claim("handled")

        register_event_step_handler(
            resident,
            name="late",
            handler=late,
            priority=30,
        )
        register_event_step_handler(
            resident,
            name="first",
            handler=first,
            priority=10,
        )
        register_event_step_handler(
            resident,
            name="second",
            handler=second,
            priority=10,
        )

        result = resident._advance_event_step(
            SimpleNamespace(),
            SimpleNamespace(),
            readiness=SimpleNamespace(),
            learning_evidence=[],
        )

        self.assertEqual(result, "handled")
        self.assertEqual(resident.calls, ["first", "second"])
        self.assertEqual(
            event_step_handler_names(resident),
            ("first", "second", "late"),
        )

    def test_claimed_none_does_not_fall_through(self) -> None:
        resident = _Resident()

        def handler(*_args, **_kwargs):
            resident.calls.append("handler")
            return EventStepDecision.claim(None)

        register_event_step_handler(
            resident,
            name="claim-none",
            handler=handler,
        )

        result = resident._advance_event_step(
            SimpleNamespace(),
            SimpleNamespace(),
            readiness=SimpleNamespace(),
            learning_evidence=[],
        )

        self.assertIsNone(result)
        self.assertEqual(resident.calls, ["handler"])

    def test_duplicate_name_is_idempotent(self) -> None:
        resident = _Resident()

        def handler(*_args, **_kwargs):
            return None

        register_event_step_handler(resident, name="same", handler=handler)
        register_event_step_handler(resident, name="same", handler=handler)

        self.assertEqual(event_step_handler_names(resident), ("same",))


if __name__ == "__main__":
    unittest.main()
