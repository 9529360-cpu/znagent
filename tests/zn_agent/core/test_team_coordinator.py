from __future__ import annotations

import unittest

from zn_agent.core.evidence_bound_work import DependencyReadiness, WorkerRun
from zn_agent.core.models import utc_now
from zn_agent.core.project_team import assemble_team
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.team_coordinator import TeamCoordinator
from zn_agent.core.team_task_state import TeamTaskStateStore


def make_item(item_id, thread_id, title, status="proposed", deps=(), parent="root-1"):
    return WorkItem(
        work_item_id=item_id,
        work_thread_id=thread_id,
        title=title,
        objective="obj",
        status=status,
        plan_version=1,
        parent_work_item_id=parent,
        dependency_ids=list(deps),
    )


def make_run(item_id, **overrides):
    kwargs = dict(
        worker_run_id=f"run-{item_id}",
        work_item_id=item_id,
        plan_version=1,
        executor_kind="team-specialist",
        model_goal_id="g1",
        model_route_id=None,
        provider=None,
        tool_scope=("terminal",),
        authority_scope=("work:thread-1",),
        state="running",
        started_at=utc_now(),
    )
    kwargs.update(overrides)
    return WorkerRun(**kwargs)


def ready(*deps):
    return DependencyReadiness(
        ready=not deps, state="ready" if not deps else "waiting",
        dependency_ids=tuple(deps),
        waiting_on=tuple(deps) if deps else (),
    )


class FakeLedger:
    def __init__(self, items, readiness):
        self._items = items
        self._readiness = readiness

    def list_work_items(self, thread_id):
        return [i for i in self._items if i.work_thread_id == thread_id]

    def dependency_readiness(self, work_item_id):
        return self._readiness[work_item_id]


def make_team(team_id="t1"):
    team = assemble_team(
        "X", ["researcher", "developer"],
        team_id=team_id, work_thread_id="thread-1",
    )
    return team


class CoordinatorTests(unittest.TestCase):
    def test_dispatch_ready_item_and_wait_on_blocked(self):
        team = make_team()
        item1 = make_item(team.plan[0].item_id, "thread-1", "t1")
        item2 = make_item(
            team.plan[1].item_id, "thread-1", "t2", deps=(team.plan[0].item_id,)
        )
        ledger = FakeLedger(
            [item1, item2],
            {
                item1.work_item_id: ready(),
                item2.work_item_id: ready(team.plan[0].item_id),
            },
        )
        coord = TeamCoordinator(team=team, root_work_item_id="root-1")
        decisions = coord.step(ledger, runs={})
        by_item = {d.work_item_id: d for d in decisions}
        dispatch = by_item[item1.work_item_id]
        self.assertEqual(dispatch.action, "dispatch")
        self.assertEqual(dispatch.specialist_name, team.members[0].name)
        self.assertIn("acceptance_criteria", dispatch.context)
        self.assertIsNotNone(dispatch.journal)
        wait = by_item[item2.work_item_id]
        self.assertEqual(wait.action, "wait")
        self.assertIn(team.plan[0].item_id, wait.reason)

    def test_verify_when_run_claims_completion(self):
        team = make_team()
        item1 = make_item(team.plan[0].item_id, "thread-1", "t1")
        ledger = FakeLedger([item1], {item1.work_item_id: ready()})
        run = make_run(item1.work_item_id, claimed_completion=True,
                       verification_status="pending")
        coord = TeamCoordinator(team=team, root_work_item_id="root-1")
        decisions = coord.step(ledger, runs={item1.work_item_id: run})
        self.assertEqual(decisions[0].action, "verify")
        self.assertIsNotNone(decisions[0].context["acceptance_criteria"])

    def test_complete_when_verified(self):
        team = make_team()
        item1 = make_item(team.plan[0].item_id, "thread-1", "t1")
        ledger = FakeLedger([item1], {item1.work_item_id: ready()})
        run = make_run(item1.work_item_id, claimed_completion=True,
                       verification_status="verified", state="finished")
        coord = TeamCoordinator(team=team, root_work_item_id="root-1")
        decisions = coord.step(ledger, runs={item1.work_item_id: run})
        self.assertEqual(decisions[0].action, "complete")

    def test_escalate_blocked_item(self):
        team = make_team()
        item1 = make_item(team.plan[0].item_id, "thread-1", "t1", status="blocked")
        ledger = FakeLedger([item1], {item1.work_item_id: ready()})
        coord = TeamCoordinator(team=team, root_work_item_id="root-1")
        decisions = coord.step(ledger, runs={})
        self.assertEqual(decisions[0].action, "escalate")
        self.assertEqual(decisions[0].journal["detail"]["kind"], "blocker")

    def test_escalate_stalled_run(self):
        team = make_team()
        item1 = make_item(team.plan[0].item_id, "thread-1", "t1", status="running")
        ledger = FakeLedger([item1], {item1.work_item_id: ready()})
        run = make_run(item1.work_item_id, started_at="2020-01-01T00:00:00+00:00")
        coord = TeamCoordinator(team=team, root_work_item_id="root-1")
        decisions = coord.step(ledger, runs={item1.work_item_id: run})
        self.assertEqual(decisions[0].action, "escalate")

    def test_team_complete_reports_without_disband(self):
        team = make_team()
        items = [
            make_item(p.item_id, "thread-1", p.title, status="completed")
            for p in team.plan
        ]
        ledger = FakeLedger(items, {})
        coord = TeamCoordinator(team=team, root_work_item_id="root-1")
        decisions = coord.step(ledger, runs={})
        actions = [d.action for d in decisions]
        self.assertIn("team_complete", actions)
        self.assertNotIn("disband", actions)

    def test_missing_item_waits(self):
        team = make_team()
        ledger = FakeLedger([], {})
        coord = TeamCoordinator(team=team, root_work_item_id="root-1")
        decisions = coord.step(ledger, runs={})
        self.assertTrue(all(d.action == "wait" for d in decisions))


