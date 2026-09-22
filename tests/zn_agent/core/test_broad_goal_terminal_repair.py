from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


class _RepairSequenceCognition:
    """Deterministic Broad-step cognition; all execution remains real."""

    _BROAD_STEP_MARKER = "You are a bounded coding/reasoning resource assisting one durable ZN Work."

    def __init__(self) -> None:
        self.calls = 0
        self.step_calls = 0
        self.questions: list[str] = []
        self.step_questions: list[str] = []

    @staticmethod
    def _write(content: str, objective: str) -> str:
        return json.dumps(
            {
                "zn_work_step": {
                    "objective": objective,
                    "action": {
                        "kind": "write_file",
                        "path": "probe.py",
                        "content": content,
                    },
                    "acceptance": {
                        "kind": "text_equals",
                        "path": "probe.py",
                        "expected_text": content,
                    },
                }
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _run(objective: str) -> str:
        return json.dumps(
            {
                "zn_work_step": {
                    "objective": objective,
                    "action": {
                        "kind": "run_python",
                        "path": "probe.py",
                        "args": [],
                    },
                    "acceptance": {
                        "kind": "command",
                        "expected_exit_code": 0,
                        "output_contains": ["READY"],
                    },
                }
            },
            ensure_ascii=False,
        )

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls += 1
        self.questions.append(question)

        # The real Resident may borrow cognition for earlier language/goal
        # understanding before it reaches the Broad rolling-step impasse. Those
        # calls must not consume the deterministic write/run repair sequence.
        if self._BROAD_STEP_MARKER not in question:
            return CognitiveIncrement(
                text="Use the attached workspace and continue with the user's stated objective.",
                provider="fixture-cognition",
                model="bounded-repair-fixture",
            )

        self.step_calls += 1
        self.step_questions.append(question)
        if self.step_calls == 1:
            text = self._write(
                'raise RuntimeError("boom-first")\n',
                "create a deliberately failing local probe so execution feedback is observable",
            )
        elif self.step_calls == 2:
            text = self._run("execute the current probe and require the READY contract")
        elif self.step_calls == 3:
            text = self._write(
                'print("READY")\n',
                "repair the probe using the real execution failure as evidence",
            )
        else:
            text = self._run("rerun the repaired probe and verify READY")
        return CognitiveIncrement(
            text=text,
            provider="fixture-cognition",
            model="bounded-repair-fixture",
        )


class BroadGoalTerminalRepairTests(unittest.TestCase):
    def test_real_python_failure_returns_to_cognition_then_repairs_and_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            try:
                cognition = _RepairSequenceCognition()
                resident.kernel.reconfigure_resources(
                    routes=[
                        ModelRoute(
                            route_id="broad-goal-repair-cognition",
                            provider="fixture",
                            model="bounded-repair-fixture",
                            capabilities={
                                "general": 1.0,
                                "reasoning": 1.0,
                                "coding": 1.0,
                                "language_understanding": 1.0,
                            },
                        )
                    ],
                    worker_factory=CognitiveResourceWorkerFactory(
                        resource_builder=lambda _route: cognition,
                    ),
                    max_attempts=1,
                    resource_status={"available": True, "error": None},
                )
                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
                ledger = control.ledger
                ledger.create_thread(thread_id="repair-loop", title="Repair loop")
                ledger.attach_workspace("repair-loop", workspace, name="Repair Workspace")
                _, event = control.start(
                    "repair-loop",
                    "Create a tiny local Python artifact, execute it, and recover from real failures until its contract passes.",
                    payload={"model_policy": "on_demand"},
                    acceptance_criteria=[
                        "a later product-level verifier still has to accept the Root Work",
                    ],
                )
                root_item = ledger.work_item_for_event(event.event_id)
                self.assertIsNotNone(root_item)
                assert root_item is not None

                terminal = None
                for _ in range(160):
                    candidate = resident.live_once()
                    if candidate is not None and candidate.event.event_id == event.event_id:
                        terminal = candidate
                        break
                    children = [
                        item
                        for item in ledger.list_work_items("repair-loop")
                        if item.parent_work_item_id == root_item.work_item_id
                    ]
                    completed_runs = [
                        item
                        for item in children
                        if item.status == "completed"
                        and any(
                            criterion.startswith("command_exit:")
                            for criterion in item.acceptance_criteria
                        )
                    ]
                    blocked_runs = [
                        item
                        for item in children
                        if item.status == "blocked"
                        and any(
                            criterion.startswith("command_exit:")
                            for criterion in item.acceptance_criteria
                        )
                    ]
                    if completed_runs and blocked_runs and cognition.step_calls >= 4:
                        break

                self.assertIsNone(
                    terminal,
                    "one repaired coding loop must not terminally accept the broad Root Work",
                )
                self.assertGreaterEqual(cognition.step_calls, 4)
                self.assertGreaterEqual(len(cognition.step_questions), 3)
                self.assertIn(
                    "boom-first",
                    cognition.step_questions[2],
                    "the repair cognition never received the real failing process output",
                )
                self.assertIn(
                    "exit_code",
                    cognition.step_questions[2],
                    "the repair cognition never received the real failing process exit evidence",
                )

                self.assertEqual(
                    (workspace / "probe.py").read_text(encoding="utf-8"),
                    'print("READY")\n',
                )
                children = [
                    item
                    for item in ledger.list_work_items("repair-loop")
                    if item.parent_work_item_id == root_item.work_item_id
                ]
                blocked = [item for item in children if item.status == "blocked"]
                completed = [item for item in children if item.status == "completed"]
                self.assertEqual(len(children), 4)
                self.assertEqual(len(blocked), 1)
                self.assertEqual(len(completed), 3)
                self.assertIn("command exited with code", blocked[0].blocker or "")
                self.assertIn("boom-first", blocked[0].blocker or "")
                self.assertTrue(
                    any("READY" in (item.result or "") for item in completed),
                    "the repaired real command was never independently accepted",
                )

                root_after = ledger.work_item_for_event(event.event_id)
                self.assertIsNotNone(root_after)
                assert root_after is not None
                self.assertNotEqual(root_after.status, "completed")
                self.assertEqual(
                    resident.store.get_working_state().stage,
                    "native_deliberation",
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
