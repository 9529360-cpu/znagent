from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.browser_goal_understanding_resident import (
    BrowserGoalUnderstandingResidentRuntime,
)
from zn_agent.core.composite_work_routing import classify_composite_work_route
from zn_agent.core.goal_resident import ResidentGoalRuntime


def _event(task: str, **payload_overrides):
    payload = {
        "work_thread_id": "work-1",
        "work_item_id": "item-1",
        "workspace_path": "C:/workspace",
        **payload_overrides,
    }
    return SimpleNamespace(
        event_id="evt-composite-route",
        kind="desktop_user_event",
        task=task,
        payload=payload,
    )


class CompositeWorkRoutingTests(unittest.TestCase):
    def test_current_browser_reference_plus_workspace_change_is_composite(self) -> None:
        decision = classify_composite_work_route(
            _event("按这个网站的新 API 文档把项目适配一下，然后跑起来确认能用。")
        )

        self.assertTrue(decision.preempt_narrow_browser)
        self.assertIn("browser_reference", decision.surfaces)
        self.assertIn("workspace_mutation", decision.surfaces)
        self.assertIn("local_verification", decision.surfaces)

    def test_same_route_is_not_tied_to_one_e2e_phrase(self) -> None:
        decision = classify_composite_work_route(
            _event(
                "Use the API documentation on this page to update the attached "
                "repository, then run tests and verify the project."
            )
        )

        self.assertTrue(decision.preempt_narrow_browser)
        self.assertIn("workspace_mutation", decision.surfaces)

    def test_plain_browser_lookup_keeps_narrow_browser_route(self) -> None:
        decision = classify_composite_work_route(
            _event("在这个网站里查 alice@example.test 最近的订单状态。")
        )

        self.assertFalse(decision.preempt_narrow_browser)
        self.assertNotIn("browser_reference", decision.surfaces)
        self.assertNotIn("workspace_mutation", decision.surfaces)

    def test_browser_mutation_of_repository_named_object_stays_on_browser_route(self) -> None:
        decision = classify_composite_work_route(
            _event(
                "On this website, update the repository setting and confirm the change."
            )
        )

        self.assertFalse(decision.preempt_narrow_browser)
        self.assertNotIn("browser_reference", decision.surfaces)
        self.assertIn("workspace_mutation", decision.surfaces)

    def test_business_website_update_is_not_mistaken_for_workspace_code_work(self) -> None:
        decision = classify_composite_work_route(
            _event("Update this client's package status on this website and confirm it.")
        )

        self.assertFalse(decision.preempt_narrow_browser)
        self.assertNotIn("browser_reference", decision.surfaces)
        self.assertNotIn("workspace_mutation", decision.surfaces)

    def test_missing_durable_work_binding_never_preempts_browser(self) -> None:
        decision = classify_composite_work_route(
            _event(
                "Use this website documentation to update the repository.",
                work_item_id="",
            )
        )

        self.assertFalse(decision.preempt_narrow_browser)
        self.assertEqual(decision.surfaces, ())

    def test_api_docs_without_current_browser_context_do_not_claim_current_page(self) -> None:
        decision = classify_composite_work_route(
            _event("Use the API documentation to update this repository, then run tests.")
        )

        self.assertFalse(decision.preempt_narrow_browser)
        self.assertNotIn("browser_reference", decision.surfaces)
        self.assertIn("workspace_mutation", decision.surfaces)

    def test_repo_abbreviation_matches_on_word_boundary(self) -> None:
        decision = classify_composite_work_route(
            _event(
                "Use this page as the reference to update the repo, then verify it."
            )
        )

        self.assertTrue(decision.preempt_narrow_browser)
        self.assertIn("browser_reference", decision.surfaces)
        self.assertIn("workspace_mutation", decision.surfaces)

    def test_report_does_not_match_repo_marker(self) -> None:
        decision = classify_composite_work_route(
            _event(
                "Use this page as the reference to update the report, then verify it."
            )
        )

        self.assertFalse(decision.preempt_narrow_browser)
        self.assertIn("browser_reference", decision.surfaces)
        self.assertNotIn("workspace_mutation", decision.surfaces)

    def test_repository_documentation_update_is_not_a_browser_reference(self) -> None:
        decision = classify_composite_work_route(
            _event("Update the documentation in this repository and run tests.")
        )

        self.assertFalse(decision.preempt_narrow_browser)
        self.assertNotIn("browser_reference", decision.surfaces)
        self.assertIn("workspace_mutation", decision.surfaces)

    def test_workspace_only_change_does_not_claim_browser_precedence(self) -> None:
        decision = classify_composite_work_route(
            _event("修改这个项目的客户端代码并运行测试。")
        )

        self.assertFalse(decision.preempt_narrow_browser)
        self.assertNotIn("browser_reference", decision.surfaces)

    def test_action_events_never_reenter_composite_routing(self) -> None:
        decision = classify_composite_work_route(
            _event(
                "按这个网站文档修改项目",
                body_action={"kind": "write_text"},
            )
        )

        self.assertFalse(decision.preempt_narrow_browser)

    def test_browser_understanding_yields_to_more_specific_composite_work(self) -> None:
        resident = BrowserGoalUnderstandingResidentRuntime.__new__(
            BrowserGoalUnderstandingResidentRuntime
        )
        event = _event(
            "Use the documentation on this website to adapt the project and verify it."
        )
        state = SimpleNamespace()
        readiness = SimpleNamespace()
        sentinel = object()

        with (
            patch.object(
                BrowserGoalUnderstandingResidentRuntime,
                "_orient_browser_goal_from_cognition",
                side_effect=AssertionError(
                    "generic browser understanding must not consume composite Work"
                ),
            ),
            patch.object(
                ResidentGoalRuntime,
                "_orient_step",
                autospec=True,
                return_value=sentinel,
            ) as base_orient,
        ):
            result = resident._orient_step(
                event,
                state,
                readiness=readiness,
                thought=None,
            )

        self.assertIs(result, sentinel)
        base_orient.assert_called_once_with(
            resident,
            event,
            state,
            readiness=readiness,
            thought=None,
        )

    def test_plain_browser_work_still_uses_browser_understanding(self) -> None:
        resident = BrowserGoalUnderstandingResidentRuntime.__new__(
            BrowserGoalUnderstandingResidentRuntime
        )
        event = _event("在这个网站里查 alice@example.test 最近的订单状态。")
        state = SimpleNamespace()
        readiness = SimpleNamespace()
        sentinel = object()

        with (
            patch.object(
                BrowserGoalUnderstandingResidentRuntime,
                "_orient_browser_goal_from_cognition",
                return_value=sentinel,
            ) as browser_orient,
            patch.object(
                ResidentGoalRuntime,
                "_orient_step",
                autospec=True,
                side_effect=AssertionError(
                    "plain browser lookup should not bypass browser understanding"
                ),
            ),
        ):
            result = resident._orient_step(
                event,
                state,
                readiness=readiness,
                thought=None,
            )

        self.assertIs(result, sentinel)
        browser_orient.assert_called_once_with(
            event,
            state,
            readiness=readiness,
            thought=None,
        )


if __name__ == "__main__":
    unittest.main()
