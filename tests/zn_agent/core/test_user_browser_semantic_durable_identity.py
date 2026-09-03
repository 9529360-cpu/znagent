from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.models import AgentEvent, EventStatus
from zn_agent.core.user_browser_extension_resident import UserBrowserExtensionResidentRuntime


class _AlwaysModelBudget:
    @staticmethod
    def decide(*_args, **_kwargs):
        return SimpleNamespace(use_model=True)


class _RecordingKernel:
    def __init__(self):
        self.calls: list[dict] = []

    def run_goal(self, question: str, **kwargs):
        self.calls.append({"question": question, **kwargs})
        return SimpleNamespace(
            goal=SimpleNamespace(route_id="test-language-route"),
            worker_result=SimpleNamespace(
                success=True,
                response='{"status":"selected","name":"客户邮箱"}',
            ),
            assessment=SimpleNamespace(success=True),
            experiences=(SimpleNamespace(metrics={"model_invoked": True}),),
        )


class _Store:
    @staticmethod
    def _save_event(_event):
        return None


class UserBrowserSemanticDurableIdentityTests(unittest.TestCase):
    def test_candidate_cognition_identity_is_stable_for_same_input_and_changes_with_fresh_input(self):
        resident = UserBrowserExtensionResidentRuntime.__new__(
            UserBrowserExtensionResidentRuntime
        )
        resident.kernel = _RecordingKernel()
        resident.budget = _AlwaysModelBudget()
        resident.store = _Store()
        event = AgentEvent(
            event_id="evt-semantic-durable-input",
            kind="desktop_user_event",
            task="查找客户订单",
            payload={"_resident_goal_understanding": {"model_invocations": 0}},
            status=EventStatus.PROCESSING,
        )
        candidates = [
            {
                "role": "textbox",
                "name": "客户邮箱",
                "enabled": True,
                "visible": True,
                "editable": True,
                "sensitive": False,
            }
        ]

        first_question = "Fresh candidates: 客户邮箱"
        changed_question = "Fresh candidates: 客户账号"
        resident._select_semantic_candidate(
            event,
            purpose="browser_semantic_input_grounding_only",
            question=first_question,
            candidates=candidates,
            required_role="textbox",
            require_editable=True,
        )
        resident._select_semantic_candidate(
            event,
            purpose="browser_semantic_input_grounding_only",
            question=first_question,
            candidates=candidates,
            required_role="textbox",
            require_editable=True,
        )
        resident._select_semantic_candidate(
            event,
            purpose="browser_semantic_input_grounding_only",
            question=changed_question,
            candidates=candidates,
            required_role="textbox",
            require_editable=True,
        )

        calls = resident.kernel.calls
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0]["goal_id"], calls[1]["goal_id"])
        self.assertNotEqual(calls[0]["goal_id"], calls[2]["goal_id"])
        self.assertEqual(calls[0]["metadata"]["input_sha256"], calls[1]["metadata"]["input_sha256"])
        self.assertNotEqual(calls[0]["metadata"]["input_sha256"], calls[2]["metadata"]["input_sha256"])
        self.assertTrue(calls[0]["goal_id"].endswith(calls[0]["metadata"]["input_sha256"][:16]))


if __name__ == "__main__":
    unittest.main()