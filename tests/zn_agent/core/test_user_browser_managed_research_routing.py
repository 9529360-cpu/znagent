from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.browser_goal_understanding_resident import BrowserGoalUnderstandingResidentRuntime
from zn_agent.core.goal_resident import ResidentGoalRuntime
from zn_agent.core.user_browser_managed_research_resident import (
    UserBrowserManagedResearchResidentRuntime,
)


class UserBrowserManagedResearchRoutingTests(unittest.TestCase):
    def test_bounded_reference_task_bypasses_generic_cognition_router(self) -> None:
        resident = UserBrowserManagedResearchResidentRuntime.__new__(
            UserBrowserManagedResearchResidentRuntime
        )
        event = SimpleNamespace(
            task="检查这里链接的两个参考页，确认它们一致的 release code，然后回来在这个页面搜索那个 code。",
            payload={"model_policy": "never"},
        )
        state = SimpleNamespace()
        readiness = SimpleNamespace()
        sentinel = object()

        with (
            patch.object(
                ResidentGoalRuntime,
                "_orient_step",
                autospec=True,
                return_value=sentinel,
            ) as resident_goal_orient,
            patch.object(
                BrowserGoalUnderstandingResidentRuntime,
                "_orient_step",
                autospec=True,
                side_effect=AssertionError(
                    "generic browser cognition must not consume a locally bounded managed-reference task"
                ),
            ) as generic_orient,
        ):
            result = resident._orient_step(
                event,
                state,
                readiness=readiness,
                thought=None,
            )

        self.assertIs(result, sentinel)
        resident_goal_orient.assert_called_once_with(
            resident,
            event,
            state,
            readiness=readiness,
            thought=None,
        )
        generic_orient.assert_not_called()

    def test_unrelated_browser_task_keeps_generic_orientation_chain(self) -> None:
        resident = UserBrowserManagedResearchResidentRuntime.__new__(
            UserBrowserManagedResearchResidentRuntime
        )
        event = SimpleNamespace(
            task="在这个页面里查一下 alice@example.test 的订单状态。",
            payload={},
        )
        state = SimpleNamespace()
        readiness = SimpleNamespace()
        sentinel = object()

        with patch.object(
            BrowserGoalUnderstandingResidentRuntime,
            "_orient_step",
            autospec=True,
            return_value=sentinel,
        ) as generic_orient:
            result = resident._orient_step(
                event,
                state,
                readiness=readiness,
                thought=None,
            )

        self.assertIs(result, sentinel)
        generic_orient.assert_called_once_with(
            resident,
            event,
            state,
            readiness=readiness,
            thought=None,
        )


if __name__ == "__main__":
    unittest.main()
