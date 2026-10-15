"""Team entry wiring: parse -> owner drives TeamRunner on the real ledger.

Covers the vertical slice that connects a user's "assemble a team" sentence
to the runner: the daemon tags ``team_request`` at ingress, the resident-side
owner loads/assembles the team durably, applies one runner step per pulse,
binds verified specialist evidence, claims via a structured CP-3
completion report, and verifies before completing -- all against the real
EvidenceBoundSteerableWorkLedger. No mocks for the ledger, the runner, or
the verifier.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.completion_verdict import render_completion_report
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

    def _record_evidence(
        self, run_id: str, summary: str = "调研完成", *, action_kind: str = ""
    ) -> None:
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
                # P2: a test-coverage claim needs a run_python evidence
                # entry -- the dev fixture records one honestly instead
                # of claiming coverage from a write alone.
                "action_kind": action_kind,
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

        # Specialist does verified work, then claims with a structured
        # CP-3 completion report citing each acceptance criterion.
        assert step.live_run_id is not None
        self._record_evidence(step.live_run_id, "调研结论：用方案 A")
        self.state.data[TEAM_CLAIM_STATE_KEY] = {
            "run_id": step.live_run_id,
            "summary": render_completion_report(
                conclusion="调研完成，结论：用方案 A，风险清单已附",
                evidence=[
                    ("调研结论有明确选型建议", "调研结论：用方案 A"),
                    ("风险清单覆盖主要未知项", "调研结论：用方案 A"),
                ],
                files=[],
                unfinished=[],
                # AS-3: the owner requires both tracks; attest DoD.
                standing_dod={
                    "no_regression": {
                        "status": "not_applicable",
                        "detail": "纯调研任务，无代码变更，无回归面。",
                    },
                    "runtime_verified": {
                        "status": "not_applicable",
                        "detail": "纯调研任务，无需运行时验证。",
                    },
                    "docs": {
                        "status": "satisfied",
                        "detail": "结论与风险已写入调研产物。",
                        "evidence_ref": "调研结论：用方案 A",
                    },
                    "rollback": {
                        "status": "satisfied",
                        "detail": "删除调研产物即可回退。",
                    },
                    "approval": {
                        "status": "satisfied",
                        "detail": "无破坏性/外部动作，无需审批。",
                    },
                },
            ),
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
        # P2: the dev claim cites test coverage, so its evidence carries
        # a run_python entry -- coverage claimed from a write alone is
        # now partial, not verified.
        assert step.live_run_id is not None
        self._record_evidence(step.live_run_id, "实现完成", action_kind="run_python")
        self.state.data[TEAM_CLAIM_STATE_KEY] = {
            "run_id": step.live_run_id,
            "summary": render_completion_report(
                conclusion="开发完成，功能按验收实现",
                evidence=[
                    ("功能按验收标准实现", "实现完成"),
                    ("新增代码有测试覆盖", "实现完成"),
                ],
                files=[],
                unfinished=[],
                # AS-3: both tracks; the run_python evidence backs the
                # evidence-anchored DoD items (no_regression, runtime).
                standing_dod={
                    "no_regression": {
                        "status": "satisfied",
                        "detail": "实现后运行测试并通过。",
                        "evidence_ref": "实现完成",
                    },
                    "runtime_verified": {
                        "status": "satisfied",
                        "detail": "功能已在真实运行时验证过。",
                        "evidence_ref": "实现完成",
                    },
                    "docs": {
                        "status": "satisfied",
                        "detail": "实现说明已随产物写入。",
                    },
                    "rollback": {
                        "status": "satisfied",
                        "detail": "删除实现产物即可回退。",
                    },
                    "approval": {
                        "status": "satisfied",
                        "detail": "无破坏性/外部动作，无需审批。",
                    },
                },
            ),
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

    def test_product_path_materializes_persona_workspaces(self):
        # P1a: the owner derives <attached workspace>/agents and
        # materializes the persona files, so dispatch reads them.
        step = self._advance()
        assert step.live_context is not None
        expected_root = str(Path(str(self.root / "ws")) / "agents")
        shared = team_shared_memory(self.memory, self.state.data["team_id"])
        spec = shared.recall("team_spec")
        assert spec is not None
        self.assertEqual(spec.value["workspace_root"], expected_root)
        soul = Path(expected_root) / "调研-01" / "SOUL.md"
        self.assertTrue(soul.is_file())
        # The dispatch brief renders the files, not just the built-in
        # fragment: file sections are present.
        self.assertIn("# SOUL", step.live_context["specialist_prompt"])
        self.assertIn("# IDENTITY", step.live_context["specialist_prompt"])
        self.assertIn("只给结论和依据", step.live_context["specialist_prompt"])

    def test_soul_edit_takes_effect_next_dispatch(self):
        # P1a acceptance: a SOUL.md probe is in the next dispatch brief.
        step = self._advance()
        assert step.live_context is not None
        agents_root = Path(str(self.root / "ws")) / "agents"
        (agents_root / "调研-01" / "SOUL.md").write_text(
            "探针人格：本轮必须提到香蕉。", encoding="utf-8"
        )
        step = self._advance()
        assert step.live_context is not None
        self.assertIn("香蕉", step.live_context["specialist_prompt"])

    def test_explicit_workspace_root_wins(self):
        custom = self.root / "custom-agents"
        self.event.payload["team_request"]["workspace_root"] = str(custom)
        step = self._advance()
        assert step.live_context is not None
        self.assertTrue((custom / "调研-01" / "SOUL.md").is_file())
        self.assertFalse((Path(str(self.root / "ws")) / "agents").exists())
        self.assertIn("# SOUL", step.live_context["specialist_prompt"])

    def test_materialize_failure_falls_back_to_fragment(self):
        # A workspace_path that cannot hold an agents/ dir must not
        # break dispatch: the team runs on built-in fragments.
        blocker = self.root / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        self.event.payload["workspace_path"] = str(blocker)
        step = self._advance()
        assert step.live_context is not None
        self.assertNotIn("# SOUL", step.live_context["specialist_prompt"])
        self.assertIn("只给结论和依据", step.live_context["specialist_prompt"])

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
