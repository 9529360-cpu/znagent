from __future__ import annotations

import unittest

from zn_agent.core.project_team import assemble_team
from zn_agent.core.team_coordinator import (
    ProgressLedger,
    TeamCoordinator,
    build_plan,
    plan_order,
    ready_tasks,
    review_journal,
    review_plan,
)
from zn_agent.core.team_timeline import (
    build_team_timeline,
    review_timeline_entry,
)
from zn_agent.core.steerable_work import WorkItem


def make_item(item_id, thread_id, title, status="proposed"):
    return WorkItem(
        work_item_id=item_id,
        work_thread_id=thread_id,
        title=title,
        objective="obj",
        status=status,
        plan_version=1,
        parent_work_item_id="root-1",
        dependency_ids=[],
    )


class FakeLedger:
    def __init__(self, items):
        self._items = items

    def list_work_items(self, thread_id):
        return [i for i in self._items if i.work_thread_id == thread_id]

    def dependency_readiness(self, work_item_id):
        from zn_agent.core.evidence_bound_work import DependencyReadiness

        return DependencyReadiness(
            ready=True, state="ready", dependency_ids=(), waiting_on=()
        )


def make_ledger_with_tasks():
    ledger = ProgressLedger()
    ledger.add_task("a", "调研", assignee="调研-01")
    ledger.add_task("b", "设计", assignee="架构-02", depends_on=("a",))
    ledger.add_task("c", "实现", assignee="开发-03", depends_on=("b",))
    return ledger


class LedgerCrudTests(unittest.TestCase):
    def test_add_get_list_and_history(self):
        ledger = ProgressLedger()
        task = ledger.add_task("a", "调研", assignee="调研-01", objective="obj")
        self.assertEqual(task.status, "todo")
        self.assertEqual(len(task.history), 1)
        self.assertEqual(task.history[0]["to"], "todo")
        self.assertIs(ledger.get_task("a"), task)
        self.assertEqual([t.task_id for t in ledger.list_tasks()], ["a"])

    def test_add_rejects_empty_duplicate_unknown_dep_self_dep(self):
        ledger = ProgressLedger()
        with self.assertRaises(ValueError):
            ledger.add_task("", "x")
        ledger.add_task("a", "A")
        with self.assertRaises(ValueError):
            ledger.add_task("a", "A again")
        with self.assertRaises(ValueError):
            ledger.add_task("b", "B", depends_on=("missing",))
        with self.assertRaises(ValueError):
            ledger.add_task("c", "C", depends_on=("c",))
        with self.assertRaises(ValueError):
            ledger.add_task("d", "D", status="bogus")

    def test_set_status_records_transition_and_is_idempotent(self):
        ledger = ProgressLedger()
        ledger.add_task("a", "A")
        task = ledger.set_status("a", "in_progress", reason="dispatch")
        self.assertEqual(task.status, "in_progress")
        self.assertEqual(len(task.history), 2)
        self.assertEqual(task.history[-1], {
            "seq": 2, "from": "todo", "to": "in_progress", "reason": "dispatch",
        })
        again = ledger.set_status("a", "in_progress")
        self.assertEqual(len(again.history), 2)  # no-op: no new record

    def test_done_is_terminal(self):
        ledger = ProgressLedger()
        ledger.add_task("a", "A")
        ledger.set_status("a", "done")
        with self.assertRaises(ValueError):
            ledger.set_status("a", "todo")
        with self.assertRaises(ValueError):
            ledger.set_status("a", "in_progress")
        with self.assertRaises(ValueError):
            ledger.set_status("a", "failed")
        self.assertEqual(ledger.get_task("a").status, "done")

    def test_failed_can_retry_through_todo(self):
        ledger = ProgressLedger()
        ledger.add_task("a", "A")
        ledger.set_status("a", "in_progress")
        ledger.set_status("a", "failed", reason="boom")
        retried = ledger.set_status("a", "todo", reason="review: retry")
        self.assertEqual(retried.status, "todo")
        self.assertEqual(len(retried.history), 4)

    def test_set_status_unknown_task_or_status_raises(self):
        ledger = ProgressLedger()
        with self.assertRaises(KeyError):
            ledger.set_status("nope", "done")
        ledger.add_task("a", "A")
        with self.assertRaises(ValueError):
            ledger.set_status("a", "bogus")


