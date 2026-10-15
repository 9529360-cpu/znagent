from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.memory import StructuredMemory
from zn_agent.core.store import KernelStore


class TimeWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def test_window_fields_persisted_on_first_write(self):
        self.memory.remember("project", "znagent")
        history = self.memory.fact_history("project")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["value"], "znagent")
        self.assertTrue(history[0]["valid_at"])
        self.assertIsNone(history[0]["invalid_at"])
        # The live facts row still holds the current value.
        self.assertEqual(self.store.get_fact("project"), "znagent")

    def test_recall_returns_only_current_value(self):
        self.memory.remember("project", "one")
        self.memory.remember("project", "two")
        match = self.memory.recall("project")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.value, "two")
        self.assertTrue(match.valid_at)
        self.assertIsNone(match.invalid_at)

    def test_contradiction_closes_old_window_without_deleting(self):
        self.memory.remember("project", "one")
        self.memory.remember("project", "two")
        history = self.memory.fact_history("project")
        self.assertEqual(len(history), 2)
        old, new = history
        # Old version closed exactly when the new version became valid.
        self.assertEqual(old["invalid_at"], new["valid_at"])
        self.assertEqual(old["value"], "one")
        self.assertIsNone(new["invalid_at"])
        self.assertEqual(new["value"], "two")
        # The facts table keeps one live row; history holds both versions.
        self.assertEqual(len(self.store.list_facts()), 1)

    def test_as_of_returns_what_was_true_then(self):
        self.memory.remember("project", "one")
        history = self.memory.fact_history("project")
        first_valid = history[0]["valid_at"]
        self.memory.remember("project", "two")
        history = self.memory.fact_history("project")
        closed_at = history[0]["invalid_at"]
        assert closed_at is not None
        # At the first version's start, "one" was true.
        old = self.memory.recall_as_of("project", first_valid)
        self.assertIsNotNone(old)
        assert old is not None
        self.assertEqual(old.value, "one")
        # Windows are [valid_at, invalid_at): at the close instant the new
        # version is already true.
        current = self.memory.recall_as_of("project", closed_at)
        self.assertIsNotNone(current)
        assert current is not None
        self.assertEqual(current.value, "two")
        # Before anything was remembered, nothing was true.
        self.assertIsNone(self.memory.recall_as_of("project", "2000-01-01T00:00:00+00:00"))

    def test_as_of_matches_alias_snapshot(self):
        self.memory.remember("project", "one", aliases=("active project",))
        self.memory.remember("project", "two", aliases=("active project",))
        first_valid = self.memory.fact_history("project")[0]["valid_at"]
        old = self.memory.recall_as_of("active project", first_valid)
        self.assertIsNotNone(old)
        assert old is not None
        self.assertEqual(old.key, "project")
        self.assertEqual(old.value, "one")

    def test_same_value_rewrite_keeps_single_window(self):
        self.memory.remember("project", "one")
        self.memory.remember("project", "one")
        history = self.memory.fact_history("project")
        self.assertEqual(len(history), 1)
        self.assertIsNone(history[0]["invalid_at"])

    def test_legacy_row_backfill_preserves_pre_window_history(self):
        # A row written without going through remember() has no ledger
        # rows; the first contradicting remember() backfills it from the
        # facts row's created_at instead of losing the old version.
        self.store.put_fact("project", "legacy")
        created = next(
            f for f in self.store.list_facts() if f["key"] == "project"
        )["created_at"]
        self.memory.remember("project", "new")
        history = self.memory.fact_history("project")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["valid_at"], created)
        self.assertEqual(history[0]["value"], "legacy")
        self.assertEqual(history[0]["invalid_at"], history[1]["valid_at"])
        old = self.memory.recall_as_of("project", created)
        self.assertIsNotNone(old)
        assert old is not None
        self.assertEqual(old.value, "legacy")

    def test_forget_closes_window_but_keeps_history(self):
        self.memory.remember("project", "one")
        first_valid = self.memory.fact_history("project")[0]["valid_at"]
        self.memory.remember("project", "two")
        self.memory.forget("project")
        self.assertIsNone(self.memory.recall("project"))
        self.assertIsNone(self.store.get_fact("project"))
        history = self.memory.fact_history("project")
        self.assertEqual(len(history), 2)
        self.assertTrue(all(row["invalid_at"] for row in history))
        old = self.memory.recall_as_of("project", first_valid)
        self.assertIsNotNone(old)
        assert old is not None
        self.assertEqual(old.value, "one")

    def test_closed_window_hides_live_row_from_current_reads(self):
        # Simulates a stale live row whose window has closed: current
        # reads must not surface it, as-of reads still can.
        self.memory.remember("project", "one", aliases=("active project",))
        first_valid = self.memory.fact_history("project")[0]["valid_at"]
        self.memory._close_open_window("project", "2999-01-01T00:00:00+00:00")
        self.assertIsNone(self.memory.recall("project"))
        self.assertEqual(
            self.memory.relevant_context("Explain the active project"), []
        )
        old = self.memory.recall_as_of("project", first_valid)
        self.assertIsNotNone(old)
        assert old is not None
        self.assertEqual(old.value, "one")

    def test_relevant_context_returns_new_value_after_contradiction(self):
        self.memory.remember("project", {"name": "one"}, aliases=("active project",))
        self.memory.remember("project", {"name": "two"}, aliases=("active project",))
        result = self.memory.relevant_context("Explain the active project")
        self.assertEqual(result, [{"key": "project", "value": {"name": "two"}}])

    def test_supersession_merge_preserves_old_version(self):
        # Near-duplicate keys with near-identical but not equal values
        # still merge in place -- and the old version gains a closed
        # window instead of being overwritten away.
        self.memory.remember("reply language", "Chinese")
        self.memory.remember("response language", "chinese")
        facts = self.store.list_facts()
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["key"], "reply language")
        self.assertEqual(facts[0]["value"], "chinese")
        history = self.memory.fact_history("reply language")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["value"], "Chinese")
        self.assertEqual(history[0]["invalid_at"], history[1]["valid_at"])
        self.assertEqual(history[1]["value"], "chinese")
        self.assertIsNone(history[1]["invalid_at"])

    def test_consolidate_closes_loser_window(self):
        self.memory.remember("old-key", "old value", aliases=("shared alias", "old-only"))
        before = self.memory.fact_history("old-key")[0]["valid_at"]
        self.memory.remember("new-key", "new value", aliases=("shared alias", "new-only"))
        report = self.memory.consolidate()
        self.assertEqual(report["merged"][0]["removed"], ["old-key"])
        history = self.memory.fact_history("old-key")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["value"], "old value")
        self.assertTrue(history[0]["invalid_at"])
        old = self.memory.recall_as_of("old-key", before)
        self.assertIsNotNone(old)
        assert old is not None
        self.assertEqual(old.value, "old value")

    def test_fact_history_unknown_key_is_empty(self):
        self.assertEqual(self.memory.fact_history("no such key"), [])

    def test_recall_as_of_rejects_empty_time(self):
        self.memory.remember("project", "one")
        with self.assertRaises(ValueError):
            self.memory.recall_as_of("project", "")


if __name__ == "__main__":
    unittest.main()
