from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.project_team import Specialist, assemble_team
from zn_agent.core.specialist_workspace import (
    append_memory,
    build_specialist_prompt,
    load_specialist_workspace,
    materialize_specialist_workspace,
    materialize_team_workspaces,
    specialist_prompt_for,
    validate_specialist_id,
    workspace_dir,
)
from zn_agent.core.team_coordinator import TeamCoordinator


def make_specialist(name="调研-01"):
    return Specialist(
        name=name,
        role_key="researcher",
        role_title="调研",
        responsibilities=("调研技术选型", "输出结论"),
        memory_namespace=f"team:t1:{name}",
        prompt_fragment="你是团队的调研专员：只给结论和依据。",
    )


class MaterializeTests(unittest.TestCase):
    def test_materialize_creates_layout_and_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = materialize_specialist_workspace(tmp, make_specialist())
            self.assertTrue(path.is_dir())
            for name in ("SOUL.md", "IDENTITY.md", "MEMORY.md", "agent.json"):
                self.assertTrue((path / name).is_file(), name)
            self.assertTrue((path / "skills").is_dir())
            soul = (path / "SOUL.md").read_text(encoding="utf-8")
            self.assertIn("只给结论和依据", soul)
            identity = (path / "IDENTITY.md").read_text(encoding="utf-8")
            self.assertIn("调研-01", identity)
            self.assertIn("researcher", identity)
            config = json.loads((path / "agent.json").read_text(encoding="utf-8"))
            self.assertEqual(config["role_key"], "researcher")
            self.assertEqual(config["responsibilities"], ["调研技术选型", "输出结论"])

    def test_materialize_never_overwrites_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = materialize_specialist_workspace(tmp, make_specialist())
            (path / "SOUL.md").write_text("手写的人格", encoding="utf-8")
            materialize_specialist_workspace(tmp, make_specialist())
            self.assertEqual(
                (path / "SOUL.md").read_text(encoding="utf-8"), "手写的人格"
            )

    def test_materialize_team_workspaces(self):
        team = assemble_team("X", ["developer", "tester"], team_id="t1")
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_team_workspaces(tmp, team)
            self.assertEqual(len(paths), 2)
            for path in paths:
                self.assertTrue((path / "SOUL.md").is_file())

    def test_validate_specialist_id_rejects_traversal(self):
        for bad in ("", ".", "..", "../evil", "a/b", "a\\b", "C:evil"):
            with self.assertRaises(ValueError, msg=bad):
                validate_specialist_id(bad)
        self.assertEqual(validate_specialist_id("调研-01"), "调研-01")


