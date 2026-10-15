from __future__ import annotations

"""Tests for AS-4 Skill evals (Tier 1 + Tier 2), deterministic, zero-token."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.skill_evals import (
    eval_description_collisions,
    eval_skills_root,
    eval_tier1_file,
    eval_tier2_root,
    extract_quoted_phrases,
    find_skill_files,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "skill_evals.py"

GOOD_BODY = "# Fix flaky tests\n\nRun the failing test three times.\nRecord each outcome.\n"
GOOD_DESC = (
    "Fixes flaky CI tests. Use when 'CI test fails intermittently'."
)
SUITE_DESC = "Runs the test suite. Use when 'run the full test suite'."
SUITE_BODY = "# Run suite\n\nRun the suite once.\nRecord the outcome.\n"


def _write_skill(
    root: Path,
    name: str,
    *,
    description: str = GOOD_DESC,
    body: str = GOOD_BODY,
    filename: str = "skill.md",
    extra_frontmatter: str = "",
    raw: str | None = None,
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
        return path
    front = (
        f"---\nname: {name}\ndescription: {description}\nversion: 1.0.0\n"
        f"allowed-tools: []\n{extra_frontmatter}---\n\n"
    )
    path.write_text(front + body, encoding="utf-8")
    return path


class ExtractQuotedPhrasesTests(unittest.TestCase):
    def test_double_and_single_quoted_phrases(self):
        phrases = extract_quoted_phrases(
            'Fixes tests. Use when "CI test fails" or \'run the suite now\'.'
        )
        self.assertEqual(phrases, ("CI test fails", "run the suite now"))

    def test_apostrophe_is_not_a_trigger_phrase(self):
        self.assertEqual(
            extract_quoted_phrases("Fixes tests. Use when it don't work."), ()
        )

    def test_no_quotes_means_no_positives(self):
        self.assertEqual(
            extract_quoted_phrases("Fixes tests. Use when CI fails."), ()
        )


class Tier1Tests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_good_skill_passes(self):
        path = _write_skill(self.root, "flaky-fix")
        result = eval_tier1_file(path)
        self.assertTrue(result.passed, result.violations)
        self.assertEqual(result.violations, ())

    def test_missing_frontmatter_is_violation(self):
        path = _write_skill(
            self.root, "bad-skill", raw="No frontmatter here.\n\nBody.\n"
        )
        result = eval_tier1_file(path)
        self.assertFalse(result.passed)
        self.assertTrue(
            any("frontmatter" in v for v in result.violations),
            result.violations,
        )

    def test_missing_section_heading_is_violation(self):
        path = _write_skill(
            self.root, "no-heading", body="Run the check.\nRecord the outcome.\n"
        )
        result = eval_tier1_file(path)
        self.assertFalse(result.passed)
        self.assertTrue(
            any("section heading" in v for v in result.violations),
            result.violations,
        )

    def test_broken_link_is_violation(self):
        path = _write_skill(
            self.root,
            "bad-link",
            body="# Steps\n\nSee [detail](references/missing.md).\n",
        )
        result = eval_tier1_file(path)
        self.assertFalse(result.passed)
        self.assertTrue(
            any("broken link" in v for v in result.violations),
            result.violations,
        )

    def test_existing_link_passes_and_external_link_not_fetched(self):
        directory = self.root / "good-link"
        references = directory / "references"
        references.mkdir(parents=True)
        (references / "detail.md").write_text("# Detail\n", encoding="utf-8")
        path = _write_skill(
            self.root,
            "good-link",
            body=(
                "# Steps\n\nSee [detail](references/detail.md) and "
                "[upstream](https://example.invalid/docs).\n"
            ),
        )
        result = eval_tier1_file(path)
        self.assertTrue(result.passed, result.violations)

    def test_link_escaping_skill_dir_is_violation(self):
        path = _write_skill(
            self.root,
            "escape-link",
            body="# Steps\n\nSee [outside](../secret.md).\n",
        )
        result = eval_tier1_file(path)
        self.assertFalse(result.passed)
        self.assertTrue(
            any("escapes" in v for v in result.violations), result.violations
        )

    def test_missing_allowed_tools_is_violation(self):
        directory = self.root / "no-tools"
        directory.mkdir(parents=True)
        path = directory / "skill.md"
        path.write_text(
            "---\nname: no-tools\ndescription: "
            + GOOD_DESC
            + "\nversion: 1.0.0\n---\n\n"
            + GOOD_BODY,
            encoding="utf-8",
        )
        result = eval_tier1_file(path)
        self.assertFalse(result.passed)
        self.assertTrue(
            any("allowed-tools" in v for v in result.violations),
            result.violations,
        )

    def test_description_over_1024_is_violation(self):
        long_desc = "Fixes tests. Use when 'CI test fails'. " + "x " * 600
        self.assertTrue(len(long_desc) > 1024)
        path = _write_skill(self.root, "too-long", description=long_desc)
        result = eval_tier1_file(path)
        self.assertFalse(result.passed)
        self.assertTrue(
            any("1024" in v for v in result.violations), result.violations
        )

    def test_description_between_500_and_1024_warns_not_violates(self):
        # Layered ceilings: passes Tier 1 with a runtime-cap warning;
        # the runtime cap itself is NOT loosened.
        desc = (
            "Fixes flaky CI tests. Use when 'CI test fails intermittently'. "
            + "Use when the test fails on CI. " * 18
        )
        self.assertTrue(500 < len(desc) <= 1024, len(desc))
        path = _write_skill(self.root, "long-desc", description=desc)
        result = eval_tier1_file(path)
        self.assertTrue(result.passed, result.violations)
        self.assertTrue(
            any("runtime cap" in w for w in result.warnings), result.warnings
        )
        # The intake >500 reason must not be duplicated as a violation.
        self.assertFalse(
            any("exceeds 500" in v for v in result.violations),
            result.violations,
        )


class Tier2Tests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_positive_query_routes_into_top_k_and_activates(self):
        _write_skill(self.root, "flaky-fix")
        _write_skill(self.root, "suite-run", description=SUITE_DESC, body=SUITE_BODY)
        result = eval_tier2_root(self.root)
        self.assertTrue(result.passed, result.checks)
        positives = [
            item for item in result.checks if item.kind == "positive"
        ]
        self.assertEqual(len(positives), 2)
        self.assertTrue(all(item.passed for item in positives))

    def test_generic_negative_queries_match_nothing(self):
        _write_skill(self.root, "flaky-fix")
        result = eval_tier2_root(self.root)
        negatives = [
            item for item in result.checks if item.kind == "generic-negative"
        ]
        self.assertEqual(len(negatives), 5)
        self.assertTrue(all(item.passed for item in negatives))
        self.assertTrue(all(item.matched_names == () for item in negatives))

    def test_shared_quoted_phrase_is_collision_violation(self):
        _write_skill(self.root, "aaa")
        _write_skill(self.root, "bbb")  # Same GOOD_DESC, same trigger.
        result = eval_tier2_root(self.root)
        self.assertFalse(result.passed)
        violations = [
            item for item in result.collisions if item.severity == "violation"
        ]
        self.assertEqual(len(violations), 1)
        self.assertIn("shared quoted trigger phrase", violations[0].reason)
        cross = [
            item
            for item in result.checks
            if item.kind == "cross-negative" and not item.passed
        ]
        self.assertTrue(cross, "shared trigger must fail cross-negatives")

    def test_near_identical_descriptions_are_collision_warning(self):
        _write_skill(self.root, "aaa")
        _write_skill(
            self.root,
            "bbb",
            description=(
                "Fixes flaky CI tests. Use when 'CI test fails sometimes'."
            ),
        )
        result = eval_tier2_root(self.root)
        self.assertTrue(result.passed)  # Warning, not a violation.
        warnings = [
            item for item in result.collisions if item.severity == "warning"
        ]
        self.assertEqual(len(warnings), 1)
        self.assertIn("Jaccard", warnings[0].reason)

    def test_distinct_skills_have_no_collision(self):
        _write_skill(self.root, "flaky-fix")
        _write_skill(self.root, "suite-run", description=SUITE_DESC, body=SUITE_BODY)
        result = eval_tier2_root(self.root)
        self.assertEqual(result.collisions, ())

    def test_overlong_description_skill_is_undiscoverable_warning(self):
        desc = (
            "Fixes flaky CI tests. Use when 'CI test fails intermittently'. "
            + "Use when the test fails on CI. " * 18
        )
        _write_skill(self.root, "long-desc", description=desc)
        result = eval_tier2_root(self.root)
        self.assertTrue(result.passed)  # Warning, not a violation.
        self.assertTrue(
            any("not discoverable" in w for w in result.warnings),
            result.warnings,
        )
        # No positive check can be derived: the router never sees it.
        self.assertFalse(
            [item for item in result.checks if item.kind == "positive"]
        )

    def test_empty_root_passes_with_no_checks(self):
        result = eval_tier2_root(self.root)
        self.assertTrue(result.passed)
        self.assertEqual(result.checks, ())
        self.assertEqual(result.collisions, ())
    def test_collisions_are_deterministic_and_sorted(self):
        _write_skill(self.root, "zzz")
        _write_skill(self.root, "aaa")
        first = eval_description_collisions_from_root(self.root)
        second = eval_description_collisions_from_root(self.root)
        self.assertEqual(first, second)


def eval_description_collisions_from_root(root: Path):
    from zn_agent.core.skill_routing import SkillRouter

    return eval_description_collisions(SkillRouter(root).discover())


class CombinedEvalTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_eval_skills_root_passes_for_good_skills(self):
        _write_skill(self.root, "flaky-fix")
        _write_skill(self.root, "suite-run", description=SUITE_DESC, body=SUITE_BODY)
        report = eval_skills_root(self.root)
        self.assertTrue(report.passed)
        self.assertEqual(len(report.tier1), 2)
        self.assertTrue(report.tier2.passed)

    def test_eval_skills_root_fails_for_bad_skill(self):
        _write_skill(self.root, "flaky-fix")
        _write_skill(self.root, "bad-skill", raw="No frontmatter.\n")
        report = eval_skills_root(self.root)
        self.assertFalse(report.passed)
        by_name = {item.skill_name: item for item in report.tier1}
        self.assertFalse(by_name["bad-skill"].passed)
        self.assertTrue(by_name["flaky-fix"].passed)

    def test_eval_is_deterministic(self):
        _write_skill(self.root, "flaky-fix")
        _write_skill(self.root, "suite-run", description=SUITE_DESC, body=SUITE_BODY)
        first = eval_skills_root(self.root).to_dict()
        second = eval_skills_root(self.root).to_dict()
        self.assertEqual(first, second)

    def test_find_skill_files_discovers_both_filenames(self):
        _write_skill(self.root, "a-skill", filename="skill.md")
        _write_skill(self.root, "b-skill", filename="SKILL.md")
        found = find_skill_files(self.root)
        self.assertEqual(
            [path.parent.name for path in found], ["a-skill", "b-skill"]
        )

    def test_script_reports_good_and_bad_roots(self):
        good = self.root / "good"
        bad = self.root / "bad"
        _write_skill(good, "flaky-fix")
        _write_skill(bad, "bad-skill", raw="No frontmatter.\n")
        env = {"PYTHONPATH": str(REPO_ROOT / "runtime" / "python")}
        good_run = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(good), "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        self.assertEqual(good_run.returncode, 0, good_run.stderr)
        self.assertTrue(json.loads(good_run.stdout)["passed"])
        bad_run = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(bad), "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        self.assertNotEqual(bad_run.returncode, 0)
        report = json.loads(bad_run.stdout)
        self.assertFalse(report["passed"])
        self.assertFalse(report["tier1"][0]["passed"])


if __name__ == "__main__":
    unittest.main()
