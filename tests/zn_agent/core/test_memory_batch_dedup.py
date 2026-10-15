from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.memory import StructuredMemory, fact_content_hash
from zn_agent.core.store import KernelStore


def _ledger_shape(memory: StructuredMemory, keys: list[str]) -> dict[str, list]:
    """Ledger content minus timestamps/ids: (value, aliases, links as
    positions in the same key's history, is_open). Batch and sequential
    runs must agree on this shape even though their timestamps differ
    (batch shares one timestamp)."""
    shape: dict[str, list] = {}
    for key in keys:
        rows = memory.fact_history(key)
        position = {row["id"]: index for index, row in enumerate(rows)}
        shape[key] = [
            (
                row["value"],
                row["aliases"],
                tuple(position[linked] for linked in row["linked_memory_ids"]),
                row["invalid_at"] is None,
            )
            for row in rows
        ]
    return shape


def _facts_shape(store: KernelStore) -> dict[str, tuple]:
    return {
        fact["key"]: (fact["value"], fact["aliases"])
        for fact in store.list_facts()
    }


class FactContentHashTests(unittest.TestCase):
    """M0-2: md5 exact-dedup identity is deterministic and canonical."""

    def test_same_input_same_hash(self):
        first = fact_content_hash("project", "one", ("a", "b"))
        second = fact_content_hash("project", "one", ("a", "b"))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 32)

    def test_different_value_different_hash(self):
        self.assertNotEqual(
            fact_content_hash("project", "one"),
            fact_content_hash("project", "two"),
        )

    def test_tuple_and_list_values_hash_alike(self):
        self.assertEqual(
            fact_content_hash("k", ("a", "b")),
            fact_content_hash("k", ["a", "b"]),
        )

    def test_alias_order_does_not_change_hash(self):
        self.assertEqual(
            fact_content_hash("k", "v", ("a", "b")),
            fact_content_hash("k", "v", ("b", "a")),
        )

    def test_key_whitespace_does_not_change_hash(self):
        self.assertEqual(
            fact_content_hash("  project ", "one"),
            fact_content_hash("project", "one"),
        )