class PlanTests(unittest.TestCase):
    def test_plan_order_respects_dependencies(self):
        ledger = make_ledger_with_tasks()
        plan = build_plan(ledger, "p1", ["c", "a", "b"])  # scrambled input
        self.assertEqual(plan_order(ledger, plan), ["a", "b", "c"])

    def test_build_plan_rejects_unknown_duplicate_empty(self):
        ledger = ProgressLedger()
        ledger.add_task("a", "A")
        with self.assertRaises(ValueError):
            build_plan(ledger, "p", [])
        with self.assertRaises(ValueError):
            build_plan(ledger, "p", ["a", "a"])
        with self.assertRaises(KeyError):
            build_plan(ledger, "p", ["a", "missing"])

    def test_ready_tasks_only_unblocked_todo(self):
        ledger = make_ledger_with_tasks()
        plan = build_plan(ledger, "p1", ["a", "b", "c"])
        self.assertEqual([t.task_id for t in ready_tasks(ledger, plan)], ["a"])
        ledger.set_status("a", "done")
        self.assertEqual([t.task_id for t in ready_tasks(ledger, plan)], ["b"])
        ledger.set_status("b", "in_progress")
        self.assertEqual(ready_tasks(ledger, plan), [])
        ledger.set_status("b", "done")
        self.assertEqual([t.task_id for t in ready_tasks(ledger, plan)], ["c"])

    def test_plan_order_cycle_raises(self):
        # A cycle cannot be built via add_task alone (deps must exist),
        # but a plan over manually-wired tasks must still be caught.
        ledger = ProgressLedger()
        ledger.add_task("a", "A")
        ledger.add_task("b", "B", depends_on=("a",))
        # Close the loop by hand (simulating a corrupted ledger).
        ledger.tasks["a"] = type(ledger.tasks["a"])(
            task_id="a", title="A", status="todo", depends_on=("b",),
            history=ledger.tasks["a"].history,
        )
        plan = build_plan(ledger, "p1", ["a", "b"])
        with self.assertRaises(ValueError):
            plan_order(ledger, plan)


class ReviewTests(unittest.TestCase):
    def test_review_continue_when_healthy(self):
        ledger = make_ledger_with_tasks()
        plan = build_plan(ledger, "p1", ["a", "b", "c"])
        ledger.set_status("a", "done")
        review = review_plan(ledger, plan)
        self.assertEqual(review.verdict, "continue")
        self.assertEqual(review.recommendations, ())
        self.assertEqual(len(ledger.reviews), 1)
        self.assertIs(ledger.reviews[0], review)

    def test_review_revise_on_failed_task(self):
        ledger = make_ledger_with_tasks()
        plan = build_plan(ledger, "p1", ["a", "b", "c"])
        ledger.set_status("a", "done")
        ledger.set_status("b", "in_progress")
        ledger.set_status("b", "failed", reason="tests red")
        review = review_plan(ledger, plan)
        self.assertEqual(review.verdict, "revise")
        self.assertTrue(any("b" in f for f in review.findings))
        self.assertTrue(any("b" in r for r in review.recommendations))
        # Review changes no task state.
        self.assertEqual(ledger.get_task("b").status, "failed")
        self.assertEqual(ledger.get_task("c").status, "todo")

    def test_review_revise_on_stalled_task(self):
        ledger = make_ledger_with_tasks()
        plan = build_plan(ledger, "p1", ["a", "b", "c"])
        ledger.set_status("a", "in_progress")
        review = review_plan(ledger, plan, stalled=["a"])
        self.assertEqual(review.verdict, "revise")
        self.assertTrue(any("a" in f for f in review.findings))

    def test_review_observations_stored_but_do_not_flip_verdict(self):
        ledger = make_ledger_with_tasks()
        plan = build_plan(ledger, "p1", ["a", "b", "c"])
        review = review_plan(
            ledger, plan, observations={"a": "started smoothly"}
        )
        self.assertEqual(review.verdict, "continue")
        self.assertEqual(review.observations, ("a: started smoothly",))

    def test_review_journal_is_timeline_decision(self):
        ledger = make_ledger_with_tasks()
        plan = build_plan(ledger, "p1", ["a", "b", "c"])
        ledger.set_status("a", "failed")
        review = review_plan(ledger, plan)
        message = review_journal("t1", review)
        self.assertEqual(message["detail"]["kind"], "decision")
        self.assertEqual(message["detail"]["review_verdict"], "revise")
        entries = build_team_timeline([message])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["kind"], "decision")
        self.assertIn("需修订", entries[0]["text"])

    def test_review_timeline_entry_shape(self):
        ledger = make_ledger_with_tasks()
        plan = build_plan(ledger, "p1", ["a", "b", "c"])
        review = review_plan(ledger, plan)
        entry = review_timeline_entry(review, team_id="t1")
        self.assertEqual(entry["kind"], "decision")
        self.assertEqual(entry["review_verdict"], "continue")
        self.assertEqual(entry["team_id"], "t1")
        self.assertIn("继续", entry["text"])


