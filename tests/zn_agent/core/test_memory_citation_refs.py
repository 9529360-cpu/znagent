from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.memory import (
    StructuredMemory,
    extract_cited_refs,
    valid_cited_refs,
)
from zn_agent.core.models import AgentEvent, CognitionRequest
from zn_agent.core.store import KernelStore


class CitationRefTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def context(self, task):
        event = AgentEvent("event", task, payload={})
        request = CognitionRequest("request", "impasse", event.event_id, task)
        return self.memory.bind_cognition_context(event, request).context.get(
            "resident_memory"
        )

    def test_facts_get_stable_numbered_refs(self):
        self.memory.remember("project", "ZN Agent", aliases=("active project",))
        self.memory.remember("deadline", "Friday", aliases=("due date",))
        bundle = self.context("update the active project before the due date")
        self.assertIsNotNone(bundle)
        assert bundle is not None
        refs = [fact["ref"] for fact in bundle["facts"]]
        self.assertEqual(refs, ["\u30101\u3011", "\u30102\u3011"])
        self.assertEqual(bundle["ref_count"], 2)

    def test_refs_assigned_after_truncation(self):
        self.memory.remember("alpha", "x" * 3000, aliases=("alpha",))
        self.memory.remember("beta", "short", aliases=("beta",))
        bundle = self.context("alpha and beta")
        assert bundle is not None
        for index, fact in enumerate(bundle["facts"], start=1):
            self.assertEqual(fact["ref"], f"\u3010{index}\u3011")

    def test_no_facts_no_refs(self):
        self.assertIsNone(self.context("what is the weather today"))

    def test_interpretation_mentions_citation(self):
        self.memory.remember("project", "ZN Agent", aliases=("active project",))
        bundle = self.context("update the active project")
        assert bundle is not None
        self.assertIn("\u30101\u3011", bundle["interpretation"])
        self.assertIn("Never invent a ref", bundle["interpretation"])


class CitedRefExtractionTests(unittest.TestCase):
    def test_extract_in_order_deduped(self):
        self.assertEqual(
            extract_cited_refs("See \u30102\u3011 and \u30101\u3011, also \u30102\u3011 again."),
            [2, 1],
        )

    def test_no_citations(self):
        self.assertEqual(extract_cited_refs("plain text"), [])

    def test_zero_ignored(self):
        self.assertEqual(extract_cited_refs("\u30100\u3011"), [])

    def test_valid_drops_out_of_range(self):
        self.assertEqual(valid_cited_refs("used \u30101\u3011 and \u30105\u3011", 2), [1])

    def test_valid_keeps_all_in_range(self):
        self.assertEqual(valid_cited_refs("\u30103\u3011\u30101\u3011\u30102\u3011", 3), [3, 1, 2])


if __name__ == "__main__":
    unittest.main()
