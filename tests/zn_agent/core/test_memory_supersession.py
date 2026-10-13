from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.memory import StructuredMemory, _bigrams, _jaccard
from zn_agent.core.store import KernelStore


class JaccardTests(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(_jaccard(_bigrams("hello world"), _bigrams("hello world")), 1.0)

    def test_disjoint(self):
        self.assertEqual(_jaccard(_bigrams("aaaa"), _bigrams("bbbb")), 0.0)

    def test_empty(self):
        self.assertEqual(_jaccard(set(), set()), 1.0)
        self.assertEqual(_jaccard({"a"}, set()), 0.0)

    def test_chinese_similar(self):
        # Bigram similarity works without word segmentation.
        score = _jaccard(_bigrams("回复语言中文"), _bigrams("回复语言中文的"))
        self.assertGreater(score, 0.7)


class SupersessionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def test_similar_content_supersedes(self):
        self.memory.remember("reply language", "Chinese", aliases=("lang",))
        # Different key, highly similar content -> updates the old key.
        self.memory.remember("response language", "Chinese")
        facts = self.store.list_facts()
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["key"], "reply language")
        self.assertEqual(facts[0]["value"], "Chinese")
        # Aliases are unioned.
        self.assertIn("lang", facts[0]["aliases"])

    def test_dissimilar_content_creates_new(self):
        self.memory.remember("reply language", "Chinese")
        self.memory.remember("favorite color", "blue")
        self.assertEqual(len(self.store.list_facts()), 2)

    def test_exact_key_overwrite_unchanged(self):
        self.memory.remember("k", "v1")
        self.memory.remember("k", "v2")
        facts = self.store.list_facts()
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["value"], "v2")

    def test_different_values_not_merged(self):
        self.memory.remember("reply language", "Chinese")
        self.memory.remember("response language", "English")
        self.assertEqual(len(self.store.list_facts()), 2)

    def test_superseded_key_kept_as_alias(self):
        self.memory.remember("reply language", "Chinese")
        self.memory.remember("response language", "Chinese")
        facts = self.store.list_facts()
        self.assertEqual(len(facts), 1)
        self.assertIn("response language", facts[0]["aliases"])

    def test_chinese_near_duplicate(self):
        self.memory.remember("回复语言", "中文")
        self.memory.remember("回答语言", "中文")
        facts = self.store.list_facts()
        self.assertEqual(len(facts), 1)


if __name__ == "__main__":
    unittest.main()
