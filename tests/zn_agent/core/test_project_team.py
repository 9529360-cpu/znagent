from __future__ import annotations

import unittest

from zn_agent.core.project_team import (
    ROLE_TEMPLATES,
    ProjectTeam,
    assemble_team,
    journal_message,
    team_journal_role_prefix,
    team_memory_key,
    team_memory_prefix,
)


class AssembleTeamTests(unittest.TestCase):
    def test_assembles_full_dev_team(self):
        team = assemble_team(
            "官网重构", ["researcher", "architect", "developer", "tester"],
            team_id="team-demo",
        )
        self.assertIsInstance(team, ProjectTeam)
        self.assertEqual(team.team_id, "team-demo")
        self.assertEqual(len(team.members), 4)
        self.assertEqual(
            [m.role_key for m in team.members],
            ["researcher", "architect", "developer", "tester"],
        )

    def test_member_names_unique_and_durable(self):
        team = assemble_team("X", ["developer", "tester"], team_id="t1")
        names = [m.name for m in team.members]
        self.assertEqual(len(set(names)), 2)
        for member in team.members:
            self.assertEqual(
                member.memory_namespace, f"team:t1:{member.name}"
            )

    def test_plan_dependency_chain(self):
        team = assemble_team(
            "X", ["researcher", "architect", "developer"], team_id="t2"
        )
        self.assertEqual(len(team.plan), 3)
        # Chain: each item depends on the previous one.
        self.assertEqual(team.plan[0].dependency_ids, ())
        self.assertEqual(team.plan[1].dependency_ids, (team.plan[0].item_id,))
        self.assertEqual(team.plan[2].dependency_ids, (team.plan[1].item_id,))
        # Assignees are the specialist names.
        for item, member in zip(team.plan, team.members):
            self.assertEqual(item.assignee, member.name)
            self.assertTrue(item.acceptance_criteria)

    def test_plan_item_maps_to_work_item_kwargs(self):
        team = assemble_team("X", ["developer"], team_id="t3")
        kwargs = team.plan[0].as_work_item_kwargs("thread-1", plan_version=1)
        self.assertEqual(kwargs["work_thread_id"], "thread-1")
        self.assertEqual(kwargs["status"], "proposed")
        self.assertEqual(kwargs["plan_version"], 1)
        self.assertIn("acceptance_criteria", kwargs)
        self.assertIn("dependency_ids", kwargs)

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            assemble_team("", ["developer"])
        with self.assertRaises(ValueError):
            assemble_team("X", [])
        with self.assertRaises(ValueError):
            assemble_team("X", ["developer", "developer"])
        with self.assertRaises(ValueError):
            assemble_team("X", ["ninja"])

    def test_role_templates_cover_dev_pipeline(self):
        self.assertEqual(
            set(ROLE_TEMPLATES), {"researcher", "architect", "developer", "tester"}
        )

    def test_custom_roles_are_not_hardcoded(self):
        from zn_agent.core.project_team import SpecialistRole

        designer = SpecialistRole(
            key="designer",
            title="设计",
            responsibilities=("出视觉稿",),
            default_objective="输出视觉设计稿",
            default_acceptance=("设计稿通过评审",),
            prompt_fragment="你是设计专员。",
        )
        team = assemble_team(
            "品牌站", ["designer", "developer"],
            team_id="t-custom",
            roles={"designer": designer},
        )
        self.assertEqual(
            [m.role_key for m in team.members], ["designer", "developer"]
        )
        self.assertEqual(team.members[0].name, "设计-01")
        self.assertEqual(team.plan[0].objective, "输出视觉设计稿")

    def test_unknown_role_still_rejected(self):
        with self.assertRaises(ValueError):
            assemble_team("X", ["ninja"])

    def test_mismatched_role_entry_rejected(self):
        from zn_agent.core.project_team import SpecialistRole

        bad = SpecialistRole(
            key="other", title="x", responsibilities=(),
            default_objective="x", default_acceptance=(),
            prompt_fragment="x",
        )
        with self.assertRaises(ValueError):
            assemble_team("X", ["designer"], roles={"designer": bad})


class JournalTests(unittest.TestCase):
    def test_message_format(self):
        msg = journal_message("t1", "开发-01", "联调通过", kind="progress")
        self.assertEqual(msg["role"], "team:t1:开发-01")
        self.assertEqual(msg["text"], "联调通过")
        self.assertEqual(msg["detail"]["kind"], "progress")

    def test_rejects_unknown_kind_and_empty_text(self):
        with self.assertRaises(ValueError):
            journal_message("t1", "a", "x", kind="gossip")
        with self.assertRaises(ValueError):
            journal_message("t1", "a", "   ")


class MemoryKeyTests(unittest.TestCase):
    def test_namespaced_and_isolated(self):
        k1 = team_memory_key("t1", "开发-01", "api 地址")
        k2 = team_memory_key("t1", "测试-01", "api 地址")
        self.assertNotEqual(k1, k2)
        self.assertTrue(k1.startswith("team:t1:开发-01:"))

    def test_prefixes_cover_everything(self):
        self.assertEqual(team_memory_prefix("t1"), "team:t1:")
        self.assertTrue(
            team_memory_key("t1", "开发-01", "x").startswith(team_memory_prefix("t1"))
        )
        msg = journal_message("t1", "开发-01", "ok")
        self.assertTrue(msg["role"].startswith(team_journal_role_prefix("t1")))


class DisbandTests(unittest.TestCase):
    def test_disband_plan_covers_everything(self):
        team = assemble_team(
            "X", ["researcher", "developer"], team_id="t9", work_thread_id="thread-9"
        )
        plan = team.disband_plan()
        self.assertEqual(plan.team_id, "t9")
        self.assertEqual(plan.work_thread_id, "thread-9")
        self.assertEqual(plan.memory_key_prefix, "team:t9:")
        self.assertEqual(plan.journal_role_prefix, "team:t9:")
        self.assertEqual(
            plan.plan_item_ids, tuple(item.item_id for item in team.plan)
        )
        # Every member memory key and journal message falls in scope.
        for member in team.members:
            self.assertTrue(
                team_memory_key("t9", member.name, "k").startswith(
                    plan.memory_key_prefix
                )
            )
        self.assertIn("删除团队 t9", plan.describe())


if __name__ == "__main__":
    unittest.main()
