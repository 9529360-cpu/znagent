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
from zn_agent.core.completion_verdict import render_completion_report
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.team_work_owner import EVIDENCE_KEY
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
        specialist proposes a valid subdirectory step. Call 3: a structured
        CP-3 report claims the item, and the runner verifies it to completion.
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
        # Call 3 claims with a structured CP-3 report citing the verified
        # subdirectory step for both acceptance criteria.
        claim = render_completion_report(
            conclusion="调研完成，调研结论已写好。",
            evidence=[
                ("调研结论有明确选型建议", "research/notes.md"),
                ("风险清单覆盖主要未知项", "research/notes.md"),
            ],
            files=["research/notes.md"],
            unfinished=[],
            # AS-3: the owner requires both tracks; attest DoD.
            standing_dod={
                "no_regression": {
                    "status": "not_applicable",
                    "detail": "纯调研任务，无代码变更，无回归面。",
                },
                "runtime_verified": {
                    "status": "not_applicable",
                    "detail": "纯调研任务，无需运行时验证。",
                },
                "docs": {
                    "status": "satisfied",
                    "detail": "结论已写入 research/notes.md。",
                    "evidence_ref": "research/notes.md",
                },
                "rollback": {
                    "status": "satisfied",
                    "detail": "删除 research/notes.md 即可回退。",
                },
                "approval": {
                    "status": "satisfied",
                    "detail": "无破坏性/外部动作，无需审批。",
                },
            },
        )
        cognition = _ScriptedSpecialist(script=[rejected, valid, claim])
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
                # Fix 5: the structured claim completed the item through
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

    def test_identical_rewrite_escalates(self):
        """P1b: byte-identical content rewritten twice escalates.

        Regression for the real-model smoke rewrite loop: every
        rewrite produced fresh verified evidence, so the no-evidence
        counter never fired while the run made zero progress.

        Unit-level on purpose: driving two identical verified
        evidence entries through the full loop is blocked by two
        pre-existing interactions (recorded as follow-ups, not
        fixed here): identical write_file rewrites are
        short-circuited by the generic overwrite-recovery layer,
        and the team run_python path ends in investigation
        completion without evidence (verified on clean main).
        The same-objective rule below IS proven through the loop.
        """
        cognition = _ScriptedSpecialist(script=["还在思考中。"] * 40)
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, event, workspace = self._start(
                Path(tmp), cognition
            )
            try:
                run_id = None
                for _ in range(20):
                    resident.live_once()
                    child = self._child(ledger, event)
                    if child is not None:
                        runs = ledger.list_worker_runs(
                            work_item_id=child.work_item_id
                        )
                        if runs:
                            run_id = runs[0].worker_run_id
                            break
                self.assertIsNotNone(run_id, "no WorkerRun dispatched")
                assert run_id is not None

                def _evidence(entries):
                    return [
                        {
                            "objective": objective,
                            "relative_path": path,
                            "content_hash": content_hash,
                            "verified": True,
                        }
                        for objective, path, content_hash in entries
                    ]

                # Identical (objective, path, hash) twice -> escalate.
                ledger.update_worker_run_metrics(
                    run_id,
                    metrics={
                        EVIDENCE_KEY: _evidence(
                            [
                                ("写 app.py", "app.py", "abc123"),
                                ("写 app.py", "app.py", "abc123"),
                            ]
                        )
                    },
                )
                reason = resident._check_rewrite_loop(run_id=run_id)
                assert reason is not None
                self.assertIn("重复提交相同内容", reason)

                # Same content, different paths -> not a rewrite.
                ledger.update_worker_run_metrics(
                    run_id,
                    metrics={
                        EVIDENCE_KEY: _evidence(
                            [
                                ("写文件", "a.py", "abc123"),
                                ("写文件", "b.py", "abc123"),
                            ]
                        )
                    },
                )
                self.assertIsNone(resident._check_rewrite_loop(run_id=run_id))

                # Same (objective, path) 4x, different content -> escalate.
                ledger.update_worker_run_metrics(
                    run_id,
                    metrics={
                        EVIDENCE_KEY: _evidence(
                            [
                                ("写 app.py", "app.py", f"hash{i}")
                                for i in range(4)
                            ]
                        )
                    },
                )
                reason = resident._check_rewrite_loop(run_id=run_id)
                assert reason is not None
                self.assertIn("同一目标重复执行 4 次", reason)

                # Same (objective, path) 3x, different content -> no fire.
                ledger.update_worker_run_metrics(
                    run_id,
                    metrics={
                        EVIDENCE_KEY: _evidence(
                            [
                                ("写 app.py", "app.py", f"hash{i}")
                                for i in range(3)
                            ]
                        )
                    },
                )
                self.assertIsNone(resident._check_rewrite_loop(run_id=run_id))
            finally:
                resident.store.close()

    def test_same_objective_loop_escalates(self):
        """P1b: same (objective, path) four times, any content, escalates."""
        script = [
            _proposal(
                objective="开发员写一份可验证的工作产物",
                path="app.py",
                content=f"version {index}\n",
            )
            for index in range(4)
        ]
        cognition = _ScriptedSpecialist(script=script)
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, event, workspace = self._start(
                Path(tmp), cognition
            )
            try:
                terminal = None
                for _ in range(60):
                    terminal = resident.live_once()
                    if terminal is not None:
                        break
                self.assertIsNotNone(
                    terminal, "same-objective loop did not escalate"
                )
                assert terminal is not None
                self.assertFalse(terminal.success)
                self.assertIn("同一目标重复执行 4 次", str(terminal.reason or ""))
                self.assertLessEqual(
                    cognition.calls, 10, "escalation took too many calls"
                )
            finally:
                resident.store.close()

    def test_repeated_steps_then_claim_completes(self):
        """P1b negative: 3 same-objective steps with different content
        do NOT escalate; a structured claim then completes the item."""
        script = [
            _proposal(
                objective="调研员写一份可验证的工作产物",
                path="research/notes.md",
                content=f"draft {index}\n",
            )
            for index in range(3)
        ]
        script.append(
            render_completion_report(
                conclusion="调研完成，调研结论已写好。",
                evidence=[
                    ("调研结论有明确选型建议", "research/notes.md"),
                    ("风险清单覆盖主要未知项", "research/notes.md"),
                ],
                files=["research/notes.md"],
                unfinished=[],
                # AS-3: the owner requires both tracks; attest DoD.
                standing_dod={
                    "no_regression": {
                        "status": "not_applicable",
                        "detail": "纯调研任务，无代码变更，无回归面。",
                    },
                    "runtime_verified": {
                        "status": "not_applicable",
                        "detail": "纯调研任务，无需运行时验证。",
                    },
                    "docs": {
                        "status": "satisfied",
                        "detail": "结论已写入 research/notes.md。",
                        "evidence_ref": "research/notes.md",
                    },
                    "rollback": {
                        "status": "satisfied",
                        "detail": "删除 research/notes.md 即可回退。",
                    },
                    "approval": {
                        "status": "satisfied",
                        "detail": "无破坏性/外部动作，无需审批。",
                    },
                },
            )
        )
        cognition = _ScriptedSpecialist(script=script)
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, event, workspace = self._start(
                Path(tmp), cognition
            )
            try:
                completed = False
                terminal = None
                for _ in range(120):
                    terminal = resident.live_once()
                    child = self._child(ledger, event)
                    if child is not None and child.status == "completed":
                        completed = True
                        break
                    if terminal is not None:
                        break
                self.assertTrue(completed, "item did not complete")
                self.assertIsNone(
                    terminal, "repeated steps wrongly escalated"
                )
            finally:
                resident.store.close()
        """Fix 1 (product side): deeply nested missing parents are created."""
        valid = _proposal(
            objective="调研员写一份可验证的工作产物",
            path="a/b/c/notes.md",
            content="调研-01 verified step\n",
        )
        claim = render_completion_report(
            conclusion="调研完成，调研结论已写好。",
            evidence=[
                ("调研结论有明确选型建议", "a/b/c/notes.md"),
                ("风险清单覆盖主要未知项", "a/b/c/notes.md"),
            ],
            files=["a/b/c/notes.md"],
            unfinished=[],
            # AS-3: the owner requires both tracks; attest DoD.
            standing_dod={
                "no_regression": {
                    "status": "not_applicable",
                    "detail": "纯调研任务，无代码变更，无回归面。",
                },
                "runtime_verified": {
                    "status": "not_applicable",
                    "detail": "纯调研任务，无需运行时验证。",
                },
                "docs": {
                    "status": "satisfied",
                    "detail": "结论已写入 a/b/c/notes.md。",
                    "evidence_ref": "a/b/c/notes.md",
                },
                "rollback": {
                    "status": "satisfied",
                    "detail": "删除 a/b/c/notes.md 即可回退。",
                },
                "approval": {
                    "status": "satisfied",
                    "detail": "无破坏性/外部动作，无需审批。",
                },
            },
        )
        cognition = _ScriptedSpecialist(script=[valid, claim])
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
