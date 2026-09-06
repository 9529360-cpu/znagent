from __future__ import annotations

import unittest

from zn_agent.core.evidence_bound_work import WorkerContextPack


class WorkerContextScopeTests(unittest.TestCase):
    def test_context_pack_is_bounded_and_contains_only_delegated_contract(self) -> None:
        pack = WorkerContextPack(
            root_goal_summary="root goal",
            work_item_objective="research current fact",
            acceptance_criteria=("page evidence exists",),
            plan_version=3,
            relevant_evidence=({"kind": "prior", "summary": "bounded"},),
            artifact_refs=({"kind": "url", "url": "https://example.com"},),
            tool_scope=("managed_browser.read",),
            authority_scope=("web_read",),
            forbidden_actions=("workspace_write", "root_acceptance"),
            expected_result_schema={"zn_work_step": {"action": {"kind": "research_page"}}},
        ).to_dict()

        self.assertEqual(pack["plan_version"], 3)
        self.assertEqual(pack["tool_scope"], ["managed_browser.read"])
        self.assertEqual(pack["authority_scope"], ["web_read"])
        self.assertIn("workspace_write", pack["forbidden_actions"])
        self.assertNotIn("transcript", pack)
        self.assertNotIn("memory", pack)
        self.assertNotIn("self_model", pack)
        self.assertNotIn("credentials", pack)
        self.assertNotIn("other_workers", pack)
        self.assertNotIn("reasoning", pack)


if __name__ == "__main__":
    unittest.main(verbosity=2)
