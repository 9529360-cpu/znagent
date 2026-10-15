from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.memory import StructuredMemory
from zn_agent.core.models import utc_now
from zn_agent.core.store import KernelStore


class HybridRetrievalTests(unittest.TestCase):
    """M0-4 (hybrid retrieval): BM25 keyword + entity weighting +
    exact + recency fusion, on top of GR-1/GR-2 validity (no second
    supersession mechanism, no vector side, no Qdrant)."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def test_entity_alias_beats_keyword_only(self):
        self.memory.remember("阿豪的电话", "分机 8001", aliases=("阿豪",))
        self.memory.remember("公司电话", "阿豪 经常打这个电话")
        results = self.memory.recall_hybrid("阿豪")
        self.assertEqual([r["key"] for r in results], ["阿豪的电话", "公司电话"])
        self.assertEqual(results[0]["matched_by"], "阿豪")
        self.assertEqual(results[0]["signals"]["entity"], 1.0)
        self.assertEqual(results[1]["signals"]["entity"], 0.0)
        self.assertGreater(results[0]["score"], results[1]["score"])

    def test_keyword_value_match_surfaces_what_exact_recall_misses(self):
        self.memory.remember("server config", "the backup window is 2am daily")
        self.assertIsNone(self.memory.recall("backup window"))
        results = self.memory.recall_hybrid("backup window")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["key"], "server config")
        self.assertEqual(results[0]["matched_by"], "keyword")
        self.assertEqual(results[0]["signals"]["keyword"], 1.0)
        self.assertEqual(results[0]["signals"]["entity"], 0.0)

    def test_exact_key_beats_partial_keyword(self):
        self.memory.remember("project", "alpha work")
        self.memory.remember("project alpha", "beta work")
        results = self.memory.recall_hybrid("project")
        self.assertEqual(results[0]["key"], "project")
        self.assertEqual(results[0]["signals"]["exact"], 1.0)
        self.assertEqual(results[0]["matched_by"], "key")

    def test_current_only_returns_latest_version_once(self):
        self.memory.remember("x", "one")
        self.memory.remember("x", "two")
        results = self.memory.recall_hybrid("x")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["value"], "two")
        self.assertIsNone(results[0]["invalid_at"])
        self.assertNotEqual(results[0]["linked_memory_ids"], ())

    def test_as_of_returns_superseded_version(self):
        self.memory.remember("x", "one")
        old_valid_at = self.memory.fact_history("x")[0]["valid_at"]
        self.memory.remember("x", "two")
        current = self.memory.recall_hybrid("x")
        self.assertEqual(current[0]["value"], "two")
        historical = self.memory.recall_hybrid("x", as_of=old_valid_at)
        self.assertEqual(len(historical), 1)
        self.assertEqual(historical[0]["value"], "one")

    def test_forget_removes_from_current_but_as_of_keeps_history(self):
        self.memory.remember("k", "v")
        valid_at = self.memory.fact_history("k")[0]["valid_at"]
        self.memory.forget("k")
        self.assertEqual(self.memory.recall_hybrid("k"), [])
        historical = self.memory.recall_hybrid("k", as_of=valid_at)
        self.assertEqual(len(historical), 1)
        self.assertEqual(historical[0]["value"], "v")

    def test_old_recall_and_relevant_context_unchanged(self):
        self.memory.remember("server config", "the backup window is 2am daily")
        # Exact recall stays exact-only: no value-text match.
        self.assertIsNone(self.memory.recall("backup window"))
        match = self.memory.recall("server config")
        assert match is not None
        self.assertEqual(match.value, "the backup window is 2am daily")
        # Cognition context stays key/alias-only: value keywords never leak in.
        self.assertEqual(self.memory.relevant_context("backup window"), [])
        self.assertEqual(
            [item["key"] for item in self.memory.relevant_context("server config")],
            ["server config"],
        )

    def test_entity_mention_in_longer_query(self):
        self.memory.remember("favorite restaurant", "川菜", aliases=("老地方",))
        self.memory.remember("notes", "老地方 附近停车难")
        results = self.memory.recall_hybrid("老地方在哪")
        self.assertEqual(results[0]["key"], "favorite restaurant")
        self.assertEqual(results[0]["signals"]["entity"], 1.0)
        self.assertEqual(results[1]["key"], "notes")
        self.assertEqual(results[1]["signals"]["entity"], 0.0)

    def test_fusion_breakdown_sums_to_score(self):
        self.memory.remember("server config", "the backup window is 2am daily")
        result = self.memory.recall_hybrid("backup window")[0]
        self.assertEqual(
            set(result["signals"]), {"keyword", "entity", "exact", "recency"}
        )
        for value in result["signals"].values():
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)
        expected = (
            0.45 * result["signals"]["keyword"]
            + 0.35 * result["signals"]["entity"]
            + 0.15 * result["signals"]["exact"]
            + 0.05 * result["signals"]["recency"]
        )
        self.assertAlmostEqual(result["score"], expected)

    def test_empty_query_and_max_facts_cap(self):
        self.assertEqual(self.memory.recall_hybrid(""), [])
        self.assertEqual(self.memory.recall_hybrid("   "), [])
        for name, value in (
            ("common one", "value one"),
            ("common two", "value two"),
            ("common three", "value three"),
        ):
            self.memory.remember(name, value)
        self.assertEqual(len(self.memory.recall_hybrid("common")), 3)
        self.assertEqual(len(self.memory.recall_hybrid("common", max_facts=2)), 2)
        self.assertEqual(self.memory.recall_hybrid("common", max_facts=0), [])

    def test_deterministic_repeat_order(self):
        self.memory.remember("阿豪的电话", "分机 8001", aliases=("阿豪",))
        self.memory.remember("公司电话", "阿豪 经常打这个电话")
        self.memory.remember("server config", "the backup window is 2am daily")
        first = self.memory.recall_hybrid("阿豪 电话 backup")
        second = self.memory.recall_hybrid("阿豪 电话 backup")
        self.assertEqual(
            [r["key"] for r in first], [r["key"] for r in second]
        )
        # Scores use a now()-based recency tie-breaker, so they agree
        # to microseconds, not bit-for-bit, across two calls.
        for a, b in zip(first, second):
            self.assertAlmostEqual(a["score"], b["score"], places=6)

    def test_as_of_legacy_row_without_ledger(self):
        self.store.put_fact("legacy key", "legacy value")
        current = self.memory.recall_hybrid("legacy key")
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["value"], "legacy value")
        self.assertIsNone(current[0]["id"])
        historical = self.memory.recall_hybrid("legacy key", as_of=utc_now())
        self.assertEqual(len(historical), 1)
        self.assertEqual(historical[0]["value"], "legacy value")

    def test_no_match_returns_empty(self):
        self.memory.remember("server config", "the backup window is 2am daily")
        self.assertEqual(self.memory.recall_hybrid("zzzqqq"), [])


if __name__ == "__main__":
    unittest.main()
