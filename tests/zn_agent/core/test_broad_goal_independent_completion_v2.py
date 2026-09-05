from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.broad_goal_completion_resident import BroadGoalCompletionResidentRuntime
from zn_agent.core.budget import CognitiveBudgetManager
from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


class _CompletionCognition:
    _BROAD_MARKER = "You are a bounded coding/reasoning resource assisting one durable ZN Work."

    def __init__(
        self,
        criteria: list[str],
        *,
        weaken_final: bool = False,
        malformed_final: bool = False,
    ) -> None:
        self.criteria = criteria
        self.weaken_final = weaken_final
        self.malformed_final = malformed_final
        self.step_calls = 0
        self.step_questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        if self._BROAD_MARKER not in question:
            return CognitiveIncrement(
                text="Continue the durable workspace objective.",
                provider="fixture",
                model="completion-fixture",
            )
        self.step_calls += 1
        self.step_questions.append(question)
        if self.step_calls == 1:
            proposal = {
                "zn_work_step": {
                    "objective": "create a tiny runnable probe",
                    "action": {
                        "kind": "write_file",
                        "path": "probe.py",
                        "content": 'print("READY")\n',
                    },
                    "acceptance": {
                        "kind": "text_equals",
                        "path": "probe.py",
                        "expected_text": 'print("READY")\n',
                    },
                }
            }
            text = json.dumps(proposal)
        elif self.step_calls == 2:
            proposal = {
                "zn_work_step": {
                    "objective": "run the workspace probe",
                    "action": {"kind": "run_python", "path": "probe.py", "args": []},
                    "acceptance": {
                        "kind": "command",
                        "expected_exit_code": 0,
                        "output_contains": ["READY"],
                    },
                }
            }
            text = json.dumps(proposal)
        elif self.malformed_final:
            text = """```json
{
  \"zn_work_step\": {
    \"objective\": \"independently verify the runnable artifact\",
    \"action\": {\"kind\": \"verify_python\", \"path\": \"probe.py\", \"args\": []},
    \"acceptance\": {
      \"kind\": \"root_verified\",
      \"criteria\": [\"copy every Root acceptance criterion exactly\", \"output_contains\": [\"READY\"]],
      \"expected_exit_code\": 0,
      \"output_contains\": [\"READY\"]
    }
  }
}
```"""
        else:
            final_criteria = ["weakened criterion"] if self.weaken_final else list(self.criteria)
            proposal = {
                "zn_work_step": {
                    "objective": "independently execute the current runnable artifact",
                    "action": {"kind": "verify_python", "path": "probe.py", "args": []},
                    "acceptance": {
                        "kind": "root_verified",
                        "criteria": final_criteria,
                        "expected_exit_code": 0,
                        "output_contains": ["READY"],
                    },
                }
            }
            text = json.dumps(proposal)
        return CognitiveIncrement(
            text=text,
            provider="fixture",
            model="completion-fixture",
        )


