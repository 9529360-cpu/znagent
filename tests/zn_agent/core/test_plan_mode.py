"""CUR-2 Plan Mode: plan first, execute only after user approval.

Unit tests pin the plan proposal parser (exact JSON, required fields,
size caps), the reviewable markdown rendering (plain markdown, no JSON
blobs), and the gate state machine (pending -> approved / rejected,
no clobbering a pending plan, approval carries the edited text).

Owner tests pin the approved plan riding into the live specialist's
context. Resident tests drive the real loop: a plan proposal writes the
plan file and blocks (no work step executes before approval); approval
with edited text resumes work with the edited plan in context;
rejection fails the team closed; with Plan Mode off, a plan-shaped
payload is not treated as a plan.
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
from zn_agent.core.evidence_bound_work import EvidenceBoundSteerableWorkLedger
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.models import ModelRoute
from zn_agent.core.plan_mode import (
    PLAN_GATE_STATE_KEY,
    PlanDecision,
    PlanProposal,
    approve_plan,
    approved_plan_text,
    parse_plan_proposal,
    plan_file_rel_path,
    plan_gate,
    plan_mode_enabled,
    plan_pending,
    reject_plan,
    render_plan_markdown,
    request_plan,
)
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.store import KernelStore
from zn_agent.core.team_work_owner import TeamWorkOwner
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


def _proposal_payload(**overrides) -> str:
    proposal = {
        "title": "拆分调研报告",
        "goal": "把调研结论拆成三份可验证的报告",
        "files": ["research/a.md", "research/b.md"],
        "steps": ["写 a.md", "写 b.md", "跑验证脚本"],
        "decisions": [
            {
                "question": "报告拆几份？",
                "options": ["2 份", "3 份"],
                "recommendation": "3 份",
            }
        ],
        "risks": ["结论不一致"],
        "acceptance": ["三份报告都有证据引用"],
    }
    proposal.update(overrides)
    return json.dumps({"plan_proposal": proposal}, ensure_ascii=False)


class ParsePlanProposalTests(unittest.TestCase):
    def test_valid_proposal_parses(self):
        proposal, err = parse_plan_proposal(_proposal_payload())
        self.assertEqual(err, "")
        assert proposal is not None
        self.assertEqual(proposal.title, "拆分调研报告")
        self.assertEqual(proposal.files, ("research/a.md", "research/b.md"))
        self.assertEqual(len(proposal.steps), 3)
        self.assertEqual(len(proposal.decisions), 1)
        self.assertEqual(proposal.decisions[0].question, "报告拆几份？")
        self.assertEqual(proposal.decisions[0].options, ("2 份", "3 份"))

    def test_prose_is_not_a_plan(self):
        proposal, err = parse_plan_proposal("我觉得应该先做个计划")
        self.assertIsNone(proposal)
        self.assertIn("plan_proposal", err)

    def test_missing_title_rejected(self):
        proposal, err = parse_plan_proposal(_proposal_payload(title=""))
        self.assertIsNone(proposal)
        self.assertIn("title", err)

    def test_empty_files_rejected(self):
        proposal, err = parse_plan_proposal(_proposal_payload(files=[]))
        self.assertIsNone(proposal)
        self.assertIn("files", err)

    def test_empty_steps_rejected(self):
        proposal, err = parse_plan_proposal(_proposal_payload(steps=[]))
        self.assertIsNone(proposal)
        self.assertIn("steps", err)

    def test_decision_needs_two_options(self):
        proposal, err = parse_plan_proposal(
            _proposal_payload(
                decisions=[{"question": "拆几份？", "options": ["3 份"]}]
            )
        )
        self.assertIsNone(proposal)
        self.assertIn("options", err)

    def test_decisions_optional(self):
        proposal, err = parse_plan_proposal(_proposal_payload(decisions=[]))
        self.assertEqual(err, "")
        assert proposal is not None
        self.assertEqual(proposal.decisions, ())

    def test_oversized_fields_capped(self):
        proposal, err = parse_plan_proposal(
            _proposal_payload(goal="x" * 5000, files=["f.md"] * 100)
        )
        self.assertEqual(err, "")
        assert proposal is not None
        self.assertEqual(len(proposal.goal), 2000)
        self.assertEqual(len(proposal.files), 30)


class RenderPlanMarkdownTests(unittest.TestCase):
    def test_markdown_is_reviewable_plain_text(self):
        proposal, _ = parse_plan_proposal(_proposal_payload())
        assert proposal is not None
        text = render_plan_markdown(
            proposal, work_item_id="wid-1", specialist_name="调研员"
        )
        self.assertIn("# 计划：拆分调研报告", text)
        self.assertIn("## 目标", text)
        self.assertIn("`research/a.md`", text)
        self.assertIn("1. 写 a.md", text)
        self.assertIn("### 抉择 1：报告拆几份？", text)
        self.assertIn("- 建议：3 份", text)
        self.assertIn("## 风险", text)
        self.assertIn("## 验收", text)
        self.assertIn("<!-- PLAN STATUS: pending -->", text)
        # No JSON blobs: the user edits markdown, not JSON.
        self.assertNotIn("{", text.replace("<!-- PLAN STATUS: pending -->", ""))

    def test_plan_file_path_is_workspace_relative(self):
        self.assertEqual(
            plan_file_rel_path("wid-1"), "plans/plan-wid-1.md"
        )
        self.assertTrue(
            plan_file_rel_path("a/b c").startswith("plans/plan-")
        )
        self.assertNotIn("/", plan_file_rel_path("a/b c")[len("plans/plan-") :])


class PlanGateTests(unittest.TestCase):
    def _proposal(self) -> PlanProposal:
        proposal, _ = parse_plan_proposal(_proposal_payload())
        assert proposal is not None
        return proposal

    def test_pending_then_approved_carries_edited_text(self):
        data: dict = {}
        self.assertFalse(plan_pending(data))
        gate, replaced = request_plan(
            data,
            work_item_id="wid-1",
            run_id="run-1",
            proposal=self._proposal(),
            plan_file="plans/plan-wid-1.md",
        )
        self.assertTrue(replaced)
        self.assertEqual(gate["status"], "pending")
        self.assertTrue(plan_pending(data))
        self.assertIsNone(approved_plan_text(data, work_item_id="wid-1"))
        gate, err = approve_plan(data, edited_markdown="用户已改：用 plan-B 方案")
        self.assertEqual(err, "")
        assert gate is not None
        self.assertEqual(gate["status"], "approved")
        self.assertEqual(
            approved_plan_text(data, work_item_id="wid-1"),
            "用户已改：用 plan-B 方案",
        )
        # Another item does not see this item's plan.
        self.assertIsNone(approved_plan_text(data, work_item_id="wid-2"))

    def test_pending_plan_is_not_clobbered_by_replan(self):
        data: dict = {}
        request_plan(
            data,
            work_item_id="wid-1",
            run_id="run-1",
            proposal=self._proposal(),
            plan_file="plans/plan-wid-1.md",
        )
        other, _ = parse_plan_proposal(_proposal_payload(title="新计划"))
        assert other is not None
        gate, replaced = request_plan(
            data,
            work_item_id="wid-1",
            run_id="run-1",
            proposal=other,
            plan_file="plans/plan-wid-1.md",
        )
        self.assertFalse(replaced)
        self.assertEqual(gate["title"], "拆分调研报告")

    def test_reject_stops_with_reason(self):
        data: dict = {}
        request_plan(
            data,
            work_item_id="wid-1",
            run_id="run-1",
            proposal=self._proposal(),
            plan_file="plans/plan-wid-1.md",
        )
        gate, err = reject_plan(data, reason="方案太复杂，先不做")
        self.assertEqual(err, "")
        assert gate is not None
        self.assertEqual(gate["status"], "rejected")
        self.assertEqual(gate["reject_reason"], "方案太复杂，先不做")
        self.assertFalse(plan_pending(data))

    def test_approve_without_pending_fails(self):
        gate, err = approve_plan({}, edited_markdown="x")
        self.assertIsNone(gate)
        self.assertIn("没有待审批", err)

    def test_approve_empty_text_fails(self):
        data: dict = {}
        request_plan(
            data,
            work_item_id="wid-1",
            run_id="run-1",
            proposal=self._proposal(),
            plan_file="plans/plan-wid-1.md",
        )
        gate, err = approve_plan(data, edited_markdown="   ")
        self.assertIsNone(gate)
        self.assertIn("为空", err)
        self.assertTrue(plan_pending(data))

    def test_plan_mode_enabled_flag(self):
        on = SimpleNamespace(
            payload={"team_request": {"plan_mode": True}}
        )
        off = SimpleNamespace(payload={"team_request": {}})
        self.assertTrue(plan_mode_enabled(on))
        self.assertFalse(plan_mode_enabled(off))
        self.assertFalse(plan_mode_enabled(SimpleNamespace(payload={})))

    def test_gate_key_constant(self):
        self.assertEqual(PLAN_GATE_STATE_KEY, "team_plan_gate")


class OwnerApprovedPlanTests(unittest.TestCase):
    """The owner injects the approved plan into the live context."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-plan-owner-"))
        self.store = KernelStore(self.root / "kernel.db")
        resident = SimpleNamespace(
            store=SimpleNamespace(path=str(self.root / "kernel.db"))
        )
        self.ledger = EvidenceBoundSteerableWorkLedger(resident)
        self.memory = StructuredMemory(self.store)
        self.thread_id = "thread-plan-owner"
        self.ledger.create_thread(thread_id=self.thread_id, title="项目 X")
        self.ledger._save_item(
            WorkItem(
                work_item_id="root-plan",
                work_thread_id=self.thread_id,
                title="XX 项目",
                objective="给 XX 项目组个团队",
                status="running",
                plan_version=1,
            )
        )
        self.event = SimpleNamespace(
            event_id="evt-plan-owner",
            payload={
                "work_thread_id": self.thread_id,
                "work_item_id": "root-plan",
                "team_request": {
                    "project_title": "XX 项目",
                    "role_keys": ["researcher"],
                    "plan_mode": True,
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
            root_work_item_id="root-plan",
        )

    def test_no_gate_means_no_approved_plan(self):
        step = self._advance()
        assert step.live_context is not None
        self.assertIsNone(step.live_context.get("approved_plan"))

    def test_approved_plan_reaches_live_context(self):
        step = self._advance()
        assert step.live_run_id is not None
        assert step.live_context is not None
        work_item_id = step.live_context["work_item_id"]
        proposal, _ = parse_plan_proposal(_proposal_payload())
        assert proposal is not None
        request_plan(
            self.state.data,
            work_item_id=work_item_id,
            run_id=step.live_run_id,
            proposal=proposal,
            plan_file=plan_file_rel_path(work_item_id),
        )
        approve_plan(
            self.state.data, edited_markdown="用户已改：用 plan-B 方案"
        )
        step = self._advance()
        assert step.live_context is not None
        self.assertEqual(
            step.live_context.get("approved_plan"), "用户已改：用 plan-B 方案"
        )


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
                model="team-plan-fixture",
            )
        self.specialist_calls += 1
        self.questions.append(question)
        index = min(self.specialist_calls - 1, len(self._script) - 1)
        return CognitiveIncrement(
            text=self._script[index],
            provider="fixture-cognition",
            model="team-plan-fixture",
        )


class ResidentPlanModeTests(unittest.TestCase):
    @staticmethod
    def _configure_cognition(resident, cognition) -> None:
        resident.kernel.reconfigure_resources(
            routes=[
                ModelRoute(
                    route_id="team-plan-cognition",
                    provider="fixture",
                    model="team-plan-fixture",
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

    def _start(self, root: Path, cognition, *, plan_mode: bool):
        workspace = root / "team-workspace"
        workspace.mkdir()
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=root / "kernel.db",
        )
        self._configure_cognition(resident, cognition)
        control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
        ledger = control.ledger
        ledger.create_thread(thread_id="team-plan-e2e", title="XX 项目")
        ledger.attach_workspace("team-plan-e2e", workspace, name="Team Workspace")
        request: dict = {
            "project_title": "XX 项目",
            "role_keys": ["researcher"],
        }
        if plan_mode:
            request["plan_mode"] = True
        _, event = control.start(
            "team-plan-e2e",
            "给 XX 项目组个团队",
            payload={
                "model_policy": "on_demand",
                "team_request": request,
            },
        )
        return resident, ledger, event, workspace

    @staticmethod
    def _write_step(*, path: str, content: str) -> str:
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

    def test_plan_proposal_writes_file_and_blocks_before_approval(self):
        """Plan proposal -> plan file written, zero work steps executed,
        team waits (not terminal) until the user approves."""
        cognition = _ScriptedSpecialist(script=[_proposal_payload()])
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, event, workspace = self._start(
                Path(tmp), cognition, plan_mode=True
            )
            try:
                for _ in range(30):
                    terminal = resident.live_once()
                    self.assertIsNone(
                        terminal, "plan awaiting approval must not terminate"
                    )
                    plan_files = list((workspace / "plans").glob("*.md"))
                    if plan_files:
                        break
                plan_files = list((workspace / "plans").glob("*.md"))
                self.assertEqual(len(plan_files), 1)
                text = plan_files[0].read_text(encoding="utf-8")
                self.assertIn("# 计划：拆分调研报告", text)
                self.assertIn("PLAN STATUS: pending", text)
                # Nothing was invented or executed: no specialist files.
                self.assertEqual(
                    sorted(p.name for p in workspace.iterdir()),
                    ["agents", "plans"],
                )
                # The gate is pending in working state.
                state = resident.store.get_working_state()
                self.assertTrue(plan_pending(state.data))
                self.assertEqual(
                    plan_gate(state.data)["title"], "拆分调研报告"
                )
            finally:
                resident.store.close()

    def test_approved_edited_plan_resumes_work_with_edited_text(self):
        """Approve with edited text -> next cognition call carries the
        edited plan, and the specialist's work step then executes."""
        write = self._write_step(
            path="research/notes.md", content="调研-01 verified step\n"
        )
        cognition = _ScriptedSpecialist(
            script=[_proposal_payload(), write]
        )
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, event, workspace = self._start(
                Path(tmp), cognition, plan_mode=True
            )
            try:
                approved = False
                wrote = False
                for _ in range(120):
                    resident.live_once()
                    state = resident.store.get_working_state()
                    if not approved and plan_pending(state.data):
                        approve_plan(
                            state.data,
                            edited_markdown="用户已改：用 plan-B 方案",
                        )
                        resident.store.save_working_state(state)
                        approved = True
                        continue
                    if approved and (workspace / "research" / "notes.md").exists():
                        wrote = True
                        break
                self.assertTrue(approved, "plan was never proposed")
                self.assertTrue(wrote, "work did not resume after approval")
                # The approved (edited) plan reached a cognition call.
                self.assertTrue(
                    any(
                        "用户已改：用 plan-B 方案" in question
                        for question in cognition.questions
                    ),
                    "edited plan did not reach cognition",
                )
                # The plan instruction reached the first cognition call.
                self.assertIn("Plan Mode", cognition.questions[0])
                self.assertIn("plan_proposal", cognition.questions[0])
            finally:
                resident.store.close()

    def test_rejected_plan_fails_closed(self):
        cognition = _ScriptedSpecialist(script=[_proposal_payload()])
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, event, workspace = self._start(
                Path(tmp), cognition, plan_mode=True
            )
            try:
                terminal = None
                rejected = False
                for _ in range(120):
                    terminal = resident.live_once()
                    if terminal is not None:
                        break
                    state = resident.store.get_working_state()
                    if not rejected and plan_pending(state.data):
                        reject_plan(state.data, reason="方案太复杂，先不做")
                        resident.store.save_working_state(state)
                        rejected = True
                self.assertTrue(rejected, "plan was never proposed")
                self.assertIsNotNone(
                    terminal, "rejected plan did not fail closed"
                )
                assert terminal is not None
                self.assertFalse(terminal.success)
                self.assertIn("方案太复杂", str(terminal.reason or ""))
                # Nothing was executed.
                self.assertEqual(
                    sorted(p.name for p in workspace.iterdir()),
                    ["agents", "plans"],
                )
            finally:
                resident.store.close()

    def test_plan_shape_ignored_when_plan_mode_off(self):
        """With Plan Mode off, a plan-shaped payload is not a plan: no
        plan file, no gate -- it falls through to normal step parsing."""
        cognition = _ScriptedSpecialist(script=[_proposal_payload()])
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, event, workspace = self._start(
                Path(tmp), cognition, plan_mode=False
            )
            try:
                for _ in range(30):
                    terminal = resident.live_once()
                    if terminal is not None:
                        break
                    if (workspace / "plans").exists():
                        break
                self.assertFalse((workspace / "plans").exists())
                state = resident.store.get_working_state()
                self.assertIsNone(plan_gate(state.data))
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
