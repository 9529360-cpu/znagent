from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.memory import StructuredMemory
from zn_agent.core.project_team import (
    assemble_team,
    journal_message,
    team_memory_prefix,
)
from zn_agent.core.store import KernelStore
from zn_agent.core.team_memory import (
    Retrospective,
    TeamMemory,
    distill_retrospective,
    save_retrospective,
    shared_namespace,
    specialist_memory,
    specialist_namespace,
    team_shared_memory,
)


class TeamMemoryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-team-mem-"))
        self.store = KernelStore(self.root / "memory.db")
        self.memory = StructuredMemory(self.store)
        self.team = assemble_team("X", ["researcher", "developer"], team_id="t9")
        self.arch = specialist_memory(self.memory, self.team.members[0])
        self.dev = specialist_memory(self.memory, self.team.members[1])

    def tearDown(self):
        self.store.close()

    def test_namespaces_isolate_facts(self):
        self.arch.remember("api风格", "REST")
        self.dev.remember("api风格", "GraphQL")
        got_arch = self.arch.recall("api风格")
        got_dev = self.dev.recall("api风格")
        self.assertEqual(got_arch.value, "REST")
        self.assertEqual(got_dev.value, "GraphQL")

    def test_recall_does_not_leak_other_namespaces(self):
        self.dev.remember("秘密", "dev-only")
        self.assertIsNone(self.arch.recall("秘密"))
        # Global (unscoped) facts are invisible through the scoped adapter.
        self.memory.remember("公开", "global")
        self.assertIsNone(self.arch.recall("公开"))

    def test_forget_scoped(self):
        self.arch.remember("k", "v")
        self.arch.forget("k")
        self.assertIsNone(self.arch.recall("k"))

    def test_keys_and_clear(self):
        self.arch.remember("a", 1)
        self.arch.remember("b", 2)
        self.dev.remember("a", 9)
        self.assertEqual(self.arch.keys(), ["a", "b"])
        removed = self.arch.clear()
        self.assertEqual(removed, 2)
        self.assertEqual(self.arch.keys(), [])
        self.assertEqual(self.dev.keys(), ["a"])

    def test_colon_in_key_rejected(self):
        with self.assertRaises(ValueError):
            self.arch.remember("a:b", 1)

    def test_empty_namespace_rejected(self):
        with self.assertRaises(ValueError):
            TeamMemory(self.memory, "  ")

    def test_disband_prefix_covers_team_memory(self):
        prefix = team_memory_prefix("t9")
        self.arch.remember("x", 1)
        self.dev.remember("y", 2)
        shared = team_shared_memory(self.memory, "t9")
        shared.remember("z", 3)
        stored = [f["key"] for f in self.store.list_facts()]
        self.assertTrue(stored)
        self.assertTrue(all(k.startswith(prefix) for k in stored))

    def test_namespace_helpers(self):
        self.assertEqual(
            specialist_namespace("t9", "阿研"), "team:t9:阿研"
        )
        self.assertEqual(shared_namespace("t9"), "team:t9:shared")


class RetrospectiveTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-team-retro-"))
        self.store = KernelStore(self.root / "memory.db")
        self.memory = StructuredMemory(self.store)

    def tearDown(self):
        self.store.close()

    def _entries(self):
        return [
            journal_message("t1", "阿研", "选用 Postgres", kind="decision"),
            journal_message("t1", "阿建", "CI 排队太久", kind="blocker"),
            journal_message("t1", "阿建", "设计稿交给阿测", kind="handoff"),
            journal_message("t1", "阿研", "今天进展顺利", kind="progress"),
            journal_message("t2", "别人", "选用 MySQL", kind="decision"),
        ]

    def test_distill_extracts_by_kind(self):
        retro = distill_retrospective("t1", self._entries())
        self.assertIsInstance(retro, Retrospective)
        self.assertEqual(retro.entry_count, 4)
        self.assertEqual(retro.decisions, ("选用 Postgres",))
        self.assertEqual(retro.blockers, ("CI 排队太久",))
        self.assertEqual(retro.handoffs, ("设计稿交给阿测",))
        self.assertEqual(len(retro.lessons), 3)
        self.assertTrue(any("决定" in lesson for lesson in retro.lessons))

    def test_distill_ignores_other_teams(self):
        retro = distill_retrospective("t1", self._entries())
        self.assertNotIn("选用 MySQL", retro.decisions)

    def test_distill_empty_journal(self):
        retro = distill_retrospective("t1", [])
        self.assertEqual(retro.entry_count, 0)
        self.assertEqual(retro.lessons, ())

    def test_save_and_recall_retrospective(self):
        shared = team_shared_memory(self.memory, "t1")
        retro = distill_retrospective("t1", self._entries())
        save_retrospective(shared, retro)
        match = shared.recall("retrospective")
        self.assertIsNotNone(match)
        self.assertEqual(match.value["team_id"], "t1")
        self.assertEqual(len(match.value["lessons"]), 3)
        # Another team cannot see it.
        other = team_shared_memory(self.memory, "t2")
        self.assertIsNone(other.recall("retrospective"))

    def test_summary(self):
        retro = distill_retrospective("t1", self._entries())
        text = retro.summary()
        self.assertIn("t1", text)
        self.assertIn("4 条日志", text)


if __name__ == "__main__":
    unittest.main()