class BroadGoalIndependentCompletionV2Tests(unittest.TestCase):
    @staticmethod
    def _configure(resident, cognition) -> None:
        resident.kernel.reconfigure_resources(
            routes=[
                ModelRoute(
                    route_id="completion-fixture",
                    provider="fixture",
                    model="completion-fixture",
                    capabilities={
                        "general": 1.0,
                        "reasoning": 1.0,
                        "coding": 1.0,
                        "language_understanding": 1.0,
                    },
                )
            ],
            worker_factory=CognitiveResourceWorkerFactory(
                resource_builder=lambda _route: cognition
            ),
            max_attempts=1,
            resource_status={"available": True, "error": None},
        )

    def _start(
        self,
        root: Path,
        *,
        weaken_final: bool = False,
        malformed_final: bool = False,
    ):
        criteria = [
            "a runnable artifact exists in the workspace",
            "a fresh process demonstrates the expected READY behavior",
        ]
        workspace = root / "workspace"
        workspace.mkdir()
        kernel = build_runtime(config={"model": {}}, store_path=root / "kernel.db")
        resident = BroadGoalCompletionResidentRuntime(
            kernel=kernel,
            budget=CognitiveBudgetManager(),
        )
        cognition = _CompletionCognition(
            criteria,
            weaken_final=weaken_final,
            malformed_final=malformed_final,
        )
        self._configure(resident, cognition)
        control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
        ledger = control.ledger
        ledger.create_thread(thread_id="completion-loop", title="Completion loop")
        ledger.attach_workspace("completion-loop", workspace, name="Completion Workspace")
        _, event = control.start(
            "completion-loop",
            "Create and independently verify one tiny runnable local artifact.",
            payload={"model_policy": "on_demand"},
            acceptance_criteria=criteria,
        )
        root_item = ledger.work_item_for_event(event.event_id)
        self.assertIsNotNone(root_item)
        return resident, cognition, ledger, event, root_item, workspace

    def test_separate_verifier_work_item_can_accept_current_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, cognition, ledger, event, root_item, workspace = self._start(Path(tmp))
            try:
                terminal = None
                for _ in range(220):
                    candidate = resident.live_once()
                    if candidate is not None and candidate.event.event_id == event.event_id:
                        terminal = candidate
                        break
                self.assertIsNotNone(terminal)
                assert terminal is not None
                self.assertTrue(terminal.success)
                self.assertEqual(terminal.execution_path.value, "body")
                self.assertGreaterEqual(cognition.step_calls, 3)
                self.assertEqual(
                    (workspace / "probe.py").read_text(encoding="utf-8"),
                    'print("READY")\n',
                )
                self.assertIn(
                    "Final Root verification is NOT available yet",
                    cognition.step_questions[0],
                )
                self.assertNotIn(
                    '"action":{"kind":"verify_python"',
                    cognition.step_questions[0],
                )
                self.assertIn(
                    "current plan now has a completed real Terminal execution",
                    cognition.step_questions[-1],
                )
                self.assertIn(
                    '"action":{"kind":"verify_python"',
                    cognition.step_questions[-1],
                )

                root_after = ledger.work_item_for_event(event.event_id)
                self.assertIsNotNone(root_after)
                assert root_after is not None
                self.assertEqual(root_after.status, "completed")
                self.assertIn("zn_independent_acceptance", root_after.result or "")
                children = [
                    item
                    for item in ledger.list_work_items("completion-loop")
                    if item.parent_work_item_id == root_item.work_item_id
                ]
                self.assertEqual(len(children), 3)
                self.assertTrue(all(item.status == "completed" for item in children))
                verifiers = [
                    item for item in children
                    if any(
                        criterion.startswith("independent_python_verification:")
                        for criterion in item.acceptance_criteria
                    )
                ]
                self.assertEqual(len(verifiers), 1)
                self.assertIn("READY", verifiers[0].result or "")
                progress = ledger.progress("completion-loop", event.event_id)
                self.assertTrue(progress.get("accepted"))
                self.assertFalse(progress.get("acceptance_pending"))
            finally:
                resident.store.close()

    def test_weakened_root_criteria_is_rejected_without_model_terminalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, cognition, ledger, event, root_item, _workspace = self._start(
                Path(tmp), weaken_final=True
            )
            try:
                terminal = None
                for _ in range(220):
                    candidate = resident.live_once()
                    if candidate is not None and candidate.event.event_id == event.event_id:
                        terminal = candidate
                        break
                    state = resident.store.get_working_state()
                    if (
                        cognition.step_calls >= 3
                        and "rejected the proposed Broad Work step"
                        in str(state.data.get("local_failure") or "")
                    ):
                        break
                self.assertIsNone(
                    terminal,
                    "malformed structured completion must not fall through to generic MODEL completion",
                )
                root_after = ledger.work_item_for_event(event.event_id)
                self.assertIsNotNone(root_after)
                assert root_after is not None
                self.assertNotEqual(root_after.status, "completed")
                self.assertIn(
                    "rejected the proposed Broad Work step",
                    str(resident.store.get_working_state().data.get("local_failure") or ""),
                )
                children = [
                    item
                    for item in ledger.list_work_items("completion-loop")
                    if item.parent_work_item_id == root_item.work_item_id
                ]
                self.assertFalse(
                    any(
                        any(
                            criterion.startswith("independent_python_verification:")
                            for criterion in item.acceptance_criteria
                        )
                        for item in children
                    )
                )
            finally:
                resident.store.close()

    def test_malformed_work_protocol_is_repaired_instead_of_model_terminalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, cognition, ledger, event, root_item, _workspace = self._start(
                Path(tmp), malformed_final=True
            )
            try:
                terminal = None
                for _ in range(240):
                    candidate = resident.live_once()
                    if candidate is not None and candidate.event.event_id == event.event_id:
                        terminal = candidate
                        break
                    state = resident.store.get_working_state()
                    if (
                        cognition.step_calls >= 3
                        and "ZN rejected the proposed Broad Work step"
                        in str(state.data.get("local_failure") or "")
                    ):
                        break
                self.assertIsNone(
                    terminal,
                    "protocol-shaped invalid JSON must remain in the Broad Work repair loop",
                )
                state = resident.store.get_working_state()
                self.assertEqual(state.stage, "native_investigation")
                self.assertIn(
                    "ZN rejected the proposed Broad Work step",
                    str(state.data.get("local_failure") or ""),
                )
                root_after = ledger.work_item_for_event(event.event_id)
                self.assertIsNotNone(root_after)
                assert root_after is not None
                self.assertNotEqual(root_after.status, "completed")
                children = [
                    item
                    for item in ledger.list_work_items("completion-loop")
                    if item.parent_work_item_id == root_item.work_item_id
                ]
                self.assertEqual(len(children), 2)
                self.assertTrue(all(item.status == "completed" for item in children))
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
