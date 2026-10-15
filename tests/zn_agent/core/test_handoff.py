"""AF-4: handoff as a tool + automatic-handoff middleware.

Covers the owner-side handoff seam in ``team_work_owner``: a specialist
hands a plan item to another specialist with full context (task +
progress + evidence refs), the middleware drains explicit requests and
applies the conservative capability-mismatch rule, and every executed /
rejected handoff is audited + journaled. Uses the real ledger and memory
-- no mocks for the paths under test.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.evidence_bound_work import EvidenceBoundSteerableWorkLedger
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.project_team import (
    ProjectTeam,
    Specialist,
    TeamPlanItem,
    assemble_team,
)
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.store import KernelStore
from zn_agent.core.team_memory import team_shared_memory
from zn_agent.core.team_runner import TeamRunner
from zn_agent.core.team_timeline import record_assignee_override
from zn_agent.core.team_work_owner import (
    HANDOFF_LOG_KEY,
    TeamWorkOwner,
    handoff_tool_spec,
)


def _member(name: str, role_key: str, title: str, responsibilities: tuple[str, ...]) -> Specialist:
    return Specialist(
        name=name,
        role_key=role_key,
        role_title=title,
        responsibilities=responsibilities,
        memory_namespace=f"ns-{name}",
        prompt_fragment="",
    )


def _custom_team() -> ProjectTeam:
    """Two-member team: a docs writer holding a deploy item (mismatch)."""
    return ProjectTeam(
        team_id="team-handoff-custom",
        project_title="部署项目",
        members=(
            _member("doc-writer", "writer", "文档", ("写文档",)),
            _member("deployer", "deployer", "部署", ("部署服务到生产",)),
        ),
        plan=(
            TeamPlanItem(
                item_id="item-1",
                title="部署服务",
                objective="部署服务到生产环境",
                acceptance_criteria=("服务可访问",),
                assignee="doc-writer",
            ),
        ),
        work_thread_id="thread-handoff",
    )


class HandoffTestBase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-handoff-"))
        self.store = KernelStore(self.root / "kernel.db")
        resident = SimpleNamespace(
            store=SimpleNamespace(path=str(self.root / "kernel.db"))
        )
        self.ledger = EvidenceBoundSteerableWorkLedger(resident)
        self.memory = StructuredMemory(self.store)
        self.thread_id = "thread-handoff"
        self.ledger.create_thread(thread_id=self.thread_id, title="交接项目")
        self.owner = TeamWorkOwner(ledger=self.ledger, memory=self.memory)
        self.team = assemble_team(
            "XX 项目",
            ["researcher", "developer"],
            team_id="team-handoff",
            work_thread_id=self.thread_id,
        )
        self.researcher = self.team.members[0].name  # 调研-01
        self.developer = self.team.members[1].name  # 开发-02

    def tearDown(self):
        self.store.close()

    def _journal_handoffs(self):
        return [
            msg
            for msg in self.ledger.list_messages(self.thread_id)
            if (msg.detail or {}).get("kind") == "handoff"
        ]


class ToolHandoffTests(HandoffTestBase):
    def test_tool_handoff_carries_full_context(self):
        item = self.team.plan[0]
        self.assertEqual(item.assignee, self.researcher)
        record = self.owner.execute_handoff(
            team=self.team,
            plan_item_id=item.item_id,
            from_specialist=self.researcher,
            to_specialist=self.developer,
            reason="需要动手实现，不只是调研",
            progress_summary="已确认选型 A；待实现接口 X",
            evidence_refs=[{"relative_path": "notes/research.md", "result": "选型 A"}],
        )
        self.assertEqual(record["status"], "executed")
        self.assertEqual(record["triggered_by"], "tool")
        self.assertEqual(record["from_specialist"], self.researcher)
        self.assertEqual(record["to_specialist"], self.developer)
        # Context: task + progress + evidence refs travel together.
        context = record["context"]
        self.assertEqual(context["task"]["plan_item_id"], item.item_id)
        self.assertTrue(context["task"]["objective"])
        self.assertEqual(
            context["task"]["acceptance_criteria"],
            list(item.acceptance_criteria),
        )
        self.assertEqual(context["progress_summary"], "已确认选型 A；待实现接口 X")
        self.assertEqual(
            context["evidence_refs"],
            [{"relative_path": "notes/research.md", "result": "选型 A"}],
        )
        self.assertIn("prior_items", context)
        self.assertIn("live_evidence", context)
        # The override is durable: re-resolving shows the new assignee.
        effective = self.owner._effective_team(self.team)
        self.assertEqual(effective.plan[0].assignee, self.developer)
        # Audit log + journal both record the handoff.
        log = self.owner.handoff_log(team_id="team-handoff")
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["handoff_id"], record["handoff_id"])
        journal = self._journal_handoffs()
        self.assertEqual(len(journal), 1)
        self.assertEqual(journal[0].detail["from_author"], self.researcher)
        self.assertEqual(journal[0].detail["to_author"], self.developer)
        self.assertEqual(journal[0].detail["handoff_id"], record["handoff_id"])

    def test_tool_handoff_validation(self):
        item = self.team.plan[0]
        base = {
            "team": self.team,
            "plan_item_id": item.item_id,
            "from_specialist": self.researcher,
            "to_specialist": self.developer,
            "reason": "需要实现",
        }
        with self.assertRaises(ValueError):
            self.owner.execute_handoff(**{**base, "plan_item_id": "no-such-item"})
        with self.assertRaises(ValueError):
            self.owner.execute_handoff(**{**base, "to_specialist": "no-such-member"})
        with self.assertRaises(ValueError):
            self.owner.execute_handoff(**{**base, "to_specialist": self.researcher})
        with self.assertRaises(ValueError):
            self.owner.execute_handoff(**{**base, "reason": "   "})
        # Only the current holder can hand off.
        with self.assertRaises(ValueError):
            self.owner.execute_handoff(**{**base, "from_specialist": self.developer})
        # A completed item cannot be handed off.
        shared = team_shared_memory(self.memory, "team-handoff")
        shared.remember(
            TeamRunner.PLAN_MAP_KEY, {item.item_id: "wid-completed"}
        )
        self.ledger._save_item(
            WorkItem(
                work_item_id="wid-completed",
                work_thread_id=self.thread_id,
                title=item.title,
                objective=item.objective,
                status="completed",
                plan_version=1,
            )
        )
        with self.assertRaises(ValueError):
            self.owner.execute_handoff(**base)
        self.assertEqual(self.owner.handoff_log(team_id="team-handoff"), [])

    def test_tool_spec_shape(self):
        spec = handoff_tool_spec()
        self.assertEqual(spec["name"], "handoff_task")
        self.assertTrue(spec["description"])
        required = spec["parameters"]["required"]
        self.assertIn("plan_item_id", required)
        self.assertIn("to_specialist", required)
        self.assertIn("reason", required)
        self.assertIn("progress_summary", spec["parameters"]["properties"])
        self.assertIn("evidence_refs", spec["parameters"]["properties"])


class MiddlewareTests(HandoffTestBase):
    def test_request_then_drain_executes(self):
        item = self.team.plan[0]
        request = self.owner.request_handoff(
            team=self.team,
            plan_item_id=item.item_id,
            from_specialist=self.researcher,
            to_specialist=self.developer,
            reason="需要动手实现",
            progress_summary="选型已定",
        )
        self.assertEqual(
            self.owner.pending_handoff_requests(team_id="team-handoff"),
            [request],
        )
        result = self.owner.run_auto_handoff(team=self.team)
        self.assertEqual(len(result.executed), 1)
        self.assertEqual(
            result.executed[0]["triggered_by"], "auto:explicit_request"
        )
        self.assertEqual(
            result.executed[0]["context"]["progress_summary"], "选型已定"
        )
        self.assertEqual(
            self.owner.pending_handoff_requests(team_id="team-handoff"), []
        )
        effective = self.owner._effective_team(self.team)
        self.assertEqual(effective.plan[0].assignee, self.developer)

    def test_duplicate_request_deduped(self):
        item = self.team.plan[0]
        first = self.owner.request_handoff(
            team=self.team,
            plan_item_id=item.item_id,
            from_specialist=self.researcher,
            to_specialist=self.developer,
            reason="需要动手实现",
        )
        second = self.owner.request_handoff(
            team=self.team,
            plan_item_id=item.item_id,
            from_specialist=self.researcher,
            to_specialist=self.developer,
            reason="需要动手实现",
        )
        self.assertEqual(first["request_id"], second["request_id"])
        self.assertEqual(
            len(self.owner.pending_handoff_requests(team_id="team-handoff")), 1
        )

    def test_request_from_non_holder_rejected_and_audited(self):
        item = self.team.plan[0]
        self.owner.request_handoff(
            team=self.team,
            plan_item_id=item.item_id,
            from_specialist=self.developer,  # not the holder
            to_specialist=self.researcher,
            reason="我想接手",
        )
        result = self.owner.run_auto_handoff(team=self.team)
        self.assertEqual(result.executed, [])
        self.assertEqual(len(result.rejected), 1)
        self.assertEqual(result.rejected[0]["status"], "rejected")
        self.assertIn("held by", result.rejected[0]["reason"])
        # No override, but the rejection is in the audit log.
        effective = self.owner._effective_team(self.team)
        self.assertEqual(effective.plan[0].assignee, self.researcher)
        log = self.owner.handoff_log(team_id="team-handoff")
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["status"], "rejected")

    def test_capability_mismatch_auto_handoff(self):
        team = _custom_team()
        result = self.owner.run_auto_handoff(team=team)
        self.assertEqual(len(result.executed), 1)
        record = result.executed[0]
        self.assertEqual(record["triggered_by"], "auto:capability_mismatch")
        self.assertEqual(record["from_specialist"], "doc-writer")
        self.assertEqual(record["to_specialist"], "deployer")
        self.assertIn("capability mismatch", record["reason"])
        effective = self.owner._effective_team(team)
        self.assertEqual(effective.plan[0].assignee, "deployer")
        log = self.owner.handoff_log(team_id="team-handoff-custom")
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["triggered_by"], "auto:capability_mismatch")

    def test_capability_ambiguous_does_not_fire(self):
        team = ProjectTeam(
            team_id="team-handoff-ambiguous",
            project_title="部署项目",
            members=(
                _member("doc-writer", "writer", "文档", ("写文档",)),
                _member("deployer-a", "deployer", "部署", ("部署服务到生产",)),
                _member("deployer-b", "deployer", "部署", ("部署服务到生产",)),
            ),
            plan=(
                TeamPlanItem(
                    item_id="item-1",
                    title="部署服务",
                    objective="部署服务到生产环境",
                    acceptance_criteria=("服务可访问",),
                    assignee="doc-writer",
                ),
            ),
            work_thread_id=self.thread_id,
        )
        result = self.owner.run_auto_handoff(team=team)
        self.assertEqual(result.executed, [])
        self.assertTrue(
            any(
                "2 full-cover candidates" in entry.get("reason", "")
                for entry in result.skipped
            )
        )
        self.assertEqual(
            self.owner._effective_team(team).plan[0].assignee, "doc-writer"
        )

    def test_capability_partial_coverage_does_not_fire(self):
        team = ProjectTeam(
            team_id="team-handoff-partial",
            project_title="实现并部署",
            members=(
                _member("coder", self.developer, "开发", ("实现功能",)),
                _member(
                    "coder-deployer",
                    self.developer,
                    "开发",
                    ("实现功能并部署服务",),
                ),
            ),
            plan=(
                TeamPlanItem(
                    item_id="item-1",
                    title="实现并部署",
                    objective="实现功能并部署服务",
                    acceptance_criteria=("服务可访问",),
                    assignee="coder",
                ),
            ),
            work_thread_id=self.thread_id,
        )
        result = self.owner.run_auto_handoff(team=team)
        self.assertEqual(result.executed, [])
        self.assertTrue(
            any(
                "partial capability coverage" in entry.get("reason", "")
                for entry in result.skipped
            )
        )
        self.assertEqual(
            self.owner._effective_team(team).plan[0].assignee, "coder"
        )

    def test_capability_ping_pong_guard(self):
        team = _custom_team()
        # Seed: deployer just handed this item away to doc-writer.
        self.owner._append_handoff_log(
            team_id="team-handoff-custom",
            record={
                "handoff_id": "handoff-seed",
                "plan_item_id": "item-1",
                "item_title": "部署服务",
                "from_specialist": "deployer",
                "to_specialist": "doc-writer",
                "reason": "seed",
                "triggered_by": "tool",
                "status": "executed",
                "created_at": "2026-01-01T00:00:00+00:00",
                "context": {},
            },
        )
        result = self.owner.run_auto_handoff(team=team)
        self.assertEqual(result.executed, [])
        self.assertTrue(
            any(
                "ping-pong guard" in entry.get("reason", "")
                for entry in result.skipped
            )
        )
        self.assertEqual(
            self.owner._effective_team(team).plan[0].assignee, "doc-writer"
        )


class AdvanceIntegrationTests(HandoffTestBase):
    def _event(self):
        return SimpleNamespace(
            event_id="evt-handoff",
            payload={
                "work_thread_id": self.thread_id,
                "work_item_id": "root-handoff",
                "workspace_path": str(self.root / "ws"),
                "team_request": {
                    "project_title": "XX 项目",
                    "role_keys": ["researcher", "developer"],
                },
            },
        )

    def _state(self):
        return SimpleNamespace(data={})

    def test_advance_without_requests_does_not_reroute(self):
        self.ledger._save_item(
            WorkItem(
                work_item_id="root-handoff",
                work_thread_id=self.thread_id,
                title="XX 项目",
                objective="给 XX 项目组个团队",
                status="running",
                plan_version=1,
            )
        )
        step = self.owner.advance(
            event=self._event(),
            state=self._state(),
            root_work_item_id="root-handoff",
        )
        self.assertEqual(step.handoffs, [])
        team = self.owner.resolve_team(
            event=self._event(),
            state=SimpleNamespace(data={}),
            thread_id=self.thread_id,
        )
        # Default plan keeps its assignees: no misfire on normal teams.
        self.assertEqual(
            [item.assignee for item in team.plan],
            [self.researcher, self.developer],
        )

    def test_advance_drains_request_and_reroutes_dispatch(self):
        self.ledger._save_item(
            WorkItem(
                work_item_id="root-handoff",
                work_thread_id=self.thread_id,
                title="XX 项目",
                objective="给 XX 项目组个团队",
                status="running",
                plan_version=1,
            )
        )
        state = self._state()
        first = self.owner.advance(
            event=self._event(),
            state=state,
            root_work_item_id="root-handoff",
        )
        self.assertEqual(first.handoffs, [])
        team = self.owner.resolve_team(
            event=self._event(), state=state, thread_id=self.thread_id
        )
        item = team.plan[0]
        self.owner.request_handoff(
            team=team,
            plan_item_id=item.item_id,
            from_specialist=item.assignee,
            to_specialist=self.developer,
            reason="需要动手实现",
            progress_summary="选型已定",
        )
        second = self.owner.advance(
            event=self._event(),
            state=state,
            root_work_item_id="root-handoff",
        )
        self.assertEqual(len(second.handoffs), 1)
        self.assertEqual(
            second.handoffs[0]["triggered_by"], "auto:explicit_request"
        )
        # The re-resolved team carries the new assignee this pulse.
        resolved = self.owner.resolve_team(
            event=self._event(), state=state, thread_id=self.thread_id
        )
        self.assertEqual(resolved.plan[0].assignee, self.developer)

    def test_owner_reassign_path_still_works(self):
        self.ledger._save_item(
            WorkItem(
                work_item_id="root-handoff",
                work_thread_id=self.thread_id,
                title="XX 项目",
                objective="给 XX 项目组个团队",
                status="running",
                plan_version=1,
            )
        )
        state = self._state()
        self.owner.advance(
            event=self._event(),
            state=state,
            root_work_item_id="root-handoff",
        )
        team = self.owner.resolve_team(
            event=self._event(), state=state, thread_id=self.thread_id
        )
        item = team.plan[1]
        self.assertEqual(item.assignee, self.developer)
        # Owner @-reassign (the pre-AF-4 path) is untouched by handoff.
        record_assignee_override(
            self.memory, team.team_id, item.item_id, self.researcher
        )
        resolved = self.owner.resolve_team(
            event=self._event(), state=state, thread_id=self.thread_id
        )
        self.assertEqual(resolved.plan[1].assignee, self.researcher)
        # ... and a handoff on top of it still works (holder = researcher).
        record = self.owner.execute_handoff(
            team=resolved,
            plan_item_id=item.item_id,
            from_specialist=self.researcher,
            to_specialist=self.developer,
            reason="改回开发",
        )
        self.assertEqual(record["status"], "executed")


if __name__ == "__main__":
    unittest.main()
