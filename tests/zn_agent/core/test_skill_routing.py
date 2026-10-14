from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.models import AgentEvent, CognitionRequest
from zn_agent.core.skill_routing import (
    SkillRouter,
    approx_tokens,
    has_trigger_condition,
    validate_skill_file,
)
from zn_agent.core.skills import SkillStore


def _write_skill(
    root: Path,
    name: str,
    *,
    description: str = "Use when you need this skill.",
    body: str = "Body.",
    filename: str = "SKILL.md",
    extra_frontmatter: str = "",
    raw: bytes | None = None,
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    if raw is not None:
        path.write_bytes(raw)
        return path
    front = (
        f"---\nname: {name}\ndescription: {description}\nversion: 1.0.0\n"
        f"allowed-tools: []\n{extra_frontmatter}---\n\n"
    )
    path.write_text(front + body, encoding="utf-8")
    return path


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.router = SkillRouter(self.root)

    def test_discovery_returns_headers_without_body(self):
        _write_skill(self.root, "task-management", body="Secret body text.")
        headers = self.router.discover()
        self.assertEqual(len(headers), 1)
        self.assertEqual(headers[0].name, "task-management")
        self.assertFalse(hasattr(headers[0], "body"))

    def test_discovery_never_reads_body(self):
        # Body is invalid UTF-8: discovery must still succeed because it
        # stops reading at the closing frontmatter fence.
        front = (
            b"---\nname: broken-body\ndescription: Use when testing.\n"
            b"version: 1.0.0\nallowed-tools: []\n---\n\n"
        )
        _write_skill(self.root, "broken-body", raw=front + b"\xff\xfe invalid \x80 body")
        headers = self.router.discover()
        self.assertEqual([header.name for header in headers], ["broken-body"])
        # ... while activation of that skill honestly fails instead of
        # surfacing garbage.
        self.assertIsNone(self.router.activate("broken-body"))

    def test_discovery_prefers_spec_filename_and_falls_back(self):
        _write_skill(self.root, "spec-name", filename="SKILL.md")
        _write_skill(self.root, "legacy-name", filename="skill.md")
        names = [header.name for header in self.router.discover()]
        self.assertEqual(names, ["legacy-name", "spec-name"])

    def test_discovery_skips_invalid_headers(self):
        _write_skill(self.root, "good")
        _write_skill(self.root, "Bad Name!", description="Use when bad.")
        self.assertEqual([h.name for h in self.router.discover()], ["good"])

    def test_discovery_missing_root_is_empty(self):
        self.assertEqual(SkillRouter(self.root / "nope").discover(), [])


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.router = SkillRouter(self.root)
        _write_skill(
            self.root,
            "task-management",
            description="Use when managing tasks in a shared TASKS.md file.",
            body="Read TASKS.md first.",
        )
        _write_skill(
            self.root,
            "deep-research",
            description="Use when doing multi-source web research.",
            body="Search at least three sources.",
        )

    def test_most_specific_cue_wins(self):
        # "multi source web research" (longer cue) beats "managing tasks".
        matched = self.router.match("do multi-source web research and managing tasks")
        self.assertEqual(matched[0].header.name, "deep-research")

    def test_body_is_never_a_match_cue(self):
        self.assertEqual(self.router.match("at least three sources"), [])

    def test_generic_single_word_does_not_match(self):
        self.assertEqual(self.router.match("managing"), [])

    def test_chinese_cue_matches(self):
        _write_skill(self.root, "cn-skill", description="当需要中文任务管理时用。")
        matched = self.router.match("帮我做中文任务管理")
        self.assertEqual([item.header.name for item in matched], ["cn-skill"])


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.router = SkillRouter(self.root)
        _write_skill(self.root, "task-management", body="Read TASKS.md first.")

    def test_activation_reads_body_only_for_matched_skill(self):
        activated = self.router.activate("task-management")
        self.assertIsNotNone(activated)
        assert activated is not None
        self.assertIn("TASKS.md", activated.body)
        self.assertEqual(activated.token_estimate, approx_tokens("Read TASKS.md first."))

    def test_activation_of_unknown_skill_is_none(self):
        self.assertIsNone(self.router.activate("nope"))

    def test_activation_rejects_over_budget_body(self):
        _write_skill(self.root, "huge", body="x" * (5000 * 4))
        self.assertIsNone(self.router.activate("huge"))

    def test_activation_lists_execution_assets_without_loading_them(self):
        directory = self.root / "task-management"
        (directory / "scripts").mkdir()
        (directory / "scripts" / "run.py").write_text("print('hi')", encoding="utf-8")
        (directory / "references").mkdir()
        (directory / "references" / "guide.md").write_text("Guide.", encoding="utf-8")
        activated = self.router.activate("task-management")
        assert activated is not None
        self.assertEqual(activated.scripts, ("run.py",))
        self.assertEqual(activated.references, ("guide.md",))
        self.assertEqual(activated.assets, ())


class ExecutionAssetTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.router = SkillRouter(self.root)
        _write_skill(self.root, "task-management", body="Body.")
        directory = self.root / "task-management"
        (directory / "scripts").mkdir()
        (directory / "scripts" / "run.py").write_text("print('hi')", encoding="utf-8")
        (directory / "references").mkdir()
        (directory / "references" / "guide.md").write_text("Guide.", encoding="utf-8")

    def test_loads_one_asset_on_demand(self):
        self.assertEqual(
            self.router.load_execution_asset("task-management", "scripts/run.py"),
            "print('hi')",
        )
        self.assertEqual(
            self.router.load_execution_asset("task-management", "references/guide.md"),
            "Guide.",
        )

    def test_rejects_traversal_and_outside_dirs(self):
        self.assertIsNone(
            self.router.load_execution_asset("task-management", "../SKILL.md")
        )
        self.assertIsNone(
            self.router.load_execution_asset("task-management", "SKILL.md")
        )
        self.assertIsNone(
            self.router.load_execution_asset("task-management", "/etc/passwd")
        )
        self.assertIsNone(
            self.router.load_execution_asset("task-management", "scripts/missing.py")
        )
        self.assertIsNone(
            self.router.load_execution_asset("nope", "scripts/run.py")
        )


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.router = SkillRouter(self.root)
        _write_skill(
            self.root,
            "task-management",
            description="Use when managing tasks in a shared TASKS.md file.",
            body="Read TASKS.md first.",
        )

    def test_route_matches_and_activates(self):
        result = self.router.route("help me with managing tasks")
        self.assertFalse(result.no_skill)
        self.assertEqual([s.header.name for s in result.matched], ["task-management"])
        self.assertIn("task-management", result.message)

    def test_route_no_match_is_honest_and_offers_fallback(self):
        result = self.router.route("what is the weather today")
        self.assertTrue(result.no_skill)
        self.assertEqual(result.matched, ())
        self.assertIn("No available skill", result.message)
        self.assertTrue(result.fallback)
        self.assertNotIn("task-management", result.message)

    def test_route_skips_unactivatable_match(self):
        _write_skill(self.root, "huge", description="Use when huge.", body="x" * (5000 * 4))
        result = self.router.route("huge", max_skills=1)
        self.assertTrue(result.no_skill)
        self.assertIn("huge", result.skipped)


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_accepts_valid_skill(self):
        path = _write_skill(self.root, "good", description="Use when managing tasks.")
        self.assertTrue(validate_skill_file(path).valid)

    def test_accepts_chinese_trigger_condition(self):
        path = _write_skill(self.root, "cn", description="当需要中文任务管理时用。")
        self.assertTrue(validate_skill_file(path).valid)

    def test_rejects_description_without_trigger_condition(self):
        path = _write_skill(self.root, "notrigger", description="Track tasks in TASKS.md.")
        result = validate_skill_file(path)
        self.assertFalse(result.valid)
        self.assertTrue(any("trigger" in reason for reason in result.reasons))

    def test_rejects_missing_allowed_tools(self):
        directory = self.root / "notools"
        directory.mkdir()
        path = directory / "SKILL.md"
        path.write_text(
            "---\nname: notools\ndescription: Use when testing.\n---\n\nBody.",
            encoding="utf-8",
        )
        result = validate_skill_file(path)
        self.assertFalse(result.valid)
        self.assertTrue(any("allowed-tools" in reason for reason in result.reasons))

    def test_rejects_over_budget_body(self):
        path = _write_skill(self.root, "huge", body="x" * (5000 * 4))
        result = validate_skill_file(path)
        self.assertFalse(result.valid)
        self.assertTrue(any("token" in reason for reason in result.reasons))

    def test_rejects_bad_name_and_empty_body(self):
        path = _write_skill(self.root, "Bad Name!", body="   ")
        result = validate_skill_file(path)
        self.assertFalse(result.valid)

    def test_external_skill_requires_human_review(self):
        path = _write_skill(
            self.root,
            "ext",
            extra_frontmatter="source: external\n",
        )
        result = validate_skill_file(path)
        self.assertFalse(result.valid)
        self.assertTrue(any("review" in reason for reason in result.reasons))
        reviewed = _write_skill(
            self.root,
            "ext-reviewed",
            extra_frontmatter="source: external\nreviewed: true\nreviewed_by: someone\n",
        )
        self.assertTrue(validate_skill_file(reviewed).valid)

    def test_local_skill_needs_no_review(self):
        path = _write_skill(self.root, "local")
        self.assertTrue(validate_skill_file(path).valid)

    def test_rejects_empty_script(self):
        path = _write_skill(self.root, "withscript")
        scripts = self.root / "withscript" / "scripts"
        scripts.mkdir()
        (scripts / "empty.py").write_text("", encoding="utf-8")
        result = validate_skill_file(path)
        self.assertFalse(result.valid)
        self.assertTrue(any("empty" in reason for reason in result.reasons))

    def test_trigger_condition_helper(self):
        self.assertTrue(has_trigger_condition("Use when managing tasks."))
        self.assertTrue(has_trigger_condition("当需要任务管理时用。"))
        self.assertFalse(has_trigger_condition("Track tasks in TASKS.md."))


class WiringTests(unittest.TestCase):
    """The real product path (SkillStore -> cognition binding) now routes
    through progressive disclosure: unmatched bodies are never read."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = SkillStore(self.root)
        _write_skill(
            self.root,
            "task-management",
            description="Use when managing tasks in a shared TASKS.md file.",
            body="Read TASKS.md first.",
        )
        # Unmatched skill whose body is unreadable: old code (discover all
        # bodies) would choke; routed binding must not touch it.
        front = (
            b"---\nname: broken-body\ndescription: Use when testing broken.\n"
            b"version: 1.0.0\nallowed-tools: []\n---\n\n"
        )
        _write_skill(self.root, "broken-body", raw=front + b"\xff\xfe invalid \x80 body")

    def test_binding_only_activates_matched_skill(self):
        event = AgentEvent("event", "help me with managing tasks", payload={})
        request = CognitionRequest("request", "impasse", event.event_id, event.task)
        bound = self.store.bind_cognition_context(event, request)
        bundle = bound.context.get("resident_skills")
        self.assertIsNotNone(bundle)
        self.assertEqual([s["name"] for s in bundle["skills"]], ["task-management"])

    def test_binding_no_match_binds_nothing(self):
        event = AgentEvent("event", "what is the weather today", payload={})
        request = CognitionRequest("request", "impasse", event.event_id, event.task)
        bound = self.store.bind_cognition_context(event, request)
        self.assertNotIn("resident_skills", bound.context)


if __name__ == "__main__":
    unittest.main()