class LoadAndPromptTests(unittest.TestCase):
    def test_load_round_trip_and_prompt_rendering(self):
        with tempfile.TemporaryDirectory() as tmp:
            materialize_specialist_workspace(tmp, make_specialist())
            (Path(tmp) / "调研-01" / "skills" / "probe.md").write_text(
                "skill", encoding="utf-8"
            )
            workspace = load_specialist_workspace(tmp, "调研-01")
            prompt = build_specialist_prompt(workspace)
            self.assertIn("只给结论和依据", prompt)
            self.assertIn("调研-01", prompt)
            self.assertIn("researcher", prompt)
            self.assertEqual(workspace.skill_files, ("probe.md",))

    def test_edit_soul_takes_effect_next_build(self):
        # No cached persona: re-reading the files picks up the edit.
        with tempfile.TemporaryDirectory() as tmp:
            materialize_specialist_workspace(tmp, make_specialist())
            first = build_specialist_prompt(load_specialist_workspace(tmp, "调研-01"))
            self.assertIn("只给结论和依据", first)
            (Path(tmp) / "调研-01" / "SOUL.md").write_text(
                "新版人格：只说英文。", encoding="utf-8"
            )
            second = build_specialist_prompt(
                load_specialist_workspace(tmp, "调研-01")
            )
            self.assertIn("只说英文", second)
            self.assertNotIn("只给结论和依据", second)

    def test_append_memory_persists_to_disk_and_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            materialize_specialist_workspace(tmp, make_specialist())
            memory_path = append_memory(tmp, "调研-01", "项目用 Python 3.12")
            self.assertTrue(memory_path.is_file())
            self.assertIn("Python 3.12", memory_path.read_text(encoding="utf-8"))
            prompt = build_specialist_prompt(
                load_specialist_workspace(tmp, "调研-01")
            )
            self.assertIn("Python 3.12", prompt)

    def test_append_memory_rejects_empty_and_missing_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            materialize_specialist_workspace(tmp, make_specialist())
            with self.assertRaises(ValueError):
                append_memory(tmp, "调研-01", "   ")
            with self.assertRaises(FileNotFoundError):
                append_memory(tmp, "不存在-99", "x")

    def test_load_missing_dir_and_malformed_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                load_specialist_workspace(tmp, "调研-01")
            materialize_specialist_workspace(tmp, make_specialist())
            (Path(tmp) / "调研-01" / "agent.json").write_text(
                "{not json", encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                load_specialist_workspace(tmp, "调研-01")

    def test_missing_optional_files_load_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = workspace_dir(tmp, "调研-01")
            path.mkdir(parents=True)
            (path / "SOUL.md").write_text("只有人格", encoding="utf-8")
            workspace = load_specialist_workspace(tmp, "调研-01")
            self.assertEqual(workspace.identity, "")
            self.assertEqual(workspace.memory_text, "")
            self.assertEqual(workspace.config, {})
            self.assertIn("只有人格", build_specialist_prompt(workspace))


class SpecialistPromptForTests(unittest.TestCase):
    def test_no_workspace_root_falls_back_to_fragment(self):
        team = assemble_team("X", ["developer"], team_id="t1")
        specialist = team.members[0]
        self.assertEqual(
            specialist_prompt_for(team, specialist), specialist.prompt_fragment
        )

    def test_workspace_prompt_used_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            team = assemble_team(
                "X", ["developer"], team_id="t1", workspace_root=tmp
            )
            materialize_team_workspaces(tmp, team)
            specialist = team.members[0]
            prompt = specialist_prompt_for(team, specialist)
            self.assertIn("按设计实现", prompt)
            self.assertNotEqual(prompt, specialist.prompt_fragment)

    def test_missing_workspace_dir_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            team = assemble_team(
                "X", ["developer"], team_id="t1", workspace_root=tmp
            )
            specialist = team.members[0]
            self.assertEqual(
                specialist_prompt_for(team, specialist),
                specialist.prompt_fragment,
            )

    def test_malformed_config_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            team = assemble_team(
                "X", ["developer"], team_id="t1", workspace_root=tmp
            )
            materialize_team_workspaces(tmp, team)
            member = team.members[0]
            (Path(tmp) / member.name / "agent.json").write_text(
                "{broken", encoding="utf-8"
            )
            self.assertEqual(
                specialist_prompt_for(team, member), member.prompt_fragment
            )


class CoordinatorDispatchTests(unittest.TestCase):
    def test_dispatch_context_uses_file_prompt(self):
        # Reuses the coordinator's FakeLedger-free path: _dispatch builds
        # the context a specialist run receives.
        from zn_agent.core.steerable_work import WorkItem

        with tempfile.TemporaryDirectory() as tmp:
            team = assemble_team(
                "X", ["developer"], team_id="t1", workspace_root=tmp
            )
            materialize_team_workspaces(tmp, team)
            member = team.members[0]
            (Path(tmp) / member.name / "SOUL.md").write_text(
                "文件人格：先写测试再写实现。", encoding="utf-8"
            )
            coordinator = TeamCoordinator(team=team, root_work_item_id="root-1")
            item = WorkItem(
                work_item_id=team.plan[0].item_id,
                work_thread_id="thread-1",
                title=team.plan[0].title,
                objective="obj",
                status="proposed",
                plan_version=1,
                parent_work_item_id="root-1",
            )
            decision = coordinator._dispatch(item, team.plan[0])
            self.assertEqual(decision.action, "dispatch")
            self.assertIn("先写测试再写实现", decision.context["specialist_prompt"])


if __name__ == "__main__":
    unittest.main()