class CoordinatorIntegrationTests(unittest.TestCase):
    def test_step_without_progress_ledger_unchanged(self):
        team = assemble_team(
            "X", ["researcher"], team_id="t1", work_thread_id="thread-1"
        )
        item = make_item(team.plan[0].item_id, "thread-1", "t1")
        coord = TeamCoordinator(team=team, root_work_item_id="root-1")
        decisions = coord.step(FakeLedger([item]), runs={})
        self.assertEqual(decisions[0].action, "dispatch")

    def test_step_mirrors_dispatch_and_complete(self):
        team = assemble_team(
            "X", ["researcher"], team_id="t1", work_thread_id="thread-1"
        )
        item_id = team.plan[0].item_id
        coord = TeamCoordinator(team=team, root_work_item_id="root-1")

        progress = ProgressLedger()
        progress.add_task(item_id, "t1")
        decisions = coord.step(FakeLedger([make_item(item_id, "thread-1", "t1")]),
                               runs={}, progress_ledger=progress)
        self.assertEqual(decisions[0].action, "dispatch")
        self.assertEqual(progress.get_task(item_id).status, "in_progress")

        # Same decisions with and without the ledger: mirroring adds nothing.
        plain = coord.step(FakeLedger([make_item(item_id, "thread-1", "t1")]),
                           runs={})
        self.assertEqual(
            [(d.action, d.work_item_id) for d in plain],
            [(d.action, d.work_item_id) for d in decisions],
        )

    def test_step_mirror_skips_untracked_items(self):
        team = assemble_team(
            "X", ["researcher"], team_id="t1", work_thread_id="thread-1"
        )
        item_id = team.plan[0].item_id
        coord = TeamCoordinator(team=team, root_work_item_id="root-1")
        decisions = coord.step(
            FakeLedger([make_item(item_id, "thread-1", "t1")]),
            runs={}, progress_ledger=ProgressLedger(),  # tracks nothing
        )
        self.assertEqual(decisions[0].action, "dispatch")  # no raise

    def test_full_loop_ledger_plan_review_revise(self):
        """End-to-end demo: build -> advance -> fail -> review -> retry."""
        ledger = make_ledger_with_tasks()
        plan = build_plan(ledger, "p1", ["a", "b", "c"])
        ledger.set_status("a", "in_progress")
        ledger.set_status("a", "done")
        self.assertEqual([t.task_id for t in ready_tasks(ledger, plan)], ["b"])
        ledger.set_status("b", "in_progress")
        ledger.set_status("b", "failed", reason="acceptance not met")
        review = review_plan(ledger, plan)
        self.assertEqual(review.verdict, "revise")
        ledger.set_status("b", "todo", reason="review: retry after fix")
        ledger.set_status("b", "in_progress")
        ledger.set_status("b", "done")
        ledger.set_status("c", "done")
        final = review_plan(ledger, plan)
        self.assertEqual(final.verdict, "continue")
        self.assertEqual(len(ledger.reviews), 2)


if __name__ == "__main__":
    unittest.main()
