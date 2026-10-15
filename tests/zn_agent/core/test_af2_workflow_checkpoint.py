"""AF-2: workflow edge vocabulary + CheckpointStorage protocol.

FanOut / FanIn / SwitchCase describe team routing (team_runner,
team_work_owner, broad_goal_* residents); CheckpointStorage (save / load /
delete) carries pulse-boundary snapshots so an interrupted run resumes from
pending steps without re-running completed ones.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.broad_goal_work_resident import describe_rolling_route
from zn_agent.core.evidence_bound_work import EvidenceBoundSteerableWorkLedger
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.project_team import ProjectTeam, TeamPlanItem, assemble_team
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.store import KernelStore
from zn_agent.core.team_memory import team_shared_memory
from zn_agent.core.team_runner import (
    Checkpoint,
    FanIn,
    FanOut,
    InMemoryCheckpointStorage,
    SwitchCase,
    TeamRunner,
    VerificationOutcome,
    WorkflowRoute,
    describe_team_route,
    pending_steps,
)
from zn_agent.core.team_work_owner import (
    TEAM_ID_STATE_KEY,
    TeamWorkOwner,
)


class StubVerifier:
    def __init__(self, passed: bool = True):
        self.passed = passed
        self.calls: list[str] = []

    def verify(self, *, item, run):
        self.calls.append(item.work_item_id)
        return VerificationOutcome(
            passed=self.passed, notes="stub checked the artifacts"
        )


class VocabularyTests(unittest.TestCase):
    def test_edges_validate(self):
        FanOut(from_step="a", to_steps=("b", "c")).validate()
        FanIn(from_steps=("b", "c"), to_step="d").validate()
        SwitchCase(
            on="verdict",
            cases=(("verified", "complete"), ("partial", "retry")),
            default="retry",
        ).validate()

    def test_edges_reject_bad_shapes(self):
        with self.assertRaises(ValueError):
            FanOut(from_step="", to_steps=("b",)).validate()
        with self.assertRaises(ValueError):
            FanOut(from_step="a", to_steps=()).validate()
        with self.assertRaises(ValueError):
            FanOut(from_step="a", to_steps=("b", "b")).validate()
        with self.assertRaises(ValueError):
            FanIn(from_steps=("b",), to_step="b").validate()
        with self.assertRaises(ValueError):
            SwitchCase(
                on="verdict",
                cases=(("x", "a"), ("x", "b")),
            ).validate()
        with self.assertRaises(ValueError):
            WorkflowRoute(name="").validate()

    def test_route_describe_renders_each_kind(self):
        route = WorkflowRoute(
            name="demo",
            edges=(
                FanOut(from_step="plan", to_steps=("a", "b")),
                SwitchCase(
                    on="verdict",
                    cases=(("verified", "complete"),),
                    default="retry",
                ),
                FanIn(from_steps=("a", "b"), to_step="done"),
            ),
        )
        route.validate()
        text = route.describe()
        self.assertIn("route demo (3 edges)", text)
        self.assertIn("fan_out plan -> a, b", text)
        self.assertIn("switch verdict: verified -> complete; default -> retry", text)
        self.assertIn("fan_in a, b -> done [require_all]", text)


class TeamRouteTests(unittest.TestCase):
    def test_chained_team_route(self):
        team = assemble_team(
            "XX 项目",
            ["researcher", "developer"],
            team_id="tx",
            work_thread_id="thread-1",
        )
        route = describe_team_route(team)
        kinds = [type(edge).__name__ for edge in route.edges]
        self.assertEqual(route.name, "team:tx")
        self.assertIn("FanOut", kinds)
        self.assertIn("FanIn", kinds)
        self.assertIn("SwitchCase", kinds)
        text = route.describe()
        self.assertIn("fan_out plan ->", text)
        self.assertIn("switch completion_verdict:", text)
        self.assertIn("verified -> complete", text)
        self.assertIn("partial -> retry", text)
        self.assertIn("rejected -> escalate", text)
        self.assertIn("-> team_complete [require_all]", text)
        # The developer item joins after its dependency (the researcher item).
        researcher, developer = (item.item_id for item in team.plan)
        joins = [
            edge
            for edge in route.edges
            if isinstance(edge, FanIn) and edge.to_step == developer
        ]
        self.assertEqual(len(joins), 1)
        self.assertEqual(joins[0].from_steps, (researcher,))

    def test_parallel_team_fans_out_to_both_items(self):
        team = ProjectTeam(
            team_id="tp",
            project_title="并行项目",
            plan=(
                TeamPlanItem(
                    item_id="tp-item-1",
                    title="A",
                    objective="做 A",
                    acceptance_criteria=("A 完成",),
                    assignee="调研-01",
                ),
                TeamPlanItem(
                    item_id="tp-item-2",
                    title="B",
                    objective="做 B",
                    acceptance_criteria=("B 完成",),
                    assignee="开发-01",
                ),
            ),
            work_thread_id="thread-1",
        )
        route = describe_team_route(team)
        fan_outs = [e for e in route.edges if isinstance(e, FanOut)]
        self.assertEqual(len(fan_outs), 1)
        self.assertEqual(fan_outs[0].to_steps, ("tp-item-1", "tp-item-2"))

    def test_rolling_route_uses_all_three_kinds(self):
        route = describe_rolling_route()
        kinds = [type(edge).__name__ for edge in route.edges]
        self.assertIn("FanOut", kinds)
        self.assertIn("FanIn", kinds)
        self.assertIn("SwitchCase", kinds)
        self.assertIn("switch proposal_valid:", route.describe())
        self.assertIn("switch verification:", route.describe())


class CheckpointProtocolTests(unittest.TestCase):
    def test_checkpoint_round_trip(self):
        checkpoint = Checkpoint(
            checkpoint_id="tx:pulse-3",
            team_id="tx",
            pulse=3,
            completed_step_ids=("tx-item-01",),
            pending_step_ids=("tx-item-02",),
            state={"stop_reason": None},
        )
        restored = Checkpoint.from_dict(checkpoint.to_dict())
        self.assertEqual(restored, checkpoint)

    def test_checkpoint_from_dict_rejects_missing_ids(self):
        with self.assertRaises(ValueError):
            Checkpoint.from_dict({"team_id": "tx"})
        with self.assertRaises(ValueError):
            Checkpoint.from_dict({"checkpoint_id": "x"})

    def test_in_memory_storage_crud(self):
        storage = InMemoryCheckpointStorage()
        self.assertIsNone(storage.load(team_id="tx", checkpoint_id="nope"))
        self.assertIsNone(storage.latest(team_id="tx"))
        self.assertFalse(storage.delete(team_id="tx", checkpoint_id="nope"))
        self.assertEqual(storage.list_ids(team_id="tx"), [])

        first = Checkpoint(
            checkpoint_id="tx:pulse-1", team_id="tx", pulse=1
        )
        second = Checkpoint(
            checkpoint_id="tx:pulse-2",
            team_id="tx",
            pulse=2,
            completed_step_ids=("tx-item-01",),
            pending_step_ids=("tx-item-02",),
        )
        storage.save(first)
        storage.save(second)
        self.assertEqual(storage.load(team_id="tx", checkpoint_id="tx:pulse-1"), first)
        self.assertEqual(storage.latest(team_id="tx"), second)
        self.assertEqual(
            storage.list_ids(team_id="tx"), ["tx:pulse-1", "tx:pulse-2"]
        )
        self.assertTrue(storage.delete(team_id="tx", checkpoint_id="tx:pulse-1"))
        self.assertIsNone(storage.load(team_id="tx", checkpoint_id="tx:pulse-1"))
        self.assertFalse(storage.delete(team_id="tx", checkpoint_id="tx:pulse-1"))

    def test_pending_steps_excludes_completed_preserves_order(self):
        checkpoint = Checkpoint(
            checkpoint_id="tx:pulse-2",
            team_id="tx",
            pulse=2,
            completed_step_ids=("b",),
        )
        self.assertEqual(pending_steps(checkpoint, ["a", "b", "c"]), ["a", "c"])


class _RunnerFixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-af2-"))
        self.store = KernelStore(self.root / "kernel.db")
        resident = SimpleNamespace(
            store=SimpleNamespace(path=str(self.root / "kernel.db"))
        )
        self.ledger = EvidenceBoundSteerableWorkLedger(resident)
        self.memory = StructuredMemory(self.store)
        self.thread_id = "thread-af2"
        self.ledger.create_thread(thread_id=self.thread_id, title="项目 X")
        self.ledger._save_item(
            WorkItem(
                work_item_id="root-1",
                work_thread_id=self.thread_id,
                title="XX 项目",
                objective="把 XX 项目做完",
                status="running",
                plan_version=1,
            )
        )
        self.team = assemble_team(
            "XX 项目",
            ["researcher", "developer"],
            team_id="tx",
            work_thread_id=self.thread_id,
        )
        self.plan_ids = [item.item_id for item in self.team.plan]
        self.verifier = StubVerifier()
        self.storage = InMemoryCheckpointStorage()
        self.runner = TeamRunner(
            team=self.team,
            ledger=self.ledger,
            memory=self.memory,
            verifier=self.verifier,
            root_work_item_id="root-1",
            checkpoint_storage=self.storage,
        )

    def tearDown(self):
        self.store.close()

    def _wid(self, plan_item_id: str) -> str:
        shared = team_shared_memory(self.memory, "tx")
        return shared.recall("plan_item_map").value[plan_item_id]

    def _claim(self, work_item_id: str, summary: str = "做完了"):
        runs = self.ledger.list_worker_runs(work_item_id=work_item_id)
        self.assertTrue(runs, f"no run for {work_item_id}")
        run = runs[-1]
        self.ledger.complete_worker_run(
            run.worker_run_id,
            result_summary=summary,
            claimed_completion=True,
            verification_status="pending",
        )


class RunnerCheckpointTests(_RunnerFixture):
    def test_no_storage_means_no_checkpoint(self):
        runner = TeamRunner(
            team=self.team,
            ledger=self.ledger,
            memory=self.memory,
            verifier=self.verifier,
            root_work_item_id="root-1",
        )
        self.assertIsNone(runner.save_checkpoint())
        self.assertIsNone(runner.latest_checkpoint())
        self.assertEqual(runner.pending_step_ids(), self.plan_ids)

    def test_checkpoint_saved_each_pulse_and_tracks_completion(self):
        self.runner.step()  # dispatch item 1
        checkpoint = self.runner.latest_checkpoint()
        self.assertIsNotNone(checkpoint)
        assert checkpoint is not None
        self.assertEqual(list(checkpoint.completed_step_ids), [])
        self.assertEqual(
            list(checkpoint.pending_step_ids), self.plan_ids
        )
        self.assertEqual(self.runner.pending_step_ids(), self.plan_ids)

        wid1 = self._wid(self.plan_ids[0])
        self._claim(wid1)
        self.runner.step()  # verify item 1
        self.runner.step()  # complete item 1
        checkpoint = self.runner.latest_checkpoint()
        self.assertIsNotNone(checkpoint)
        assert checkpoint is not None
        self.assertEqual(
            list(checkpoint.completed_step_ids), [self.plan_ids[0]]
        )
        self.assertEqual(
            list(checkpoint.pending_step_ids), [self.plan_ids[1]]
        )
        self.assertEqual(
            self.runner.pending_step_ids(), [self.plan_ids[1]]
        )
        # The checkpoint carries the plan map so a restart can rebuild.
        self.assertEqual(
            checkpoint.state["plan_item_map"][self.plan_ids[0]], wid1
        )

    def test_interrupt_resume_does_not_rerun_completed_steps(self):
        # Run item 1 to completion, then "interrupt": drop the runner.
        self.runner.step()
        wid1 = self._wid(self.plan_ids[0])
        self._claim(wid1)
        self.runner.step()
        self.runner.step()
        checkpoint = self.runner.latest_checkpoint()
        self.assertIsNotNone(checkpoint)
        assert checkpoint is not None
        self.assertEqual(
            list(checkpoint.completed_step_ids), [self.plan_ids[0]]
        )

        # Restart: a fresh runner on the same durable ledger + storage.
        resumed = TeamRunner(
            team=self.team,
            ledger=self.ledger,
            memory=self.memory,
            verifier=self.verifier,
            root_work_item_id="root-1",
            checkpoint_storage=self.storage,
        )
        self.assertEqual(resumed.pending_step_ids(), [self.plan_ids[1]])

        # Drive to team completion; item 1 must never be re-dispatched.
        wid2 = self._wid(self.plan_ids[1])
        for _ in range(8):
            result = resumed.step()
            if result.team_complete:
                break
            live = [
                action
                for action in result.actions
                if action.startswith("dispatched:")
            ]
            self.assertNotIn(f"dispatched:{wid1}", live)
            if f"dispatched:{wid2}" in result.actions:
                self._claim(wid2, summary="开发完成")
        else:
            self.fail("team did not complete after resume")
        self.assertTrue(result.team_complete)

        items = {
            item.work_item_id: item
            for item in self.ledger.list_work_items(self.thread_id)
        }
        children = [
            item for item in items.values() if item.parent_work_item_id == "root-1"
        ]
        self.assertEqual(len(children), 2)  # no duplicated plan items
        self.assertEqual(items[wid1].status, "completed")
        self.assertEqual(items[wid2].status, "completed")
        self.assertEqual(
            list(self.storage.latest(team_id="tx").completed_step_ids),
            self.plan_ids,
        )


class OwnerCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-af2-owner-"))
        self.store = KernelStore(self.root / "kernel.db")
        resident = SimpleNamespace(
            store=SimpleNamespace(path=str(self.root / "kernel.db"))
        )
        self.ledger = EvidenceBoundSteerableWorkLedger(resident)
        self.memory = StructuredMemory(self.store)
        self.thread_id = "thread-af2-owner"
        self.ledger.create_thread(thread_id=self.thread_id, title="项目 X")
        self.ledger._save_item(
            WorkItem(
                work_item_id="root-entry",
                work_thread_id=self.thread_id,
                title="XX 项目",
                objective="给 XX 项目组个团队",
                status="running",
                plan_version=1,
            )
        )
        self.event = SimpleNamespace(
            event_id="evt-af2",
            payload={
                "work_thread_id": self.thread_id,
                "work_item_id": "root-entry",
                "workspace_path": str(self.root / "ws"),
                "team_request": {
                    "project_title": "XX 项目",
                    "role_keys": ["researcher", "developer"],
                },
            },
        )
        self.state = SimpleNamespace(data={})
        self.storage = InMemoryCheckpointStorage()
        self.owner = TeamWorkOwner(
            ledger=self.ledger,
            memory=self.memory,
            checkpoint_storage=self.storage,
        )

    def tearDown(self):
        self.store.close()

    def test_owner_advance_saves_checkpoint(self):
        step = self.owner.advance(
            event=self.event,
            state=self.state,
            root_work_item_id="root-entry",
        )
        self.assertIsNotNone(step.live_run_id)
        team_id = self.state.data[TEAM_ID_STATE_KEY]
        checkpoint = self.owner.latest_checkpoint(team_id)
        self.assertIsNotNone(checkpoint)
        assert checkpoint is not None
        self.assertEqual(checkpoint.team_id, team_id)
        self.assertEqual(list(checkpoint.completed_step_ids), [])
        self.assertEqual(len(checkpoint.pending_step_ids), 2)

    def test_owner_without_storage_has_no_checkpoint(self):
        owner = TeamWorkOwner(ledger=self.ledger, memory=self.memory)
        self.assertIsNone(owner.latest_checkpoint("tx"))

    def test_owner_describe_route(self):
        team = assemble_team(
            "XX 项目",
            ["researcher", "developer"],
            team_id="tx",
            work_thread_id=self.thread_id,
        )
        route = TeamWorkOwner.describe_route(team)
        self.assertEqual(route.name, "team:tx")
        self.assertIn("fan_out plan ->", route.describe())


if __name__ == "__main__":
    unittest.main()
