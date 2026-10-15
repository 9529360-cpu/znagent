from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.memory import StructuredMemory
from zn_agent.core.store import KernelStore


class LinkedMemoryIdsTests(unittest.TestCase):
    """M0-1 (ADD + linked_memory_ids): a new fact never overwrites an
    old memory. The new ledger version links the ids of the versions
    it superseded, so the chain stays auditable."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def test_contradiction_links_new_version_to_old(self):
        self.memory.remember("project", "one")
        self.memory.remember("project", "two")
        history = self.memory.fact_history("project")
        self.assertEqual(len(history), 2)
        old, new = history
        self.assertEqual(old["linked_memory_ids"], ())
        self.assertEqual(new["linked_memory_ids"], (old["id"],))
        self.assertNotEqual(old["id"], new["id"])
        # The live row still holds only the current value.
        self.assertEqual(self.store.get_fact("project"), "two")
        self.assertEqual(len(self.store.list_facts()), 1)
        # recall() surfaces the current version's id + links.
        match = self.memory.recall("project")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.value, "two")
        self.assertEqual(match.id, new["id"])
        self.assertEqual(match.linked_memory_ids, (old["id"],))

    def test_chain_grows_across_three_versions(self):
        self.memory.remember("project", "one")
        self.memory.remember("project", "two")
        self.memory.remember("project", "three")
        history = self.memory.fact_history("project")
        self.assertEqual(len(history), 3)
        first, second, third = history
        self.assertEqual(first["linked_memory_ids"], ())
        self.assertEqual(second["linked_memory_ids"], (first["id"],))
        self.assertEqual(third["linked_memory_ids"], (second["id"],))
        # Walking newest -> oldest via links visits every version.
        by_id = {row["id"]: row for row in history}
        seen = [third["id"]]
        current = third
        while current["linked_memory_ids"]:
            current = by_id[current["linked_memory_ids"][0]]
            seen.append(current["id"])
        self.assertEqual(seen, [third["id"], second["id"], first["id"]])

    def test_same_value_rewrite_links_nothing_and_dedups(self):
        self.memory.remember("project", "one")
        self.memory.remember("project", "one")
        history = self.memory.fact_history("project")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["linked_memory_ids"], ())
        match = self.memory.recall("project")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.linked_memory_ids, ())

    def test_first_version_links_nothing(self):
        self.memory.remember("project", "one")
        history = self.memory.fact_history("project")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["linked_memory_ids"], ())
        match = self.memory.recall("project")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertIsNotNone(match.id)
        self.assertEqual(match.id, history[0]["id"])
        self.assertEqual(match.linked_memory_ids, ())

    def test_recall_as_of_carries_link_ids(self):
        self.memory.remember("project", "one")
        first_valid = self.memory.fact_history("project")[0]["valid_at"]
        self.memory.remember("project", "two")
        history = self.memory.fact_history("project")
        closed_at = history[0]["invalid_at"]
        assert closed_at is not None
        old = self.memory.recall_as_of("project", first_valid)
        self.assertIsNotNone(old)
        assert old is not None
        self.assertEqual(old.value, "one")
        self.assertEqual(old.id, history[0]["id"])
        self.assertEqual(old.linked_memory_ids, ())
        current = self.memory.recall_as_of("project", closed_at)
        self.assertIsNotNone(current)
        assert current is not None
        self.assertEqual(current.value, "two")
        self.assertEqual(current.id, history[1]["id"])
        self.assertEqual(current.linked_memory_ids, (history[0]["id"],))

    def test_supersession_merge_links_closed_version(self):
        # Near-duplicate keys with near-identical but not equal values
        # merge in place; the merged version links the closed version.
        self.memory.remember("reply language", "Chinese")
        self.memory.remember("response language", "chinese")
        history = self.memory.fact_history("reply language")
        self.assertEqual(len(history), 2)
        old, new = history
        self.assertEqual(old["value"], "Chinese")
        self.assertEqual(new["value"], "chinese")
        self.assertEqual(old["linked_memory_ids"], ())
        self.assertEqual(new["linked_memory_ids"], (old["id"],))

    def test_legacy_backfill_snapshot_is_linked(self):
        # A row written without remember() has no ledger rows; the
        # first contradicting remember() backfills a closed snapshot,
        # and the new version links that snapshot's id.
        self.store.put_fact("project", "legacy")
        created = next(
            f for f in self.store.list_facts() if f["key"] == "project"
        )["created_at"]
        self.memory.remember("project", "new")
        history = self.memory.fact_history("project")
        self.assertEqual(len(history), 2)
        old, new = history
        self.assertEqual(old["value"], "legacy")
        self.assertEqual(old["linked_memory_ids"], ())
        self.assertEqual(new["linked_memory_ids"], (old["id"],))
        before = self.memory.recall_as_of("project", created)
        self.assertIsNotNone(before)
        assert before is not None
        self.assertEqual(before.value, "legacy")
        self.assertEqual(before.id, old["id"])

    def test_forget_keeps_link_chain(self):
        self.memory.remember("project", "one")
        first_valid = self.memory.fact_history("project")[0]["valid_at"]
        self.memory.remember("project", "two")
        self.memory.forget("project")
        self.assertIsNone(self.memory.recall("project"))
        history = self.memory.fact_history("project")
        self.assertEqual(len(history), 2)
        old, new = history
        self.assertEqual(old["linked_memory_ids"], ())
        self.assertEqual(new["linked_memory_ids"], (old["id"],))
        before = self.memory.recall_as_of("project", first_valid)
        self.assertIsNotNone(before)
        assert before is not None
        self.assertEqual(before.value, "one")
        self.assertEqual(before.id, old["id"])

    def test_consolidate_does_not_link_loser_into_winner(self):
        # Consolidation merges different keys sharing an alias; the
        # winner is not a new version of the losers, so it links none.
        self.memory.remember(
            "old-key", "old value", aliases=("shared alias", "old-only")
        )
        self.memory.remember(
            "new-key", "new value", aliases=("shared alias", "new-only")
        )
        report = self.memory.consolidate()
        self.assertEqual(report["merged"][0]["removed"], ["old-key"])
        winner = self.memory.fact_history("new-key")
        self.assertEqual(len(winner), 1)
        self.assertEqual(winner[0]["linked_memory_ids"], ())
        loser = self.memory.fact_history("old-key")
        self.assertEqual(len(loser), 1)
        self.assertEqual(loser[0]["linked_memory_ids"], ())

    def test_close_open_window_returns_closed_ids(self):
        self.memory.remember("project", "one")
        version_id = self.memory.fact_history("project")[0]["id"]
        closed = self.memory._close_open_window(
            "project", "2999-01-01T00:00:00+00:00"
        )
        self.assertEqual(closed, [version_id])
        # Nothing open any more: a second close links nothing.
        self.assertEqual(
            self.memory._close_open_window("project", "2999-01-02T00:00:00+00:00"),
            [],
        )

    def test_migration_adds_link_column_to_pre_m01_table(self):
        # A memory_history table created before M0-1 (no linked column)
        # gains the column in place; old rows read back with empty links.
        with self.store._lock, self.store._conn:
            self.store._conn.execute(
                "CREATE TABLE memory_history("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "fact_key TEXT NOT NULL, value_json TEXT NOT NULL, "
                "aliases_json TEXT NOT NULL, valid_at TEXT NOT NULL, "
                "invalid_at TEXT)"
            )
        self.memory.remember("project", "one")
        self.memory.remember("project", "two")
        history = self.memory.fact_history("project")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["linked_memory_ids"], ())
        self.assertEqual(history[1]["linked_memory_ids"], (history[0]["id"],))


if __name__ == "__main__":
    unittest.main()
