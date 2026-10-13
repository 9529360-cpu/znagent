"""Slice 4 vertical test: a team runs end to end on the real Work ledger.

assemble_team -> ensure_plan_items -> coordinator.step -> apply
    -> verify (stubbed fresh observation) -> complete -> retrospective

Uses the real EvidenceBoundSteerableWorkLedger on a temp sqlite file
with a minimal fake resident (the ledger only needs resident.store.path).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.evidence_bound_work import EvidenceBoundSteerableWorkLedger
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.project_team import assemble_team
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.store import KernelStore
from zn_agent.core.team_memory import team_shared_memory
from zn_agent.core.team_runner import (
    TeamRunner,
    VerificationOutcome,
)


class StubVerifier:
    """Fresh observation, stubbed: pass unless told otherwise."""

    def __init__(self, passed: bool = True):
        self.passed = passed
        self.calls: list[str] = []

    def verify(self, *, item, run):
        self.calls.append(item.work_item_id)
        return VerificationOutcome(
            passed=self.passed, notes="stub checked the artifacts"
        )


class TeamRunnerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-team-run-"))
        # The ledger shares the resident's sqlite file (events table lives
        # in the kernel schema), exactly like production.
        self.store = KernelStore(self.root / "kernel.db")
        resident = SimpleNamespace(
            store=SimpleNamespace(path=str(self.root / "kernel.db"))
        )
        self.ledger = EvidenceBoundSteerableWorkLedger(resident)
        self.memory = StructuredMemory(self.store)
        self.thread_id = "thread-team-1"
        self.ledger.create_thread(thread_id=self.thread_id, title="项目 X")
        root = WorkItem(
            work_item_id="root-1",
            work_thread_id=self.thread_id,
            title="XX 项目",
            objective="把 XX 项目做完",
            status="running",
            plan_version=1,
        )
        self.ledger._save_item(root)
        self.team = assemble_team(
            "XX 项目",
            ["researcher", "developer"],
            team_id="tx",
            work_thread_id=self.thread_id,
        )
        self.verifier = StubVerifier()
        self.runner = TeamRunner(
            team=self.team,
            ledger=self.ledger,
            memory=self.memory,
            verifier=self.verifier,
            root_work_item_id="root-1",
        )

    def tearDown(self):
        self.store.close()

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

    def _wid(self, plan_item_id: str) -> str:
        shared = team_shared_memory(self.memory, "tx")
        return shared.recall("plan_item_map").value[plan_item_id]

    def test_full_loop_to_retrospective(self):
        plan_ids = [p.item_id for p in self.team.plan]
        self.assertEqual(len(plan_ids), 2)

        # Step 1: items materialized, first dispatched (deps chain).
        r1 = self.runner.step()
        self.assertTrue(
            any(a.startswith("dispatched:") for a in r1.actions), r1.actions
        )
        wid1 = self._wid(plan_ids[0])

        # Worker claims completion.
        self._claim(wid1)

        # Step 2: verify with fresh observation (stubbed).
        r2 = self.runner.step()
        self.assertIn(f"verified:{wid1}:pass", r2.actions)
        self.assertEqual(self.verifier.calls, [wid1])

        # Step 3: complete item 1 (item 2's readiness is evaluated on the
        # pre-step snapshot, so its dispatch lands on the next step).
        r3 = self.runner.step()
        wid2 = self._wid(plan_ids[1])
        self.assertIn(f"completed:{wid1}", r3.actions)

        # Step 4: item 2's dependency is now completed -> dispatched.
        r4 = self.runner.step()
        self.assertIn(f"dispatched:{wid2}", r4.actions)

        self._claim(wid2, summary="开发完成")

        # Step 5+6: verify then complete item 2 -> team complete.
        r5 = self.runner.step()
        self.assertIn(f"verified:{wid2}:pass", r5.actions)
        r6 = self.runner.step()
        self.assertIn(f"completed:{wid2}", r6.actions)

        # Step 7: all items completed on the pre-step snapshot -> done.
        r7 = self.runner.step()
        self.assertTrue(r7.team_complete)
        self.assertIsNotNone(r7.retrospective_summary)
        self.assertIn("tx", r7.retrospective_summary)

        # Retrospective persisted under the team shared namespace.
        shared = team_shared_memory(self.memory, "tx")
        retro = shared.recall("retrospective")
        self.assertIsNotNone(retro)
        self.assertEqual(retro.value["team_id"], "tx")

        # All items really completed in the ledger.
        items = {
            i.work_item_id: i
            for i in self.ledger.list_work_items(self.thread_id)
        }
        self.assertEqual(items[wid1].status, "completed")
        self.assertEqual(items[wid2].status, "completed")

    def test_plan_map_survives_runner_restart(self):
        self.runner.step()
        plan_ids = [p.item_id for p in self.team.plan]
        wid1 = self._wid(plan_ids[0])
        # A fresh runner on the same durable state must not duplicate items.
        runner2 = TeamRunner(
            team=self.team,
            ledger=self.ledger,
            memory=self.memory,
            verifier=self.verifier,
            root_work_item_id="root-1",
        )
        id_map = runner2.ensure_plan_items()
        self.assertEqual(id_map[plan_ids[0]], wid1)
        items = self.ledger.list_work_items(self.thread_id)
        children = [i for i in items if i.parent_work_item_id == "root-1"]
        self.assertEqual(len(children), 2)

    def test_escalation_on_blocked_item(self):
        self.runner.step()
        plan_ids = [p.item_id for p in self.team.plan]
        wid1 = self._wid(plan_ids[0])
        self.ledger.block_child_item(wid1, blocker="卡住了")
        result = self.runner.step()
        self.assertEqual(len(result.escalations), 1)
        self.assertEqual(result.escalations[0].work_item_id, wid1)
        self.assertFalse(result.team_complete)

    def test_failed_verification_does_not_complete(self):
        self.runner.step()
        plan_ids = [p.item_id for p in self.team.plan]
        wid1 = self._wid(plan_ids[0])
        self._claim(wid1)
        self.verifier.passed = False
        r2 = self.runner.step()
        self.assertIn(f"verified:{wid1}:fail", r2.actions)
        r3 = self.runner.step()
        self.assertNotIn(f"completed:{wid1}", r3.actions)
        items = {
            i.work_item_id: i
            for i in self.ledger.list_work_items(self.thread_id)
        }
        self.assertNotEqual(items[wid1].status, "completed")


if __name__ == "__main__":
    unittest.main()
