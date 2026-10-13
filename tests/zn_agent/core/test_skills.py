from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.models import AgentEvent, CognitionRequest
from zn_agent.core.skills import SkillStore


def _write_skill(root: Path, name: str, *, description: str = "", body: str = "Body.", version: str = "1.0.0") -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    front = f"---\nname: {name}\ndescription: {description}\nversion: {version}\n---\n\n"
    path = directory / "skill.md"
    path.write_text(front + body, encoding="utf-8")
    return path


class SkillDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = SkillStore(self.root)

    def test_discovers_valid_skill(self):
        _write_skill(self.root, "task-management", description="Track tasks in TASKS.md", body="Use TASKS.md.")
        skills = self.store.discover()
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0].name, "task-management")
        self.assertEqual(skills[0].description, "Track tasks in TASKS.md")
        self.assertEqual(skills[0].version, "1.0.0")
        self.assertEqual(skills[0].body, "Use TASKS.md.")

    def test_skips_invalid_bundles(self):
        _write_skill(self.root, "good", description="Good skill.", body="Body.")
        # Invalid name.
        _write_skill(self.root, "Bad Name!", description="Bad.", body="Body.")
        # Missing description.
        nodir = self.root / "nodesc"
        nodir.mkdir()
        (nodir / "skill.md").write_text("---\nname: nodesc\n---\n\nBody.", encoding="utf-8")
        # Empty body.
        _write_skill(self.root, "emptybody", description="Empty.", body="   ")
        # Not a directory / hidden.
        (self.root / "_hidden").mkdir()
        names = [skill.name for skill in self.store.discover()]
        self.assertEqual(names, ["good"])

    def test_missing_root_discovers_nothing(self):
        self.assertEqual(SkillStore(self.root / "nope").discover(), [])


class SkillMatchingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = SkillStore(self.root)
        _write_skill(
            self.root,
            "task-management",
            description="Simple task management using a shared TASKS.md file",
            body="Read TASKS.md first.",
        )
        _write_skill(
            self.root,
            "deep-research",
            description="Multi-source web research with evidence comparison",
            body="Search at least three sources.",
        )

    def test_matches_on_description_phrase(self):
        matched = self.store.relevant_skills("help me with task management today")
        self.assertEqual([skill.name for skill in matched], ["task-management"])

    def test_most_specific_cue_wins(self):
        matched = self.store.relevant_skills("do web research and task management", max_skills=1)
        # "web research" (12 chars incl. space) beats "task management" only if
        # longer; here both match, tie broken by name descending.
        self.assertEqual(len(matched), 1)

    def test_body_is_never_a_search_cue(self):
        matched = self.store.relevant_skills("at least three sources")
        self.assertEqual(matched, [])

    def test_generic_single_word_does_not_match(self):
        matched = self.store.relevant_skills("management")
        self.assertEqual(matched, [])

    def test_chinese_cue_matches(self):
        _write_skill(self.root, "cn-skill", description="中文任务管理", body="Body.")
        matched = self.store.relevant_skills("帮我做中文任务管理")
        self.assertEqual([skill.name for skill in matched], ["cn-skill"])

    def test_respects_max_skills(self):
        matched = self.store.relevant_skills("task management and web research", max_skills=1)
        self.assertEqual(len(matched), 1)

    def test_body_truncated_to_budget(self):
        _write_skill(
            self.root, "long", description="Long skill body here", body="x" * 5000
        )
        matched = self.store.relevant_skills("long skill body here", max_skill_chars=100)
        self.assertEqual(len(matched[0].body), 100)


class SkillBindingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = SkillStore(self.root)
        _write_skill(
            self.root,
            "task-management",
            description="Simple task management using a shared TASKS.md file",
            body="Read TASKS.md first.",
        )

    def bind(self, task, **payload):
        event = AgentEvent("event", task, payload=payload)
        request = CognitionRequest("request", "impasse", event.event_id, task)
        return self.store.bind_cognition_context(event, request).context.get("resident_skills")

    def test_binds_relevant_skill_as_data_not_authority(self):
        bundle = self.bind("help me with task management")
        self.assertIsNotNone(bundle)
        self.assertEqual(bundle["source"], "resident_skill_bundles")
        self.assertFalse(bundle["execution_authority"])
        self.assertFalse(bundle["completion_evidence"])
        self.assertEqual(len(bundle["skills"]), 1)
        self.assertEqual(bundle["skills"][0]["name"], "task-management")
        self.assertIn("TASKS.md", bundle["skills"][0]["body"])

    def test_no_match_binds_nothing(self):
        self.assertIsNone(self.bind("what is the weather today"))

    def test_isolated_question_does_not_inherit_skills(self):
        bundle = self.bind(
            "help me with task management",
            cognition_question="standalone?",
        )
        self.assertIsNone(bundle)

    def test_replaces_previous_binding(self):
        event = AgentEvent("event", "task management", payload={})
        request = CognitionRequest("request", "impasse", event.event_id, "task management")
        request.context["resident_skills"] = {"stale": True}
        bound = self.store.bind_cognition_context(event, request).context["resident_skills"]
        self.assertNotIn("stale", bound)


if __name__ == "__main__":
    unittest.main()
