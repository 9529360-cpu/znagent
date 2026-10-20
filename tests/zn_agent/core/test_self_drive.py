from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.approval_cards import (
    APPROVAL_KINDS,
    ApprovalCardStore,
)
from zn_agent.core.completion_verdict import render_completion_report
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.self_drive import (
    APPROVAL_KIND_GOAL_CONTROL,
    SELF_DRIVE_SOURCE,
    SelfDriveDriver,
    _drive_quietly,
    install_self_drive_behavior,
)


class ScriptedCognition:
    """Mock cognition: scripted JSON answers, records every question."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.questions: list[str] = []
        self.calls = 0

    def __call__(self, question: str, context: str) -> str:
        self.questions.append(question)
        self.calls += 1
        if not self.answers:
            raise AssertionError("cognition called with no scripted answer left")
        return self.answers.pop(0)


def _next_step(task, strategy="s1"):
    return json.dumps(
        {"decision": "next_step", "task": task, "strategy": strategy},
        ensure_ascii=False,
    )


def _done_report(evidence, standing_dod=None):
    conclusion = "目标已达成"
    files: list[str] = []
    unfinished: list[str] = []
    if standing_dod is None:
        standing_dod = {
            "no_regression": {
                "status": "satisfied",
                "detail": "只读推进，无回归面",
                "evidence_ref": evidence[0][1] if evidence else "",
            },
            "runtime_verified": {
                "status": "satisfied",
                "detail": "步骤均已执行",
                "evidence_ref": evidence[0][1] if evidence else "",
            },
            "docs": {"status": "not_applicable", "detail": "无需文档"},
            "rollback": {"status": "not_applicable", "detail": "只读目标，无需回滚"},
            "approval": {"status": "not_applicable", "detail": "用户目标，无需审批"},
        }
    return json.dumps(
        {
            "decision": "done",
            "completion_report": render_completion_report(
                conclusion=conclusion,
                evidence=evidence,
                files=files,
                unfinished=unfinished,
                standing_dod=standing_dod,
            ),
        },
        ensure_ascii=False,
    )


class SelfDriveTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "kernel.db"
        self.resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=self.db,
        )
        self.addCleanup(self.resident.store.close)

    def make_driver(self, cognition=None, approval_store=None, notify=None):
        return SelfDriveDriver(
            will=self.resident.will,
            store=self.resident.store,
            cognitive_invoke=cognition,
            approval_store=approval_store,
            notify=notify,
        )

    def submit(self, driver, acceptance=("产出 X",), origin="user"):
        return driver.submit_goal(
            "整理下载目录", acceptance=list(acceptance), origin=origin
        )

    def run_step(self, intention_id, success=True, summary="step done"):
        """Simulate the ordinary event pipeline finishing one queued step."""
        intention = self.resident.will.get(intention_id)
        self.assertIsNotNone(intention.next_task, "expected a queued step")
        event_id = f"evt-{len(self.resident.will.get(intention_id).progress):03d}"
        self.resident.will.engage(intention_id, event_id)
        self.resident.will.observe_event_outcome(
            intention_id, event_id=event_id, success=success, summary=summary
        )
        return event_id


class IntakeTests(SelfDriveTestBase):
    def test_goal_control_kind_registered(self):
        self.assertIn(APPROVAL_KIND_GOAL_CONTROL, APPROVAL_KINDS)

    def test_submit_user_goal_starts_immediately(self):
        cognition = ScriptedCognition([_next_step("列出下载目录文件")])
        driver = self.make_driver(cognition=cognition)
        intention = self.submit(driver)
        self.assertEqual(intention.source, SELF_DRIVE_SOURCE)
        summary = driver.drive()
        self.assertEqual(summary["steps_proposed"], 1)
        refreshed = self.resident.will.get(intention.intention_id)
        self.assertEqual(refreshed.next_task, "列出下载目录文件")
        goal = driver.get_goal(intention.intention_id)
        self.assertEqual(goal["last_strategy"], "s1")
        self.assertIsNone(goal["blocked_reason"])

    def test_submit_rejects_empty_acceptance(self):
        driver = self.make_driver()
        with self.assertRaises(ValueError):
            driver.submit_goal("目标", acceptance=[])
        with self.assertRaises(ValueError):
            driver.submit_goal("目标", acceptance=["  "])

    def test_submit_rejects_unknown_origin(self):
        driver = self.make_driver()
        with self.assertRaises(ValueError):
            driver.submit_goal("目标", acceptance=["产出 X"], origin="cron")


class CrossPulseAdvanceTests(SelfDriveTestBase):
    def test_advances_across_pulses_until_cp3_verified(self):
        cognition = ScriptedCognition(
            [
                _next_step("列出下载目录文件", "enumerate"),
                _next_step("按类型归档", "organize"),
            ]
        )
        driver = self.make_driver(cognition=cognition)
        intention = self.submit(driver, acceptance=("产出清单", "完成归档"))
        gid = intention.intention_id

        driver.drive()
        self.run_step(gid, success=True, summary="列出 12 个文件")
        driver.drive()
        self.run_step(gid, success=True, summary="归档完成")

        # Third pulse: cognition claims done; the report must cite real steps.
        cognition.answers.append(
            _done_report(
                [
                    ("产出清单", "列出下载目录文件"),
                    ("完成归档", "按类型归档"),
                ]
            )
        )
        summary = driver.drive()
        self.assertEqual(summary["completions"], 1)
        refreshed = self.resident.will.get(gid)
        self.assertEqual(refreshed.status, "completed")
        goal = driver.get_goal(gid)
        self.assertEqual(len(goal["step_history"]), 2)
        self.assertTrue(all(s["success"] for s in goal["step_history"]))

    def test_no_cognition_waits_quietly(self):
        driver = self.make_driver(cognition=None)
        intention = self.submit(driver)
        summary = driver.drive()
        self.assertEqual(summary["steps_proposed"], 0)
        refreshed = self.resident.will.get(intention.intention_id)
        self.assertIsNone(refreshed.next_task)
        self.assertEqual(refreshed.status, "active")


class RerouteTests(SelfDriveTestBase):
    def test_failure_switches_strategy_with_avoid_block(self):
        answers = [
            _next_step("用 A 方式同步", "plan-a"),
            _next_step("改用 B 方式同步", "plan-b"),
        ]
        cognition = ScriptedCognition(answers)
        driver = self.make_driver(cognition=cognition)
        intention = self.submit(driver)
        gid = intention.intention_id

        driver.drive()
        self.run_step(gid, success=False, summary="permission denied by policy")
        driver.drive()

        # The second cognition question must carry the tried-strategy block.
        self.assertEqual(cognition.calls, 2)
        self.assertIn("plan-a", cognition.questions[1])
        refreshed = self.resident.will.get(gid)
        self.assertEqual(refreshed.next_task, "改用 B 方式同步")
        goal = driver.get_goal(gid)
        self.assertEqual(goal["last_strategy"], "plan-b")

    def test_exhausted_strategies_block_explicitly(self):
        cognition = ScriptedCognition(
            [_next_step(f"尝试{i}", f"plan-{i}") for i in range(6)]
        )
        notes: list[str] = []
        driver = self.make_driver(cognition=cognition, notify=notes.append)
        intention = self.submit(driver)
        gid = intention.intention_id

        for _ in range(4):
            driver.drive()
            self.run_step(gid, success=False, summary="not found: resource missing")
        summary = driver.drive()

        refreshed = self.resident.will.get(gid)
        self.assertEqual(refreshed.status, "blocked")
        goal = driver.get_goal(gid)
        self.assertIn("连续", goal["blocked_reason"])
        self.assertGreaterEqual(summary["blocks"], 1)
        self.assertTrue(any("显式阻塞" in note for note in notes))

    def test_identical_failure_twice_blocks_at_once(self):
        cognition = ScriptedCognition(
            [
                _next_step("同一任务", "same-plan"),
                _next_step("同一任务", "same-plan"),
            ]
        )
        driver = self.make_driver(cognition=cognition)
        intention = self.submit(driver)
        gid = intention.intention_id

        driver.drive()
        self.run_step(gid, success=False, summary="boom")
        driver.drive()
        self.run_step(gid, success=False, summary="boom")
        driver.drive()

        refreshed = self.resident.will.get(gid)
        self.assertEqual(refreshed.status, "blocked")
        self.assertIn("2 次", driver.get_goal(gid)["blocked_reason"])


class VerdictGateTests(SelfDriveTestBase):
    def test_partial_verdict_retries_with_feedback(self):
        bad_report = _done_report([("产出清单", "列出下载目录文件")])
        cognition = ScriptedCognition(
            [_next_step("列出下载目录文件", "enumerate"), bad_report]
        )
        driver = self.make_driver(cognition=cognition)
        intention = self.submit(driver, acceptance=("产出清单", "完成归档"))
        gid = intention.intention_id

        driver.drive()
        self.run_step(gid, success=True, summary="列出 12 个文件")

        # First done claim: one criterion uncovered -> partial -> bounded
        # retry step, the goal stays active and owns the retry budget.
        driver.drive()
        refreshed = self.resident.will.get(gid)
        self.assertIsNotNone(refreshed.next_task)
        self.assertIn("完成裁决", refreshed.next_task)
        self.assertEqual(refreshed.status, "active")
        tracking = driver.get_goal(gid)["verdict_tracking"]
        self.assertEqual(tracking["attempts"], 1)
        self.assertFalse(tracking["consecutive_same"] >= 2)

    def test_identical_failing_verdict_escalates_at_once(self):
        # Mirrors the M-5 single-Work gate: the second consecutive identical
        # verdict escalates immediately instead of burning the retry budget.
        bad_report = _done_report([("产出清单", "列出下载目录文件")])
        cognition = ScriptedCognition(
            [_next_step("列出下载目录文件", "enumerate")] + [bad_report] * 2
        )
        driver = self.make_driver(cognition=cognition)
        intention = self.submit(driver, acceptance=("产出清单", "完成归档"))
        gid = intention.intention_id

        driver.drive()
        self.run_step(gid, success=True, summary="列出 12 个文件")
        driver.drive()  # partial -> retry queued
        self.assertEqual(self.resident.will.get(gid).status, "active")

        self.run_step(gid, success=True, summary="补救步骤完成")
        driver.drive()  # identical verdict again -> escalate at once
        refreshed = self.resident.will.get(gid)
        self.assertEqual(refreshed.status, "blocked")
        self.assertIn("完成裁决", driver.get_goal(gid)["blocked_reason"])

    def test_rejected_report_does_not_complete(self):
        cognition = ScriptedCognition(
            [
                _next_step("做点事", "s"),
                json.dumps({"decision": "done", "completion_report": "not json"}),
            ]
        )
        driver = self.make_driver(cognition=cognition)
        intention = self.submit(driver)
        gid = intention.intention_id
        driver.drive()
        self.run_step(gid, success=True, summary="ok")
        # Malformed report is invalid -> counts toward invalid streak, no completion.
        driver.drive()
        refreshed = self.resident.will.get(gid)
        self.assertNotEqual(refreshed.status, "completed")


class InvalidCognitionTests(SelfDriveTestBase):
    def test_three_invalid_answers_block_explicitly(self):
        cognition = ScriptedCognition(["garbage", "{}", "[]"])
        driver = self.make_driver(cognition=cognition)
        intention = self.submit(driver)
        gid = intention.intention_id
        for _ in range(3):
            driver.drive()
        refreshed = self.resident.will.get(gid)
        self.assertEqual(refreshed.status, "blocked")
        self.assertIn("不可用", driver.get_goal(gid)["blocked_reason"])


class ControlTests(SelfDriveTestBase):
    def test_user_pause_and_resume(self):
        cognition = ScriptedCognition([_next_step("做点事"), _next_step("继续做")])
        driver = self.make_driver(cognition=cognition)
        intention = self.submit(driver)
        gid = intention.intention_id

        self.assertEqual(driver.pause_goal(gid, by="user", reason="稍等"), "paused")
        self.assertEqual(self.resident.will.get(gid).status, "paused")
        summary = driver.drive()
        self.assertEqual(summary["steps_proposed"], 0)

        self.assertEqual(driver.resume_goal(gid, by="user"), "resumed")
        driver.drive()
        self.assertIsNotNone(self.resident.will.get(gid).next_task)

    def test_user_redirect_resets_generation_and_drops_pending_step(self):
        cognition = ScriptedCognition([_next_step("旧方向步骤")])
        driver = self.make_driver(cognition=cognition)
        intention = self.submit(driver)
        gid = intention.intention_id
        driver.drive()
        self.assertIsNotNone(self.resident.will.get(gid).next_task)

        result = driver.redirect_goal(
            gid, new_objective="改做新方向", new_acceptance=["新产出"], by="user"
        )
        self.assertEqual(result, "redirected")
        goal = driver.get_goal(gid)
        self.assertEqual(goal["objective"], "改做新方向")
        self.assertEqual(goal["acceptance"], ["新产出"])
        self.assertEqual(goal["generation"], 2)
        self.assertIsNone(goal["strategy_ledger"])
        refreshed = self.resident.will.get(gid)
        self.assertIsNone(refreshed.next_task, "stale step must not run under new objective")

    def test_redirect_deferred_while_step_in_flight(self):
        cognition = ScriptedCognition([_next_step("旧方向步骤"), _next_step("新方向步骤")])
        driver = self.make_driver(cognition=cognition)
        intention = self.submit(driver)
        gid = intention.intention_id
        driver.drive()
        # Engage the step manually: now a step is in flight.
        self.resident.will.engage(gid, "evt-1")

        result = driver.redirect_goal(gid, new_objective="改做新方向", by="user")
        self.assertEqual(result, "deferred")
        self.assertEqual(driver.get_goal(gid)["generation"], 1)

        self.resident.will.observe_event_outcome(
            gid, event_id="evt-1", success=True, summary="旧步骤完成"
        )
        driver.drive()
        goal = driver.get_goal(gid)
        self.assertEqual(goal["objective"], "改做新方向")
        self.assertEqual(goal["generation"], 2)

    def test_pause_by_resident_fail_closed_without_channel(self):
        driver = self.make_driver(cognition=None, approval_store=None)
        intention = self.submit(driver)
        gid = intention.intention_id
        result = driver.pause_goal(gid, by="resident", reason="预算将超")
        self.assertEqual(result, "paused-fail-closed")
        self.assertEqual(self.resident.will.get(gid).status, "paused")

    def test_unknown_goal_raises(self):
        driver = self.make_driver()
        with self.assertRaises(ValueError):
            driver.pause_goal("intent-nope", by="user")


class ApprovalEnvelopeTests(SelfDriveTestBase):
    def _approval_store(self):
        return ApprovalCardStore(self.db)

    def test_resident_goal_needs_approval_to_start(self):
        store = self._approval_store()
        cognition = ScriptedCognition([_next_step("做点事")])
        driver = self.make_driver(cognition=cognition, approval_store=store)
        intention = driver.submit_goal(
            "ZN 自己发现的目标", acceptance=["产出 X"], origin="resident"
        )
        gid = intention.intention_id

        goal = driver.get_goal(gid)
        self.assertIsNotNone(goal["pending_control"])
        self.assertEqual(goal["pending_control"]["action"], "start")
        card_id = goal["pending_control"]["card_id"]

        # Still waiting: no step proposed.
        driver.drive()
        self.assertIsNone(self.resident.will.get(gid).next_task)

        store.decide(card_id, "allow_once")
        summary = driver.drive()
        self.assertEqual(summary["steps_proposed"], 1)
        self.assertIsNotNone(self.resident.will.get(gid).next_task)

    def test_denied_start_blocks_without_reask(self):
        store = self._approval_store()
        driver = self.make_driver(cognition=None, approval_store=store)
        intention = driver.submit_goal(
            "ZN 自己发现的目标", acceptance=["产出 X"], origin="resident"
        )
        gid = intention.intention_id
        card_id = driver.get_goal(gid)["pending_control"]["card_id"]

        store.decide(card_id, "deny")
        driver.drive()
        refreshed = self.resident.will.get(gid)
        self.assertEqual(refreshed.status, "blocked")
        self.assertIn("拒绝", driver.get_goal(gid)["blocked_reason"])
        # Deny is sticky: submitting again does not reopen the question here;
        # the recorded denial stays on the goal.
        self.assertTrue(driver.get_goal(gid)["control_denied"]["start"])

    def test_resident_goal_fail_closed_without_approval_channel(self):
        driver = self.make_driver(cognition=None, approval_store=None)
        intention = driver.submit_goal(
            "ZN 自己发现的目标", acceptance=["产出 X"], origin="resident"
        )
        refreshed = self.resident.will.get(intention.intention_id)
        self.assertEqual(refreshed.status, "blocked")
        self.assertIn("审批", driver.get_goal(intention.intention_id)["blocked_reason"])

    def test_goal_control_scope_is_concrete(self):
        store = self._approval_store()
        driver = self.make_driver(approval_store=store)
        intention = driver.submit_goal(
            "ZN 自己发现的目标", acceptance=["产出 X"], origin="resident"
        )
        card_id = driver.get_goal(intention.intention_id)["pending_control"]["card_id"]
        request = store.get_request(card_id)
        self.assertEqual(request.action_kind, APPROVAL_KIND_GOAL_CONTROL)
        self.assertTrue(
            request.scope.startswith(
                f"self-drive-goal:{intention.intention_id}:start"
            )
        )
        self.assertNotIn("*", request.scope)

    def test_broken_approval_channel_blocks_fail_closed(self):
        class ExplodingApprovalStore:
            def request_approval(self, **kwargs):
                raise RuntimeError("store down")

            def get_request(self, request_id):
                raise RuntimeError("store down")

        driver = self.make_driver(
            cognition=None, approval_store=ExplodingApprovalStore()
        )
        # No orphan: the intention is blocked, never left active undecided.
        intention = driver.submit_goal(
            "ZN 自己发现的目标", acceptance=["产出 X"], origin="resident"
        )
        refreshed = self.resident.will.get(intention.intention_id)
        self.assertEqual(refreshed.status, "blocked")
        self.assertIn("fail closed", driver.get_goal(intention.intention_id)["blocked_reason"])
        self.assertTrue(driver._recent_errors)

    def test_resident_pause_with_broken_channel_fail_closed(self):
        class ExplodingApprovalStore:
            def request_approval(self, **kwargs):
                raise RuntimeError("store down")

            def get_request(self, request_id):
                raise RuntimeError("store down")

        driver = self.make_driver(
            cognition=None, approval_store=ExplodingApprovalStore()
        )
        intention = self.submit(driver)
        gid = intention.intention_id
        # Never raises into the cognition loop; fails closed instead.
        result = driver.pause_goal(gid, by="resident", reason="预算将超")
        self.assertEqual(result, "paused-fail-closed")
        self.assertEqual(self.resident.will.get(gid).status, "paused")


class PruneTests(SelfDriveTestBase):
    def test_prune_keeps_active_and_newest_terminal(self):
        driver = self.make_driver(cognition=None, approval_store=None)
        blocked_ids = [
            driver.submit_goal(
                f"ZN 目标 {i}", acceptance=["产出 X"], origin="resident"
            ).intention_id
            for i in range(3)
        ]
        active = self.submit(driver)
        self.assertEqual(
            self.resident.will.get(active.intention_id).status, "active"
        )

        driver._prune_terminal_goals(keep=1)
        remaining = {item["intention_id"] for item in driver.list_goals(limit=100)}
        # The active goal is never pruned; only the newest terminal survives.
        self.assertIn(active.intention_id, remaining)
        self.assertIn(blocked_ids[-1], remaining)
        self.assertNotIn(blocked_ids[0], remaining)
        self.assertNotIn(blocked_ids[1], remaining)


class InstallTests(SelfDriveTestBase):
    def test_install_wraps_pulse_and_exposes_driver(self):
        cognition = ScriptedCognition([_next_step("做点事")])
        driver = install_self_drive_behavior(
            self.resident, cognitive_invoke=cognition
        )
        self.assertIsNotNone(driver)
        self.assertIs(self.resident.self_drive, driver)
        intention = driver.submit_goal("目标", acceptance=["产出 X"])
        self.resident.pulse()
        self.assertIsNotNone(self.resident.will.get(intention.intention_id).next_task)
        # Second install is idempotent.
        again = install_self_drive_behavior(self.resident)
        self.assertIs(again, driver)

    def test_drive_error_never_breaks_pulse(self):
        class ExplodingDriver:
            def __init__(self):
                self.errors: list[str] = []

            def drive(self):
                raise RuntimeError("boom")

            def note_driver_error(self, text: str):
                self.errors.append(text)

        class FakeResident:
            def __init__(self):
                self.will = object()
                self.store = object()
                self.pulse_calls = 0

            def pulse(self):
                self.pulse_calls += 1
                return "pulse-ok"

        resident = FakeResident()
        exploding = ExplodingDriver()
        original = resident.pulse

        def pulse():
            _drive_quietly(exploding)
            return original()

        resident.pulse = pulse
        self.assertEqual(resident.pulse(), "pulse-ok")
        self.assertEqual(resident.pulse_calls, 1)
        self.assertTrue(exploding.errors)

    def test_install_requires_will_and_store(self):
        with self.assertRaises(ValueError):
            install_self_drive_behavior(object())


class RetiredDirectionGuardTests(unittest.TestCase):
    """M-14 must not resurrect the retired self-maintenance control plane."""

    def test_no_maintenance_control_plane_vocabulary(self):
        path = Path(__file__).resolve().parents[3] / "runtime" / "python" / "zn_agent" / "core" / "self_drive.py"
        text = path.read_text(encoding="utf-8").lower()
        forbidden = [
            "maintenance",
            "self_repair",
            "self-repair",
            "self_heal",
            "auto_fix",
            "autofix",
            "bug_report",
            "bugreport",
        ]
        hits = [token for token in forbidden if token in text]
        self.assertEqual(hits, [], f"retired self-maintenance vocabulary: {hits}")

    def test_no_new_daemon_rpc_surface(self):
        text = Path(__file__).resolve().parents[3] / "runtime" / "python" / "zn_agent" / "core" / "self_drive.py"
        source = text.read_text(encoding="utf-8")
        self.assertNotIn("daemon", source)
        self.assertNotIn("add_rpc", source)
        self.assertNotIn("rpc_method", source)

    def test_no_second_state_machine(self):
        text = Path(__file__).resolve().parents[3] / "runtime" / "python" / "zn_agent" / "core" / "self_drive.py"
        source = text.read_text(encoding="utf-8")
        # The goal lifecycle is NativeWill's; the driver must not define its
        # own status enum or transition table.
        self.assertNotIn("class GoalState", source)
        self.assertNotIn("class SelfDriveState", source)


if __name__ == "__main__":
    unittest.main()
