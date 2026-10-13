from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.memory import StructuredMemory
from zn_agent.core.store import KernelStore


class ConsolidateTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def test_merges_alias_collision_keeping_newest(self):
        self.memory.remember("old-key", "old value", aliases=("shared alias", "old-only"))
        self.memory.remember("new-key", "new value", aliases=("shared alias", "new-only"))
        report = self.memory.consolidate()
        self.assertEqual(len(report["merged"]), 1)
        self.assertEqual(report["merged"][0]["kept"], "new-key")
        self.assertEqual(report["merged"][0]["removed"], ["old-key"])
        # Winner keeps its value; aliases are unioned.
        self.assertEqual(self.store.get_fact("new-key"), "new value")
        remaining = self.store.list_facts()
        self.assertEqual(len(remaining), 1)
        aliases = set(remaining[0]["aliases"])
        self.assertIn("shared alias", aliases)
        self.assertIn("old-only", aliases)
        self.assertIn("new-only", aliases)
        self.assertEqual(report["fact_count"], 1)

    def test_no_collision_no_change(self):
        self.memory.remember("a", "1", aliases=("alpha",))
        self.memory.remember("b", "2", aliases=("beta",))
        report = self.memory.consolidate()
        self.assertEqual(report["merged"], [])
        self.assertEqual(report["fact_count"], 2)

    def test_key_itself_counts_as_claim(self):
        # A fact whose KEY equals another fact's alias collides too.
        self.memory.remember("project", "v1", aliases=("proj",))
        self.memory.remember("proj", "v2", aliases=())
        report = self.memory.consolidate()
        self.assertEqual(len(report["merged"]), 1)
        self.assertEqual(report["fact_count"], 1)

    def test_idempotent(self):
        self.memory.remember("a", "1", aliases=("shared",))
        self.memory.remember("b", "2", aliases=("shared",))
        first = self.memory.consolidate()
        second = self.memory.consolidate()
        self.assertEqual(len(first["merged"]), 1)
        self.assertEqual(second["merged"], [])
        self.assertEqual(second["fact_count"], 1)

    def test_empty_store(self):
        report = self.memory.consolidate()
        self.assertEqual(report, {"merged": [], "fact_count": 0})


if __name__ == "__main__":
    unittest.main()
