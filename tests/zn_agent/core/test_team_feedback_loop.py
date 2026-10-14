"""Team feedback loop: rejection feedback, no false claims, no-progress
escalation, parent auto-creation.

Regression tests for the real-model smoke findings: subdirectory proposals
died on a missing parent, rejected proposals were mis-recorded as
completion claims ("完成" in the proposal text), the model never learned
why its proposal was refused, and a run with zero evidence progress spun
for 150 pulses / 30 minutes without escalating.

Every test drives the real resident loop with a fixture cognition, the
same harness as test_team_resident_entry.py.
"""

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


def _proposal(*, objective: str, path: str, content: str) -> str:
    return json.dumps(
        {
            "zn_work_step": {
                "objective": objective,
                "action": {
                    "kind": "write_file",
                    "path": path,
                    "content": content,
                },
                "acceptance": {
                    "kind": "text_equals",
                    "path": path,
                    "expected_text": content,
                },
            }
        },
        ensure_ascii=False,
    )


class _ScriptedSpecialist:
    """Fixture cognition: scripted replies per live-specialist call."""

    def __init__(self, *, script: list[str]) -> None:
        self._script = list(script)
        self.calls = 0
        self.specialist_calls = 0
        self.questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls += 1
        if "调研-01" not in question:
            return CognitiveIncrement(
                text="继续按现有证据推进。",
                provider="fixture-cognition",
                model="team-feedback-fixture",
            )
        self.specialist_calls += 1
        self.questions.append(question)
        index = min(self.specialist_calls - 1, len(self._script) - 1)
        return CognitiveIncrement(
            text=self._script[index],
            provider="fixture-cognition",
            model="team-feedback-fixture",
        )


