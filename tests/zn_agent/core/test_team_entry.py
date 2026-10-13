"""Team entry wiring: parse -> owner drives TeamRunner on the real ledger.

Covers the vertical slice that connects a user's "assemble a team" sentence
to the runner: the daemon tags ``team_request`` at ingress, the resident-side
owner loads/assembles the team durably, applies one runner step per pulse,
binds verified specialist evidence, claims via the specialist's prose, and
verifies before completing -- all against the real
EvidenceBoundSteerableWorkLedger. No mocks for the ledger, the runner, or
the verifier.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.evidence_bound_work import EvidenceBoundSteerableWorkLedger
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.store import KernelStore
from zn_agent.core.team_memory import team_shared_memory
from zn_agent.core.team_request import parse_team_request
from zn_agent.core.team_work_owner import (
    EVIDENCE_KEY,
    TEAM_CLAIM_STATE_KEY,
    TeamWorkOwner,
    verified_evidence,
)


class ParseTeamRequestTests(unittest.TestCase):
    def test_chinese_default_roles(self):
        parsed = parse_team_request("给 XX 项目组个团队")
        assert parsed is not None
        self.assertEqual(parsed.project_title, "XX 项目")
        self.assertEqual(
            parsed.role_keys, ("researcher", "architect", "developer", "tester")
        )

    def test_chinese_explicit_role_only(self):
        parsed = parse_team_request("组建一个团队做记账 App，带一个测试")
        assert parsed is not None
        self.assertEqual(parsed.project_title, "做记账 App")
        self.assertEqual(parsed.role_keys, ("tester",))

    def test_chinese_multiple_explicit_roles_in_plan_order(self):
        parsed = parse_team_request("给新产品组个团队，需要架构和测试")
        assert parsed is not None
        self.assertEqual(parsed.project_title, "新产品")
        self.assertEqual(parsed.role_keys, ("architect", "tester"))

    def test_english_roles(self):
        parsed = parse_team_request(
            "assemble a team for the billing app with a designer"
        )
        assert parsed is not None
        self.assertEqual(parsed.project_title, "the billing app")
        self.assertEqual(parsed.role_keys, ("architect",))

    def test_english_build_filler_is_not_a_role(self):
        parsed = parse_team_request("assemble a team to build the dashboard")
        assert parsed is not None
        self.assertEqual(parsed.project_title, "the dashboard")
        self.assertEqual(
            parsed.role_keys, ("researcher", "architect", "developer", "tester")
        )

    def test_plain_task_is_not_a_team_request(self):
        self.assertIsNone(parse_team_request("帮我写个脚本"))
        self.assertIsNone(parse_team_request("查一下明天的天气"))

    def test_passing_mention_is_not_a_team_request(self):
        self.assertIsNone(parse_team_request("我们团队明天开会"))
        self.assertIsNone(parse_team_request("团队的周报写完了吗"))

    def test_no_project_left_is_not_a_team_request(self):
        self.assertIsNone(parse_team_request("组个团队"))
        self.assertIsNone(parse_team_request(""))
        self.assertIsNone(parse_team_request("   "))

    def test_project_about_testing_is_not_a_tester_role(self):
        parsed = parse_team_request("做一个测试项目，组个团队")
        assert parsed is not None
        self.assertEqual(parsed.project_title, "做一个测试项目")
        self.assertEqual(
            parsed.role_keys, ("researcher", "architect", "developer", "tester")
        )


class TeamWorkOwnerIntegrationTests(unittest.TestCase):
    """Owner + runner on the real ledger; the test plays the specialist."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-team-entry-"))
        self.store = KernelStore(self.root / "kernel.db")
        resident = SimpleNamespace(
            store=SimpleNamespace(path=str(self.root / "kernel.db"))
        )
        self.ledger = EvidenceBoundSteerableWorkLedger(resident)
        self.memory = StructuredMemory(self.store)
        self.thread_id = "thread-team-entry"
        self.ledger.create_thread(thread_id=self.thread_id, title="项目 X")
        self.root_item = WorkItem(
            work_item_id="root-entry",
            work_thread_id=self.thread_id,
            title="XX 项目",
            objective="给 XX 项目组个团队",
            status="running",
            plan_version=1,
        )
        self.ledger._save_item(self.root_item)
        self.event = SimpleNamespace(
            event_id="evt-team-entry",
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
        self.owner = TeamWorkOwner(ledger=self.ledger, memory=self.memory)

    def tearDown(self):
        self.store.close()

    def _advance(self):
        return self.owner.advance(
            event=self.event,
            state=self.state,
            root_work_item_id="root-entry",
        )

    def _record_evidence(self, run_id: str, summary: str = "调研完成") -> None:
        run = self.ledger.worker_run(run_id)
        assert run is not None
        evidence = verified_evidence(run)
        evidence.append(
            {
                "kind": "verified_body_step",
                "objective": "specialist step",
                "result": summary,
                "verified": True,
                "artifact_refs": [],
            }
        )
        self.ledger.update_worker_run_metrics(
            run_id, metrics={EVIDENCE_KEY: evidence}
        )

    def test_full_loop_to_team_complete(self):
        # Pulse 1: team assembled, first item dispatched.
        step = self._advance()
        self.assertIsNotNone(step.live_run_id)
        self.assertEqual(step.live_specialist_name, "调研-01")

        # Specialist does verified work, then claims via prose summary.
        assert step.live_run_id is not None
        self._record_evidence(step.live_run_id, "调研结论：用方案 A")
        self.state.data[TEAM_CLAIM_STATE_KEY] = {
            "run_id": step.live_run_id,
            "summary": "调研完成，结论：用方案 A，风险清单已附",
        }

        # Pulse 2: claim applied, runner verifies with fresh observation.
        step = self._advance()
        self.assertIsNone(step.live_run_id)  # claimed run is not live
        run = self.ledger.worker_run(step.live_run_id) if step.live_run_id else None
        self.assertIsNone(run)

        # Pulse 3: item 1 completes (item 2's readiness was evaluated on
        # the pre-step snapshot, so its dispatch lands on the next step).
        step = self._advance()
        self.assertIsNone(step.live_run_id)
        items = {
            item.work_item_id: item
            for item in self.ledger.list_work_items(self.thread_id)
        }
        first = next(
            item for item in items.values() if item.title == "XX 项目·调研"
        )
        self.assertEqual(first.status, "completed")

        # Pulse 4: second item dispatched.
        step = self._advance()
        self.assertIsNotNone(step.live_run_id)
        self.assertEqual(step.live_specialist_name, "开发-02")

        # Second specialist, same rhythm: verify, complete, team_complete.
        assert step.live_run_id is not None
        self._record_evidence(step.live_run_id, "实现完成")
        self.state.data[TEAM_CLAIM_STATE_KEY] = {
            "run_id": step.live_run_id,
            "summary": "开发完成，功能按验收实现",
        }
        self._advance()  # claim applied -> verify
        self._advance()  # item 2 completes
        step = self._advance()  # all items completed -> team_complete
        self.assertTrue(step.team_complete)
        self.assertIsNotNone(step.retrospective_summary)

    def test_claim_without_evidence_is_dropped(self):
        step = self._advance()
        assert step.live_run_id is not None
        # Prose claim with zero verified evidence must not land.
        self.state.data[TEAM_CLAIM_STATE_KEY] = {
            "run_id": step.live_run_id,
            "summary": "我做完了（但没有任何可验证证据）",
        }
        self._advance()
        run = self.ledger.worker_run(step.live_run_id)
        assert run is not None
        self.assertFalse(run.claimed_completion)

    def test_restart_does_not_duplicate_plan_items(self):
        self._advance()
        before = [
            item.work_item_id
            for item in self.ledger.list_work_items(self.thread_id)
            if item.parent_work_item_id == "root-entry"
        ]
        # Simulate a restart: a fresh owner, same durable state + memory.
        fresh_owner = TeamWorkOwner(ledger=self.ledger, memory=self.memory)
        fresh_owner.advance(
            event=self.event,
            state=self.state,
            root_work_item_id="root-entry",
        )
        after = [
            item.work_item_id
            for item in self.ledger.list_work_items(self.thread_id)
            if item.parent_work_item_id == "root-entry"
        ]
        self.assertEqual(before, after)

    def test_team_spec_persists_for_reconstruction(self):
        self._advance()
        shared = team_shared_memory(self.memory, self.state.data["team_id"])
        spec = shared.recall("team_spec")
        assert spec is not None
        self.assertEqual(spec.value["project_title"], "XX 项目")
        self.assertEqual(spec.value["role_keys"], ["researcher", "developer"])

    def test_non_team_event_is_not_handled(self):
        plain = SimpleNamespace(payload={"task": "hello"})
        self.assertFalse(TeamWorkOwner.handles(plain))
        self.assertFalse(
            TeamWorkOwner.handles(
                SimpleNamespace(payload={"team_request": {"project_title": ""}})
            )
        )


if __name__ == "__main__":
    unittest.main()
