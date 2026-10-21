from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.memory import (
    StructuredMemory,
    _SEMANTIC_PLURAL_TO_SINGULAR,
    _SEMANTIC_SYNONYM_SETS,
    _semantic_expand,
    _semantic_score,
)
from zn_agent.core.store import KernelStore

PAST = "2000-01-01T00:00:00+00:00"


class SemanticFallbackTests(unittest.TestCase):
    """Q8: lightweight semantic fallback for recall_hybrid.

    A deterministic, locally-computed synonym / cross-language /
    word-form expansion rescues candidates the BM25+entity+exact
    signals dropped. No vector side, no network, no schema change.
    The fallback only appends AFTER primary hits; when it finds
    nothing, results are identical to the pre-Q8 behaviour.
    """

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def test_synonym_query_recalls_fact(self):
        # Before Q8: recall_hybrid("手机") -> [] (verified on origin/main).
        self.memory.remember("电话号码", "138-0000-0000")
        for query in ("手机", "phone", "telephone"):
            with self.subTest(query=query):
                results = self.memory.recall_hybrid(query)
                self.assertEqual([r["key"] for r in results], ["电话号码"])
                self.assertEqual(results[0]["matched_by"], "semantic")
                self.assertGreater(results[0]["signals"]["semantic"], 0.0)
                self.assertEqual(results[0]["signals"]["keyword"], 0.0)
                self.assertEqual(results[0]["signals"]["entity"], 0.0)
                self.assertEqual(results[0]["signals"]["exact"], 0.0)

    def test_plural_form_recalls_fact(self):
        # Deterministic word-form normalisation, no stemmer.
        self.memory.remember("email address", "a@example.com")
        results = self.memory.recall_hybrid("emails")
        self.assertEqual([r["key"] for r in results], ["email address"])
        self.assertEqual(results[0]["matched_by"], "semantic")

    def test_rescued_ranks_after_primary_hits(self):
        self.memory.remember("server config", "the backup window is 2am daily")
        self.memory.remember("电话号码", "138-0000-0000")
        results = self.memory.recall_hybrid("backup window 手机")
        self.assertEqual(
            [r["key"] for r in results], ["server config", "电话号码"]
        )
        self.assertEqual(results[0]["matched_by"], "keyword")
        self.assertEqual(results[1]["matched_by"], "semantic")
        self.assertGreater(results[0]["score"], results[1]["score"])

    def test_rescued_signals_breakdown_sums_to_score(self):
        self.memory.remember("电话号码", "138-0000-0000")
        result = self.memory.recall_hybrid("手机")[0]
        self.assertEqual(
            set(result["signals"]),
            {"keyword", "entity", "exact", "recency", "semantic"},
        )
        expected = (
            0.10 * result["signals"]["semantic"]
            + 0.05 * result["signals"]["recency"]
        )
        self.assertAlmostEqual(result["score"], expected)

    def test_no_semantic_hit_behavior_identical(self):
        # Contract: when the fallback finds nothing, every result keeps
        # the legacy 4-key signals, the legacy score formula, and the
        # legacy matched_by values -- i.e. pre-Q8 behaviour, pinned.
        self.memory.remember("server config", "the backup window is 2am daily")
        self.memory.remember("project", "alpha work")
        for query in ("backup window", "project", "server"):
            with self.subTest(query=query):
                results = self.memory.recall_hybrid(query)
                self.assertTrue(results)
                for result in results:
                    self.assertEqual(
                        set(result["signals"]),
                        {"keyword", "entity", "exact", "recency"},
                    )
                    self.assertNotEqual(result["matched_by"], "semantic")
                    expected = (
                        0.45 * result["signals"]["keyword"]
                        + 0.35 * result["signals"]["entity"]
                        + 0.15 * result["signals"]["exact"]
                        + 0.05 * result["signals"]["recency"]
                    )
                    self.assertAlmostEqual(result["score"], expected)
        self.assertEqual(self.memory.recall_hybrid("zzzqqq"), [])

    def test_max_facts_cap_covers_rescued_candidates(self):
        self.memory.remember("common one", "value one")
        self.memory.remember("common two", "value two")
        self.memory.remember("common three", "value three")
        self.memory.remember("电话号码", "138-0000-0000")
        capped = self.memory.recall_hybrid("common 手机", max_facts=3)
        self.assertEqual(len(capped), 3)
        self.assertNotIn("电话号码", [r["key"] for r in capped])
        full = self.memory.recall_hybrid("common 手机")
        self.assertEqual(full[-1]["key"], "电话号码")
        self.assertEqual(full[-1]["matched_by"], "semantic")

    def test_supersession_hides_old_version_from_fallback(self):
        self.memory.remember("电话号码", "111")
        self.memory.remember("电话号码", "222")
        results = self.memory.recall_hybrid("手机")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["value"], "222")

    def test_forget_opt_out_hides_from_fallback(self):
        self.memory.remember("电话号码", "138-0000-0000")
        self.assertTrue(self.memory.recall_hybrid("手机"))
        self.memory.forget("电话号码")
        self.assertEqual(self.memory.recall_hybrid("手机"), [])

    def test_expired_fact_not_rescued(self):
        self.memory.remember("电话号码", "138-0000-0000", expires_at=PAST)
        self.assertEqual(self.memory.recall_hybrid("手机"), [])

    def test_as_of_mode_still_works_with_fallback(self):
        self.memory.remember("电话号码", "111")
        old_valid_at = self.memory.fact_history("电话号码")[0]["valid_at"]
        self.memory.remember("电话号码", "222")
        historical = self.memory.recall_hybrid("手机", as_of=old_valid_at)
        self.assertEqual(len(historical), 1)
        self.assertEqual(historical[0]["value"], "111")

    def test_empty_query_returns_empty(self):
        self.memory.remember("电话号码", "138-0000-0000")
        self.assertEqual(self.memory.recall_hybrid(""), [])
        self.assertEqual(self.memory.recall_hybrid("   "), [])

    def test_synonym_sets_disjoint(self):
        seen: dict[str, int] = {}
        for index, group in enumerate(_SEMANTIC_SYNONYM_SETS):
            for token in group:
                self.assertNotIn(
                    token, seen,
                    f"token {token!r} in two synonym sets",
                )
                seen[token] = index

    def test_expand_is_additive_and_deterministic(self):
        tokens = ["手机", "emails", "zzzqqq"]
        first = _semantic_expand(tokens)
        second = _semantic_expand(tokens)
        self.assertEqual(first, second)
        self.assertTrue(set(tokens) <= first)
        self.assertIn("电话", first)
        self.assertIn("phone", first)
        self.assertIn("email", first)

    def test_semantic_score_zero_without_overlap(self):
        self.assertEqual(_semantic_score(["zzzqqq"], ["电话号码"]), 0.0)
        self.assertEqual(_semantic_score([], ["电话号码"]), 0.0)
        score = _semantic_score(["手机"], ["电话号码"])
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_plural_map_has_no_broken_stems(self):
        for plural, singular in _SEMANTIC_PLURAL_TO_SINGULAR.items():
            self.assertTrue(
                plural in (singular + "s", singular + "es")
                or (plural, singular) == ("children", "child"),
                f"suspicious pair {plural!r} -> {singular!r}",
            )


if __name__ == "__main__":
    unittest.main()