class TeamFeedbackLoopTests(unittest.TestCase):
    @staticmethod
    def _configure_cognition(resident, cognition) -> None:
        resident.kernel.reconfigure_resources(
            routes=[
                ModelRoute(
                    route_id="team-feedback-cognition",
                    provider="fixture",
                    model="team-feedback-fixture",
                    capabilities={
                        "general": 1.0,
                        "reasoning": 1.0,
                        "coding": 1.0,
                        "research": 1.0,
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

    def _start(self, root: Path, cognition) -> tuple:
        workspace = root / "team-workspace"
        workspace.mkdir()
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=root / "kernel.db",
        )
        self._configure_cognition(resident, cognition)
        control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
        ledger = control.ledger
        ledger.create_thread(thread_id="team-feedback", title="XX 项目")
        ledger.attach_workspace("team-feedback", workspace, name="Team Workspace")
        _, event = control.start(
            "team-feedback",
            "给 XX 项目组个团队",
            payload={
                "model_policy": "on_demand",
                "team_request": {
                    "project_title": "XX 项目",
                    "role_keys": ["researcher"],
                },
            },
        )
        return resident, ledger, event, workspace

    @staticmethod
    def _child(ledger, event):
        root = ledger.work_item_for_event(event.event_id)
        children = [
            item
            for item in ledger.list_work_items("team-feedback")
            if root is not None
            and item.parent_work_item_id == root.work_item_id
        ]
        return children[0] if children else None

    def test_rejected_proposal_feeds_back_no_false_claim_gaodingle_claims(self):
        """Fixes 2, 3, 5 (plus the prompt side of fix 1).

        Call 1: a rejected write_file proposal whose objective contains
        "完成" -- the old fall-through recorded it as a completion claim.
        Call 2: the question must carry the rejection reason, and the
        specialist proposes a valid subdirectory step. Call 3: "搞定了"
        claims the item, and the runner verifies it to completion.
        """
        rejected = _proposal(
            objective="完成调研并写出结论",
            path="../escape.md",
            content="must not be written\n",
        )
        valid = _proposal(
            objective="调研员写一份可验证的工作产物",
            path="research/notes.md",
            content="调研-01 verified step\n",
        )
        cognition = _ScriptedSpecialist(
            script=[rejected, valid, "搞定了，调研结论已写好。"]
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident, ledger, event, workspace = self._start(root, cognition)
            try:
                completed = False
                for _ in range(120):
                    resident.live_once()
                    state = resident.store.get_working_state()
                    # While the rejection for call 1 is pending, no
                    # completion claim may exist: the rejected proposal
                    # must not enter the prose claim branch.
                    if state.data.get("team_proposal_rejection"):
                        self.assertNotIn(
                            "team_completion_claim",
                            state.data,
                            "rejected proposal was recorded as a completion claim",
                        )
                    child = self._child(ledger, event)
                    if child is not None and child.status == "completed":
                        completed = True
                        break
                self.assertTrue(completed, "team item did not complete")
                self.assertGreaterEqual(
                    cognition.specialist_calls, 3, "specialist script did not run"
                )
                # Fix 2: the rejection reason reached the next call.
                self.assertGreaterEqual(len(cognition.questions), 2)
                self.assertIn("相对路径", cognition.questions[1])
                self.assertIn("REJECTED", cognition.questions[1])
                # Fix 1 (prompt side): the first question says the
                # workspace starts empty and prefers root paths.
                self.assertIn("starts EMPTY", cognition.questions[0])
                self.assertIn("workspace root", cognition.questions[0])
                # Fix 1 (product side): the valid subdirectory step was
                # written -- its missing parent was created, not rejected.
                self.assertTrue((workspace / "research" / "notes.md").is_file())
                # Boundary still holds: the escape proposal wrote nothing
                # outside the workspace.
                self.assertFalse((root / "escape.md").exists())
                # Fix 5: the "搞定了" claim completed the item through
                # verification (not claim-only).
                runs = ledger.list_worker_runs(
                    work_item_id=self._child(ledger, event).work_item_id
                )
                self.assertTrue(runs)
                self.assertEqual(runs[-1].verification_status, "verified")
            finally:
                resident.store.close()

    def test_zero_evidence_pulses_escalate(self):
        """Fix 4: N consecutive pulses with no verified evidence escalate.

        The fixture never proposes a step and never claims completion --
        every pulse produces a fresh cognition call but zero progress.
        The run must escalate after the threshold, not spin for 150
        pulses / 30 minutes.
        """
        cognition = _ScriptedSpecialist(
            script=["还在思考中，需要再看一下材料。"] * 40
        )
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, event, workspace = self._start(
                Path(tmp), cognition
            )
            try:
                terminal = None
                for _ in range(60):
                    terminal = resident.live_once()
                    # A terminalized event resets the working state to
                    # idle, so the escalation is observed on the returned
                    # terminal result, not on working-state local_failure.
                    if terminal is not None:
                        break
                self.assertIsNotNone(
                    terminal,
                    "zero-evidence run did not escalate within 60 pulses",
                )
                assert terminal is not None
                self.assertFalse(terminal.success)
                self.assertIn("连续 8", str(terminal.reason or ""))
                self.assertLessEqual(
                    cognition.calls,
                    15,
                    "escalation took too many cognition calls",
                )
            finally:
                resident.store.close()

    def test_nested_missing_parents_are_created(self):
        """Fix 1 (product side): deeply nested missing parents are created."""
        valid = _proposal(
            objective="调研员写一份可验证的工作产物",
            path="a/b/c/notes.md",
            content="调研-01 verified step\n",
        )
        cognition = _ScriptedSpecialist(script=[valid, "搞定了，调研结论已写好。"])
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, event, workspace = self._start(Path(tmp), cognition)
            try:
                completed = False
                for _ in range(120):
                    resident.live_once()
                    child = self._child(ledger, event)
                    if child is not None and child.status == "completed":
                        completed = True
                        break
                self.assertTrue(completed, "team item did not complete")
                self.assertTrue(
                    (workspace / "a" / "b" / "c" / "notes.md").is_file(),
                    "nested missing parents were not created",
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