class TaskStateMirrorTests(unittest.TestCase):
    """DSH-2 (T1): mirror_decision wired into the coordinator dispatch /
    complete path as a never-raising observer (AF-3 progress-ledger
    pattern: optional-in, off when None)."""

    def test_dispatch_then_complete_mirror_to_snapshots(self):
        team = make_team()
        pid = team.plan[0].item_id
        item1 = make_item(pid, "thread-1", "t1")
        ledger = FakeLedger([item1], {pid: ready()})
        store = TeamTaskStateStore()
        store.sync_from_team(team)
        coord = TeamCoordinator(team=team, root_work_item_id="root-1")

        decisions = coord.step(ledger, runs={}, task_state_store=store)
        self.assertEqual(decisions[0].action, "dispatch")
        snap = store.get_task(pid)
        self.assertEqual(snap.status, "in_progress")
        self.assertEqual(snap.revision, 2)
        self.assertEqual(snap.history[-1]["reason"], "coordinator:dispatch")

        run = make_run(pid, claimed_completion=True,
                       verification_status="verified", state="finished")
        decisions = coord.step(
            ledger, runs={pid: run}, task_state_store=store)
        self.assertEqual(decisions[0].action, "complete")
        snap = store.get_task(pid)
        self.assertEqual(snap.status, "done")
        self.assertEqual(snap.revision, 3)
        self.assertEqual(snap.history[-1]["reason"], "coordinator:complete")

    def test_mirror_never_changes_decisions(self):
        team = make_team()
        pid = team.plan[0].item_id
        item1 = make_item(pid, "thread-1", "t1")
        ledger = FakeLedger([item1], {pid: ready()})
        store = TeamTaskStateStore()
        store.sync_from_team(team)
        coord = TeamCoordinator(team=team, root_work_item_id="root-1")

        plain = coord.step(ledger, runs={})
        mirrored = coord.step(ledger, runs={}, task_state_store=store)
        self.assertEqual(
            [(d.action, d.work_item_id, d.reason) for d in mirrored],
            [(d.action, d.work_item_id, d.reason) for d in plain],
        )

    def test_mirror_skips_unknown_tasks(self):
        team = make_team()
        pid = team.plan[0].item_id
        item1 = make_item(pid, "thread-1", "t1")
        ledger = FakeLedger([item1], {pid: ready()})
        store = TeamTaskStateStore()  # never synced: knows no tasks
        coord = TeamCoordinator(team=team, root_work_item_id="root-1")

        decisions = coord.step(ledger, runs={}, task_state_store=store)
        self.assertEqual(decisions[0].action, "dispatch")
        self.assertEqual(store.list_tasks(), [])

    def test_mirror_translates_id_map(self):
        team = make_team()
        pid = team.plan[0].item_id
        item1 = make_item("work-1", "thread-1", "t1")
        ledger = FakeLedger([item1], {"work-1": ready()})
        store = TeamTaskStateStore()
        store.sync_from_team(team)  # snapshots keyed by plan item id
        coord = TeamCoordinator(team=team, root_work_item_id="root-1")

        decisions = coord.step(
            ledger, runs={}, id_map={pid: "work-1"}, task_state_store=store)
        self.assertEqual(decisions[0].action, "dispatch")
        self.assertEqual(decisions[0].work_item_id, "work-1")
        snap = store.get_task(pid)
        self.assertEqual(snap.status, "in_progress")

    def test_mirror_skips_same_status_no_revision_consumed(self):
        team = make_team()
        pid = team.plan[0].item_id
        item1 = make_item(pid, "thread-1", "t1")
        ledger = FakeLedger([item1], {pid: ready()})
        store = TeamTaskStateStore()
        store.sync_from_team(team)
        before = store.update_task(pid, expected_revision=1,
                                   status="in_progress")
        coord = TeamCoordinator(team=team, root_work_item_id="root-1")

        decisions = coord.step(ledger, runs={}, task_state_store=store)
        self.assertEqual(decisions[0].action, "dispatch")
        after = store.get_task(pid)
        self.assertEqual(after.status, "in_progress")
        self.assertEqual(after.revision, before.revision)

    def test_mirror_never_raises_on_broken_store(self):
        class BrokenStore(TeamTaskStateStore):
            def mirror_decision(self, decision, *, reason=""):
                raise RuntimeError("boom")

        team = make_team()
        pid = team.plan[0].item_id
        item1 = make_item(pid, "thread-1", "t1")
        ledger = FakeLedger([item1], {pid: ready()})
        coord = TeamCoordinator(team=team, root_work_item_id="root-1")

        decisions = coord.step(
            ledger, runs={}, task_state_store=BrokenStore())
        self.assertEqual(decisions[0].action, "dispatch")


if __name__ == "__main__":
    unittest.main()
