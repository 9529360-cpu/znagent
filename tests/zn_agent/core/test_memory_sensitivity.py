from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.store import (
    SENSITIVITY_LEVELS,
    SENSITIVITY_NON_RETAINABLE,
    SENSITIVITY_NORMAL,
    SENSITIVITY_SENSITIVE,
    KernelStore,
    normalize_sensitivity,
)


class NormalizeSensitivityTests(unittest.TestCase):
    def test_known_tiers_pass_through(self):
        for tier in SENSITIVITY_LEVELS:
            self.assertEqual(normalize_sensitivity(tier), tier)

    def test_none_clears_to_normal(self):
        self.assertEqual(normalize_sensitivity(None), SENSITIVITY_NORMAL)

    def test_whitespace_is_tolerated(self):
        self.assertEqual(
            normalize_sensitivity("  non_retainable  "),
            SENSITIVITY_NON_RETAINABLE,
        )

    def test_unknown_tiers_raise(self):
        for bad in ("", "private", "NON_RETAINABLE", "top-secret", 123, ["normal"]):
            with self.assertRaises(ValueError, msg=f"sensitivity={bad!r}"):
                normalize_sensitivity(bad)


class FactSensitivityTests(unittest.TestCase):
    """Q11: facts carry a ``sensitivity`` tier; ``non_retainable`` facts
    are stored, listed, and forgettable, but never enter live recall or
    cognition context."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def test_default_tier_is_normal(self):
        self.memory.remember("promo code", "SAVE20")
        facts = self.store.list_facts()
        self.assertEqual(facts[0]["sensitivity"], SENSITIVITY_NORMAL)
        match = self.memory.recall("promo code")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.value, "SAVE20")

    def test_non_retainable_not_recalled(self):
        self.memory.remember(
            "bank pin", "1234", sensitivity=SENSITIVITY_NON_RETAINABLE
        )
        self.assertIsNone(self.memory.recall("bank pin"))
        self.assertEqual(self.memory.recall_hybrid("bank pin"), [])

    def test_non_retainable_not_in_cognition_context(self):
        self.memory.remember(
            "bank pin", "1234", sensitivity=SENSITIVITY_NON_RETAINABLE
        )
        self.memory.remember("hotel name", "Hilton")
        self.assertEqual(self.memory.relevant_context("bank pin"), [])
        live = self.memory.relevant_context("hotel name")
        self.assertTrue(any(fact["key"] == "hotel name" for fact in live))

    def test_sensitive_tier_marks_without_changing_behavior(self):
        self.memory.remember("api note", "rotate quarterly", sensitivity="sensitive")
        facts = self.store.list_facts()
        self.assertEqual(facts[0]["sensitivity"], SENSITIVITY_SENSITIVE)
        # Marker only this round: recall and cognition still work.
        match = self.memory.recall("api note")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.value, "rotate quarterly")
        self.assertTrue(
            any(
                fact["key"] == "api note"
                for fact in self.memory.relevant_context("api note")
            )
        )

    def test_non_retainable_visible_in_list_and_forgettable(self):
        self.memory.remember(
            "bank pin", "1234", sensitivity=SENSITIVITY_NON_RETAINABLE
        )
        facts = self.store.list_facts()
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["key"], "bank pin")
        self.assertEqual(facts[0]["sensitivity"], SENSITIVITY_NON_RETAINABLE)
        self.memory.forget("bank pin")
        self.assertEqual(self.store.list_facts(), [])

    def test_as_of_still_returns_non_retainable_fact(self):
        self.memory.remember(
            "bank pin", "1234", sensitivity=SENSITIVITY_NON_RETAINABLE
        )
        valid_at = self.memory.fact_history("bank pin")[0]["valid_at"]
        # The filter hides the fact from live recall; it does not rewrite
        # history.
        old = self.memory.recall_as_of("bank pin", valid_at)
        self.assertIsNotNone(old)
        assert old is not None
        self.assertEqual(old.value, "1234")

    def test_sensitivity_preserved_when_not_mentioned(self):
        self.memory.remember(
            "bank pin", "1234", sensitivity=SENSITIVITY_NON_RETAINABLE
        )
        # A plain re-remember without sensitivity must not reset the tier.
        self.memory.remember("bank pin", "1234")
        facts = self.store.list_facts()
        self.assertEqual(facts[0]["sensitivity"], SENSITIVITY_NON_RETAINABLE)
        self.assertIsNone(self.memory.recall("bank pin"))

    def test_explicit_none_clears_tier_to_normal(self):
        self.memory.remember(
            "bank pin", "1234", sensitivity=SENSITIVITY_NON_RETAINABLE
        )
        self.assertIsNone(self.memory.recall("bank pin"))
        self.memory.remember("bank pin", "1234", sensitivity=None)
        self.assertEqual(self.store.list_facts()[0]["sensitivity"], "normal")
        match = self.memory.recall("bank pin")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.value, "1234")

    def test_explicit_tier_change_updates_in_place(self):
        self.memory.remember("note", "keep")
        self.assertEqual(len(self.memory.fact_history("note")), 1)
        self.memory.remember("note", "keep", sensitivity="sensitive")
        self.assertEqual(len(self.memory.fact_history("note")), 1)
        self.assertEqual(self.store.list_facts()[0]["sensitivity"], "sensitive")

    def test_sensitivity_only_update_opens_no_new_window(self):
        self.memory.remember("note", "keep")
        self.assertEqual(len(self.memory.fact_history("note")), 1)
        # Same content, only the tier changes: in-place refresh, no new
        # ledger version (supersession/consolidation untouched).
        self.memory.remember("note", "keep", sensitivity="non_retainable")
        self.assertEqual(len(self.memory.fact_history("note")), 1)
        self.assertEqual(
            self.store.list_facts()[0]["sensitivity"], "non_retainable"
        )
        self.assertIsNone(self.memory.recall("note"))

    def test_contradiction_keeps_explicit_tier(self):
        self.memory.remember("pin", "1111", sensitivity="non_retainable")
        # New value, same key: the versioned rewrite keeps the tier when
        # the caller does not mention one.
        self.memory.remember("pin", "2222")
        facts = self.store.list_facts()
        self.assertEqual(facts[0]["sensitivity"], "non_retainable")
        self.assertEqual(facts[0]["value"], "2222")
        self.assertIsNone(self.memory.recall("pin"))

    def test_supersession_merge_adopts_explicit_non_retainable(self):
        self.memory.remember("reply language", "Chinese", aliases=("lang",))
        # Near-duplicate key merges into the existing target; an explicit
        # non_retainable marker must survive the merge onto the target.
        self.memory.remember(
            "response language", "Chinese", sensitivity="non_retainable"
        )
        facts = self.store.list_facts()
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["key"], "reply language")
        self.assertEqual(facts[0]["sensitivity"], "non_retainable")
        self.assertIsNone(self.memory.recall("reply language"))

    def test_consolidate_skips_non_retainable(self):
        self.memory.remember(
            "card pin", "4321", aliases=("pin",),
            sensitivity="non_retainable",
        )
        self.memory.remember("door pin", "9999", aliases=("pin",))
        report = self.memory.consolidate()
        # A merge must not drag the marked fact back into cognition or
        # move its value under a normal key.
        merged = {entry["kept"] for entry in report["merged"]}
        self.assertNotIn("card pin", merged)
        self.assertNotIn("door pin", merged)
        self.assertIsNone(self.memory.recall("card pin"))
        match = self.memory.recall("door pin")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.value, "9999")

    def test_malformed_sensitivity_raises(self):
        with self.assertRaises(ValueError):
            self.memory.remember("k", "v", sensitivity="top-secret")
        with self.assertRaises(ValueError):
            self.memory.remember("k", "v", sensitivity=123)
        with self.assertRaises(ValueError):
            self.memory.remember("k", "v", sensitivity="  ")
        # Nothing was written by the failed calls.
        self.assertEqual(self.store.list_facts(), [])

    def test_tier_survives_restart(self):
        self.memory.remember(
            "bank pin", "1234", sensitivity=SENSITIVITY_NON_RETAINABLE
        )
        self.memory.remember("hotel name", "Hilton")
        self.store.close()
        reopened = KernelStore(self.root / "memory.db")
        try:
            memory = StructuredMemory(reopened)
            facts = reopened.list_facts()
            by_key = {fact["key"]: fact for fact in facts}
            self.assertEqual(
                by_key["bank pin"]["sensitivity"], SENSITIVITY_NON_RETAINABLE
            )
            self.assertEqual(by_key["hotel name"]["sensitivity"], "normal")
            # The filter still holds after restart.
            self.assertIsNone(memory.recall("bank pin"))
            match = memory.recall("hotel name")
            self.assertIsNotNone(match)
            assert match is not None
            self.assertEqual(match.value, "Hilton")
        finally:
            reopened.close()


class RememberManySensitivityTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def test_dict_items_carry_sensitivity(self):
        result = self.memory.remember_many([
            {"key": "pin", "value": "1234", "sensitivity": "non_retainable"},
            {"key": "hotel", "value": "Hilton", "sensitivity": "sensitive"},
            ("plain", "value"),
        ])
        self.assertEqual(result["written"], 3)
        by_key = {
            fact["key"]: fact for fact in self.store.list_facts()
        }
        self.assertEqual(by_key["pin"]["sensitivity"], "non_retainable")
        self.assertEqual(by_key["hotel"]["sensitivity"], "sensitive")
        self.assertEqual(by_key["plain"]["sensitivity"], "normal")
        self.assertIsNone(self.memory.recall("pin"))
        match = self.memory.recall("hotel")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.value, "Hilton")
        self.assertIsNotNone(self.memory.recall("plain"))

    def test_malformed_sensitivity_aborts_batch(self):
        with self.assertRaises(ValueError):
            self.memory.remember_many([
                {"key": "pin", "value": "1234", "sensitivity": "non_retainable"},
                {"key": "bad", "value": "x", "sensitivity": "classified-x"},
            ])
        # Malformed items raise before anything is written.
        self.assertEqual(self.store.list_facts(), [])


class StoreSensitivityTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)

    def test_put_fact_sensitivity_roundtrip(self):
        self.store.put_fact("k", "v", sensitivity="non_retainable")
        facts = self.store.list_facts()
        self.assertEqual(facts[0]["sensitivity"], "non_retainable")
        # Default (SENSITIVITY_UNSET) preserves the existing tier.
        self.store.put_fact("k", "v2")
        self.assertEqual(self.store.list_facts()[0]["sensitivity"], "non_retainable")
        # Explicit None resets it to normal.
        self.store.put_fact("k", "v3", sensitivity=None)
        self.assertEqual(self.store.list_facts()[0]["sensitivity"], "normal")
        self.assertEqual(self.store.get_fact("k"), "v3")

    def test_put_fact_rejects_bad_tier(self):
        with self.assertRaises(ValueError):
            self.store.put_fact("k", "v", sensitivity="classified")
        self.assertEqual(self.store.list_facts(), [])

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
            ("legacy", '"v"', "[]", "2000-01-01T00:00:00+00:00",
             "2000-01-01T00:00:00+00:00"),
        )
        conn.commit()
        conn.close()
        # Opening with the new code migrates the old database in place;
        # the tier backfills to "normal" (recall behaves as before).
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
            self.assertIn("sensitivity", columns)
            facts = store.list_facts()
            self.assertEqual(len(facts), 1)
            self.assertEqual(facts[0]["sensitivity"], "normal")
            memory = StructuredMemory(store)
            match = memory.recall("legacy")
            self.assertIsNotNone(match)
            assert match is not None
            self.assertEqual(match.value, "v")
        finally:
            store.close()


class RememberRpcSensitivityTests(unittest.TestCase):
    """The ``remember`` RPC accepts a ``sensitivity`` param; the
    ``memory_list`` RPC shows the marker without leaking the value."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.resident = build_resident_runtime(
            config={"model": {}}, store_path=self.root / "kernel.db"
        )
        self.addCleanup(lambda: self.resident.store.close())
        self.rpc = ResidentRpcServer(self.resident)

    def call(self, method, **params):
        response = self.rpc.handle(
            {"id": method, "method": method, "params": params}
        )
        self.assertTrue(response["ok"], response.get("error"))
        return response["result"]

    def call_raw(self, method, **params):
        return self.rpc.handle(
            {"id": method, "method": method, "params": params}
        )

    def test_remember_accepts_sensitivity_and_list_shows_it(self):
        result = self.call(
            "remember", key="bank pin", value="1234",
            sensitivity="non_retainable",
        )
        self.assertEqual(result["saved"], True)
        listed = self.call("memory_list")
        by_key = {item["key"]: item for item in listed}
        self.assertEqual(by_key["bank pin"]["sensitivity"], "non_retainable")
        self.assertNotIn("1234", str(listed))
        # ...yet explicit recall through memory stays filtered.
        self.assertIsNone(self.resident.memory.recall("bank pin"))

    def test_remember_without_sensitivity_defaults_to_normal(self):
        self.call("remember", key="hotel", value="Hilton")
        listed = self.call("memory_list")
        self.assertEqual(listed[0]["sensitivity"], "normal")

    def test_remember_rejects_bad_sensitivity(self):
        # Like the other remember-param validations (missing key,
        # non-list aliases), a bad tier raises out of handle.
        with self.assertRaises(ValueError):
            self.call_raw(
                "remember", key="k", value="v", sensitivity="classified"
            )
        self.assertEqual(self.resident.memory.store.list_facts(), [])

    def test_list_item_shape_includes_sensitivity(self):
        self.call("remember", key="k", value="v")
        listed = self.call("memory_list")
        self.assertEqual(len(listed), 1)
        self.assertEqual(
            set(listed[0]),
            {"key", "aliases", "updated_at", "tier", "sensitivity"},
        )


if __name__ == "__main__":
    unittest.main()
