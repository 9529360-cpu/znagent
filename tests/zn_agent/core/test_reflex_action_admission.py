from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.reflex_intent import (
    ReflexIntentDescriptor,
    ReflexIntentRegistry,
)
from zn_agent.core.research_information_resident import (
    ResearchInformationResidentRuntime,
)


def _event(task: str):
    return SimpleNamespace(
        event_id="evt-reflex-admission",
        kind="desktop_user_event",
        task=task,
        priority=0,
        payload={},
    )


class ReflexActionAdmissionTests(unittest.TestCase):
    def test_grounded_action_candidate_precedes_memory_capability_and_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            event = _event("打开 Chrome。")
            state = WorkingState(
                current_event_id=event.event_id,
                stage="orient",
            )
            try:
                with (
                    patch.object(
                        resident.memory,
                        "recall",
                        side_effect=AssertionError("reflex must precede memory"),
                    ),
                    patch.object(
                        resident.capabilities,
                        "resolve",
                        side_effect=AssertionError("reflex must precede capability lookup"),
                    ),
                    patch.object(
                        resident.kernel,
                        "run_goal",
                        side_effect=AssertionError("reflex must not call a model"),
                    ),
                ):
                    result = resident._orient_step(
                        event,
                        state,
                        readiness=SimpleNamespace(),
                    )

                self.assertIsNone(result)
                self.assertEqual(state.stage, "native_investigation")
                self.assertEqual(
                    state.next_action,
                    "ground deterministic reflex through current machine evidence",
                )
                checkpoint = state.data["reflex_intent"]
                self.assertEqual(checkpoint["event_id"], event.event_id)
                self.assertEqual(checkpoint["intent_id"], "windows.application.open")
                self.assertEqual(checkpoint["action_id"], "windows.application.launch")
                self.assertEqual(checkpoint["body_action_kind"], "launch_application")
                self.assertEqual(checkpoint["slots"], {"application_name": "Chrome"})

                persisted = resident.store.get_working_state()
                self.assertEqual(persisted.stage, "native_investigation")
                self.assertEqual(persisted.data["reflex_intent"], checkpoint)
            finally:
                resident.store.close()

    def test_missing_action_fabric_binding_falls_through_without_reflex_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            event = _event("打开 Chrome。")
            state = WorkingState(
                current_event_id=event.event_id,
                stage="orient",
            )
            sentinel = object()
            try:
                resident.action_fabric.unregister("windows.application.launch")
                with patch.object(
                    ResearchInformationResidentRuntime,
                    "_orient_step",
                    return_value=sentinel,
                ) as fallback:
                    result = resident._orient_step(
                        event,
                        state,
                        readiness=SimpleNamespace(),
                    )

                self.assertIs(result, sentinel)
                self.assertNotIn("reflex_intent", state.data)
                fallback.assert_called_once()
            finally:
                resident.store.close()

    def test_ambiguous_reflex_falls_through_without_dispatch_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            registry = ReflexIntentRegistry()
            for intent_id in ("test.one", "test.two"):
                registry.register(
                    ReflexIntentDescriptor(
                        intent_id=intent_id,
                        description=intent_id,
                        required_slots=("application_name",),
                        action_id="windows.application.launch",
                        priority=100,
                        tags=("action_candidate", "requires_grounding"),
                    ),
                    lambda _event: {"application_name": "Chrome"},
                )
            resident.reflex_intents = registry
            event = _event("打开 Chrome。")
            state = WorkingState(
                current_event_id=event.event_id,
                stage="orient",
            )
            sentinel = object()
            try:
                with patch.object(
                    ResearchInformationResidentRuntime,
                    "_orient_step",
                    return_value=sentinel,
                ) as fallback:
                    result = resident._orient_step(
                        event,
                        state,
                        readiness=SimpleNamespace(),
                    )

                self.assertIs(result, sentinel)
                self.assertNotIn("reflex_intent", state.data)
                fallback.assert_called_once()
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
