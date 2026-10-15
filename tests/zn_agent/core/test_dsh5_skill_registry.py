from __future__ import annotations

import tempfile
import unittest
from dataclasses import fields
from pathlib import Path

from zn_agent.core.skills import (
    LayeredSkillRegistry,
    SkillDirectoryEntry,
    SkillLayer,
)


def _write_skill(
    root: Path,
    name: str,
    *,
    description: str = "A skill.",
    body: str = "Body.",
    version: str = "1.0.0",
    rank: object = None,
    globs: list[str] | None = None,
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"name: {name}", f"description: {description}", f"version: {version}"]
    if rank is not None:
        lines.append(f"rank: {rank}")
    if globs is not None:
        lines.append("globs: [" + ", ".join(f'"{item}"' for item in globs) + "]")
    lines.append("---")
    lines.append("")
    path = directory / "skill.md"
    path.write_text("\n".join(lines) + "\n" + body, encoding="utf-8")
    return path


class LayeredRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.host = self.tmp / "host"
        self.scope = self.tmp / "scope"
        self.host.mkdir()
        self.scope.mkdir()

    def _registry(self, **kwargs):
        return LayeredSkillRegistry(
            layers=(
                SkillLayer.single("host", self.host),
                SkillLayer.single("project", self.scope),
            ),
            **kwargs,
        )

    def test_nearest_layer_wins_same_name(self):
        _write_skill(self.host, "dup", description="Host version.", body="HOST BODY")
        _write_skill(self.scope, "dup", description="Scope version.", body="SCOPE BODY")
        registry = self._registry()
        entries = registry.list()
        self.assertEqual([entry.name for entry in entries], ["dup"])
        self.assertEqual(entries[0].layer, "project")
        self.assertEqual(entries[0].description, "Scope version.")
        self.assertEqual(entries[0].path, self.scope / "dup" / "skill.md")
        got = registry.get("dup")
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(got.body, "SCOPE BODY")

    def test_nearest_layer_wins_even_with_lower_rank(self):
        _write_skill(self.host, "dup", description="Host.", body="HOST BODY", rank=999)
        _write_skill(self.scope, "dup", description="Scope.", body="SCOPE BODY", rank=0)
        registry = self._registry()
        self.assertEqual(registry.list()[0].layer, "project")
        got = registry.get("dup")
        assert got is not None
        self.assertEqual(got.body, "SCOPE BODY")

    def test_same_layer_same_name_highest_rank_wins(self):
        first = self.tmp / "first"
        second = self.tmp / "second"
        first.mkdir()
        second.mkdir()
        _write_skill(first, "dup", description="Low rank.", body="LOW BODY", rank=2)
        _write_skill(second, "dup", description="High rank.", body="HIGH BODY", rank=10)
        registry = LayeredSkillRegistry(
            layers=(SkillLayer(name="project", roots=(first, second)),)
        )
        entries = registry.list()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].rank, 10)
        self.assertEqual(entries[0].description, "High rank.")
        got = registry.get("dup")
        assert got is not None
        self.assertEqual(got.body, "HIGH BODY")

    def test_rank_defaults_to_zero_and_invalid_rank_reads_as_zero(self):
        _write_skill(self.host, "plain", description="No rank.", body="PLAIN BODY")
        _write_skill(self.host, "weird", description="Bad rank.", body="WEIRD BODY", rank="high")
        registry = LayeredSkillRegistry(layers=(SkillLayer.single("host", self.host),))
        by_name = {entry.name: entry for entry in registry.list()}
        self.assertEqual(by_name["plain"].rank, 0)
        self.assertEqual(by_name["weird"].rank, 0)

    def test_same_layer_same_rank_smallest_path_wins_deterministically(self):
        first = self.tmp / "aaa"
        second = self.tmp / "zzz"
        first.mkdir()
        second.mkdir()
        _write_skill(first, "dup", description="First.", body="FIRST BODY", rank=5)
        _write_skill(second, "dup", description="Second.", body="SECOND BODY", rank=5)
        registry = LayeredSkillRegistry(
            layers=(SkillLayer(name="project", roots=(second, first)),)
        )
        first_run = registry.list()
        second_run = registry.list()
        self.assertEqual(first_run, second_run)
        self.assertEqual(len(first_run), 1)
        self.assertEqual(first_run[0].path, first / "dup" / "skill.md")
        got = registry.get("dup")
        assert got is not None
        self.assertEqual(got.body, "FIRST BODY")

    def test_list_returns_directory_only_no_body(self):
        _write_skill(
            self.host,
            "task-management",
            description="Track tasks.",
            body="Full body text here.",
            globs=["*.py"],
        )
        registry = LayeredSkillRegistry(layers=(SkillLayer.single("host", self.host),))
        entries = registry.list()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertIsInstance(entry, SkillDirectoryEntry)
        field_names = {item.name for item in fields(entry)}
        self.assertNotIn("body", field_names)
        self.assertFalse(hasattr(entry, "body"))
        self.assertEqual(entry.layer, "host")
        self.assertEqual(entry.globs, ("*.py",))
        # Full text is only available through get().
        got = registry.get("task-management")
        assert got is not None
        self.assertEqual(got.body, "Full body text here.")

    def test_list_never_reads_bodies(self):
        directory = self.host / "broken-body"
        directory.mkdir(parents=True, exist_ok=True)
        front = "---\nname: broken-body\ndescription: Valid frontmatter.\nversion: 1.0.0\n---\n\n"
        (directory / "skill.md").write_bytes(front.encode("utf-8") + b"\xff\xfe not utf-8")
        registry = LayeredSkillRegistry(layers=(SkillLayer.single("host", self.host),))
        entries = registry.list()
        self.assertEqual([entry.name for entry in entries], ["broken-body"])
        # The winner is listed, but its body cannot be read: no fallback,
        # no silent shadowing, just None.
        self.assertIsNone(registry.get("broken-body"))

    def test_get_unknown_name_returns_none(self):
        registry = LayeredSkillRegistry(layers=(SkillLayer.single("host", self.host),))
        self.assertIsNone(registry.get("no-such-skill"))

    def test_empty_registry_and_missing_roots(self):
        registry = LayeredSkillRegistry(layers=())
        self.assertEqual(registry.list(), [])
        self.assertIsNone(registry.get("anything"))
        registry = LayeredSkillRegistry(
            layers=(SkillLayer.single("host", self.tmp / "does-not-exist"),)
        )
        self.assertEqual(registry.list(), [])
        self.assertIsNone(registry.get("anything"))

    def test_list_sorted_by_name_and_shadowed_entries_hidden(self):
        _write_skill(self.host, "zebra", description="Zebra host.", body="ZEBRA HOST")
        _write_skill(self.host, "apple", description="Apple host.", body="APPLE HOST")
        _write_skill(self.scope, "zebra", description="Zebra scope.", body="ZEBRA SCOPE")
        registry = self._registry()
        self.assertEqual([entry.name for entry in registry.list()], ["apple", "zebra"])
        self.assertEqual(
            [entry.layer for entry in registry.list()], ["host", "project"]
        )


if __name__ == "__main__":
    unittest.main()
