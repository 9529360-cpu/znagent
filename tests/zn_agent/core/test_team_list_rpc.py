from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.team_memory import delete_team_memory, team_shared_memory
from zn_agent.core.team_work_owner import TEAM_SPEC_KEY


class TeamListRpcTests(unittest.TestCase):
    """The read-only ``team_list`` RPC: inventory of active teams."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.resident = build_resident_runtime(
            config={"model": {}}, store_path=self.root / "kernel.db"
        )
        self.addCleanup(lambda: self.resident.store.close())
        self.rpc = ResidentRpcServer(self.resident)

    def call(self, method, **params):
        response = self.rpc.handle(
            {"id": method, "method": method, "params": params}
        )
        self.assertTrue(response["ok"], response.get("error"))
        return response["result"]

    def _create_team(
        self, team_id, project, roles=("researcher", "developer")
    ):
        team_shared_memory(self.resident.memory, team_id).remember(
            TEAM_SPEC_KEY,
            {"project_title": project, "role_keys": list(roles)},
        )
        return team_id

    def test_empty_lists_nothing(self):
        self.assertEqual(self.call("team_list"), [])

    def test_lists_team_id_objective_roster_and_status(self):
        self._create_team(
            "team-7f3a9c1e", project="公司官网改版", roles=("researcher", "developer")
        )
        listed = self.call("team_list")
        self.assertEqual(len(listed), 1)
        item = listed[0]
        self.assertEqual(
            set(item), {"team_id", "project_title", "roster", "status"}, item
        )
        self.assertEqual(item["team_id"], "team-7f3a9c1e")
        self.assertEqual(item["project_title"], "公司官网改版")
        self.assertEqual(item["status"], "active")
        self.assertEqual(item["roster"], ["调研-01", "开发-02"])

    def test_multiple_teams_are_all_listed(self):
        self._create_team("team-aa11bb22", project="仓库物流系统", roles=("architect",))
        self._create_team("team-cc33dd44", project="用户行为分析", roles=("tester",))
        listed = self.call("team_list")
        self.assertEqual(len(listed), 2)
        by_id = {item["team_id"]: item for item in listed}
        self.assertEqual(set(by_id), {"team-aa11bb22", "team-cc33dd44"})
        self.assertEqual(by_id["team-aa11bb22"]["roster"], ["架构-01"])

    def test_disbanded_team_disappears(self):
        # Disband deletes every fact under the team:{id}: prefix; the
        # listing must follow the same ground truth.
        self._create_team("team-doom99", project="要解散的试点项目")
        self.assertEqual(len(self.call("team_list")), 1)
        removed = delete_team_memory(self.resident.memory, "team-doom99")
        self.assertGreater(removed, 0)
        self.assertEqual(self.call("team_list"), [])

    def test_team_content_beyond_roster_never_leaks(self):
        self._create_team("team-secret77", project="机密数据项目")
        team_shared_memory(self.resident.memory, "team-secret77").remember(
            "plan-note", {"text": "super-secret-journal-content"}
        )
        listed = self.call("team_list")
        self.assertEqual(len(listed), 1)
        self.assertNotIn("super-secret-journal-content", str(listed))
        for item in listed:
            self.assertEqual(
                set(item), {"team_id", "project_title", "roster", "status"}
            )

    def test_limit_is_respected(self):
        # Project titles must be clearly dissimilar: StructuredMemory.remember
        # supersedes near-duplicate facts on purpose (not a team_list concern).
        teams = (
            ("team-l0a1b2", "限额测试：官网改版", ("researcher",)),
            ("team-l3c4d5", "限额测试：数据分析", ("tester",)),
            ("team-l6e7f8", "限额测试：移动应用", ("developer", "architect")),
            ("team-l9a0b1", "限额测试：客服机器人", ("researcher", "tester")),
            ("team-l2c3d4", "限额测试：支付系统", ("developer",)),
        )
        for team_id, project, roles in teams:
            self._create_team(team_id, project=project, roles=roles)
        listed = self.call("team_list", limit=2)
        self.assertEqual(len(listed), 2)

    def test_limit_is_capped(self):
        teams = (
            ("team-c0f1e2", "上限测试：物流调度", ("architect",)),
            ("team-c3a4b5", "上限测试：推荐引擎", ("researcher",)),
            ("team-c6d7e8", "上限测试：消息队列", ("developer",)),
        )
        for team_id, project, roles in teams:
            self._create_team(team_id, project=project, roles=roles)
        # The server-side cap is 200; an absurd limit must not error.
        listed = self.call("team_list", limit=10_000)
        self.assertEqual(len(listed), 3)
        self.assertEqual(ResidentRpcServer._limit({"limit": 10_000}), 200)

    def test_unknown_role_keys_fall_back_to_role_keys(self):
        # A spec assembled with custom roles (not in the built-in
        # registry) must not break the whole inventory.
        self._create_team(
            "team-custom5", project="定制咨询项目", roles=("futurologist",)
        )
        listed = self.call("team_list")
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["roster"], ["futurologist"])

    def test_malformed_spec_is_skipped(self):
        team_shared_memory(self.resident.memory, "team-broken6").remember(
            TEAM_SPEC_KEY, "not-a-spec-dict"
        )
        team_shared_memory(self.resident.memory, "team-empty7").remember(
            TEAM_SPEC_KEY, {"project_title": "", "role_keys": []}
        )
        self._create_team("team-good88", project="正常运营项目")
        listed = self.call("team_list")
        self.assertEqual([item["team_id"] for item in listed], ["team-good88"])


if __name__ == "__main__":
    unittest.main()