class ExactDedupTests(unittest.TestCase):
    """M0-2: an exact repeat remember() writes nothing at all."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def test_exact_repeat_writes_nothing(self):
        original = StructuredMemory._put_fact_locked
        calls: list[int] = []

        def counting(self, *args, **kwargs):
            calls.append(1)
            return original(self, *args, **kwargs)

        StructuredMemory._put_fact_locked = counting
        self.addCleanup(setattr, StructuredMemory, "_put_fact_locked", original)
        self.memory.remember("project", "one", aliases=("a",))
        self.assertEqual(len(calls), 1)
        before = next(
            f for f in self.store.list_facts() if f["key"] == "project"
        )
        self.memory.remember("project", "one", aliases=("a",))
        self.assertEqual(len(calls), 1)
        after = next(
            f for f in self.store.list_facts() if f["key"] == "project"
        )
        self.assertEqual(after["updated_at"], before["updated_at"])
        self.assertEqual(len(self.memory.fact_history("project")), 1)
        self.assertEqual(self.store.get_fact("project"), "one")

    def test_alias_order_repeat_writes_nothing(self):
        self.memory.remember("project", "one", aliases=("a", "b"))
        self.memory.remember("project", "one", aliases=("b", "a"))
        self.assertEqual(len(self.memory.fact_history("project")), 1)
        self.assertEqual(
            self.store.get_fact("project"), "one"
        )

    def test_same_value_new_aliases_refreshes_without_new_window(self):
        self.memory.remember("project", "one", aliases=("a",))
        self.memory.remember("project", "one", aliases=("b",))
        self.assertEqual(len(self.memory.fact_history("project")), 1)
        updated = next(
            f for f in self.store.list_facts() if f["key"] == "project"
        )
        self.assertEqual(updated["aliases"], ("b",))

    def test_contradiction_still_versions(self):
        self.memory.remember("project", "one", aliases=("a",))
        self.memory.remember("project", "two", aliases=("a",))
        history = self.memory.fact_history("project")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[1]["linked_memory_ids"], (history[0]["id"],))


class RememberManyTests(unittest.TestCase):
    """M0-2: remember_many batches the same decisions under one commit."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def _fresh(self):
        store = KernelStore(self.root / "other.db")
        self.addCleanup(store.close)
        return store, StructuredMemory(store)

    def test_batch_matches_sequential(self):
        items = [
            ("project", "one"),
            ("project", "one"),  # exact repeat -> deduped
            ("reply language", "Chinese"),
            ("response language", "chinese"),  # supersession merge
            ("city", "Rome", ("capital",)),
            ("city", "Rome", ("capital city",)),  # same value, new aliases
            ("city", "Milan"),  # contradiction -> new version
            {"key": "pet", "value": "cat", "aliases": ("animal",)},
            ("project", "two"),  # contradiction after repeats
            ("project", "two"),  # exact repeat of current -> deduped
            ("pet", "cat"),  # non-consecutive repeat -> deduped
        ]
        report = self.memory.remember_many(items)
        other_store, other_memory = self._fresh()
        for item in items:
            if isinstance(item, dict):
                other_memory.remember(
                    item["key"], item["value"],
                    aliases=tuple(item.get("aliases", ())),
                )
            elif len(item) == 2:
                other_memory.remember(item[0], item[1])
            else:
                other_memory.remember(item[0], item[1], aliases=item[2])
        keys = ["project", "reply language", "response language", "city", "pet"]
        self.assertEqual(
            _ledger_shape(self.memory, keys),
            _ledger_shape(other_memory, keys),
        )
        self.assertEqual(_facts_shape(self.store), _facts_shape(other_store))
        self.assertEqual(
            [r["action"] for r in report["results"]],
            [
                "created", "deduped", "created", "versioned", "created",
                "deduped", "versioned", "created", "versioned", "deduped",
                "deduped",
            ],
        )
        # written = 4 created + 3 versioned + 2 alias-refresh dedupes
        # (items 6 and 11: same value, different aliases -> aliases
        # refreshed, no new window). Sequential behaves the same.
        self.assertEqual(report["written"], 9)
        self.assertEqual(report["deduped"], 4)

    def test_batch_repeat_after_change_is_versioned_not_deduped(self):
        # k=v, k=v2, k=v: the last item repeats an EARLIER value, but
        # the live value is v2, so it must version, not dedup.
        report = self.memory.remember_many(
            [("k", "v"), ("k", "v2"), ("k", "v")]
        )
        self.assertEqual(
            [r["action"] for r in report["results"]],
            ["created", "versioned", "versioned"],
        )
        self.assertEqual(len(self.memory.fact_history("k")), 3)
        self.assertEqual(self.store.get_fact("k"), "v")

    def test_batch_commits_once(self):
        statements: list[str] = []
        self.store._conn.set_trace_callback(statements.append)
        try:
            self.memory.remember_many(
                [("a", "one"), ("b", "two"), ("a", "one")]
            )
        finally:
            self.store._conn.set_trace_callback(None)
        commits = sum(1 for s in statements if s.strip().upper() == "COMMIT")
        self.assertEqual(commits, 1)
        statements.clear()
        other_store, other_memory = self._fresh()
        other_store._conn.set_trace_callback(statements.append)
        try:
            other_memory.remember("a", "one")
            other_memory.remember("b", "two")
            other_memory.remember("a", "one")
        finally:
            other_store._conn.set_trace_callback(None)
        sequential_commits = sum(
            1 for s in statements if s.strip().upper() == "COMMIT"
        )
        self.assertGreater(sequential_commits, 1)

    def test_batch_empty(self):
        report = self.memory.remember_many([])
        self.assertEqual(report["results"], [])
        self.assertEqual(report["written"], 0)
        self.assertEqual(self.store.list_facts(), [])

    def test_batch_malformed_item_raises_before_writing(self):
        with self.assertRaises(ValueError):
            self.memory.remember_many([("ok", "one"), ("bad",)])
        self.assertEqual(self.store.list_facts(), [])
        with self.assertRaises(ValueError):
            self.memory.remember_many([{"key": "ok"}])
        self.assertEqual(self.store.list_facts(), [])
        with self.assertRaises(ValueError):
            self.memory.remember_many(["not-a-tuple"])
        self.assertEqual(self.store.list_facts(), [])

    def test_batch_rolls_back_on_bad_key(self):
        with self.assertRaises(ValueError):
            self.memory.remember_many([("ok", "one"), ("", "bad")])
        self.assertEqual(self.store.list_facts(), [])
        self.assertEqual(self.memory.fact_history("ok"), [])

    def test_batch_accepts_bare_string_alias(self):
        report = self.memory.remember_many([("k", "v", "single")])
        self.assertEqual(report["results"][0]["action"], "created")
        fact = next(f for f in self.store.list_facts() if f["key"] == "k")
        self.assertEqual(fact["aliases"], ("single",))


if __name__ == "__main__":
    unittest.main()
