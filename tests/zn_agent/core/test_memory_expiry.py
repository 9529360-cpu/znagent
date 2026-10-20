from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from zn_agent.core.memory import StructuredMemory
from zn_agent.core.models import utc_now
from zn_agent.core.store import KernelStore

PAST = "2000-01-01T00:00:00+00:00"
FUTURE = "2999-12-31T00:00:00+00:00"


class FactExpiryTests(unittest.TestCase):
    """Q7(b): facts carry an optional ``expires_at``; live recall paths
    filter out expired facts without deleting rows or ledger history."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def test_expired_fact_not_recalled(self):
        self.memory.remember("promo code", "SAVE20", expires_at=PAST)
        self.assertIsNone(self.memory.recall("promo code"))
        self.assertEqual(
            self.memory.recall_hybrid("promo code"), [],
        )

    def test_unexpired_fact_recalled(self):
        self.memory.remember("promo code", "SAVE20", expires_at=FUTURE)
        match = self.memory.recall("promo code")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.value, "SAVE20")
        hits = self.memory.recall_hybrid("promo code")
        self.assertTrue(any(hit["key"] == "promo code" for hit in hits))

    def test_no_expiry_recalls_as_before(self):
        self.memory.remember("promo code", "SAVE20")
        match = self.memory.recall("promo code")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.value, "SAVE20")
        self.assertIsNone(self.store.list_facts()[0]["expires_at"])

    def test_expiry_boundary_is_inclusive(self):
        now = utc_now()
        self.memory.remember("promo code", "SAVE20", expires_at=now)
        # expires_at == now counts as expired (<=), never as a live fact.
        self.assertIsNone(self.memory.recall("promo code"))

    def test_expiry_preserved_when_not_mentioned(self):
        self.memory.remember("promo code", "SAVE20", expires_at=FUTURE)
        # A plain re-remember without expires_at must not clear the TTL.
        self.memory.remember("promo code", "SAVE20B")
        facts = self.store.list_facts()
        self.assertEqual(facts[0]["expires_at"], FUTURE)
        self.assertIsNotNone(self.memory.recall("promo code"))

    def test_explicit_none_clears_expiry(self):
        self.memory.remember("promo code", "SAVE20", expires_at=PAST)
        self.assertIsNone(self.memory.recall("promo code"))
        self.memory.remember("promo code", "SAVE20", expires_at=None)
        self.assertIsNone(self.store.list_facts()[0]["expires_at"])
        match = self.memory.recall("promo code")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.value, "SAVE20")

    def test_expiry_only_update_opens_no_new_window(self):
        self.memory.remember("promo code", "SAVE20")
        self.assertEqual(len(self.memory.fact_history("promo code")), 1)
        # Same content, only the expiry changes: in-place refresh, no
        # new ledger version (supersession/consolidation untouched).
        self.memory.remember("promo code", "SAVE20", expires_at=FUTURE)
        self.assertEqual(len(self.memory.fact_history("promo code")), 1)
        self.assertEqual(self.store.list_facts()[0]["expires_at"], FUTURE)
        self.assertIsNotNone(self.memory.recall("promo code"))

    def test_supersession_merge_preserves_target_expiry(self):
        self.memory.remember(
            "reply language", "Chinese", aliases=("lang",),
            expires_at=FUTURE,
        )
        # Near-duplicate key merges into the existing target; the merge
        # must not drop the target's expiry.
        self.memory.remember("response language", "Chinese")
        facts = self.store.list_facts()
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["key"], "reply language")
        self.assertEqual(facts[0]["expires_at"], FUTURE)
        self.assertIsNotNone(self.memory.recall("reply language"))

    def test_as_of_still_returns_expired_fact(self):
        self.memory.remember("promo code", "SAVE20", expires_at=PAST)
        valid_at = self.memory.fact_history("promo code")[0]["valid_at"]
        # Expiry filters live recall; it does not rewrite history.
        old = self.memory.recall_as_of("promo code", valid_at)
        self.assertIsNotNone(old)
        assert old is not None
        self.assertEqual(old.value, "SAVE20")

    def test_relevant_context_skips_expired(self):
        self.memory.remember("flight number", "CA123", expires_at=PAST)
        self.memory.remember("hotel name", "Hilton", expires_at=FUTURE)
        self.assertEqual(self.memory.relevant_context("flight number"), [])
        live = self.memory.relevant_context("hotel name")
        self.assertTrue(any(fact["key"] == "hotel name" for fact in live))

    def test_expires_at_accepts_datetime(self):
        self.memory.remember(
            "promo code", "SAVE20",
            expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
        )
        self.assertIsNone(self.memory.recall("promo code"))

    def test_malformed_expires_at_raises(self):
        with self.assertRaises(ValueError):
            self.memory.remember("k", "v", expires_at="not-a-timestamp")
        with self.assertRaises(ValueError):
            self.memory.remember("k", "v", expires_at=12345)
        with self.assertRaises(ValueError):
            self.memory.remember("k", "v", expires_at="   ")
        # Nothing was written by the failed calls.
        self.assertEqual(self.store.list_facts(), [])


class RememberManyExpiryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def test_dict_items_carry_expires_at(self):
        result = self.memory.remember_many([
            {"key": "promo", "value": "SAVE20", "expires_at": PAST},
            {"key": "hotel", "value": "Hilton", "expires_at": FUTURE},
            ("plain", "value"),
        ])
        self.assertEqual(result["written"], 3)
        self.assertIsNone(self.memory.recall("promo"))
        match = self.memory.recall("hotel")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.value, "Hilton")
        self.assertIsNotNone(self.memory.recall("plain"))

    def test_malformed_expires_at_aborts_batch(self):
        with self.assertRaises(ValueError):
            self.memory.remember_many([
                {"key": "promo", "value": "SAVE20", "expires_at": PAST},
                {"key": "bad", "value": "x", "expires_at": "yesterday-ish"},
            ])
        # Malformed items raise before anything is written.
        self.assertEqual(self.store.list_facts(), [])


class StoreExpiryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)

    def test_put_fact_expires_at_roundtrip(self):
        self.store.put_fact("k", "v", expires_at=PAST)
        facts = self.store.list_facts()
        self.assertEqual(facts[0]["expires_at"], PAST)
        # Default (EXPIRES_UNSET) preserves the existing expiry.
        self.store.put_fact("k", "v2")
        self.assertEqual(self.store.list_facts()[0]["expires_at"], PAST)
        # Explicit None clears it.
        self.store.put_fact("k", "v3", expires_at=None)
        self.assertIsNone(self.store.list_facts()[0]["expires_at"])
        self.assertEqual(self.store.get_fact("k"), "v3")

    def test_migration_adds_column_to_old_database(self):
        path = self.root / "old.db"
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE facts(fact_key TEXT PRIMARY KEY, "
            "value_json TEXT NOT NULL, aliases_json TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO facts VALUES(?,?,?,?,?)",
            ("legacy", '"v"', "[]", PAST, PAST),
        )
        conn.commit()
        conn.close()
        # Opening with the new code migrates the old database in place.
        store = KernelStore(path)
        try:
            # Explicitly close the check connection: on Windows an unclosed
            # sqlite handle keeps old.db locked, which makes the temp dir
            # cleanup fail with WinError 32.
            check = sqlite3.connect(path)
            try:
                columns = {
                    row[1] for row in check.execute("PRAGMA table_info(facts)").fetchall()
                }
            finally:
                check.close()
            self.assertIn("expires_at", columns)
            facts = store.list_facts()
            self.assertEqual(len(facts), 1)
            self.assertIsNone(facts[0]["expires_at"])
            memory = StructuredMemory(store)
            match = memory.recall("legacy")
            self.assertIsNotNone(match)
            assert match is not None
            self.assertEqual(match.value, "v")
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
