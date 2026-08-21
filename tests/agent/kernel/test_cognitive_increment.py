from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.kernel import (
    CognitiveSituation,
    EmbodiedResidentRuntime,
    EventStatus,
    KernelStore,
    ModelRoute,
    WorkerResult,
    ZNKernelRuntime,
)


class _Worker:
    def __init__(self, calls: list[str], response: str):
        self.calls = calls
        self.response = response

    def run(self, goal, kernel_context):
        self.calls.append(goal.task)
        return WorkerResult(
            success=True,
            response=self.response,
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class _Factory:
    def __init__(self, calls: list[str], response: str = "borrowed insight"):
        self.calls = calls
        self.response = response

    def create(self, route):
        return _Worker(self.calls, self.response)


def _resident(db: Path, calls: list[str], response: str = "borrowed insight"):
    kernel = ZNKernelRuntime(
        store=KernelStore(db),
        routes=[
            ModelRoute(
                "primary",
                "test",
                "model",
                {"general": 0.9},
            )
        ],
        worker_factory=_Factory(calls, response),
    )
    return EmbodiedResidentRuntime(kernel=kernel)


class CognitiveIncrementTests(unittest.TestCase):
    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 16) -> None:
        for _ in range(limit):
            if resident.store.get_working_state().stage == stage:
                return
            result = resident.live_once()
            if result is not None:
                raise AssertionError(
                    f"event completed before reaching {stage}: {result}"
                )
        raise AssertionError(
            f"resident did not reach {stage}; current="
            f"{resident.store.get_working_state().stage}"
        )

    def test_external_success_becomes_increment_before_event_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []
            resident = _resident(Path(tmp) / "kernel.db", calls, "specific external insight")
            event = resident.enqueue("explain an unfamiliar concept precisely")
            self._advance_until_stage(resident, "external_cognition")

            # This pulse performs the model call. The borrowed result returns to
            # ZN's own state instead of escaping as the event result.
            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            persisted_event = resident.store.get_event(event.event_id)
            living = resident.life.snapshot()

            self.assertEqual(len(calls), 1)
            self.assertEqual(state.stage, "cognition_integration")
            self.assertEqual(persisted_event.status, EventStatus.PROCESSING)
            self.assertIsNone(resident.result_for(event.event_id))
            increment = state.data.get("cognitive_increment")
            self.assertIsInstance(increment, dict)
            self.assertEqual(increment["content"], "specific external insight")
            self.assertEqual(increment["source"], "external:primary")

            # Model success is not ZN acceptance. The impasse is still open,
            # learning has not been staged, and the knowledge profile has not
            # yet been credited by this increment.
            self.assertIsNotNone(living.current_impasse)
            self.assertEqual(living.current_impasse.event_id, event.event_id)
            self.assertEqual(living.current_impasse.status, "open")
            self.assertEqual(resident.life.recent_learning_candidates(5), [])
            before_knowledge = resident.kernel.self_model.knowledge("general")
            self.assertEqual(before_knowledge.evidence_count, 0)

            pulse = resident.pulse()
            situation = resident.life.snapshot().current_situation
            self.assertIsInstance(situation, CognitiveSituation)
            self.assertEqual(situation.working_stage, "cognition_integration")
            self.assertEqual(situation.cognitive_increment_source, "external:primary")
            self.assertEqual(pulse.thought.action_kind, "integrate_cognition")
            self.assertEqual(pulse.thought.action_target, event.event_id)

            result = resident.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(result.response, "specific external insight")
            self.assertEqual(result.model_invocations, 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result.event.status, EventStatus.COMPLETED)
            self.assertIsNotNone(resident.result_for(event.event_id))
            self.assertEqual(len(resident.life.recent_learning_candidates(5)), 1)
            self.assertIsNone(resident.life.snapshot().current_impasse)
            after_knowledge = resident.kernel.self_model.knowledge("general")
            self.assertGreater(after_knowledge.evidence_count, 0)
            resident.store.close()

    def test_restart_after_model_call_integrates_without_calling_model_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first_calls: list[str] = []
            first = _resident(db, first_calls, "increment survives restart")
            event = first.enqueue("reason about a novel restart question")
            self._advance_until_stage(first, "external_cognition")
            self.assertIsNone(first.live_once())
            state = first.store.get_working_state()
            increment_id = state.data["cognitive_increment"]["increment_id"]
            self.assertEqual(state.stage, "cognition_integration")
            self.assertEqual(len(first_calls), 1)
            self.assertIsNotNone(first.life.snapshot().current_impasse)
            self.assertEqual(first.life.recent_learning_candidates(5), [])
            first.store.close()

            second_calls: list[str] = []
            second = _resident(db, second_calls, "this must never be called")
            pulse = second.pulse()
            situation = second.life.snapshot().current_situation

            self.assertEqual(situation.active_event_id, event.event_id)
            self.assertEqual(situation.working_stage, "cognition_integration")
            self.assertEqual(situation.cognitive_increment_id, increment_id)
            self.assertEqual(pulse.thought.action_kind, "integrate_cognition")

            result = second.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(result.event.event_id, event.event_id)
            self.assertEqual(result.response, "increment survives restart")
            self.assertEqual(result.model_invocations, 1)
            self.assertEqual(second_calls, [])
            self.assertEqual(len(second.life.recent_learning_candidates(5)), 1)
            self.assertIsNone(second.life.snapshot().current_impasse)
            second.store.close()


if __name__ == "__main__":
    unittest.main()
