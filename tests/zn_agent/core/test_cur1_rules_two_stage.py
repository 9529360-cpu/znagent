from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.models import AgentEvent, CognitionRequest
from zn_agent.core.skills import (
    MAX_RESIDENT_SUMMARY_CHARS,
    SkillStore,
    make_resident_entry,
    rule_applies_to_path,
    validate_resident_entry,
)
from zn_agent.core.specialist_workspace import (
    SpecialistWorkspace,
    build_specialist_prompt,
    build_specialist_resident_summary,
    load_specialist_workspace,
    materialize_specialist_workspace,
    specialist_prompt_for,
    validate_resident_summary,
)
from zn_agent.core.specialist_workspace import (
    rule_applies_to_path as specialist_rule_applies,
)


def _write_skill(
    root: Path,
    name: str,
    *,
    description: str = "",
    body: str = "Body.",
    version: str = "1.0.0",
    extra_frontmatter: str = "",
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    front = (
        f"---\nname: {name}\ndescription: {description}\nversion: {version}\n"
        f"allowed-tools: []\n{extra_frontmatter}---\n\n"
    )
    path = directory / "skill.md"
    path.write_text(front + body, encoding="utf-8")
    return path


def _bind(store: SkillStore, task: str, *, include_bodies: bool = False, **payload):
    event = AgentEvent("event", task, payload=payload)
    request = CognitionRequest("request", "impasse", event.event_id, task)
    bound = store.bind_cognition_context(event, request, include_bodies=include_bodies)
    return bound.context.get("resident_skills")


class ResidentBindingTests(unittest.TestCase):
    """Default binding is two-stage: summaries only, never bodies."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = SkillStore(self.root)
        _write_skill(
            self.root,
            "task-management",
            description="Use when managing tasks in a shared TASKS.md file.",
            body="Read TASKS.md first. Then update the board. " + "Detail. " * 200,
        )
        _write_skill(
            self.root,
            "deep-research",
            description="Use when doing multi-source web research.",
            body="Search at least three sources.",
        )

    def test_default_binding_has_summary_no_body(self):
        bundle = _bind(self.store, "help me with managing tasks")
        self.assertIsNotNone(bundle)
        self.assertEqual(bundle["stage"], "resident-summary")
        self.assertEqual(len(bundle["skills"]), 1)
        entry = bundle["skills"][0]
        self.assertEqual(entry["name"], "task-management")
        self.assertNotIn("body", entry)
        self.assertIn("TASKS.md", entry["summary"])
        self.assertIn("when managing tasks", entry["trigger"])
        self.assertLessEqual(len(entry["summary"]), MAX_RESIDENT_SUMMARY_CHARS)
        self.assertLessEqual(len(entry["trigger"]), MAX_RESIDENT_SUMMARY_CHARS)
        self.assertIn("activate_skill", bundle["activation"])

    def test_unmatched_skill_body_never_bound(self):
        bundle = _bind(self.store, "help me with managing tasks")
        names = [entry["name"] for entry in bundle["skills"]]
        self.assertNotIn("deep-research", names)
        self.assertNotIn("three sources", json.dumps(bundle))

    def test_no_match_binds_nothing(self):
        self.assertIsNone(_bind(self.store, "what is the weather today"))

    def test_activation_loads_full_body_on_demand(self):
        _bind(self.store, "help me with managing tasks")
        activated = self.store.activate_skill("task-management")
        self.assertIsNotNone(activated)
        self.assertIn("Detail.", activated.body)
        self.assertGreater(len(activated.body), MAX_RESIDENT_SUMMARY_CHARS)

    def test_activation_unknown_skill_returns_none(self):
        self.assertIsNone(self.store.activate_skill("no-such-skill"))

    def test_resident_payload_smaller_than_legacy_full_body(self):
        resident = _bind(self.store, "help me with managing tasks")
        legacy = _bind(
            self.store, "help me with managing tasks", include_bodies=True
        )
        self.assertEqual(legacy["stage"], "full-body (legacy opt-in)")
        self.assertIn("TASKS.md", legacy["skills"][0]["body"])
        resident_bytes = len(json.dumps(resident, ensure_ascii=False))
        legacy_bytes = len(json.dumps(legacy, ensure_ascii=False))
        self.assertLess(resident_bytes, legacy_bytes)

    def test_legacy_opt_in_still_injects_body(self):
        bundle = _bind(
            self.store, "help me with managing tasks", include_bodies=True
        )
        self.assertIn("Read TASKS.md first.", bundle["skills"][0]["body"])


class ResidentEntryCapTests(unittest.TestCase):
    def test_long_description_truncates_with_flag(self):
        entry = make_resident_entry(
            "long", "Use when testing. " + "Word " * 200, "1.0.0"
        )
        self.assertTrue(entry["truncated"])
        self.assertLessEqual(len(entry["summary"]), MAX_RESIDENT_SUMMARY_CHARS)
        self.assertLessEqual(len(entry["trigger"]), MAX_RESIDENT_SUMMARY_CHARS)
        self.assertEqual(entry["summary"], "Use when testing")
        self.assertTrue(entry["trigger"].endswith("…"))
        validate_resident_entry(entry)

    def test_short_description_not_truncated(self):
        entry = make_resident_entry("s", "Use when testing short rules.", "1.0.0")
        self.assertFalse(entry["truncated"])
        self.assertEqual(entry["summary"], "Use when testing short rules")
        self.assertEqual(entry["trigger"], "Use when testing short rules.")

    def test_validator_rejects_over_cap(self):
        entry = make_resident_entry("s", "Use when testing.", "1.0.0")
        entry["summary"] = "x" * (MAX_RESIDENT_SUMMARY_CHARS + 1)
        with self.assertRaises(ValueError):
            validate_resident_entry(entry)
        entry["summary"] = "ok"
        entry["trigger"] = "x" * (MAX_RESIDENT_SUMMARY_CHARS + 1)
        with self.assertRaises(ValueError):
            validate_resident_entry(entry)


class GlobsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = SkillStore(self.root)
        _write_skill(
            self.root,
            "py-linter",
            description="Use when linting Python files.",
            body="Run ruff on the file.",
            extra_frontmatter="globs: ['*.py']\n",
        )
        _write_skill(
            self.root,
            "general-notes",
            description="Use when writing general notes.",
            body="Write clearly.",
        )

    def test_rule_applies_to_path(self):
        self.assertTrue(rule_applies_to_path((), "anything.md"))
        self.assertTrue(rule_applies_to_path(["*.py"], "src/main.py"))
        self.assertFalse(rule_applies_to_path(["*.py"], "src/main.md"))
        self.assertTrue(rule_applies_to_path(["src/**/*.py"], "src/a/b.py"))
        self.assertFalse(rule_applies_to_path(["src/**/*.py"], "other/a.py"))

    def test_globs_filter_before_activation(self):
        matched = self.store.relevant_skills("linting Python files", file_path="x.py")
        self.assertEqual([skill.name for skill in matched], ["py-linter"])
        matched = self.store.relevant_skills("linting Python files", file_path="x.md")
        self.assertEqual(matched, [])

    def test_skill_without_globs_applies_everywhere(self):
        matched = self.store.relevant_skills("writing general notes", file_path="x.md")
        self.assertEqual([skill.name for skill in matched], ["general-notes"])

    def test_bind_uses_payload_file_path(self):
        bundle = _bind(
            self.store, "linting Python files", file_path="notes.md"
        )
        self.assertIsNone(bundle)
        bundle = _bind(self.store, "linting Python files", file_path="main.py")
        self.assertIsNotNone(bundle)
        self.assertEqual(bundle["skills"][0]["globs"], ["*.py"])

    def test_invalid_globs_ignored(self):
        _write_skill(
            self.root,
            "bad-globs",
            description="Use when testing bad globs handling.",
            body="Body.",
            extra_frontmatter="globs: ['../escape', '/abs/path', '']\n",
        )
        skill = self.store.activate_skill("bad-globs")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.globs, ())

    def test_globs_scoped_by_file_type(self):
        _write_skill(
            self.root,
            "md-style",
            description="Use when styling Markdown documents.",
            body="Use headings.",
            extra_frontmatter="globs: ['*.md']\n",
        )
        matched = self.store.relevant_skills(
            "styling Markdown documents", file_path="doc.md"
        )
        self.assertEqual([skill.name for skill in matched], ["md-style"])
        matched = self.store.relevant_skills(
            "styling Markdown documents", file_path="doc.py"
        )
        self.assertEqual(matched, [])


class SpecialistResidentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        specialist = type(
            "Spec",
            (),
            {
                "name": "researcher-01",
                "role_key": "researcher",
                "role_title": "Researcher",
                "responsibilities": ["gather evidence"],
                "prompt_fragment": "built-in persona",
                "memory_namespace": "researcher",
            },
        )()
        self.specialist = specialist
        materialize_specialist_workspace(self.tmp, specialist)
        soul_path = self.tmp / "researcher-01" / "SOUL.md"
        soul_path.write_text(
            "# SOUL\n\n"
            "You gather evidence from primary sources and "
            + "very long detail " * 100
            + ". Second sentence.\n",
            encoding="utf-8",
        )
        config_path = self.tmp / "researcher-01" / "agent.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["trigger"] = "Use when research is needed."
        config["globs"] = ["*.md", "*.py"]
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.workspace = load_specialist_workspace(self.tmp, "researcher-01")
        self.team = type("Team", (), {"workspace_root": str(self.tmp)})()

    def test_resident_summary_capped_no_full_text(self):
        summary = build_specialist_resident_summary(self.workspace)
        self.assertEqual(summary["specialist_id"], "researcher-01")
        self.assertLessEqual(len(summary["summary"]), MAX_RESIDENT_SUMMARY_CHARS)
        self.assertEqual(summary["trigger"], "Use when research is needed.")
        self.assertEqual(summary["globs"], ["*.md", "*.py"])
        self.assertTrue(summary["truncated"])
        self.assertNotIn("Second sentence", json.dumps(summary))
        self.assertLess(len(json.dumps(summary)), 1200)
        validate_resident_summary(summary)

    def test_resident_stage_prompt_is_short_form(self):
        prompt = specialist_prompt_for(
            self.team, self.specialist, stage="resident"
        )
        self.assertIn("Summary:", prompt)
        self.assertIn("Trigger: Use when research is needed.", prompt)
        self.assertIn("Globs: *.md, *.py", prompt)
        self.assertIn("Activation:", prompt)
        self.assertNotIn("Second sentence", prompt)

    def test_full_stage_unchanged(self):
        prompt = specialist_prompt_for(self.team, self.specialist, stage="full")
        self.assertEqual(prompt, build_specialist_prompt(self.workspace))
        self.assertIn("very long detail", prompt)

    def test_invalid_stage_rejected(self):
        with self.assertRaises(ValueError):
            specialist_prompt_for(self.team, self.specialist, stage="bogus")

    def test_validator_rejects_over_cap(self):
        summary = build_specialist_resident_summary(self.workspace)
        summary["trigger"] = "x" * (MAX_RESIDENT_SUMMARY_CHARS + 1)
        with self.assertRaises(ValueError):
            validate_resident_summary(summary)

    def test_specialist_globs_matching(self):
        self.assertTrue(specialist_rule_applies(["*.md"], "notes.md"))
        self.assertFalse(specialist_rule_applies(["*.md"], "notes.py"))
        self.assertTrue(specialist_rule_applies((), "anything.txt"))

    def test_trigger_falls_back_to_role_when_unset(self):
        config_path = self.tmp / "researcher-01" / "agent.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config.pop("trigger", None)
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        workspace = load_specialist_workspace(self.tmp, "researcher-01")
        summary = build_specialist_resident_summary(workspace)
        self.assertIn("Researcher", summary["trigger"])
        self.assertIn("gather evidence", summary["trigger"])


if __name__ == "__main__":
    unittest.main()
