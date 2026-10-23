"""PERF-3 regression locks: recall_hybrid N+1 optimizations must not change
recall semantics.

- ``_open_window_rows`` (batch) == per-key ``_open_window_row`` results.
- ``_hybrid_entity_score`` with query-local memo == without memo.
- ``recall_hybrid`` ranking/shapes are deterministic across calls
  (modulo the time-based recency tie-breaker).
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.memory import (
    StructuredMemory,
    _hybrid_entity_score,
)
from zn_agent.core.store import KernelStore


class Perf3RecallHybridEquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def _shape(self, results):
        """recall_hybrid result with the time-based fields stripped.

        ``score`` carries the recency term, so it can drift a hair
        between two live calls; ranking + signals are the stable
        semantics we lock here.
        """
        shaped = []
        for rec in results:
            signals = dict(rec["signals"])
            signals.pop("recency", None)
            shaped.append({
                "key": rec["key"],
                "value": rec["value"],
                "signals": signals,
                "matched_by": rec["matched_by"],
                "id": rec["id"],
                "linked_memory_ids": list(rec["linked_memory_ids"]),
            })
        return shaped

    def test_open_window_rows_matches_single_row(self):
        self.memory.remember("阿豪的电话", "分机 8001", aliases=("阿豪",))
        self.memory.remember("阿豪的电话", "分机 8002", aliases=("阿豪",))
        self.memory.remember("公司电话", "前台总机")
        keys = ["阿豪的电话", "公司电话", "从没出现过的key"]
        batch = self.memory._open_window_rows(keys)
        for key in keys:
            self.assertEqual(
                batch[key], self.memory._open_window_row(key),
                f"batch row for {key!r} must equal single-key row",
            )
        # The versioned key reports the open (latest) window.
        self.assertIsNotNone(batch["阿豪的电话"])
        self.assertEqual(batch["从没出现过的key"], None)

    def test_entity_score_memo_equivalence(self):
        cases = [
            ("阿豪", ["阿豪", "电话"], "阿豪的电话", ("阿豪", "公司总机")),
            ("meeting", ["meeting"], "项目例会", ("周会", "meeting room")),
            ("xyz", ["xyz"], "无关事实", ("别名",)),
        ]
        for query_norm, query_tokens, key, aliases in cases:
            plain = _hybrid_entity_score(query_norm, query_tokens, key, aliases)
            memoed = _hybrid_entity_score(
                query_norm, query_tokens, key, aliases,
                _token_memo={}, _norm_memo={},
            )
            self.assertEqual(plain, memoed)
        # Shared memo dicts across many candidates stay consistent. Use
        # names that miss both early returns (no exact match, no CJK
        # mention) so the token path (and the memo) is actually
        # exercised.
        token_memo: dict = {}
        norm_memo: dict = {}
        cold_cases = [
            (["季度", "报告"], "项目例会", ("周会",)),
            (["server", "status"], "数据库备份", ("db", "backup")),
        ]
        for query_tokens, key, aliases in cold_cases:
            first = _hybrid_entity_score(
                "季度报告", query_tokens, key, aliases,
                _token_memo=token_memo, _norm_memo=norm_memo,
            )
            second = _hybrid_entity_score(
                "季度报告", query_tokens, key, aliases,
                _token_memo=token_memo, _norm_memo=norm_memo,
            )
            self.assertEqual(first, second)
            self.assertTrue(token_memo, "token memo should be populated")
            self.assertTrue(norm_memo, "norm memo should be populated")

    def test_recall_hybrid_ranking_stable(self):
        facts = [
            ("阿豪的电话", "分机 8001", ("阿豪",)),
            ("公司电话", "阿豪 经常打这个电话", ()),
            ("server config", "the backup window is 2am daily", ()),
            ("会议纪要", "周三例会讨论发布计划", ("例会",)),
        ]
        for key, value, aliases in facts:
            self.memory.remember(key, value, aliases=aliases)
        for query in ["阿豪", "backup window", "例会"]:
            first = self._shape(self.memory.recall_hybrid(query, max_facts=10))
            second = self._shape(self.memory.recall_hybrid(query, max_facts=10))
            self.assertEqual(
                [r["key"] for r in first], [r["key"] for r in second],
                f"ranking for {query!r} must be deterministic",
            )
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
