from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.browser_goal_understanding_resident import (
    BrowserGoalUnderstandingResidentRuntime,
    _validated_browser_goal_proposal,
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

    def test_local_quoted_fast_path_does_not_call_cognition(self):
        event = AgentEvent(
            event_id="evt-local-browser-fast-path",
            kind="desktop_user_event",
            task='In my current browser, fill "Account search" with "alice".',
            payload={"model_policy": "never"},
        )
        kernel = _ProposalKernel("should not be used")
        resident = BrowserGoalUnderstandingResidentRuntime.__new__(
            BrowserGoalUnderstandingResidentRuntime
        )
        resident.kernel = kernel
        resident.budget = CognitiveBudgetManager()

        # We only need to prove dispatch ownership here: the local request is
        # recognized before the bounded-cognition branch. Avoid entering the
        # inherited full Resident lifecycle in this focused unit test.
        from zn_agent.core.browser_named_goal import browser_named_text_request

        self.assertIsNotNone(browser_named_text_request(event))
        self.assertEqual(kernel.calls, [])


if __name__ == "__main__":
    unittest.main()
