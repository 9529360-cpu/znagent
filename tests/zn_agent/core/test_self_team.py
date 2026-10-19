from __future__ import annotations

"""M-12: ZN's own judgment to assemble a parallel specialist team.

Covers the pure decision (mock cognition), the approval/budget envelope,
the durable driver, and the plan shaping for self-assembled teams. The
model is always a mock here -- the point is ZN's judgment and guards,
not model quality.
"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.approval_cards import ApprovalCardStore
from zn_agent.core.project_team import assemble_team
from zn_agent.core.self_team import (
    DECIDE_ASSEMBLE,
    DECIDE_NEEDS_APPROVAL,
    DECIDE_NOT_APPLICABLE,
    DECIDE_NO_TEAM,
    DECIDE_PENDING_APPROVAL,
    SELF_TEAM_STATE_KEY,
    SelfTeamDecision,
    SelfTeamDriver,
    SelfTeamEnvelope,
    SelfTeamWorkOwner,
    apply_self_team_plan,
    check_self_team_envelope,
    decide_self_team,
    inject_self_team_request,
    prescreen_self_team,
)
from zn_agent.core.team_work_owner import TeamWorkOwner

_TASK_PARALLEL = (
    "同时推进三件事：1. 调研三家竞品的定价策略；"
    "2. 设计我们自己的计费模块架构；3. 给现有计费代码补集成测试"
)


def _cognition_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _assemble_answer(*, parallel=True, roles=("researcher", "architect", "tester")):
    subtasks = {
        "researcher": "调研三家竞品的定价策略并输出对比",
        "architect": "设计计费模块架构与接口契约",
        "developer": "实现计费模块核心逻辑",
        "tester": "给计费模块补集成测试",
    }
    return _cognition_json(
        {
            "assemble": True,
            "reason": "三个子任务相互独立、可并行",
            "project_title": "计费模块攻坚",
            "role_keys": list(roles),
            "subtasks": [subtasks.get(role, f"子任务-{role}") for role in roles],
            "parallel": parallel,
        }
    )


def _mock_invoke(text: str, calls: list | None = None):
    def invoke(question: str, context: str) -> str:
        if calls is not None:
            calls.append(question)
        return text

    return invoke


def _event(task: str, **payload_overrides):
    payload = {
        "work_thread_id": "thread-1",
        "workspace_path": "/tmp/ws",
    }
    payload.update(payload_overrides)
    return SimpleNamespace(
        task=task, payload=payload, event_id="evt-1", priority=0
    )


def _state():
    return SimpleNamespace(data={})


class _Kernel:
    """Fake kernel: one bounded run_goal call returning canned model text."""

    def __init__(self, response: str, calls: list | None = None) -> None:
        self._response = response
        self.calls: list = calls if calls is not None else []

    def run_goal(self, question, **kwargs):
        self.calls.append(question)
        return SimpleNamespace(
            worker_result=SimpleNamespace(success=True, response=self._response),
            assessment=SimpleNamespace(success=True),
        )


class _Store:
    """ApprovalCardStore with a save_working_state hook for the driver."""

    def __init__(self, cards: ApprovalCardStore) -> None:
        self._cards = cards
        self.saved: list = []

    def save_working_state(self, state) -> None:
        self.saved.append(state)

    def __getattr__(self, name):
        return getattr(self._cards, name)


class PrescreenTest(unittest.TestCase):
    def test_small_task_never_reaches_cognition(self):
        calls: list = []
        decision = decide_self_team(
            "帮我写个脚本",
            cognitive_invoke=_mock_invoke("{}", calls),
        )
        self.assertEqual(decision.decision, DECIDE_NO_TEAM)
        self.assertEqual(calls, [])

    def test_empty_task(self):
        decision = decide_self_team("", cognitive_invoke=_mock_invoke("{}"))
        self.assertEqual(decision.decision, DECIDE_NO_TEAM)

    def test_explicit_optout(self):
        calls: list = []
        decision = decide_self_team(
            "调研一下竞品定价，不要组队，我自己看",
            cognitive_invoke=_mock_invoke("{}", calls),
        )
        self.assertEqual(decision.decision, DECIDE_NO_TEAM)
        self.assertEqual(calls, [])

    def test_explicit_team_ask_stays_on_user_path(self):
        calls: list = []
        decision = decide_self_team(
            "给计费项目组个团队",
            cognitive_invoke=_mock_invoke("{}", calls),
        )
        self.assertEqual(decision.decision, DECIDE_NO_TEAM)
        self.assertIn("用户", decision.reason)
        self.assertEqual(calls, [])

    def test_parallel_signals_route_to_cognition(self):
        calls: list = []
        decide_self_team(
            _TASK_PARALLEL, cognitive_invoke=_mock_invoke(_assemble_answer(), calls)
        )
        self.assertEqual(len(calls), 1)


class CognitionDecisionTest(unittest.TestCase):
    def test_assemble_parallel(self):
        decision = decide_self_team(
            _TASK_PARALLEL, cognitive_invoke=_mock_invoke(_assemble_answer())
        )
        self.assertEqual(decision.decision, DECIDE_ASSEMBLE)
        self.assertEqual(decision.role_keys, ("researcher", "architect", "tester"))
        self.assertEqual(len(decision.subtasks), 3)
        self.assertTrue(decision.parallel)
        self.assertTrue(decision.project_title)

    def test_cognition_declines(self):
        decision = decide_self_team(
            "把这篇长文档总结成三段话，顺便列出里面的数字",
            cognitive_invoke=_mock_invoke(
                _cognition_json(
                    {"assemble": False, "reason": "单人一步可做完，无并行收益"}
                )
            ),
        )
        self.assertEqual(decision.decision, DECIDE_NO_TEAM)

    def test_garbage_answer_fails_closed(self):
        decision = decide_self_team(
            _TASK_PARALLEL, cognitive_invoke=_mock_invoke("组队吧！相信我")
        )
        self.assertEqual(decision.decision, DECIDE_NO_TEAM)

    def test_unknown_role_rejected(self):
        decision = decide_self_team(
            _TASK_PARALLEL,
            cognitive_invoke=_mock_invoke(
                _assemble_answer(roles=("researcher", "ceo", "tester"))
            ),
        )
        self.assertEqual(decision.decision, DECIDE_NO_TEAM)

    def test_duplicate_roles_rejected(self):
        decision = decide_self_team(
            _TASK_PARALLEL,
            cognitive_invoke=_mock_invoke(
                _assemble_answer(roles=("researcher", "researcher", "tester"))
            ),
        )
        self.assertEqual(decision.decision, DECIDE_NO_TEAM)

    def test_cognition_exception_fails_closed(self):
        def boom(question: str, context: str) -> str:
            raise RuntimeError("provider down")

        decision = decide_self_team(_TASK_PARALLEL, cognitive_invoke=boom)
        self.assertEqual(decision.decision, DECIDE_NO_TEAM)

    def test_cognition_disabled(self):
        calls: list = []
        decision = decide_self_team(
            _TASK_PARALLEL,
            allow_cognition=False,
            cognitive_invoke=_mock_invoke(_assemble_answer(), calls),
        )
        self.assertEqual(decision.decision, DECIDE_NO_TEAM)
        self.assertEqual(calls, [])

    def test_missing_parallel_flag_defaults_to_chain(self):
        payload = json.loads(_assemble_answer())
        del payload["parallel"]
        decision = decide_self_team(
            _TASK_PARALLEL, cognitive_invoke=_mock_invoke(json.dumps(payload))
        )
        self.assertEqual(decision.decision, DECIDE_ASSEMBLE)
        self.assertFalse(decision.parallel)

    def test_model_text_is_sanitized(self):
        decision = decide_self_team(
            _TASK_PARALLEL,
            cognitive_invoke=_mock_invoke(
                _cognition_json(
                    {
                        "assemble": True,
                        "reason": "<b>并行</b>",
                        "project_title": "<script>x</script>计费",
                        "role_keys": ["researcher", "tester"],
                        "subtasks": ["<i>调研</i>竞品", "补测试"],
                        "parallel": True,
                    }
                )
            ),
        )
        self.assertEqual(decision.decision, DECIDE_ASSEMBLE)
        self.assertNotIn("<", decision.project_title)
        self.assertNotIn("<", decision.subtasks[0])


class EnvelopeTest(unittest.TestCase):
    def _assemble(self) -> SelfTeamDecision:
        decision = decide_self_team(
            _TASK_PARALLEL, cognitive_invoke=_mock_invoke(_assemble_answer())
        )
        self.assertEqual(decision.decision, DECIDE_ASSEMBLE)
        return decision

    def test_inside_envelope_passes_through(self):
        decision = check_self_team_envelope(self._assemble(), _TASK_PARALLEL)
        self.assertEqual(decision.decision, DECIDE_ASSEMBLE)

    def test_over_budget_needs_approval(self):
        decision = decide_self_team(
            _TASK_PARALLEL,
            cognitive_invoke=_mock_invoke(_assemble_answer()),
            envelope=SelfTeamEnvelope(max_specialists=2),
        )
        self.assertEqual(decision.decision, DECIDE_NEEDS_APPROVAL)
        self.assertIn("2", decision.needs_approval_reason)

    def test_sensitive_task_needs_approval(self):
        task = "把各系统的登录密码整理成一张表发我，同时把旧系统的账号数据导出来备份"
        decision = decide_self_team(
            task, cognitive_invoke=_mock_invoke(_assemble_answer())
        )
        self.assertEqual(decision.decision, DECIDE_NEEDS_APPROVAL)
        self.assertIn("敏感", decision.needs_approval_reason)

    def test_envelope_ignores_no_team(self):
        decision = SelfTeamDecision(decision=DECIDE_NO_TEAM, reason="小任务")
        out = check_self_team_envelope(
            decision, _TASK_PARALLEL, envelope=SelfTeamEnvelope(max_specialists=1)
        )
        self.assertEqual(out.decision, DECIDE_NO_TEAM)


class InjectTest(unittest.TestCase):
    def test_assemble_injects_user_path_payload(self):
        decision = decide_self_team(
            _TASK_PARALLEL, cognitive_invoke=_mock_invoke(_assemble_answer())
        )
        event = _event(_TASK_PARALLEL)
        self.assertTrue(inject_self_team_request(event, decision))
        self.assertTrue(TeamWorkOwner.handles(event))
        request = event.payload["team_request"]
        self.assertTrue(request["self_team"])
        self.assertEqual(request["project_title"], decision.project_title)
        self.assertEqual(list(request["role_keys"]), list(decision.role_keys))

    def test_never_overrides_existing_team_request(self):
        event = _event(
            "给计费项目组个团队",
            team_request={"project_title": "计费", "role_keys": ["researcher"]},
        )
        decision = SelfTeamDecision(
            decision=DECIDE_ASSEMBLE,
            reason="x",
            project_title="other",
            role_keys=("tester",),
        )
        self.assertFalse(inject_self_team_request(event, decision))
        self.assertEqual(event.payload["team_request"]["project_title"], "计费")

    def test_no_team_injects_nothing(self):
        event = _event("帮我写个脚本")
        decision = SelfTeamDecision(decision=DECIDE_NO_TEAM, reason="小")
        self.assertFalse(inject_self_team_request(event, decision))
        self.assertNotIn("team_request", event.payload)


class ApplyPlanTest(unittest.TestCase):
    def _team(self):
        return assemble_team(
            "计费模块攻坚",
            ("researcher", "architect", "tester"),
            team_id="team-test",
        )

    def test_parallel_drops_dependencies_and_sets_objectives(self):
        team = self._team()
        request = {
            "self_team": True,
            "self_team_subtasks": ["调研竞品", "设计架构", "补测试"],
            "self_team_parallel": True,
        }
        out = apply_self_team_plan(team, request)
        self.assertEqual(
            [item.objective for item in out.plan], ["调研竞品", "设计架构", "补测试"]
        )
        for item in out.plan:
            self.assertEqual(item.dependency_ids, ())

    def test_sequential_keeps_chain(self):
        team = self._team()
        request = {
            "self_team": True,
            "self_team_subtasks": ["调研竞品", "设计架构", "补测试"],
            "self_team_parallel": False,
        }
        out = apply_self_team_plan(team, request)
        self.assertEqual(out.plan[0].dependency_ids, ())
        self.assertEqual(out.plan[1].dependency_ids, (out.plan[0].item_id,))
        self.assertEqual(out.plan[2].dependency_ids, (out.plan[1].item_id,))

    def test_length_mismatch_keeps_safe_plan(self):
        team = self._team()
        before = [item.objective for item in team.plan]
        out = apply_self_team_plan(
            team,
            {
                "self_team": True,
                "self_team_subtasks": ["只有一条"],
                "self_team_parallel": True,
            },
        )
        self.assertEqual([item.objective for item in out.plan], before)


class DriverTest(unittest.TestCase):
    def _driver(self, kernel, store=None, envelope=None):
        return SelfTeamDriver(
            kernel=kernel, budget=None, store=store, envelope=envelope
        )

    def test_not_applicable_without_workspace(self):
        event = _event("帮我写个脚本", workspace_path="")
        driver = self._driver(_Kernel("{}"))
        self.assertFalse(SelfTeamDriver.consider(event))
        self.assertEqual(driver.step(event, _state()), DECIDE_NOT_APPLICABLE)

    def test_team_event_not_considered(self):
        event = _event(
            "给计费项目组个团队",
            team_request={"project_title": "计费", "role_keys": ["researcher"]},
        )
        self.assertFalse(SelfTeamDriver.consider(event))

    def test_assemble_once_then_cached(self):
        calls: list = []
        kernel = _Kernel(_assemble_answer(), calls)
        driver = self._driver(kernel)
        event = _event(_TASK_PARALLEL)
        state = _state()
        self.assertEqual(driver.step(event, state), DECIDE_ASSEMBLE)
        self.assertTrue(TeamWorkOwner.handles(event))
        self.assertIn(SELF_TEAM_STATE_KEY, state.data)
        # Same pulse, second call: the event already carries the injected
        # team_request, so the driver correctly reports the team path owns
        # it now -- and no second cognition call happened.
        self.assertEqual(driver.step(event, state), DECIDE_NOT_APPLICABLE)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            state.data[SELF_TEAM_STATE_KEY]["decision"], DECIDE_ASSEMBLE
        )

    def test_next_pulse_reinjects_from_durable_record(self):
        # Across pulses the event is reloaded without the in-memory
        # injection; the durable record must re-inject it without another
        # cognition call.
        calls: list = []
        kernel = _Kernel(_assemble_answer(), calls)
        driver = self._driver(kernel)
        event = _event(_TASK_PARALLEL)
        state = _state()
        self.assertEqual(driver.step(event, state), DECIDE_ASSEMBLE)
        # Simulate the next pulse: fresh event object, same working state.
        event2 = _event(_TASK_PARALLEL)
        self.assertFalse(TeamWorkOwner.handles(event2))
        self.assertEqual(driver.step(event2, state), DECIDE_ASSEMBLE)
        self.assertTrue(TeamWorkOwner.handles(event2))
        self.assertEqual(len(calls), 1)

    def test_no_team_passes_through(self):
        kernel = _Kernel(
            _cognition_json({"assemble": False, "reason": "单人可做完"})
        )
        driver = self._driver(kernel)
        event = _event("把这篇长文档总结成三段话，顺便列出里面的数字和结论")
        state = _state()
        self.assertEqual(driver.step(event, state), DECIDE_NO_TEAM)
        self.assertNotIn("team_request", event.payload)

    def test_record_roundtrip(self):
        decision = decide_self_team(
            _TASK_PARALLEL, cognitive_invoke=_mock_invoke(_assemble_answer())
        )
        revived = SelfTeamDecision.from_record(decision.to_record())
        self.assertIsNotNone(revived)
        assert revived is not None
        self.assertEqual(revived.decision, DECIDE_ASSEMBLE)
        self.assertEqual(revived.role_keys, decision.role_keys)
        self.assertTrue(revived.parallel)
        self.assertIsNone(SelfTeamDecision.from_record({"decision": "bogus"}))
        self.assertIsNone(SelfTeamDecision.from_record(None))

    def test_self_team_owner_is_team_owner(self):
        self.assertTrue(issubclass(SelfTeamWorkOwner, TeamWorkOwner))


class ApprovalFlowTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cards = ApprovalCardStore(str(Path(self._tmp.name) / "test.db"))

    def _driver(self, kernel):
        return SelfTeamDriver(
            kernel=kernel,
            budget=None,
            store=_Store(self.cards),
            envelope=SelfTeamEnvelope(max_specialists=2),
        )

    def _pending_event(self):
        kernel = _Kernel(_assemble_answer())
        driver = self._driver(kernel)
        event = _event(_TASK_PARALLEL)
        state = _state()
        self.assertEqual(driver.step(event, state), DECIDE_PENDING_APPROVAL)
        return driver, event, state

    def test_needs_approval_opens_card_and_waits(self):
        driver, event, state = self._pending_event()
        record = state.data[SELF_TEAM_STATE_KEY]
        request_id = record["approval_request_id"]
        self.assertTrue(request_id)
        pending = self.cards.pending_requests()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].action_kind, "team_assembly")
        # Still pending on the next pulse: no second card, no assembly.
        self.assertEqual(driver.step(event, state), DECIDE_PENDING_APPROVAL)
        self.assertEqual(len(self.cards.pending_requests()), 1)
        self.assertNotIn("team_request", event.payload)

    def test_approved_assembles(self):
        driver, event, state = self._pending_event()
        request_id = state.data[SELF_TEAM_STATE_KEY]["approval_request_id"]
        self.cards.decide(request_id, "allow_once")
        self.assertEqual(driver.step(event, state), DECIDE_ASSEMBLE)
        self.assertTrue(TeamWorkOwner.handles(event))
        self.assertTrue(event.payload["team_request"]["self_team"])

    def test_denied_stays_solo(self):
        driver, event, state = self._pending_event()
        request_id = state.data[SELF_TEAM_STATE_KEY]["approval_request_id"]
        self.cards.decide(request_id, "deny")
        self.assertEqual(driver.step(event, state), DECIDE_NO_TEAM)
        self.assertNotIn("team_request", event.payload)

    def test_no_store_fails_closed(self):
        kernel = _Kernel(_assemble_answer())
        driver = SelfTeamDriver(
            kernel=kernel,
            budget=None,
            store=SimpleNamespace(save_working_state=lambda s: None),
            envelope=SelfTeamEnvelope(max_specialists=2),
        )
        event = _event(_TASK_PARALLEL)
        state = _state()
        self.assertEqual(driver.step(event, state), DECIDE_NO_TEAM)
        self.assertNotIn("team_request", event.payload)


if __name__ == "__main__":
    unittest.main()
