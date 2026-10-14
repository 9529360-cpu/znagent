"""CP-4: failure classification + hard-stop rules.

Policy-level: four categories, reroute chain, blocked report, approval
guard. Runner-level (real ledger): rate limit hard-stops the round with
no retry, approval bypass is intercepted, retryable failures exhaust
into a needs-user escalation, unrecognized errors still propagate.
"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.evidence_bound_work import EvidenceBoundSteerableWorkLedger
from zn_agent.core.failure_policy import (
    ApprovalBypassBlocked,
    ApprovalRejectedError,
    FailurePolicy,
)
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.project_team import TeamPlanItem, assemble_team
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.store import KernelStore
from zn_agent.core.team_memory import team_shared_memory
from zn_agent.core.team_runner import (
    TeamRunner,
    VerificationOutcome,
)


class _ProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _independent_team(project: str, roles: list[str], team_id: str, thread_id: str):
    """A team whose plan items have no dependencies (all dispatchable)."""
    team = assemble_team(
        project, roles, team_id=team_id, work_thread_id=thread_id
    )
    team.plan = tuple(
        replace(item, dependency_ids=()) for item in team.plan
    )
    return team


class _FailingVerifier:
    """Raises a configured error for selected items, else passes."""

    def __init__(self, *, fail_on: dict[str, BaseException] | None = None):
        self.fail_on = dict(fail_on or {})
        self.calls: list[str] = []

    def verify(self, *, item, run):
        self.calls.append(item.work_item_id)
        if item.work_item_id in self.fail_on:
            raise self.fail_on[item.work_item_id]
        return VerificationOutcome(passed=True, notes="ok")


class FailurePolicyClassificationTests(unittest.TestCase):
    def setUp(self):
        self.policy = FailurePolicy()

    def test_rate_limit_is_round_hard_stop(self):
        observed = self.policy.classify(
            _ProviderError("too many requests", status_code=429)
        )
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual(observed.category, "hard_stop")
        self.assertEqual(observed.scope, "round")
        self.assertEqual(observed.kind, "rate_limit")

    def test_overload_is_reroute(self):
        observed = self.policy.classify(
            _ProviderError("service temporarily unavailable", status_code=503)
        )
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual(observed.category, "reroute")
        self.assertEqual(observed.scope, "item")

    def test_network_blip_is_retryable(self):
        observed = self.policy.classify(ConnectionError("connection reset"))
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual(observed.category, "retryable")
        self.assertEqual(observed.scope, "item")

    def test_permanent_auth_is_needs_user_not_retryable(self):
        observed = self.policy.classify(
            _ProviderError("invalid api key", status_code=401)
        )
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual(observed.category, "needs_user")
        self.assertNotEqual(observed.category, "retryable")
        self.assertTrue(observed.reconnect_hint)

    def test_billing_is_needs_user(self):
        observed = self.policy.classify(
            _ProviderError("insufficient_quota", status_code=402)
        )
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual(observed.category, "needs_user")

    def test_content_policy_is_hard_stop_not_reroute(self):
        observed = self.policy.classify(
            _ProviderError(
                "request blocked by content policy", status_code=403
            )
        )
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual(observed.category, "hard_stop")
        self.assertNotEqual(observed.category, "reroute")

    def test_context_overflow_is_reroute(self):
        observed = self.policy.classify(
            _ProviderError("maximum context length exceeded", status_code=400)
        )
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual(observed.category, "reroute")

    def test_authority_denial_is_hard_stop(self):
        observed = self.policy.classify(
            PermissionError("worker action is outside the admitted action")
        )
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual(observed.category, "hard_stop")

    def test_unknown_error_returns_none_so_caller_reraises(self):
        self.assertIsNone(self.policy.classify(RuntimeError("boom")))

    def test_approval_rejection_never_reroutes(self):
        self.policy.record_approval_rejection("dispatch:wid-1", "用户拒绝")
        with self.assertRaises(ApprovalBypassBlocked):
            self.policy.require_not_rejected("dispatch:wid-1")
        # The bypass attempt itself classifies as a round hard stop.
        observed = self.policy.classify(
            ApprovalRejectedError("approval rejected")
        )
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual(observed.category, "hard_stop")
        self.assertEqual(observed.scope, "round")
        # Other actions are unaffected.
        self.policy.require_not_rejected("dispatch:wid-2")

    def test_reroute_chain_order_and_exhaustion(self):
        self.assertEqual(
            self.policy.next_path("cognition", []), "primary_route"
        )
        self.assertEqual(
            self.policy.next_path("cognition", ["primary_route"]),
            "alternate_route",
        )
        self.assertEqual(
            self.policy.next_path(
                "cognition",
                ["primary_route", "alternate_route", "reduced_scope"],
            ),
            "ask_user",
        )
        self.assertIsNone(
            self.policy.next_path(
                "cognition",
                ["primary_route", "alternate_route", "reduced_scope", "ask_user"],
            )
        )
        # Unknown task kind falls back to the default chain.
        self.assertEqual(self.policy.next_path("nope", []), "alternate_path")

    def test_blocked_report_shape(self):
        report = self.policy.build_blocked_report(
            tried_paths=["primary_route"],
            blocking_reason="限流",
            user_action="稍后重试",
            partial_progress=["dispatched:wid-1"],
            failure_kind="rate_limit",
        )
        self.assertEqual(report["tried_paths"], ["primary_route"])
        self.assertEqual(report["blocking_reason"], "限流")
        self.assertEqual(report["needs_user_to"], "稍后重试")
        self.assertEqual(report["partial_progress"], ["dispatched:wid-1"])
        self.assertEqual(report["failure_kind"], "rate_limit")

    def test_attempts_exhaust_then_success_resets(self):
        self.assertFalse(self.policy.attempts_exhausted("wid-1", "network"))
        self.policy.record_attempt("wid-1", "network")
        self.assertFalse(self.policy.attempts_exhausted("wid-1", "network"))
        self.policy.record_attempt("wid-1", "network")
        self.assertTrue(self.policy.attempts_exhausted("wid-1", "network"))
        self.assertTrue(self.policy.note_success("wid-1"))
        self.assertFalse(self.policy.attempts_exhausted("wid-1", "network"))


class _RunnerHarness(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-failure-policy-"))
        self.store = KernelStore(self.root / "kernel.db")
        resident = SimpleNamespace(
            store=SimpleNamespace(path=str(self.root / "kernel.db"))
        )
        self.ledger = EvidenceBoundSteerableWorkLedger(resident)
        self.memory = StructuredMemory(self.store)
        self.thread_id = "thread-fp-1"
        self.ledger.create_thread(thread_id=self.thread_id, title="项目 X")
        root = WorkItem(
            work_item_id="root-1",
            work_thread_id=self.thread_id,
            title="XX 项目",
            objective="把 XX 项目做完",
            status="running",
            plan_version=1,
        )
        self.ledger._save_item(root)
        self.team = _independent_team(
            "XX 项目", ["researcher", "developer"],
            team_id="tx", thread_id=self.thread_id,
        )

    def tearDown(self):
        self.store.close()

    def _make_runner(self, verifier):
        return TeamRunner(
            team=self.team,
            ledger=self.ledger,
            memory=self.memory,
            verifier=verifier,
            root_work_item_id="root-1",
        )

    def _wid(self, plan_item_id: str) -> str:
        shared = team_shared_memory(self.memory, "tx")
        return shared.recall("plan_item_map").value[plan_item_id]

    def _claim(self, work_item_id: str):
        runs = self.ledger.list_worker_runs(work_item_id=work_item_id)
        self.assertTrue(runs, f"no run for {work_item_id}")
        run = runs[-1]
        self.ledger.complete_worker_run(
            run.worker_run_id,
            result_summary="做完了",
            claimed_completion=True,
            verification_status="pending",
        )


class TeamRunnerFailurePolicyTests(_RunnerHarness):
    def test_rate_limit_hard_stops_round_without_retry(self):
        # Three independent items: the failure hits the middle one, so the
        # test proves both partial progress (first verified) and that no
        # further work happens after the hard stop (third untouched).
        self.team = _independent_team(
            "XX 项目", ["researcher", "developer", "tester"],
            team_id="tx", thread_id=self.thread_id,
        )
        runner = self._make_runner(_FailingVerifier())
        runner.step()  # dispatch all three independent items
        plan_ids = [p.item_id for p in self.team.plan]
        wid1, wid2, wid3 = (self._wid(pid) for pid in plan_ids)
        self._claim(wid1)
        self._claim(wid2)
        self._claim(wid3)
        failing = _FailingVerifier(
            fail_on={wid2: _ProviderError("too many requests", status_code=429)}
        )
        runner = self._make_runner(failing)
        result = runner.step()
        self.assertTrue(result.hard_stopped)
        # One attempt per item, no in-round retry: wid1 verified, wid2 hit
        # the limit, wid3 never attempted.
        self.assertEqual(failing.calls, [wid1, wid2])
        self.assertIn(f"verified:{wid1}:pass", result.actions)
        self.assertNotIn(f"verified:{wid3}:pass", result.actions)
        self.assertTrue(result.escalations)
        report = result.blocked_report
        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(report["failure_kind"], "rate_limit")
        self.assertIn("限流", report["blocking_reason"])
        # Partial progress from this round is reported, not dropped.
        self.assertEqual(report["partial_progress"], [f"verified:{wid1}:pass"])

    def test_approval_bypass_blocked_before_any_side_effect(self):
        runner = self._make_runner(_FailingVerifier())
        id_map = runner.ensure_plan_items()
        plan_ids = [p.item_id for p in self.team.plan]
        wid1, wid2 = id_map[plan_ids[0]], id_map[plan_ids[1]]
        runner.record_approval_rejection(
            f"dispatch:{wid1}", "用户拒绝该派活"
        )
        result = runner.step()
        self.assertTrue(result.hard_stopped)
        # No WorkerRun was created for the rejected dispatch...
        self.assertEqual(self.ledger.list_worker_runs(work_item_id=wid1), [])
        # ...and the round stopped before dispatching the second item.
        self.assertEqual(self.ledger.list_worker_runs(work_item_id=wid2), [])
        self.assertTrue(result.escalations)
        # Rejection survives a fresh runner (owner rebuilds it per pulse).
        runner2 = self._make_runner(_FailingVerifier())
        self.assertEqual(
            runner2.failure_policy.rejected_reason(f"dispatch:{wid1}"),
            "用户拒绝该派活",
        )

    def test_retryable_failure_exhausts_into_needs_user(self):
        plan_ids = [p.item_id for p in self.team.plan]
        runner = self._make_runner(_FailingVerifier())
        runner.step()  # dispatch both
        wid1, wid2 = self._wid(plan_ids[0]), self._wid(plan_ids[1])
        self._claim(wid1)
        self._claim(wid2)
        failing = _FailingVerifier(
            fail_on={wid1: ConnectionError("connection reset")}
        )
        runner = self._make_runner(failing)
        r2 = runner.step()
        # First failure: bounded, no escalation, other item still verified.
        self.assertFalse(r2.hard_stopped)
        self.assertEqual(len(r2.escalations), 0)
        self.assertIn(f"verified:{wid2}:pass", r2.actions)
        # One attempt per item: wid1 failed once, wid2 verified once.
        self.assertEqual(failing.calls, [wid1, wid2])
        # Second consecutive failure on the same item: exhausted -> escalate.
        r3 = runner.step()
        self.assertFalse(r3.hard_stopped)
        self.assertTrue(r3.needs_user)
        self.assertEqual(len(r3.escalations), 1)
        detail = r3.escalations[0].detail
        self.assertTrue(detail.get("needs_user"))
        report = detail.get("blocked_report") or {}
        self.assertIn("连续失败", report.get("blocking_reason", ""))
        self.assertTrue(report.get("needs_user_to"))
        self.assertTrue(report.get("tried_paths"))
        # One attempt per step, no spin: wid1 failed once per step, wid2
        # verified once in the first of the two steps.
        self.assertEqual(failing.calls, [wid1, wid2, wid1])

    def test_unrecognized_error_propagates(self):
        runner = self._make_runner(_FailingVerifier())
        runner.step()
        plan_ids = [p.item_id for p in self.team.plan]
        wid1 = self._wid(plan_ids[0])
        self._claim(wid1)
        runner = self._make_runner(
            _FailingVerifier(fail_on={wid1: RuntimeError("boom")})
        )
        with self.assertRaises(RuntimeError):
            runner.step()


if __name__ == "__main__":
    unittest.main()
