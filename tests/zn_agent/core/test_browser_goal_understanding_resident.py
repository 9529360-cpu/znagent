from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.browser_goal_understanding_resident import (
    BrowserGoalUnderstandingResidentRuntime,
    _validated_browser_goal_proposal,
    _validated_browser_semantic_goal_proposal,
    browser_semantic_lookup_goal,
)
from zn_agent.core.budget import CognitiveBudgetManager
from zn_agent.core.models import AgentEvent, EventStatus, WorkingState
from zn_agent.core.store import KernelStore


class _ProposalKernel:
    def __init__(self, response: str):
        self.response = response
        self.calls: list[dict] = []

    def run_goal(self, question: str, **kwargs):
        self.calls.append({"question": question, **kwargs})
        return SimpleNamespace(
            goal=SimpleNamespace(route_id="test-language-route"),
            worker_result=SimpleNamespace(success=True, response=self.response),
            assessment=SimpleNamespace(success=True),
            experiences=(SimpleNamespace(metrics={"model_invoked": True}),),
        )


class BrowserGoalUnderstandingTests(unittest.TestCase):
    def test_proposal_must_be_grounded_in_literal_user_task(self):
        task = "In my current browser, put alice in Account search."
        accepted = _validated_browser_goal_proposal(
            task,
            '{"kind":"user_browser_named_text","target_name":"Account search","text":"alice"}',
        )
        self.assertEqual(
            accepted,
            {
                "kind": "user_browser_named_text",
                "target_name": "Account search",
                "text": "alice",
            },
        )

        self.assertIsNone(
            _validated_browser_goal_proposal(
                task,
                '{"kind":"user_browser_named_text","target_name":"Account search","text":"alice@example.com"}',
            )
        )
        self.assertIsNone(
            _validated_browser_goal_proposal(
                task,
                '{"kind":"user_browser_named_text","target_name":"Email","text":"alice"}',
            )
        )
        self.assertIsNone(
            _validated_browser_goal_proposal(
                task,
                '{"kind":"user_browser_named_text","target_name":"Account search","text":"alice","x":0.4}',
            )
        )

    def test_semantic_lookup_goal_keeps_business_intent_separate_from_browser_identity(self):
        task = (
            "在这个已经登录的网站里，把 alice@example.test 这个客户的订单找出来，"
            "确认现在是什么状态。"
        )
        accepted = _validated_browser_semantic_goal_proposal(
            task,
            '{"kind":"user_browser_semantic_lookup",'
            '"subject_value":"alice@example.test",'
            '"subject_semantics":"客户标识",'
            '"operation":"查找该客户的订单",'
            '"desired_result":"确认当前订单状态"}',
        )
        self.assertEqual(
            accepted,
            {
                "kind": "user_browser_semantic_lookup",
                "subject_value": "alice@example.test",
                "subject_semantics": "客户标识",
                "operation": "查找该客户的订单",
                "desired_result": "确认当前订单状态",
            },
        )
        self.assertNotIn("target_name", accepted)
        self.assertNotIn("tab_id", accepted)
        self.assertNotIn("url", accepted)

        self.assertIsNone(
            _validated_browser_semantic_goal_proposal(
                task,
                '{"kind":"user_browser_semantic_lookup",'
                '"subject_value":"bob@example.test",'
                '"subject_semantics":"客户标识",'
                '"operation":"查找该客户的订单",'
                '"desired_result":"确认当前订单状态"}',
            )
        )
        self.assertIsNone(
            _validated_browser_semantic_goal_proposal(
                task,
                '{"kind":"user_browser_semantic_lookup",'
                '"subject_value":"alice@example.test",'
                '"subject_semantics":"客户标识",'
                '"operation":"查找该客户的订单",'
                '"desired_result":"确认当前订单状态",'
                '"selector":"#customer"}',
            )
        )

    def test_semantic_lookup_orientation_does_not_require_accessible_control_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = (
                "在这个已经登录的网站里，把 alice@example.test 这个客户的订单找出来，"
                "确认现在是什么状态。"
            )
            kernel = _ProposalKernel(
                '{"kind":"user_browser_semantic_lookup",'
                '"subject_value":"alice@example.test",'
                '"subject_semantics":"客户邮箱或账号",'
                '"operation":"查找客户订单",'
                '"desired_result":"当前订单状态"}'
            )
            store = KernelStore(Path(tmp) / "kernel.db")
            event = AgentEvent(
                event_id="evt-semantic-browser-understanding",
                kind="desktop_user_event",
                task=task,
                payload={},
                status=EventStatus.PROCESSING,
            )
            store.enqueue_event(event)
            state = WorkingState(
                current_event_id=event.event_id,
                stage="orient",
                data={},
            )
            store.save_working_state(state)

            resident = BrowserGoalUnderstandingResidentRuntime.__new__(
                BrowserGoalUnderstandingResidentRuntime
            )
            resident.kernel = kernel
            resident.store = store
            resident.budget = CognitiveBudgetManager()

            result = resident._orient_step(
                event,
                state,
                readiness=SimpleNamespace(),
                thought=None,
            )

            self.assertIsNone(result)
            self.assertEqual(len(kernel.calls), 1)
            self.assertEqual(state.stage, "native_investigation")
            self.assertNotIn("resident_goal", event.payload)
            self.assertNotIn("native_action", event.payload)
            goal = browser_semantic_lookup_goal(event)
            self.assertIsNotNone(goal)
            assert goal is not None
            self.assertEqual(goal["subject_value"], "alice@example.test")
            self.assertEqual(goal["operation"], "查找客户订单")
            self.assertNotIn("Account search", str(event.payload))
            store.close()

    def test_unquoted_work_uses_one_bounded_proposal_then_persists_typed_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = "In my current browser, put alice in Account search."
            kernel = _ProposalKernel(
                '{"kind":"user_browser_named_text","target_name":"Account search","text":"alice"}'
            )
            store = KernelStore(Path(tmp) / "kernel.db")
            event = AgentEvent(
                event_id="evt-natural-browser-understanding",
                kind="desktop_user_event",
                task=task,
                payload={},
                status=EventStatus.PROCESSING,
            )
            store.enqueue_event(event)
            state = WorkingState(
                current_event_id=event.event_id,
                stage="orient",
                data={},
            )
            store.save_working_state(state)

            resident = BrowserGoalUnderstandingResidentRuntime.__new__(
                BrowserGoalUnderstandingResidentRuntime
            )
            resident.kernel = kernel
            resident.store = store
            resident.budget = CognitiveBudgetManager()

            result = resident._orient_step(
                event,
                state,
                readiness=SimpleNamespace(),
                thought=None,
            )

            self.assertIsNone(result)
            self.assertEqual(len(kernel.calls), 1)
            self.assertEqual(kernel.calls[0]["max_attempts_override"], 1)
            self.assertEqual(
                kernel.calls[0]["required_capabilities"],
                ("language_understanding",),
            )
            self.assertEqual(state.stage, "native_investigation")
            self.assertNotIn("body_action", event.payload)
            self.assertNotIn("native_action", event.payload)
            self.assertEqual(
                event.payload["resident_goal"],
                {
                    "kind": "user_browser_named_text",
                    "target_name": "Account search",
                    "text": "alice",
                },
            )

            persisted = store.get_event(event.event_id)
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.payload["resident_goal"], event.payload["resident_goal"])
            metadata = persisted.payload["_resident_goal_understanding"]
            self.assertEqual(metadata["source"], "bounded_cognition_proposal")
            self.assertEqual(metadata["model_invocations"], 1)
            store.close()

    def test_model_cannot_mint_text_or_target_outside_user_task(self):
        task = "在当前浏览器里把 Account search 填成 alice"
        invented_text = _validated_browser_goal_proposal(
            task,
            '{"kind":"user_browser_named_text","target_name":"Account search","text":"alice@example.com"}',
        )
        invented_target = _validated_browser_goal_proposal(
            task,
            '{"kind":"user_browser_named_text","target_name":"Password","text":"alice"}',
        )
        self.assertIsNone(invented_text)
        self.assertIsNone(invented_target)


if __name__ == "__main__":
    unittest.main()