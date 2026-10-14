"""CP-3: structured completion verdict + final-report contract.

Unit tests pin the adjudicator (no evidence -> rejected, missing section
-> rejected, partial coverage -> partial with the missing list, full
citation -> verified); owner tests pin the retry budget (identical
rejection escalates at once, distinct rejections escalate past the
budget, a corrected report still completes); resident tests drive the
real loop (a prose claim is sent back with actionable feedback, the
corrected structured report completes the item).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.cognitive_resource import (
    CognitiveIncrement,
    CognitiveResourceWorkerFactory,
)
from zn_agent.core.completion_verdict import (
    MAX_VERDICT_ATTEMPTS,
    adjudicate_completion,
    record_verdict_attempt,
    render_completion_report,
)
from zn_agent.core.evidence_bound_work import EvidenceBoundSteerableWorkLedger
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.store import KernelStore
from zn_agent.core.team_work_owner import (
    EVIDENCE_KEY,
    TEAM_CLAIM_STATE_KEY,
    TeamWorkOwner,
    verified_evidence,
)
from zn_agent.core.work_restore_control import RestoreAwareWorkControl

CRITERIA = ["调研结论有明确选型建议", "风险清单覆盖主要未知项"]


def _evidence(*, ref: str = "research/notes.md") -> list[dict]:
    return [
        {
            "kind": "verified_body_step",
            "objective": "调研员写一份可验证的工作产物",
            "result": "调研-01 verified step",
            "relative_path": ref,
            "verified": True,
            "artifact_refs": [],
        }
    ]


def _run_evidence(*, ref: str = "test_app.py") -> list[dict]:
    """One verified run_python step: the test script actually executed."""
    return [
        {
            "kind": "verified_body_step",
            "objective": "开发运行测试脚本",
            "result": "run_python test_app.py exit 0",
            "relative_path": ref,
            "action_kind": "run_python",
            "verified": True,
            "artifact_refs": [],
        }
    ]


def _full_report(*, ref: str = "research/notes.md") -> str:
    return render_completion_report(
        conclusion="调研完成，结论已写好。",
        evidence=[(criterion, ref) for criterion in CRITERIA],
        files=[ref],
        unfinished=[],
    )


class AdjudicateCompletionTests(unittest.TestCase):
    def test_no_evidence_claim_is_rejected(self):
        verdict = adjudicate_completion(
            expected_output=CRITERIA, evidence=[], summary=_full_report()
        )
        self.assertEqual(verdict.verdict, "rejected")
        self.assertIn("没有任何", verdict.reason)

    def test_prose_claim_is_rejected_with_shape_fix(self):
        verdict = adjudicate_completion(
            expected_output=CRITERIA,
            evidence=_evidence(),
            summary="搞定了，调研结论已写好。",
        )
        self.assertEqual(verdict.verdict, "rejected")
        self.assertIn("completion_report", verdict.actionable_fix)

    def test_missing_section_is_rejected(self):
        report = json.loads(_full_report())
        del report["completion_report"]["files"]
        verdict = adjudicate_completion(
            expected_output=CRITERIA,
            evidence=_evidence(),
            summary=json.dumps(report, ensure_ascii=False),
        )
        self.assertEqual(verdict.verdict, "rejected")
        self.assertIn("files", verdict.reason)

    def test_partial_coverage_is_partial_with_missing_list(self):
        verdict = adjudicate_completion(
            expected_output=CRITERIA,
            evidence=_evidence(),
            summary=render_completion_report(
                conclusion="调研完成一半。",
                evidence=[(CRITERIA[0], "research/notes.md")],
                files=["research/notes.md"],
                unfinished=[],
            ),
        )
        self.assertEqual(verdict.verdict, "partial")
        self.assertEqual(verdict.missing_items, (CRITERIA[1],))
        self.assertIn(CRITERIA[1], verdict.reason)

    def test_unfinished_list_forces_partial(self):
        verdict = adjudicate_completion(
            expected_output=CRITERIA,
            evidence=_evidence(),
            summary=render_completion_report(
                conclusion="调研完成。",
                evidence=[(c, "research/notes.md") for c in CRITERIA],
                files=["research/notes.md"],
                unfinished=[CRITERIA[1]],
            ),
        )
        self.assertEqual(verdict.verdict, "partial")
        self.assertIn(CRITERIA[1], verdict.missing_items)

    def test_unmatched_evidence_ref_leaves_criterion_uncovered(self):
        verdict = adjudicate_completion(
            expected_output=CRITERIA,
            evidence=_evidence(),
            summary=render_completion_report(
                conclusion="调研完成。",
                evidence=[
                    (CRITERIA[0], "research/notes.md"),
                    (CRITERIA[1], "some/other/file.md"),
                ],
                files=["research/notes.md"],
                unfinished=[],
            ),
        )
        self.assertEqual(verdict.verdict, "partial")
        self.assertEqual(verdict.missing_items, (CRITERIA[1],))

    def test_unknown_criterion_is_rejected(self):
        verdict = adjudicate_completion(
            expected_output=CRITERIA,
            evidence=_evidence(),
            summary=render_completion_report(
                conclusion="调研完成。",
                evidence=[("发明一个新验收项", "research/notes.md")],
                files=[],
                unfinished=[],
            ),
        )
        self.assertEqual(verdict.verdict, "rejected")
        self.assertIn("不在 expected_output", verdict.reason)

    def test_full_citation_is_verified(self):
        verdict = adjudicate_completion(
            expected_output=CRITERIA,
            evidence=_evidence(),
            summary=_full_report(),
        )
        self.assertEqual(verdict.verdict, "verified")
        self.assertEqual(verdict.missing_items, ())
        self.assertIn("research/notes.md", verdict.evidence_refs)

    def test_conclusion_saying_unverified_while_claiming_done_is_rejected(self):
        verdict = adjudicate_completion(
            expected_output=CRITERIA,
            evidence=_evidence(),
            summary=render_completion_report(
                conclusion="调研完成，但风险清单未证实。",
                evidence=[(c, "research/notes.md") for c in CRITERIA],
                files=["research/notes.md"],
                unfinished=[],
            ),
        )
        self.assertEqual(verdict.verdict, "rejected")
        self.assertIn("未证实", verdict.reason)

    def test_test_criterion_without_run_evidence_is_partial(self):
        """P2: a test-coverage claim with only written files is partial --
        the smoke run caught a developer writing test_app.py and never
        running it while the claim still passed."""
        criteria = ["功能按验收标准实现", "新增代码有测试覆盖"]
        verdict = adjudicate_completion(
            expected_output=criteria,
            evidence=_evidence(ref="app.py"),
            summary=render_completion_report(
                conclusion="开发完成。",
                evidence=[(c, "app.py") for c in criteria],
                files=["app.py"],
                unfinished=[],
            ),
        )
        self.assertEqual(verdict.verdict, "partial")
        self.assertIn("新增代码有测试覆盖", verdict.missing_items)
        self.assertIn("run_python", verdict.actionable_fix)

    def test_test_file_written_but_never_run_blocks_the_whole_claim(self):
        """P2: a test file written but never run holds the claim even
        when no criterion mentions tests -- the specialist produced
        tests it never executed."""
        verdict = adjudicate_completion(
            expected_output=["实现加法功能"],
            evidence=_evidence(ref="app.py") + _evidence(ref="test_app.py"),
            summary=render_completion_report(
                conclusion="开发完成。",
                evidence=[("实现加法功能", "app.py")],
                files=["app.py", "test_app.py"],
                unfinished=[],
            ),
        )
        self.assertEqual(verdict.verdict, "partial")
        self.assertIn("实现加法功能", verdict.missing_items)
        self.assertIn("run_python", verdict.actionable_fix)

    def test_run_python_evidence_satisfies_test_claim(self):
        criteria = ["功能按验收标准实现", "新增代码有测试覆盖"]
        verdict = adjudicate_completion(
            expected_output=criteria,
            evidence=_evidence(ref="app.py") + _run_evidence(),
            summary=render_completion_report(
                conclusion="开发完成。",
                evidence=[
                    ("功能按验收标准实现", "app.py"),
                    ("新增代码有测试覆盖", "test_app.py"),
                ],
                files=["app.py", "test_app.py"],
                unfinished=[],
            ),
        )
        self.assertEqual(verdict.verdict, "verified")

    def test_latest_in_criterion_does_not_trigger_run_gate(self):
        """Word-boundary matching: 'latest' must not match 'test'."""
        verdict = adjudicate_completion(
            expected_output=["使用 latest 版本的接口"],
            evidence=_evidence(ref="notes.md"),
            summary=render_completion_report(
                conclusion="调研完成。",
                evidence=[("使用 latest 版本的接口", "notes.md")],
                files=["notes.md"],
                unfinished=[],
            ),
        )
        self.assertEqual(verdict.verdict, "verified")


class VerdictRetryBudgetTests(unittest.TestCase):
    @staticmethod
    def _verdict(missing: tuple[str, ...]) -> object:
        return adjudicate_completion(
            expected_output=CRITERIA,
            evidence=_evidence(),
            summary=render_completion_report(
                conclusion="调研完成。",
                evidence=[
                    (c, "research/notes.md") for c in CRITERIA if c not in missing
                ],
                files=[],
                unfinished=list(missing),
            ),
        )

    def test_second_identical_rejection_escalates_at_once(self):
        tracking = None
        tracking, escalate, _ = record_verdict_attempt(
            tracking, run_id="run-1", verdict=self._verdict((CRITERIA[1],))
        )
        self.assertFalse(escalate)
        tracking, escalate, reason = record_verdict_attempt(
            tracking, run_id="run-1", verdict=self._verdict((CRITERIA[1],))
        )
        self.assertTrue(escalate)
        assert reason is not None
        self.assertIn("相同", reason)

    def test_distinct_rejections_escalate_past_the_budget(self):
        tracking = None
        # Alternate the missing item so no two consecutive rejections are
        # identical; the budget (not the identical rule) must escalate.
        sequence = [(CRITERIA[1],), (CRITERIA[0],)] * 2
        for index, missing in enumerate(sequence):
            tracking, escalate, _ = record_verdict_attempt(
                tracking, run_id="run-1", verdict=self._verdict(missing)
            )
            if index < MAX_VERDICT_ATTEMPTS:
                self.assertFalse(escalate, f"escalated early at attempt {index + 1}")
            else:
                self.assertTrue(escalate, "budget did not escalate")

    def test_new_run_resets_the_counters(self):
        tracking, _, _ = record_verdict_attempt(
            None, run_id="run-1", verdict=self._verdict((CRITERIA[1],))
        )
        tracking, escalate, _ = record_verdict_attempt(
            tracking, run_id="run-2", verdict=self._verdict((CRITERIA[1],))
        )
        self.assertFalse(escalate)
        self.assertEqual(tracking["attempts"], 1)


class OwnerVerdictTests(unittest.TestCase):
    """Owner + real ledger; the test plays the specialist."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-team-verdict-"))
        self.store = KernelStore(self.root / "kernel.db")
        resident = SimpleNamespace(
            store=SimpleNamespace(path=str(self.root / "kernel.db"))
        )
        self.ledger = EvidenceBoundSteerableWorkLedger(resident)
        self.memory = StructuredMemory(self.store)
        self.thread_id = "thread-team-verdict"
        self.ledger.create_thread(thread_id=self.thread_id, title="项目 X")
        self.ledger._save_item(
            WorkItem(
                work_item_id="root-verdict",
                work_thread_id=self.thread_id,
                title="XX 项目",
                objective="给 XX 项目组个团队",
                status="running",
                plan_version=1,
            )
        )
        self.event = SimpleNamespace(
            event_id="evt-team-verdict",
            payload={
                "work_thread_id": self.thread_id,
                "work_item_id": "root-verdict",
                "team_request": {
                    "project_title": "XX 项目",
                    "role_keys": ["researcher"],
                },
            },
        )
        self.state = SimpleNamespace(data={})
        self.owner = TeamWorkOwner(ledger=self.ledger, memory=self.memory)

    def tearDown(self):
        self.store.close()

    def _advance(self):
        return self.owner.advance(
            event=self.event,
            state=self.state,
            root_work_item_id="root-verdict",
        )

    def _record_evidence(self, run_id: str) -> None:
        run = self.ledger.worker_run(run_id)
        assert run is not None
        evidence = verified_evidence(run)
        evidence.extend(_evidence())
        self.ledger.update_worker_run_metrics(
            run_id, metrics={EVIDENCE_KEY: evidence}
        )

    def _claim(self, run_id: str, summary: str) -> None:
        self.state.data[TEAM_CLAIM_STATE_KEY] = {
            "run_id": run_id,
            "summary": summary,
        }

    def test_rejected_claim_does_not_land_and_returns_feedback(self):
        step = self._advance()
        assert step.live_run_id is not None
        self._record_evidence(step.live_run_id)
        self._claim(step.live_run_id, "搞定了，调研结论已写好。")
        step = self._advance()
        run = self.ledger.worker_run(step.live_run_id) if step.live_run_id else None
        assert run is not None
        self.assertFalse(run.claimed_completion)
        assert step.verdict_feedback is not None
        self.assertEqual(step.verdict_feedback["verdict"], "rejected")
        self.assertIn("completion_report", step.verdict_feedback["actionable_fix"])
        self.assertIsNone(step.verdict_escalation)
        # The run is still live: the specialist gets another chance.
        self.assertIsNotNone(step.live_run_id)

    def test_partial_claim_lists_missing_then_corrected_report_completes(self):
        step = self._advance()
        assert step.live_run_id is not None
        run_id = step.live_run_id
        self._record_evidence(run_id)
        self._claim(
            run_id,
            render_completion_report(
                conclusion="调研完成一半。",
                evidence=[(CRITERIA[0], "research/notes.md")],
                files=["research/notes.md"],
                unfinished=[],
            ),
        )
        step = self._advance()
        assert step.verdict_feedback is not None
        self.assertEqual(step.verdict_feedback["verdict"], "partial")
        self.assertIn(CRITERIA[1], step.verdict_feedback["missing_items"])
        run = self.ledger.worker_run(run_id)
        assert run is not None
        self.assertFalse(run.claimed_completion)
        # Corrected report cites every criterion -> lands -> verifies ->
        # completes on the following pulses.
        self._claim(run_id, _full_report())
        self._advance()  # claim lands, runner verifies
        step = self._advance()  # item completes
        items = {
            item.work_item_id: item
            for item in self.ledger.list_work_items(self.thread_id)
        }
        first = next(
            item for item in items.values() if item.title == "XX 项目·调研"
        )
        self.assertEqual(first.status, "completed")

    def test_identical_rejection_twice_escalates(self):
        step = self._advance()
        assert step.live_run_id is not None
        run_id = step.live_run_id
        self._record_evidence(run_id)
        partial = render_completion_report(
            conclusion="调研完成一半。",
            evidence=[(CRITERIA[0], "research/notes.md")],
            files=["research/notes.md"],
            unfinished=[],
        )
        self._claim(run_id, partial)
        step = self._advance()
        self.assertIsNone(step.verdict_escalation)
        self._claim(run_id, partial)
        step = self._advance()
        assert step.verdict_escalation is not None
        self.assertIn("相同", step.verdict_escalation)


