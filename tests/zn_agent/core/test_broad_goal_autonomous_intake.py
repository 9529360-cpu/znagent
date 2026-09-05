from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.broad_goal_autonomous_resident import BroadGoalAutonomousResidentRuntime
from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


GOAL = (
    "Build a tiny local reading-list product. Keep the first version simple, make it genuinely runnable, "
    "and make sure saved items are still there after restarting it."
)
CRITERIA = [
    "The first version can be started and used through a real local runtime path.",
    "A user can add at least one reading-list item and observe it in the product.",
    "An item saved in one process is still observable from a newly started process.",
]


class _IntakeCognition:
    MARKER = "Before any execution, define the Root acceptance contract."

    def __init__(self, *, malformed: bool = False) -> None:
        self.malformed = malformed
        self.intake_questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        if self.MARKER in question:
            self.intake_questions.append(question)
            text = (
                "I think it is done"
                if self.malformed
                else json.dumps({"zn_root_acceptance": {"criteria": CRITERIA}})
            )
        else:
            text = "Continue the current durable objective without claiming completion."
        return CognitiveIncrement(text=text, provider="fixture", model="autonomous-intake-fixture")


def _configure(resident, cognition) -> None:
    resident.kernel.reconfigure_resources(
        routes=[
            ModelRoute(
                route_id="autonomous-intake-fixture",
                provider="fixture",
                model="autonomous-intake-fixture",
                capabilities={
                    "general": 1.0,
                    "reasoning": 1.0,
                    "coding": 1.0,
                    "language_understanding": 1.0,
                },
            )
        ],
        worker_factory=CognitiveResourceWorkerFactory(resource_builder=lambda _route: cognition),
        max_attempts=1,
        resource_status={"available": True, "error": None},
    )


class BroadGoalAutonomousIntakeTests(unittest.TestCase):
    def _start(self, root: Path, cognition: _IntakeCognition):
        workspace = root / "workspace"
        workspace.mkdir()
        resident = build_resident_runtime(config={"model": {}}, store_path=root / "kernel.db")
        self.assertIsInstance(resident, BroadGoalAutonomousResidentRuntime)
        _configure(resident, cognition)
        control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
        ledger = control.ledger
        ledger.create_thread(thread_id="autonomous-root", title="Autonomous Root")
        ledger.attach_workspace("autonomous-root", workspace, name="Autonomous Workspace")
        _, event = control.start(
            "autonomous-root",
            GOAL,
            payload={"model_policy": "on_demand"},
        )
        return resident, ledger, event, workspace

    def test_root_acceptance_is_formed_from_goal_before_any_workspace_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cognition = _IntakeCognition()
            resident, ledger, event, workspace = self._start(Path(tmp), cognition)
            try:
                initial = ledger.work_item_for_event(event.event_id)
                self.assertIsNotNone(initial)
                assert initial is not None
                self.assertEqual(initial.acceptance_criteria, [])
                self.assertEqual(list(workspace.iterdir()), [])

                persisted = None
                for _ in range(96):
                    terminal = resident.live_once()
                    self.assertIsNone(terminal, "acceptance formation must not terminalize the Root Work")
                    candidate = ledger.work_item_for_event(event.event_id)
                    if candidate is not None and candidate.acceptance_criteria:
                        persisted = candidate
                        break

                self.assertIsNotNone(persisted)
                assert persisted is not None
                self.assertEqual(persisted.acceptance_criteria, CRITERIA)
                self.assertEqual(list(workspace.iterdir()), [], "intake must define success before execution")
                self.assertEqual(len(cognition.intake_questions), 1)
                self.assertIn(GOAL, cognition.intake_questions[0])
                state = resident.store.get_working_state()
                self.assertEqual(state.stage, "native_deliberation")
                self.assertEqual(state.data["autonomous_root_acceptance"]["criteria"], CRITERIA)
            finally:
                resident.store.close()

    def test_unstructured_intake_cannot_become_model_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cognition = _IntakeCognition(malformed=True)
            resident, ledger, event, workspace = self._start(Path(tmp), cognition)
            try:
                terminal = None
                for _ in range(96):
                    terminal = resident.live_once()
                    state = resident.store.get_working_state()
                    if cognition.intake_questions and "rejected broad-goal intake" in str(
                        state.data.get("local_failure") or ""
                    ):
                        break
                self.assertIsNone(terminal)
                root = ledger.work_item_for_event(event.event_id)
                self.assertIsNotNone(root)
                assert root is not None
                self.assertEqual(root.acceptance_criteria, [])
                self.assertNotEqual(root.status, "completed")
                self.assertEqual(list(workspace.iterdir()), [])
                self.assertIn(
                    "rejected broad-goal intake",
                    str(resident.store.get_working_state().data.get("local_failure") or ""),
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
