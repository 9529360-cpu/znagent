from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.broad_goal_completion_resident import BroadGoalCompletionResidentRuntime
from zn_agent.core.steerable_work import WorkItem


class WorkerPhaseRepairTests(unittest.TestCase):
    @staticmethod
    def _item(item_id: str, *, status: str, criterion: str) -> WorkItem:
        return WorkItem(
            work_item_id=item_id,
            work_thread_id="phase-repair",
            parent_work_item_id="root",
            title=item_id,
            objective=item_id,
            status=status,
            plan_version=1,
            acceptance_criteria=[criterion],
        )

    @staticmethod
    def _run(item_id: str, kind: str, verification: str = "accepted"):
        return SimpleNamespace(
            work_item_id=item_id,
            executor_kind=kind,
            state="completed",
            verification_status=verification,
        )

    def test_failed_command_routes_back_to_write_then_run(self) -> None:
        root = SimpleNamespace(work_item_id="root", plan_version=1)
        research_meta = self._item(
            "research-meta",
            status="completed",
            criterion="delegated_worker_evidence: research/research_page",
        )
        first_write = self._item(
            "write-1",
            status="completed",
            criterion="text_equals: app.py",
        )
        failed_run = self._item(
            "run-failed",
            status="blocked",
            criterion="command_exit: 0; output_contains: expected",
        )
        runs = [self._run("research-meta", "research")]

        phase = BroadGoalCompletionResidentRuntime._next_worker_phase(
            None,
            root,
            [research_meta, first_write, failed_run],
            runs,
        )
        self.assertEqual(phase, ("coding", "write_file"))

        repair_write = self._item(
            "write-2",
            status="completed",
            criterion="text_equals: app.py",
        )
        phase = BroadGoalCompletionResidentRuntime._next_worker_phase(
            None,
            root,
            [research_meta, first_write, failed_run, repair_write],
            runs,
        )
        self.assertEqual(phase, ("coding", "run_python"))

    def test_failed_review_routes_to_coding_repair_before_reviewing_again(self) -> None:
        root = SimpleNamespace(work_item_id="root", plan_version=1)
        research_meta = self._item(
            "research-meta",
            status="completed",
            criterion="delegated_worker_evidence: research/research_page",
        )
        first_write = self._item(
            "write-1",
            status="completed",
            criterion="text_equals: app.py",
        )
        accepted_run = self._item(
            "run-1",
            status="completed",
            criterion="command_exit: 0; output_contains: ok",
        )
        failed_review_effect = self._item(
            "review-effect-failed",
            status="blocked",
            criterion="command_exit: 0; output_contains: root-signal",
        )
        runs = [self._run("research-meta", "research")]

        phase = BroadGoalCompletionResidentRuntime._next_worker_phase(
            None,
            root,
            [research_meta, first_write, accepted_run, failed_review_effect],
            runs,
        )
        self.assertEqual(phase, ("coding", "write_file"))

        repair_write = self._item(
            "write-2",
            status="completed",
            criterion="text_equals: app.py",
        )
        phase = BroadGoalCompletionResidentRuntime._next_worker_phase(
            None,
            root,
            [research_meta, first_write, accepted_run, failed_review_effect, repair_write],
            runs,
        )
        self.assertEqual(phase, ("coding", "run_python"))

    def test_accepted_review_finishes_delegated_sequence(self) -> None:
        root = SimpleNamespace(work_item_id="root", plan_version=1)
        research_meta = self._item(
            "research-meta",
            status="completed",
            criterion="delegated_worker_evidence: research/research_page",
        )
        write_effect = self._item(
            "write-1",
            status="completed",
            criterion="text_equals: app.py",
        )
        coding_effect = self._item(
            "run-1",
            status="completed",
            criterion="command_exit: 0; output_contains: ok",
        )
        review_meta = self._item(
            "review-meta",
            status="completed",
            criterion="delegated_worker_evidence: review/run_python",
        )
        review_effect = self._item(
            "review-effect",
            status="completed",
            criterion="command_exit: 0; output_contains: ok",
        )
        runs = [
            self._run("research-meta", "research"),
            self._run("review-meta", "review"),
        ]
        phase = BroadGoalCompletionResidentRuntime._next_worker_phase(
            None,
            root,
            [research_meta, write_effect, coding_effect, review_meta, review_effect],
            runs,
        )
        self.assertIsNone(phase)


if __name__ == "__main__":
    unittest.main(verbosity=2)
