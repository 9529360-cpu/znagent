"""M-3: generic plan -> verify -> reroute loop for single Work.

Engine tests cover the deterministic diagnosis (ZN.md §1.10), the
failure signature, and the bounded budget (identical repeat blocks at
once; distinct failures block at the consecutive cap; verified progress
resets the streak). Resident tests drive the real loop: the Work-layer
``_fail_postcondition_verification`` hook records a failed step in the
strategy ledger and terminal-blocks only when the budget is exhausted;
the full-loop test proves a first-strategy verification failure switches
strategy and continues, with the ledger block reaching the next
cognition call. The M-5 completion-report round keeps its own verdict
budget: a rejected report must not add a strategy-ledger entry.
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
from zn_agent.core.completion_verdict import render_completion_report
from zn_agent.core.models import (
    ExecutionPath,
    ModelRoute,
    ResidentRunResult,
    WorkingState,
    utc_now,
)
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.plan_verify_reroute import (
    MAX_CONSECUTIVE_FAILURES,
    STRATEGY_LEDGER_KEY,
    StrategyLedger,
    diagnose_missing_resource,
    failure_signature,
)
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


class EngineDiagnosisTests(unittest.TestCase):
    def test_permission_markers(self) -> None:
        self.assertEqual(
            diagnose_missing_resource("permission denied while writing"),
            "permission",
        )
        self.assertEqual(
            diagnose_missing_resource("写入被拒绝：需要审批"),
            "permission",
        )

    def test_proof_markers_win_over_fact_markers(self) -> None:
        # "missing expected output fragment" is a proof failure (the
        # evidence did not prove the outcome), not a missing file.
        self.assertEqual(
            diagnose_missing_resource(
                "missing expected output fragment(s): 'READY'"
            ),
            "proof",
        )
        self.assertEqual(
            diagnose_missing_resource("expected exit code 0, observed 1"),
            "proof",
        )

    def test_fact_markers(self) -> None:
        self.assertEqual(
            diagnose_missing_resource("file not found: probe.py"), "fact"
        )
        self.assertEqual(diagnose_missing_resource("找不到文件 probe.py"), "fact")

    def test_capability_markers(self) -> None:
        self.assertEqual(
            diagnose_missing_resource("readable managed browser adapter is unavailable"),
            "capability",
        )
        self.assertEqual(
            diagnose_missing_resource("该操作不支持"), "capability"
        )

    def test_understanding_markers_and_default(self) -> None:
        self.assertEqual(
            diagnose_missing_resource("NameError: name 'x' is not defined"),
            "understanding",
        )
        self.assertEqual(
            diagnose_missing_resource("command timed out"),
            "understanding",
        )


class EngineBudgetTests(unittest.TestCase):
    def test_signature_masks_digits_but_keeps_strategy(self) -> None:
        self.assertEqual(
            failure_signature("run_python:probe.py", "exit code 1 at line 12"),
            failure_signature("run_python:probe.py", "exit code 2 at line 99"),
        )
        self.assertNotEqual(
            failure_signature("run_python:probe.py", "exit code 1"),
            failure_signature("write_file:other.py", "exit code 1"),
        )

    def test_identical_repeat_blocks_at_once(self) -> None:
        ledger = StrategyLedger()
        decision, _ = ledger.record_failure(
            "run_python:probe.py",
            "expected exit code 0, observed 1",
            child_work_item_id="child-1",
        )
        self.assertEqual(decision, "switch")
        decision, blocked = ledger.record_failure(
            "run_python:probe.py",
            "expected exit code 0, observed 1",
            child_work_item_id="child-2",
        )
        self.assertEqual(decision, "blocked")
        self.assertIn("同一", blocked or "")

    def test_distinct_failures_block_at_consecutive_cap(self) -> None:
        ledger = StrategyLedger()
        for index in range(MAX_CONSECUTIVE_FAILURES - 1):
            decision, _ = ledger.record_failure(
                f"strategy-{index}",
                f"distinct failure {index}",
                child_work_item_id=f"child-{index}",
            )
            self.assertEqual(decision, "switch")
        decision, blocked = ledger.record_failure(
            "strategy-last",
            "distinct failure last",
            child_work_item_id="child-last",
        )
        self.assertEqual(decision, "blocked")
        self.assertIn(str(MAX_CONSECUTIVE_FAILURES), blocked or "")

    def test_verified_success_resets_the_streak(self) -> None:
        ledger = StrategyLedger()
        ledger.record_failure("s1", "failure one", child_work_item_id="c1")
        ledger.record_failure("s2", "failure two", child_work_item_id="c2")
        ledger.record_success()
        self.assertEqual(ledger.consecutive_failures, 0)
        # Two more failures after progress must not block yet.
        for index in range(2):
            decision, _ = ledger.record_failure(
                f"s-after-{index}",
                f"failure after {index}",
                child_work_item_id=f"c-after-{index}",
            )
            self.assertEqual(decision, "switch")
        # Entries stay for audit even though the streak reset.
        self.assertEqual(len(ledger.entries), 4)

    def test_reentrant_same_attempt_is_duplicate_not_blocked(self) -> None:
        ledger = StrategyLedger()
        decision, _ = ledger.record_failure(
            "run_python:probe.py",
            "expected exit code 0, observed 1",
            child_work_item_id="child-1",
        )
        self.assertEqual(decision, "switch")
        decision, _ = ledger.record_failure(
            "run_python:probe.py",
            "expected exit code 0, observed 1",
            child_work_item_id="child-1",
        )
        self.assertEqual(decision, "duplicate")
        self.assertEqual(len(ledger.entries), 1)

    def test_plan_scope_change_starts_a_fresh_ledger(self) -> None:
        ledger = StrategyLedger()
        ledger.record_failure("s1", "failure one", child_work_item_id="c1")
        raw = ledger.to_dict()
        raw["plan_version"] = 1
        raw["root_work_item_id"] = "root-1"
        same_plan = StrategyLedger.from_state(
            raw, plan_version=1, root_work_item_id="root-1"
        )
        self.assertEqual(len(same_plan.entries), 1)
        new_plan = StrategyLedger.from_state(
            raw, plan_version=2, root_work_item_id="root-1"
        )
        self.assertEqual(len(new_plan.entries), 0)
        self.assertEqual(new_plan.consecutive_failures, 0)

    def test_attempt_numbers_stay_monotonic_past_the_entry_cap(self) -> None:
        # Failure texts must differ in words: the signature masks
        # digits, so texts differing only by a number are identical.
        failures = [
            "the script produced no output at all",
            "the output had the wrong shape entirely",
            "the script wrote to the wrong file path",
            "the script hung until the timeout fired",
            "the page came back empty",
            "the page redirected somewhere unexpected",
            "the file landed in the wrong directory",
            "the command could not find its input",
            "the probe crashed on startup",
            "the result contradicted the earlier evidence",
            "the workspace layout did not match the plan",
            "the artifact was missing its header",
            "the run finished but nothing was persisted",
            "the verification read stale state",
        ]
        ledger = StrategyLedger()
        for index, failure in enumerate(failures):
            decision, _ = ledger.record_failure(
                f"strategy-{index}",
                failure,
                child_work_item_id=f"child-{index}",
            )
            self.assertEqual(decision, "switch")
            ledger.record_success()
        self.assertEqual(len(ledger.entries), 12)
        self.assertEqual(
            [entry.attempt for entry in ledger.entries],
            list(range(3, 15)),
        )

    def test_prompt_block_and_round_trip(self) -> None:
        ledger = StrategyLedger()
        self.assertEqual(ledger.prompt_block(), "")
        ledger.record_failure(
            "run_python:probe.py",
            "expected exit code 0, observed 1",
            child_work_item_id="c1",
        )
        block = ledger.prompt_block()
        self.assertIn("strategy-ledger", block)
        self.assertIn("run_python:probe.py", block)
        self.assertIn("缺证明", block)
        self.assertIn("不要编造", block)
        restored = StrategyLedger.from_state(ledger.to_dict())
        self.assertEqual(len(restored.entries), 1)
        self.assertEqual(restored.entries[0].missing_resource, "proof")
        self.assertTrue(restored.entries[0].switch_reason)
        report = ledger.blocked_report()
        self.assertEqual(report["tried_strategies"], ["run_python:probe.py"])
        self.assertEqual(report["missing_resource"], "proof")


class ResidentHookTests(unittest.TestCase):
    """Drive the Work-layer investigation hook with mock step failures.

    Each failure is staged as the real loop leaves it: a blocked child
    whose blocker carries the failure text, ``local_failure`` set, the
    rolling step still pointing at the failed child, stage
    ``native_investigation``. One ``live_once`` pulse then runs the real
    investigation hook (record, or terminal-block when exhausted).
    """

    def _start(self, root: Path):
        workspace = root / "workspace"
        workspace.mkdir()
        kernel = build_runtime(config={"model": {}}, store_path=root / "kernel.db")
        resident = BroadGoalCompletionResidentRuntime(
            kernel=kernel,
            budget=CognitiveBudgetManager(),
        )
        control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
        ledger = control.ledger
        ledger.create_thread(thread_id="m3-hook", title="M-3 hook")
        ledger.attach_workspace("m3-hook", workspace, name="M-3 Hook Workspace")
        _, event = control.start(
            "m3-hook",
            "Create and independently verify one tiny runnable local artifact.",
            payload={"model_policy": "on_demand"},
            acceptance_criteria=CRITERIA,
        )
        root_item = resident.work_ledger.work_item_for_event(event.event_id)
        assert root_item is not None
        return resident, event, root_item, workspace

    @staticmethod
    def _stage_failure(resident, event, root_item, *, child_id: str, failure: str):
        """Stage one failed rolling step the way the real loop leaves it."""
        child = WorkItem(
            work_item_id=child_id,
            work_thread_id=root_item.work_thread_id,
            parent_work_item_id=root_item.work_item_id,
            title="Run the workspace probe",
            objective="run the workspace probe",
            status="blocked",
            plan_version=root_item.plan_version,
            acceptance_criteria=["command_exit: 0; output_contains: READY"],
        )
        child.blocker = failure
        child.result = failure
        child.updated_at = utc_now()
        resident.work_ledger._save_item(child)
        # Merge into the existing working state: a fresh WorkingState
        # would discard the accumulated strategy ledger (the real loop
        # carries state across pulses).
        state = resident.store.get_working_state()
        state.current_event_id = event.event_id
        state.stage = "native_investigation"
        state.next_action = "investigate the failed step"
        state.data["local_failure"] = failure
        state.data["broad_goal_rolling_step"] = {
            "work_item_id": child_id,
            "root_work_item_id": root_item.work_item_id,
            "work_thread_id": root_item.work_thread_id,
            "plan_version": root_item.plan_version,
            "relative_path": "probe.py",
            "objective": "run the workspace probe",
            "increment_id": f"inc-{child_id}",
            "action_kind": "run_python",
        }
        resident.store.save_working_state(state)
        return state

    def _ledger(self, resident):
        raw = resident.store.get_working_state().data.get(STRATEGY_LEDGER_KEY)
        return StrategyLedger.from_state(raw)

    def test_failed_step_is_recorded_and_loop_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, event, root_item, _workspace = self._start(Path(tmp))
            try:
                self._stage_failure(
                    resident,
                    event,
                    root_item,
                    child_id="child-1",
                    failure="command exited with code 1",
                )
                result = resident.live_once()
                self.assertIsNone(result)
                ledger = self._ledger(resident)
                self.assertEqual(len(ledger.entries), 1)
                self.assertEqual(
                    ledger.entries[0].missing_resource, "understanding"
                )
                self.assertIn("run_python:probe.py", ledger.entries[0].strategy)
                self.assertTrue(ledger.entries[0].switch_reason)
            finally:
                resident.store.close()

    def test_proposal_rejection_is_not_a_strategy_attempt(self) -> None:
        # A proposal rejection reuses the investigation stage, but its
        # local_failure is about the rejected proposal, not the rolling
        # child -- the child's blocker still carries the child's own
        # execution failure, so the rejection must not be recorded.
        with tempfile.TemporaryDirectory() as tmp:
            resident, event, root_item, _workspace = self._start(Path(tmp))
            try:
                self._stage_failure(
                    resident,
                    event,
                    root_item,
                    child_id="child-1",
                    failure="command exited with code 1",
                )
                first = resident.live_once()
                self.assertIsNone(first)
                self.assertEqual(len(self._ledger(resident).entries), 1)
                # Now stage a proposal rejection against the same stale
                # rolling child: local_failure changes, blocker does not.
                state = resident.store.get_working_state()
                state.data["local_failure"] = (
                    "ZN rejected the proposed Broad Work step because it "
                    "did not match any bounded contract"
                )
                state.stage = "native_investigation"
                resident.store.save_working_state(state)
                resident.live_once()
                self.assertEqual(len(self._ledger(resident).entries), 1)
            finally:
                resident.store.close()

    def test_identical_repeat_terminal_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, event, root_item, _workspace = self._start(Path(tmp))
            try:
                self._stage_failure(
                    resident,
                    event,
                    root_item,
                    child_id="child-1",
                    failure="command exited with code 1",
                )
                first = resident.live_once()
                self.assertIsNone(first)
                self._stage_failure(
                    resident,
                    event,
                    root_item,
                    child_id="child-2",
                    failure="command exited with code 1",
                )
                second = resident.live_once()
                self.assertIsNotNone(second)
                assert second is not None
                self.assertFalse(second.success)
                self.assertIn("同一", second.reason or "")
                # live_once resets working state to idle after
                # publishing the terminal outcome; the terminal
                # result itself is the blocking evidence.
            finally:
                resident.store.close()

    def test_distinct_failures_exhaust_the_budget(self) -> None:
        # Failure texts must differ in words, not just digits: the
        # signature masks digits, so "failure 0" / "failure 1" are the
        # same failure.
        failures = [
            "alpha failure: the script produced no output at all",
            "beta failure: the output had the wrong shape entirely",
            "gamma failure: the script wrote to the wrong file path",
            "delta failure: the script hung until the timeout fired",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            resident, event, root_item, _workspace = self._start(Path(tmp))
            try:
                for index, failure in enumerate(
                    failures[: MAX_CONSECUTIVE_FAILURES - 1]
                ):
                    self._stage_failure(
                        resident,
                        event,
                        root_item,
                        child_id=f"child-{index}",
                        failure=failure,
                    )
                    result = resident.live_once()
                    self.assertIsNone(result)
                self._stage_failure(
                    resident,
                    event,
                    root_item,
                    child_id="child-last",
                    failure=failures[MAX_CONSECUTIVE_FAILURES - 1],
                )
                blocked = resident.live_once()
                self.assertIsNotNone(blocked)
                assert blocked is not None
                self.assertFalse(blocked.success)
                self.assertIn(
                    f"连续 {MAX_CONSECUTIVE_FAILURES} 次", blocked.reason or ""
                )
            finally:
                resident.store.close()

    def test_verified_child_resets_the_streak(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, event, root_item, _workspace = self._start(Path(tmp))
            try:
                self._stage_failure(
                    resident,
                    event,
                    root_item,
                    child_id="child-1",
                    failure="command exited with code 1",
                )
                self.assertIsNone(resident.live_once())
                # A verified child rolls forward through the real path.
                state = resident.store.get_working_state()
                child = resident.work_ledger.create_child_item(
                    root_work_item_id=root_item.work_item_id,
                    objective="run the workspace probe",
                    acceptance_criteria=["command_exit: 0; output_contains: READY"],
                )
                state.data["broad_goal_rolling_step"] = {
                    "work_item_id": child.work_item_id,
                    "root_work_item_id": root_item.work_item_id,
                    "work_thread_id": root_item.work_thread_id,
                    "plan_version": root_item.plan_version,
                    "relative_path": "probe.py",
                    "objective": "run the workspace probe",
                    "increment_id": "inc-verified",
                    "action_kind": "run_python",
                }
                resident.store.save_working_state(state)
                resident._roll_forward_verified_child(
                    event,
                    state,
                    result=ResidentRunResult(
                        event=event,
                        execution_path=ExecutionPath.BODY,
                        success=True,
                        response="probe.py",
                        reason="verified child",
                    ),
                )
                ledger = self._ledger(resident)
                self.assertEqual(ledger.consecutive_failures, 0)
                self.assertEqual(len(ledger.entries), 1)
            finally:
                resident.store.close()

    def test_research_failure_uses_the_same_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, event, root_item, _workspace = self._start(Path(tmp))
            try:
                state = WorkingState(
                    current_event_id=event.event_id,
                    stage="native_investigation",
                    next_action="investigate the research failure",
                    data={},
                )
                child = resident.work_ledger.create_child_item(
                    root_work_item_id=root_item.work_item_id,
                    objective="read the spec page",
                    acceptance_criteria=["page_read: https://example.com/spec"],
                )
                state.data["broad_goal_research_step"] = {
                    "work_item_id": child.work_item_id,
                    "root_work_item_id": root_item.work_item_id,
                    "work_thread_id": root_item.work_thread_id,
                    "plan_version": root_item.plan_version,
                    "objective": "read the spec page",
                    "url": "https://example.com/spec",
                    "increment_id": "inc-research-1",
                }
                resident.store.save_working_state(state)
                result = resident._fail_research_step(
                    event,
                    state,
                    child,
                    "managed browser returned incomplete page evidence",
                )
                self.assertIsNone(result)
                ledger = self._ledger(resident)
                self.assertEqual(len(ledger.entries), 1)
                self.assertIn(
                    "research_page:https://example.com/spec",
                    ledger.entries[0].strategy,
                )
            finally:
                resident.store.close()


class _RerouteCognition:
    """Fixture cognition: fail the first run, then switch strategy."""

    _BROAD_MARKER = "You are a bounded coding/reasoning resource assisting one durable ZN Work."

    def __init__(self, *, report_script: list[str]) -> None:
        self._report_script = list(report_script)
        self.step_calls = 0
        self.report_calls = 0
        self.questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.questions.append(question)
        if "completion_report" in question:
            index = min(self.report_calls, len(self._report_script) - 1)
            self.report_calls += 1
            return CognitiveIncrement(
                text=self._report_script[index],
                provider="fixture",
                model="reroute-fixture",
            )
        if self._BROAD_MARKER not in question:
            return CognitiveIncrement(
                text="Continue the durable workspace objective.",
                provider="fixture",
                model="reroute-fixture",
            )
        self.step_calls += 1
        if self.step_calls == 1:
            proposal = {
                "zn_work_step": {
                    "objective": "create a tiny runnable probe",
                    "action": {
                        "kind": "write_file",
                        "path": "probe.py",
                        "content": "import sys\nsys.exit(1)\n",
                    },
                    "acceptance": {
                        "kind": "text_equals",
                        "path": "probe.py",
                        "expected_text": "import sys\nsys.exit(1)\n",
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
        elif self.step_calls == 3:
            # Switched strategy: rewrite the probe from the fresh
            # failure evidence instead of re-running the broken script.
            proposal = {
                "zn_work_step": {
                    "objective": "rewrite the probe to emit READY",
                    "action": {
                        "kind": "write_file",
                        "path": "probe.py",
                        "content": (
                            "from pathlib import Path\n"
                            "Path('state.json').write_text('{\\\"status\\\": \\\"READY\\\"}', encoding='utf-8')\n"
                            "print('READY')\n"
                        ),
                    },
                    "acceptance": {
                        "kind": "text_equals",
                        "path": "probe.py",
                        "expected_text": (
                            "from pathlib import Path\n"
                            "Path('state.json').write_text('{\\\"status\\\": \\\"READY\\\"}', encoding='utf-8')\n"
                            "print('READY')\n"
                        ),
                    },
                }
            }
        elif self.step_calls == 4:
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
            model="reroute-fixture",
        )


class PlanVerifyRerouteLoopTests(unittest.TestCase):
    @staticmethod
    def _configure(resident, cognition) -> None:
        resident.kernel.reconfigure_resources(
            routes=[
                ModelRoute(
                    route_id="reroute-cognition",
                    provider="fixture",
                    model="reroute-fixture",
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
        cognition = _RerouteCognition(report_script=report_script)
        self._configure(resident, cognition)
        control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
        ledger = control.ledger
        ledger.create_thread(thread_id="m3-loop", title="M-3 loop")
        ledger.attach_workspace("m3-loop", workspace, name="M-3 Loop Workspace")
        _, event = control.start(
            "m3-loop",
            "Create and independently verify one tiny runnable local artifact.",
            payload={"model_policy": "on_demand"},
            acceptance_criteria=CRITERIA,
        )
        return resident, cognition, ledger, event

    def _run_until_terminal(self, resident, event, *, limit: int = 220):
        # The resident resets working state to idle after publishing a
        # terminal outcome (like rolling history and local_failure),
        # so the ledger must be snapshotted mid-loop, not after terminal.
        terminal = None
        last_ledger: StrategyLedger | None = None
        for _ in range(limit):
            candidate = resident.live_once()
            raw = resident.store.get_working_state().data.get(
                STRATEGY_LEDGER_KEY
            )
            if isinstance(raw, dict) and raw.get("entries"):
                last_ledger = StrategyLedger.from_state(raw)
            if candidate is not None and candidate.event.event_id == event.event_id:
                terminal = candidate
                break
        return terminal, last_ledger

    def test_first_strategy_failure_switches_strategy_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, cognition, ledger, event = self._start(
                Path(tmp), report_script=[_full_report()]
            )
            try:
                terminal, recorded = self._run_until_terminal(resident, event)
                self.assertIsNotNone(terminal)
                assert terminal is not None
                self.assertTrue(terminal.success)
                # The ledger block reached a later cognition call: the
                # failed run_python strategy, its diagnosis, and the
                # switch guidance were all visible to the next proposal.
                ledger_questions = [
                    question
                    for question in cognition.questions
                    if "strategy-ledger" in question
                ]
                self.assertGreaterEqual(len(ledger_questions), 1)
                self.assertIn("run_python:probe.py", ledger_questions[0])
                # The action failure text is "command exited with code
                # 1": no fact/capability/permission/proof marker fits,
                # so the loop diagnoses missing understanding (re-derive
                # the plan from fresh evidence) and switches strategy.
                self.assertIn("缺理解", ledger_questions[0])
                # The M-5 claim round replaces the step question, so it
                # must not carry the step-strategy ledger block.
                for question in cognition.questions:
                    if "completion_report" in question:
                        self.assertNotIn("strategy-ledger", question)
                # Mid-loop ledger snapshot: one failed attempt (the
                # first run), streak reset by the verified steps that
                # followed.
                self.assertIsNotNone(recorded)
                assert recorded is not None
                self.assertEqual(len(recorded.entries), 1)
                self.assertEqual(
                    recorded.entries[0].missing_resource, "understanding"
                )
                self.assertEqual(recorded.consecutive_failures, 0)
                root = ledger.work_item_for_event(event.event_id)
                assert root is not None
                self.assertEqual(root.status, "completed")
            finally:
                resident.store.close()

    def test_rejected_completion_report_does_not_touch_strategy_ledger(
        self,
    ) -> None:
        # M-5 boundary: a partial completion report is rejected by the
        # CP-3 adjudicator under its own budget; it is not a strategy
        # attempt and must not add a strategy-ledger entry.
        with tempfile.TemporaryDirectory() as tmp:
            resident, cognition, ledger, event = self._start(
                Path(tmp), report_script=[_partial_report(), _full_report()]
            )
            try:
                terminal, recorded = self._run_until_terminal(resident, event)
                self.assertIsNotNone(terminal)
                assert terminal is not None
                self.assertTrue(terminal.success)
                self.assertEqual(cognition.report_calls, 2)
                self.assertIsNotNone(recorded)
                assert recorded is not None
                self.assertEqual(len(recorded.entries), 1)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
