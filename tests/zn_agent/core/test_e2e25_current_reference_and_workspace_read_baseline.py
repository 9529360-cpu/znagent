from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from zn_agent.core.broad_goal_completion_resident import BroadGoalCompletionResidentRuntime
from zn_agent.core.broad_goal_research_resident import BroadGoalResearchResidentRuntime
from zn_agent.core.steerable_work import WorkItem


class E2E25CurrentReferenceAndWorkspaceReadBaselineTests(unittest.TestCase):
    @staticmethod
    def _item(item_id: str, *, status: str, criterion: str) -> WorkItem:
        return WorkItem(
            work_item_id=item_id,
            work_thread_id="e2e25-baseline",
            parent_work_item_id="root",
            title=item_id,
            objective=item_id,
            status=status,
            plan_version=1,
            acceptance_criteria=[criterion],
        )

    def test_current_page_research_proposal_is_url_free_and_resident_owned(self) -> None:
        resident = SimpleNamespace(
            work_ledger=SimpleNamespace(plan_version=lambda _thread_id: 1)
        )
        root = SimpleNamespace(work_thread_id="e2e25-baseline", plan_version=1)
        content = json.dumps(
            {
                "zn_work_step": {
                    "objective": "Read the API documentation currently referenced by the user",
                    "action": {"kind": "research_current_page"},
                    "acceptance": {"kind": "page_read_current_reference"},
                }
            }
        )

        parsed = BroadGoalResearchResidentRuntime._parse_research_page_step(
            resident, root, content
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["source_kind"], "current_user_browser_page")
        self.assertNotIn("url", parsed)

    def test_delegated_coding_reads_existing_workspace_before_any_write(self) -> None:
        root = SimpleNamespace(work_item_id="root", plan_version=1)
        research_meta = self._item(
            "research-meta",
            status="completed",
            criterion="delegated_worker_evidence: research/research_current_page",
        )
        accepted_research = SimpleNamespace(
            work_item_id="research-meta",
            executor_kind="research",
            state="completed",
            verification_status="accepted",
        )

        phase = BroadGoalCompletionResidentRuntime._next_worker_phase(
            None,
            root,
            [research_meta],
            [accepted_research],
        )

        self.assertEqual(phase, ("coding", "read_workspace_file"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