class _ScriptedSpecialist:
    """Fixture cognition: scripted replies per live-specialist call."""

    def __init__(self, *, script: list[str]) -> None:
        self._script = list(script)
        self.specialist_calls = 0
        self.questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        if "调研-01" not in question:
            return CognitiveIncrement(
                text="继续按现有证据推进。",
                provider="fixture-cognition",
                model="team-verdict-fixture",
            )
        self.specialist_calls += 1
        self.questions.append(question)
        index = min(self.specialist_calls - 1, len(self._script) - 1)
        return CognitiveIncrement(
            text=self._script[index],
            provider="fixture-cognition",
            model="team-verdict-fixture",
        )


class ResidentVerdictTests(unittest.TestCase):
    @staticmethod
    def _configure_cognition(resident, cognition) -> None:
        resident.kernel.reconfigure_resources(
            routes=[
                ModelRoute(
                    route_id="team-verdict-cognition",
                    provider="fixture",
                    model="team-verdict-fixture",
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

    def _start(self, root: Path, cognition):
        workspace = root / "team-workspace"
        workspace.mkdir()
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=root / "kernel.db",
        )
        self._configure_cognition(resident, cognition)
        control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
        ledger = control.ledger
        ledger.create_thread(thread_id="team-verdict-e2e", title="XX 项目")
        ledger.attach_workspace("team-verdict-e2e", workspace, name="Team Workspace")
        _, event = control.start(
            "team-verdict-e2e",
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
            for item in ledger.list_work_items("team-verdict-e2e")
            if root is not None
            and item.parent_work_item_id == root.work_item_id
        ]
        return children[0] if children else None

    @staticmethod
    def _proposal(*, path: str, content: str) -> str:
        return json.dumps(
            {
                "zn_work_step": {
                    "objective": "调研员写一份可验证的工作产物",
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

    def test_prose_claim_is_sent_back_then_structured_report_completes(self):
        """Prose claim -> rejected with actionable fix in the next question
        -> corrected structured report -> item completes via verification."""
        valid = self._proposal(
            path="research/notes.md", content="调研-01 verified step\n"
        )
        cognition = _ScriptedSpecialist(
            script=[valid, "搞定了，调研结论已写好。", _full_report()]
        )
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
                self.assertGreaterEqual(cognition.specialist_calls, 3)
                # The rejection feedback reached the next cognition call.
                self.assertGreaterEqual(len(cognition.questions), 3)
                self.assertIn("完成裁决", cognition.questions[2])
                self.assertIn("completion_report", cognition.questions[2])
                runs = ledger.list_worker_runs(
                    work_item_id=self._child(ledger, event).work_item_id
                )
                self.assertTrue(runs)
                self.assertEqual(runs[-1].verification_status, "verified")
            finally:
                resident.store.close()

    def test_identical_rejection_twice_escalates_in_the_real_loop(self):
        partial = render_completion_report(
            conclusion="调研完成一半。",
            evidence=[(CRITERIA[0], "research/notes.md")],
            files=["research/notes.md"],
            unfinished=[],
        )
        valid = self._proposal(
            path="research/notes.md", content="调研-01 verified step\n"
        )
        cognition = _ScriptedSpecialist(script=[valid, partial, partial])
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, event, workspace = self._start(Path(tmp), cognition)
            try:
                terminal = None
                for _ in range(120):
                    terminal = resident.live_once()
                    if terminal is not None:
                        break
                self.assertIsNotNone(
                    terminal, "identical rejections did not escalate"
                )
                assert terminal is not None
                self.assertFalse(terminal.success)
                self.assertIn("相同", str(terminal.reason or ""))
            finally:
                resident.store.close()


class ResidentGapReportTests(ResidentVerdictTests):
    """P2: a specialist gap report stops the team -- it must not be
    executed as a step, and the next deliberation fails closed with
    the gap instead of re-asking cognition to invent the scope."""

    def test_gap_report_fails_closed_without_inventing_scope(self):
        gap = json.dumps(
            {
                "gap_report": {
                    "missing": "没有设计文档",
                    "needed": "架构专员的设计文档",
                    "impact": "无法确定接口范围",
                }
            },
            ensure_ascii=False,
        )
        cognition = _ScriptedSpecialist(script=[gap])
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, event, workspace = self._start(Path(tmp), cognition)
            try:
                terminal = None
                for _ in range(120):
                    terminal = resident.live_once()
                    if terminal is not None:
                        break
                self.assertIsNotNone(terminal, "gap report did not fail closed")
                assert terminal is not None
                self.assertFalse(terminal.success)
                self.assertIn("缺口", str(terminal.reason or ""))
                self.assertIn("没有设计文档", str(terminal.reason or ""))
                # Nothing was invented: the only workspace content is the
                # persona scaffolding materialized on dispatch, no
                # specialist-invented scope files.
                self.assertEqual(
                    sorted(p.name for p in workspace.iterdir()),
                    ["agents"],
                )
            finally:
                resident.store.close()


class PriorItemsTests(unittest.TestCase):
    """P2: the live specialist sees prior completed items' conclusions
    in its brief, so it can build on decided scope -- and tell when
    the design/scope info it needs is missing."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-team-prior-"))
        self.store = KernelStore(self.root / "kernel.db")
        resident = SimpleNamespace(
            store=SimpleNamespace(path=str(self.root / "kernel.db"))
        )
        self.ledger = EvidenceBoundSteerableWorkLedger(resident)
        self.memory = StructuredMemory(self.store)
        self.thread_id = "thread-team-prior"
        self.ledger.create_thread(thread_id=self.thread_id, title="项目 X")
        self.ledger._save_item(
            WorkItem(
                work_item_id="root-prior",
                work_thread_id=self.thread_id,
                title="XX 项目",
                objective="给 XX 项目组个团队",
                status="running",
                plan_version=1,
            )
        )
        self.event = SimpleNamespace(
            event_id="evt-team-prior",
            payload={
                "work_thread_id": self.thread_id,
                "work_item_id": "root-prior",
                "team_request": {
                    "project_title": "XX 项目",
                    "role_keys": ["researcher", "developer"],
                },
            },
        )
        self.state = SimpleNamespace(data={})
        self.owner = TeamWorkOwner(ledger=self.ledger, memory=self.memory)

    def tearDown(self):
        self.store.close()

    def test_dev_brief_carries_completed_researcher_summary(self):
        step = self.owner.advance(
            event=self.event, state=self.state, root_work_item_id="root-prior"
        )
        assert step.live_run_id is not None
        run_id = step.live_run_id
        run = self.ledger.worker_run(run_id)
        assert run is not None
        evidence = verified_evidence(run)
        evidence.extend(_evidence())
        self.ledger.update_worker_run_metrics(
            run_id, metrics={EVIDENCE_KEY: evidence}
        )
        self.state.data[TEAM_CLAIM_STATE_KEY] = {
            "run_id": run_id,
            "summary": _full_report(),
        }
        self.owner.advance(
            event=self.event, state=self.state, root_work_item_id="root-prior"
        )  # claim lands
        self.owner.advance(
            event=self.event, state=self.state, root_work_item_id="root-prior"
        )  # researcher item completes
        step = self.owner.advance(
            event=self.event, state=self.state, root_work_item_id="root-prior"
        )  # developer dispatched
        self.assertEqual(step.live_specialist_name, "开发-02")
        assert step.live_context is not None
        priors = step.live_context.get("prior_items")
        assert isinstance(priors, list)
        self.assertEqual(len(priors), 1)
        self.assertIn("调研", priors[0]["title"])
        self.assertIn("调研完成", priors[0]["conclusion"])


if __name__ == "__main__":
    unittest.main()
