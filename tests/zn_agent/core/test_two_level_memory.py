from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.memory import StructuredMemory
from zn_agent.core.store import KernelStore
from zn_agent.core.two_level_memory import (
    HOT_CAPACITY,
    TIER_DEEP,
    TIER_HOT,
    TwoLevelMemory,
    capture_nickname,
    forget_nickname,
    list_nicknames,
    resolve_nickname,
    resolve_reference,
)


class TwoLevelMemoryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-kwp2-"))
        self.store = KernelStore(self.root / "memory.db")
        self.memory = StructuredMemory(self.store)
        self.two = TwoLevelMemory(self.memory, hot_capacity=3, promote_after_hits=3)

    def tearDown(self):
        self.store.close()

    def test_new_facts_start_hot(self):
        self.two.remember("喜好", "茶")
        self.assertEqual(self.two.tier_of("喜好"), TIER_HOT)
        self.assertEqual(self.two.stats()["hot"], 1)

    def test_capacity_demotion_keeps_facts_recallable(self):
        for key in ("a", "b", "c", "d", "e"):
            self.two.remember(key, f"值-{key}")
        stats = self.two.stats()
        self.assertEqual(stats["hot"], 3)
        self.assertEqual(stats["deep"], 2)
        self.assertEqual(stats["total"], 5)
        # Demotion never deletes: every fact still recalls.
        for key in ("a", "b", "c", "d", "e"):
            match = self.two.recall(key)
            self.assertIsNotNone(match, key)
            self.assertEqual(match.value, f"值-{key}")

    def test_decode_table_indexes_deep_facts(self):
        self.two.remember("项目计划", "x" * 500, aliases=("计划",))
        self.two.demote("项目计划")
        table = self.two.decode_table()
        self.assertEqual(len(table), 1)
        row = table[0]
        self.assertEqual(row["key"], "项目计划")
        self.assertIn("计划", row["aliases"])
        self.assertTrue(row["summary"])
        self.assertLessEqual(len(row["summary"]), 200)
        self.assertTrue(row["demoted_at"])

    def test_demote_promote_round_trip(self):
        self.two.remember("k", "v")
        self.assertTrue(self.two.demote("k"))
        self.assertEqual(self.two.tier_of("k"), TIER_DEEP)
        self.assertIn("k", self.two.deep_keys())
        self.assertTrue(self.two.promote("k"))
        self.assertEqual(self.two.tier_of("k"), TIER_HOT)
        self.assertEqual(self.two.deep_keys(), [])

    def test_demote_promote_missing_key(self):
        self.assertFalse(self.two.demote("不存在"))
        self.assertFalse(self.two.promote("不存在"))
        self.assertIsNone(self.two.tier_of("不存在"))

    def test_coldest_demoted_first(self):
        small = TwoLevelMemory(self.memory, hot_capacity=2, promote_after_hits=3)
        small.remember("a", 1)
        small.remember("b", 2)
        small.recall("a")  # a has 1 hit; b has 0 -> b is colder.
        small.remember("c", 3)
        self.assertEqual(small.tier_of("b"), TIER_DEEP)
        self.assertEqual(small.tier_of("a"), TIER_HOT)
        self.assertEqual(small.tier_of("c"), TIER_HOT)

    def test_auto_promotion_boundary(self):
        self.two.remember("常用", "v")
        self.two.demote("常用")
        # Below threshold: 1 and 2 hits keep it deep.
        self.two.recall("常用")
        self.assertEqual(self.two.tier_of("常用"), TIER_DEEP)
        self.two.recall("常用")
        self.assertEqual(self.two.tier_of("常用"), TIER_DEEP)
        # At threshold (3rd hit): promoted.
        self.two.recall("常用")
        self.assertEqual(self.two.tier_of("常用"), TIER_HOT)

    def test_recall_deep_promotes_at_threshold(self):
        quick = TwoLevelMemory(self.memory, hot_capacity=10, promote_after_hits=1)
        quick.remember("深存", "v")
        quick.demote("深存")
        self.assertEqual(quick.recall_deep("深存"), "v")
        self.assertEqual(quick.tier_of("深存"), TIER_HOT)
        self.assertIsNone(quick.recall_deep("不存在"))

    def test_relevant_context_counts_as_hit(self):
        quick = TwoLevelMemory(self.memory, hot_capacity=10, promote_after_hits=1)
        quick.remember("项目计划", "下周上线")
        quick.demote("项目计划")
        items = quick.relevant_context("项目计划")
        self.assertTrue(any(item["key"] == "项目计划" for item in items))
        self.assertEqual(quick.tier_of("项目计划"), TIER_HOT)

    def test_promotion_evicts_coldest_not_itself(self):
        small = TwoLevelMemory(self.memory, hot_capacity=2, promote_after_hits=1)
        small.remember("a", 1)
        small.remember("b", 2)
        small.recall("a")  # a has 1 hit; b has 0 -> b is colder.
        small.remember("c", 3)  # demotes b; hot = {a, c}, deep = {b}.
        self.assertEqual(small.tier_of("b"), TIER_DEEP)
        # Promoting b when hot is full must evict the coldest *other* fact
        # (c, 0 hits), never the just-promoted b.
        small.promote("b")
        self.assertEqual(small.tier_of("b"), TIER_HOT)
        self.assertEqual(small.tier_of("c"), TIER_DEEP)
        self.assertEqual(len(small.hot_keys()), 2)

    def test_forget_drops_tier_row(self):
        self.two.remember("k", "v")
        self.two.demote("k")
        self.two.forget("k")
        self.assertIsNone(self.two.tier_of("k"))
        self.assertEqual(self.two.decode_table(), [])

    def test_legacy_facts_count_as_hot(self):
        self.memory.remember("旧事实", "写在 KWP-2 之前")
        self.assertEqual(self.two.tier_of("旧事实"), TIER_HOT)
        self.assertIn("旧事实", self.two.hot_keys())

    def test_rebalance(self):
        self.two.remember("a", 1)
        self.two.remember("b", 2)
        self.two.remember("c", 3)
        self.two.demote("a")
        # Forcing over-capacity by hand is impossible via the adapter, so
        # rebalance is a no-op here but must not error or move anything.
        self.assertEqual(self.two.rebalance(), [])
        self.assertEqual(self.two.tier_of("a"), TIER_DEEP)

    def test_default_capacity_is_about_100(self):
        self.assertEqual(HOT_CAPACITY, 100)


class NicknameTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-kwp2-nick-"))
        self.store = KernelStore(self.root / "memory.db")
        self.memory = StructuredMemory(self.store)

    def tearDown(self):
        self.store.close()

    def test_capture_and_resolve(self):
        self.assertTrue(capture_nickname(self.memory, "阿豪", "用户", source="对话"))
        self.assertEqual(resolve_nickname(self.memory, "阿豪"), "用户")

    def test_recapture_updates_canonical(self):
        capture_nickname(self.memory, "蛋蛋", "ZN")
        capture_nickname(self.memory, "蛋蛋", "诸葛蛋蛋")
        self.assertEqual(resolve_nickname(self.memory, "蛋蛋"), "诸葛蛋蛋")

    def test_unknown_nickname_is_none(self):
        self.assertIsNone(resolve_nickname(self.memory, "没见过"))

    def test_bad_input_rejected(self):
        self.assertFalse(capture_nickname(self.memory, "", "用户"))
        self.assertFalse(capture_nickname(self.memory, "阿豪", ""))
        self.assertFalse(capture_nickname(self.memory, "  ", "用户"))

    def test_list_and_forget(self):
        capture_nickname(self.memory, "阿豪", "用户")
        capture_nickname(self.memory, "老李", "李工")
        self.assertEqual(
            list_nicknames(self.memory), {"老李": "李工", "阿豪": "用户"}
        )
        self.assertTrue(forget_nickname(self.memory, "老李"))
        self.assertIsNone(resolve_nickname(self.memory, "老李"))
        self.assertFalse(forget_nickname(self.memory, "老李"))

    def test_nickname_is_an_ordinary_fact(self):
        capture_nickname(self.memory, "阿豪", "用户")
        keys = [f["key"] for f in self.store.list_facts()]
        self.assertIn("nickname:阿豪", keys)

    def test_resolve_reference_rewrites_nicknames(self):
        capture_nickname(self.memory, "阿豪", "用户")
        capture_nickname(self.memory, "阿豪哥", "用户本人")
        # Longest nickname wins: 阿豪哥 -> 用户本人, not 用户 + 哥.
        self.assertEqual(
            resolve_reference(self.memory, "阿豪哥说明天开会"),
            "用户本人说明天开会",
        )
        self.assertEqual(
            resolve_reference(self.memory, "阿豪说明天开会"),
            "用户说明天开会",
        )
        self.assertEqual(resolve_reference(self.memory, ""), "")

    def test_resolve_reference_ignores_unknown_text(self):
        capture_nickname(self.memory, "阿豪", "用户")
        self.assertEqual(resolve_reference(self.memory, "今天天气不错"), "今天天气不错")


if __name__ == "__main__":
    unittest.main()
