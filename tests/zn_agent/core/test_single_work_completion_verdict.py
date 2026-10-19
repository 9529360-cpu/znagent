"""M-5: CP-3 completion verdict reused for single (non-team) Work.

The same adjudicator as the team path gates single-Work Root
acceptance (``accept_root_with_current_evidence``): a verifier pass
alone never accepts a Root -- the claim must be a structured
completion report citing every Root acceptance criterion against the
completed children's Body-verified evidence, plus the standing DoD.
``partial`` / ``rejected`` feed reason + missing list + actionable fix
back for a bounded retry; two identical rejections escalate at once.

Ledger tests drive ``accept_root_with_current_evidence`` directly
(children materialized through the ledger, no cognition). Resident
tests drive the real loop: verifier pass -> report round -> verdict.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.broad_goal_completion_resident import (
    BroadGoalCompletionResidentRuntime,
)
from zn_agent.core.budget import CognitiveBudgetManager
from zn_agent.core.cognitive_resource import (
    CognitiveIncrement,
    CognitiveResourceWorkerFactory,
)
from zn_agent.core.completion_verdict import (
    CompletionVerdictError,
    render_completion_report,
)
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_restore_control import RestoreAwareWorkControl

CRITERIA = [
    "a runnable artifact exists in the workspace",
    "a fresh process demonstrates the expected READY behavior",
]


def _dod(*, ref: str = "probe.py") -> dict[str, dict[str, str]]:
    return {
        "no_regression": {
            "status": "satisfied",
            "detail": "只新增 probe.py / state.json，未动其他文件。",
            "evidence_ref": ref,
        },
        "runtime_verified": {
            "status": "satisfied",
            "detail": "独立验证器进程实际运行并输出 READY。",
            "evidence_ref": "READY",
        },
        "docs": {
            "status": "satisfied",
            "detail": "小探针无面向用户的文档面，结果记在 Work 线程。",
        },
        "rollback": {
            "status": "satisfied",
            "detail": "删除 probe.py 与 state.json 即可回退。",
        },
        "approval": {
            "status": "satisfied",
            "detail": "仅本地工作区写入，无需审批。",
        },
    }


def _full_report() -> str:
    return render_completion_report(
        conclusion="可运行产物已独立验证通过。",
        evidence=[
            (CRITERIA[0], "probe.py"),
            (CRITERIA[1], "READY"),
        ],
        files=["probe.py", "state.json"],
        unfinished=[],
        standing_dod=_dod(),
    )


def _partial_report() -> str:
    """Cites only the first criterion: a partial verdict with one missing."""
    return render_completion_report(
        conclusion="产物写好了，行为还没引证据。",
        evidence=[(CRITERIA[0], "probe.py")],
        files=["probe.py"],
        unfinished=[],
        standing_dod=_dod(),
    )


class SingleWorkEvidenceEntriesTests(unittest.TestCase):
    """Evidence builder: completed children -> adjudicator entries."""

    def test_page_read_url_keeps_its_scheme(self):
        from zn_agent.core.evidence_bound_work import single_work_evidence_entries
        from zn_agent.core.steerable_work import WorkItem

        entries = single_work_evidence_entries(
            [
                WorkItem(
                    work_item_id="item-1",
                    work_thread_id="t",
                    title="read",
                    objective="read the spec page",
                    status="completed",
                    plan_version=1,
                    acceptance_criteria=["page_read: https://example.com/spec"],
                    result="page read",
                ),
                WorkItem(
                    work_item_id="item-2",
                    work_thread_id="t",
                    title="running",
                    objective="still running",
                    status="running",
                    plan_version=1,
                    acceptance_criteria=["text_equals: draft.md"],
                ),
            ]
        )
        # Only completed children become evidence; the URL keeps its
        # scheme (a split on ":" would have mangled it to "//...").
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["relative_path"], "https://example.com/spec")
        self.assertTrue(entries[0]["verified"])

    def test_run_children_carry_run_python_action_kind(self):
        from zn_agent.core.evidence_bound_work import single_work_evidence_entries
        from zn_agent.core.steerable_work import WorkItem

        entries = single_work_evidence_entries(
            [
                WorkItem(
                    work_item_id="item-1",
                    work_thread_id="t",
                    title="run",
                    objective="run the probe",
                    status="completed",
                    plan_version=1,
                    acceptance_criteria=["command_exit: 0; output_contains: READY"],
                    result="READY",
                ),
            ]
        )
        self.assertEqual(entries[0]["action_kind"], "run_python")


class SingleWorkLedgerVerdictTests(unittest.TestCase):
    """Ledger gate: verifier pass + report verdict decide acceptance."""

    def _setup(self, root: Path):
        workspace = root / "workspace"
        workspace.mkdir()
        kernel = build_runtime(config={"model": {}}, store_path=root / "kernel.db")
        resident = BroadGoalCompletionResidentRuntime(
            kernel=kernel,
            budget=CognitiveBudgetManager(),
        )
        control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
        ledger = control.ledger
        ledger.create_thread(thread_id="single-verdict", title="Single verdict")
        ledger.attach_workspace(
            "single-verdict", workspace, name="Single Verdict Workspace"
        )
        _, event = control.start(
            "single-verdict",
            "Create and independently verify one tiny runnable local artifact.",
            payload={"model_policy": "on_demand"},
            acceptance_criteria=CRITERIA,
        )
        work_ledger = resident.work_ledger
        root_item = work_ledger.work_item_for_event(event.event_id)
        assert root_item is not None
        # Completed children = the Body-verified evidence the
        # adjudicator cites: a write, a run, and the verifier run.
        write_child = work_ledger.create_child_item(
            root_work_item_id=root_item.work_item_id,
            objective="create a tiny runnable probe",
            acceptance_criteria=["text_equals: probe.py"],
        )
        work_ledger.complete_child_item(
            write_child.work_item_id, result="probe.py written, text matches"
        )
        run_child = work_ledger.create_child_item(
            root_work_item_id=root_item.work_item_id,
            objective="run the workspace probe",
            acceptance_criteria=["command_exit: 0; output_contains: READY"],
        )
        work_ledger.complete_child_item(
            run_child.work_item_id, result="READY"
        )
        verifier = work_ledger.create_child_item(
            root_work_item_id=root_item.work_item_id,
            objective="independently execute and reread the runnable artifact",
            acceptance_criteria=[
                "independent_python_verification: probe.py; "
                "fresh_persisted_read: state.json"
            ],
        )
        work_ledger.complete_child_item(
            verifier.work_item_id,
            result=json.dumps(
                {
                    "terminal": "READY",
                    "fresh_persisted_read": {
                        "path": "state.json",
                        "contains": ["READY"],
                    },
                },
                ensure_ascii=False,
            ),
        )
        return resident, work_ledger, event, verifier

    def _accept(self, work_ledger, event, verifier, report):
        return work_ledger.accept_root_with_current_evidence(
            event.event_id,
            verifier_work_item_id=verifier.work_item_id,
            verification_summary="READY",
            completion_report=report,
        )

    def test_no_report_is_rejected(self):
        """A verifier pass with no report never accepts the Root."""
        with tempfile.TemporaryDirectory() as tmp:
            resident, work_ledger, event, verifier = self._setup(Path(tmp))
            try:
                with self.assertRaises(CompletionVerdictError) as caught:
                    self._accept(work_ledger, event, verifier, None)
                self.assertEqual(caught.exception.verdict.verdict, "rejected")
                root = work_ledger.work_item_for_event(event.event_id)
                assert root is not None
                self.assertNotEqual(root.status, "completed")
            finally:
                resident.store.close()

    def test_prose_claim_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, work_ledger, event, verifier = self._setup(Path(tmp))
            try:
                with self.assertRaises(CompletionVerdictError) as caught:
                    self._accept(
                        work_ledger, event, verifier, "搞定了，产物已验证。"
                    )
                self.assertEqual(caught.exception.verdict.verdict, "rejected")
                self.assertIn(
                    "completion_report",
                    caught.exception.verdict.actionable_fix,
                )
            finally:
                resident.store.close()

    def test_partial_claim_lists_missing_then_corrected_report_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, work_ledger, event, verifier = self._setup(Path(tmp))
            try:
                with self.assertRaises(CompletionVerdictError) as caught:
                    self._accept(
                        work_ledger, event, verifier, _partial_report()
                    )
                self.assertEqual(caught.exception.verdict.verdict, "partial")
                self.assertIn(
                    CRITERIA[1], caught.exception.verdict.missing_items
                )
                accepted = self._accept(
                    work_ledger, event, verifier, _full_report()
                )
                self.assertEqual(accepted.status, "completed")
                self.assertIn(
                    "zn_independent_acceptance", accepted.result or ""
                )
            finally:
                resident.store.close()

    def test_dangling_evidence_ref_leaves_criterion_uncovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, work_ledger, event, verifier = self._setup(Path(tmp))
            try:
                report = render_completion_report(
                    conclusion="可运行产物已独立验证通过。",
                    evidence=[
                        (CRITERIA[0], "probe.py"),
                        (CRITERIA[1], "nonexistent/file.md"),
                    ],
                    files=["probe.py"],
                    unfinished=[],
                    standing_dod=_dod(),
                )
                with self.assertRaises(CompletionVerdictError) as caught:
                    self._accept(work_ledger, event, verifier, report)
                self.assertEqual(caught.exception.verdict.verdict, "partial")
                self.assertIn(
                    CRITERIA[1], caught.exception.verdict.missing_items
                )
            finally:
                resident.store.close()

    def test_missing_standing_dod_is_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, work_ledger, event, verifier = self._setup(Path(tmp))
            try:
                report = render_completion_report(
                    conclusion="可运行产物已独立验证通过。",
                    evidence=[
                        (CRITERIA[0], "probe.py"),
                        (CRITERIA[1], "READY"),
                    ],
                    files=["probe.py"],
                    unfinished=[],
                )
                with self.assertRaises(CompletionVerdictError) as caught:
                    self._accept(work_ledger, event, verifier, report)
                self.assertEqual(caught.exception.verdict.verdict, "partial")
                self.assertEqual(
                    caught.exception.verdict.dod_missing,
                    (
                        "no_regression",
                        "runtime_verified",
                        "docs",
                        "rollback",
                        "approval",
                    ),
                )
            finally:
                resident.store.close()

    def test_full_report_is_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, work_ledger, event, verifier = self._setup(Path(tmp))
            try:
                accepted = self._accept(
                    work_ledger, event, verifier, _full_report()
                )
                self.assertEqual(accepted.status, "completed")
            finally:
                resident.store.close()


class _ClaimCognition:
    """Fixture cognition: three work steps, then scripted report rounds."""

    _BROAD_MARKER = "You are a bounded coding/reasoning resource assisting one durable ZN Work."

    def __init__(self, *, report_script: list[str]) -> None:
        self._report_script = list(report_script)
        self.step_calls = 0
        self.report_calls = 0
        self.report_questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        if "completion_report" in question:
            index = min(self.report_calls, len(self._report_script) - 1)
            self.report_calls += 1
            self.report_questions.append(question)
            return CognitiveIncrement(
                text=self._report_script[index],
                provider="fixture",
                model="single-verdict-fixture",
            )
        if self._BROAD_MARKER not in question:
            return CognitiveIncrement(
                text="Continue the durable workspace objective.",
                provider="fixture",
                model="single-verdict-fixture",
            )
        self.step_calls += 1
        if self.step_calls == 1:
            source = (
                "from pathlib import Path\n"
                "Path('state.json').write_text('{\\\"status\\\":\\\"READY\\\"}', encoding='utf-8')\n"
                "print('READY')\n"
            )
            proposal = {
                "zn_work_step": {
                    "objective": "create a tiny runnable probe",
                    "action": {
                        "kind": "write_file",
                        "path": "probe.py",
                        "content": source,
                    },
                    "acceptance": {
                        "kind": "text_equals",
                        "path": "probe.py",
                        "expected_text": source,
                    },
                }
            }
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
        else:
            proposal = {
                "zn_work_step": {
                    "objective": "independently execute and reread the current runnable artifact",
                    "action": {"kind": "verify_python", "path": "probe.py", "args": []},
                    "acceptance": {
                        "kind": "root_verified",
                        "criteria": list(CRITERIA),
                        "expected_exit_code": 0,
                        "output_contains": ["READY"],
                        "persisted_read": {
                            "path": "state.json",
                            "contains": ["READY"],
                        },
                    },
                }
            }
        return CognitiveIncrement(
            text=json.dumps(proposal),
            provider="fixture",
            model="single-verdict-fixture",
        )


class SingleWorkResidentVerdictTests(unittest.TestCase):
    @staticmethod
    def _configure(resident, cognition) -> None:
        resident.kernel.reconfigure_resources(
            routes=[
                ModelRoute(
                    route_id="single-verdict-cognition",
                    provider="fixture",
                    model="single-verdict-fixture",
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

    def _start(self, root: Path, *, report_script: list[str]):
        workspace = root / "workspace"
        workspace.mkdir()
        kernel = build_runtime(config={"model": {}}, store_path=root / "kernel.db")
        resident = BroadGoalCompletionResidentRuntime(
            kernel=kernel,
            budget=CognitiveBudgetManager(),
        )
        cognition = _ClaimCognition(report_script=report_script)
        self._configure(resident, cognition)
        control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
        ledger = control.ledger
        ledger.create_thread(thread_id="single-verdict-e2e", title="Single verdict")
        ledger.attach_workspace(
            "single-verdict-e2e", workspace, name="Single Verdict Workspace"
        )
        _, event = control.start(
            "single-verdict-e2e",
            "Create and independently verify one tiny runnable local artifact.",
            payload={"model_policy": "on_demand"},
            acceptance_criteria=CRITERIA,
        )
        return resident, cognition, ledger, event

    def _run_until_terminal(self, resident, event, *, limit: int = 220):
        terminal = None
        for _ in range(limit):
            candidate = resident.live_once()
            if candidate is not None and candidate.event.event_id == event.event_id:
                terminal = candidate
                break
        return terminal

    def test_prose_claim_is_sent_back_then_corrected_report_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, cognition, ledger, event = self._start(
                Path(tmp),
                report_script=["搞定了，产物已验证。", _full_report()],
            )
            try:
                terminal = self._run_until_terminal(resident, event)
                self.assertIsNotNone(terminal)
                assert terminal is not None
                self.assertTrue(terminal.success)
                self.assertEqual(cognition.report_calls, 2)
                # The rejection feedback reached the next cognition call.
                self.assertIn("完成裁决", cognition.report_questions[1])
                self.assertIn("completion_report", cognition.report_questions[1])
                root = ledger.work_item_for_event(event.event_id)
                assert root is not None
                self.assertEqual(root.status, "completed")
            finally:
                resident.store.close()

    def test_partial_claim_is_sent_back_then_corrected_report_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, cognition, ledger, event = self._start(
                Path(tmp),
                report_script=[_partial_report(), _full_report()],
            )
            try:
                terminal = self._run_until_terminal(resident, event)
                self.assertIsNotNone(terminal)
                assert terminal is not None
                self.assertTrue(terminal.success)
                self.assertEqual(cognition.report_calls, 2)
                self.assertIn(CRITERIA[1], cognition.report_questions[1])
            finally:
                resident.store.close()

    def test_identical_rejection_twice_escalates(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, cognition, ledger, event = self._start(
                Path(tmp),
                report_script=[_partial_report(), _partial_report()],
            )
            try:
                terminal = self._run_until_terminal(resident, event)
                self.assertIsNotNone(terminal)
                assert terminal is not None
                self.assertFalse(terminal.success)
                self.assertIn("相同", str(terminal.reason or ""))
                root = ledger.work_item_for_event(event.event_id)
                assert root is not None
                self.assertNotEqual(root.status, "completed")
            finally:
                resident.store.close()


class FullAutonomousStackVerdictTests(unittest.TestCase):
    """Production chain: intake -> steps -> verifier -> report, all
    through BroadGoalAutonomousResidentRuntime (not just the
    completion layer). Guards the claim round against the layers above
    it (autonomous intake must not swallow the completion report)."""

    _INTAKE_MARKER = "Before any execution, define the Root acceptance contract."

    def _start(self, root: Path):
        from zn_agent.core.broad_goal_autonomous_resident import (
            BroadGoalAutonomousResidentRuntime,
        )
        from zn_agent.core.provider_bridge import build_resident_runtime

        workspace = root / "workspace"
        workspace.mkdir()
        resident = build_resident_runtime(
            config={"model": {}}, store_path=root / "kernel.db"
        )
        assert isinstance(resident, BroadGoalAutonomousResidentRuntime)
        cognition = _ClaimCognition(report_script=[_full_report()])
        SingleWorkResidentVerdictTests._configure(resident, cognition)
        control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
        ledger = control.ledger
        ledger.create_thread(thread_id="single-verdict-full", title="Full stack")
        ledger.attach_workspace(
            "single-verdict-full", workspace, name="Full Stack Workspace"
        )
        _, event = control.start(
            "single-verdict-full",
            "Create and independently verify one tiny runnable local artifact.",
            payload={"model_policy": "on_demand"},
        )
        return resident, cognition, ledger, event

    def test_full_stack_completes_through_the_report_round(self):
        # Wrap the claim fixture: intake comes first on this stack.
        with tempfile.TemporaryDirectory() as tmp:
            resident, cognition, ledger, event = self._start(Path(tmp))
            real_invoke = cognition.invoke

            def invoke(*, question: str, context: str) -> CognitiveIncrement:
                if self._INTAKE_MARKER in question:
                    return CognitiveIncrement(
                        text=json.dumps(
                            {"zn_root_acceptance": {"criteria": CRITERIA}}
                        ),
                        provider="fixture",
                        model="single-verdict-fixture",
                    )
                return real_invoke(question=question, context=context)

            cognition.invoke = invoke  # type: ignore[method-assign]
            try:
                terminal = None
                for _ in range(260):
                    candidate = resident.live_once()
                    if (
                        candidate is not None
                        and candidate.event.event_id == event.event_id
                    ):
                        terminal = candidate
                        break
                self.assertIsNotNone(terminal)
                assert terminal is not None
                self.assertTrue(terminal.success)
                self.assertEqual(cognition.report_calls, 1)
                root = ledger.work_item_for_event(event.event_id)
                assert root is not None
                self.assertEqual(root.status, "completed")
                self.assertEqual(root.acceptance_criteria, CRITERIA)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
