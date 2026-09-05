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


class _RepairingCognition:
    _BROAD_MARKER = "You are a bounded coding/reasoning resource assisting one durable ZN Work."

    def __init__(self, criteria: list[str]) -> None:
        self.criteria = list(criteria)
        self.step_calls = 0
        self.questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        if self._BROAD_MARKER not in question and "Repair the immediately previous bounded ZN Work protocol" not in question:
            return CognitiveIncrement(
                text="Continue the durable workspace objective.",
                provider="fixture",
                model="protocol-repair-fixture",
            )
        self.step_calls += 1
        self.questions.append(question)
        if self.step_calls == 1:
            proposal = {
                "zn_work_step": {
                    "objective": "create a runnable probe",
                    "action": {
                        "kind": "write_file",
                        "path": "probe.py",
                        "content": 'print("READY")\n',
                    },
                    "acceptance": {"kind": "file_exists", "path": "probe.py"},
                }
            }
        elif self.step_calls == 2:
            proposal = {
                "zn_work_step": {
                    "objective": "repair the rejected write contract",
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
        elif self.step_calls == 3:
            proposal = {
                "zn_work_step": {
                    "objective": "run the repaired probe",
                    "action": {"kind": "run_python", "path": "probe.py", "args": []},
                    "acceptance": {
                        "kind": "command",
                        "expected_exit_code": 0,
                        "output_contains": ["READY"],
                    },
                }
            }
        else:
            proposal = {
                "zn_work_step": {
                    "objective": "independently verify the repaired probe",
                    "action": {"kind": "verify_python", "path": "probe.py", "args": []},
                    "acceptance": {
                        "kind": "root_verified",
                        "criteria": list(self.criteria),
                        "expected_exit_code": 0,
                        "output_contains": ["READY"],
                    },
                }
            }
        return CognitiveIncrement(
            text=json.dumps(proposal),
            provider="fixture",
            model="protocol-repair-fixture",
        )


class BroadGoalProtocolRepairTests(unittest.TestCase):
    def test_contract_mismatch_gets_precise_stateful_retry_and_then_executes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            criteria = [
                "a runnable artifact exists in the workspace",
                "a fresh process demonstrates the expected READY behavior",
            ]
            kernel = build_runtime(config={"model": {}}, store_path=root / "kernel.db")
            resident = BroadGoalCompletionResidentRuntime(
                kernel=kernel,
                budget=CognitiveBudgetManager(),
            )
            cognition = _RepairingCognition(criteria)
            resident.kernel.reconfigure_resources(
                routes=[
                    ModelRoute(
                        route_id="protocol-repair-fixture",
                        provider="fixture",
                        model="protocol-repair-fixture",
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
            control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
            ledger = control.ledger
            ledger.create_thread(thread_id="protocol-repair", title="Protocol repair")
            ledger.attach_workspace("protocol-repair", workspace, name="Protocol Repair Workspace")
            _, event = control.start(
                "protocol-repair",
                "Create and independently verify one tiny runnable local artifact.",
                payload={"model_policy": "on_demand"},
                acceptance_criteria=criteria,
            )
            try:
                terminal = None
                for _ in range(280):
                    candidate = resident.live_once()
                    if candidate is not None and candidate.event.event_id == event.event_id:
                        terminal = candidate
                        break
                self.assertIsNotNone(terminal)
                assert terminal is not None
                self.assertTrue(terminal.success)
                self.assertEqual(terminal.execution_path.value, "body")
                self.assertEqual(cognition.step_calls, 4)
                self.assertGreaterEqual(len(cognition.questions), 2)
                repair_question = cognition.questions[1]
                self.assertIn(
                    "Repair the immediately previous bounded ZN Work protocol proposal",
                    repair_question,
                )
                self.assertIn(
                    "write_file requires acceptance.kind=text_equals",
                    repair_question,
                )
                self.assertIn("Previous rejected proposal", repair_question)
                self.assertIn('"kind": "file_exists"', repair_question)
                self.assertIn("Do not use markdown fences", repair_question)
                self.assertEqual(
                    (workspace / "probe.py").read_text(encoding="utf-8"),
                    'print("READY")\n',
                )
                state = resident.store.get_working_state()
                self.assertNotIn(resident._PROTOCOL_REPAIR_KEY, state.data)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
