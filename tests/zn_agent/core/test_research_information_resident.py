from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.models import ModelRoute, WorkerResult
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.research_information_work import source_identity
from zn_agent.core.web_resource import FailoverWebResource, WebDocument, WebResourceError, WebSearchItem


class _FailingResource:
    def __init__(self, name: str):
        self.name = name
        self.search_calls = 0
        self.extract_calls = 0

    def search(self, query: str, *, limit: int = 5):
        self.search_calls += 1
        raise WebResourceError(f"{self.name} search unavailable")

    def extract(self, urls: list[str]):
        self.extract_calls += 1
        raise WebResourceError(f"{self.name} extract unavailable")


class _GoodResource:
    name = "secondary"

    def __init__(self):
        self.search_calls = 0
        self.extract_calls = 0

    def search(self, query: str, *, limit: int = 5):
        self.search_calls += 1
        return [
            WebSearchItem(title="A", url="https://a.example/research", position=1, metadata={"published_date": "2026-09-10"}),
            WebSearchItem(title="B", url="https://b.example/research", position=2),
        ]

    def extract(self, urls: list[str]):
        self.extract_calls += 1
        content = {
            "https://a.example/research": "Observed Alpha adoption is expanding.",
            "https://b.example/research": "Independent Alpha coverage emphasizes deployment tradeoffs.",
        }
        return [
            WebDocument(url=url, title=url, content=content[url], metadata={"requestedURL": url, "sourceURL": url})
            for url in urls
        ]


class _Worker:
    def __init__(self, factory):
        self.factory = factory

    def run(self, goal, kernel_context):
        if not self.factory.responses:
            return WorkerResult(success=False, response="", verification_passed=False, error="fixture response queue exhausted", metrics={"model_invoked": True})
        self.factory.calls += 1
        return WorkerResult(success=True, response=self.factory.responses.pop(0), verification_passed=True, metrics={"model_invoked": True})


class _Factory:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def create(self, route):
        return _Worker(self)


def _configure_model(resident, responses):
    factory = _Factory(responses)
    resident.kernel.reconfigure_resources(
        routes=[ModelRoute(route_id="fixture", provider="fixture", model="fixture", capabilities={"general": 1.0, "research": 1.0})],
        worker_factory=factory,
        max_attempts=1,
        resource_status={"available": True, "error": None},
    )
    return factory


class ResearchInformationResidentTests(unittest.TestCase):
    def _responses(self):
        first = source_identity("https://a.example/research")
        second = source_identity("https://b.example/research")
        plan = json.dumps({"research_plan": {"subject": "Alpha", "queries": ["Alpha current research"]}})
        synthesis = json.dumps(
            {
                "research_synthesis": {
                    "claims": [
                        {"text": "Observed Alpha adoption is expanding.", "supports": [{"source_id": first, "quote": "Observed Alpha adoption is expanding."}]},
                        {"text": "Independent coverage emphasizes deployment tradeoffs.", "supports": [{"source_id": second, "quote": "Independent Alpha coverage emphasizes deployment tradeoffs."}]},
                    ],
                    "conflicts": [],
                    "recommendation": None,
                    "unknowns": [],
                    "follow_up_queries": [],
                }
            }
        )
        return plan, synthesis

    def test_existing_web_failover_is_used_by_research_without_new_provider_router(self) -> None:
        first = _FailingResource("primary")
        second = _GoodResource()
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(config={"model": {}}, store_path=Path(tmp) / "kernel.db")
            plan, synthesis = self._responses()
            _configure_model(resident, [plan, synthesis])
            resident.configure_research_web_resource(FailoverWebResource([first, second]))
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="failover", title="Failover")
                snapshot, run = ledger.submit("failover", "帮我研究 Alpha 当前情况，别只看一个来源。")
                self.assertTrue(run.success, run.response)
                self.assertEqual(first.search_calls, 1)
                self.assertEqual(second.search_calls, 1)
                self.assertEqual(first.extract_calls, 1)
                self.assertEqual(second.extract_calls, 1)
                self.assertIn(source_identity("https://a.example/research"), run.response)
                self.assertIn(source_identity("https://b.example/research"), run.response)
            finally:
                resident.store.close()

    def test_all_web_resources_unavailable_blocks_instead_of_model_answer_fallback(self) -> None:
        first = _FailingResource("primary")
        second = _FailingResource("secondary")
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(config={"model": {}}, store_path=Path(tmp) / "kernel.db")
            plan, synthesis = self._responses()
            factory = _configure_model(resident, [plan, synthesis])
            resident.configure_research_web_resource(FailoverWebResource([first, second]))
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="all-down", title="Blocked")
                snapshot, run = ledger.submit("all-down", "帮我研究 Alpha 当前情况，别只看一个来源。")
                self.assertFalse(run.success)
                self.assertIn("无法获得足够的当前来源", run.response)
                self.assertEqual(first.search_calls, 1)
                self.assertEqual(second.search_calls, 1)
                self.assertEqual(factory.calls, 1, "model synthesis must not run after source acquisition failed")
                self.assertEqual(len(factory.responses), 1, "the unused synthesis response proves no model-knowledge fallback occurred")
            finally:
                resident.store.close()

    def test_no_model_is_a_cognition_blocker_not_a_search_snippet_summary(self) -> None:
        resource = _GoodResource()
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(config={"model": {}}, store_path=Path(tmp) / "kernel.db")
            resident.configure_research_web_resource(resource)
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="no-model", title="No model")
                snapshot, run = ledger.submit("no-model", "帮我研究 Alpha 当前情况，别只看一个来源。")
                self.assertFalse(run.success)
                self.assertIn("research cognition blocker", run.response)
                self.assertEqual(resource.search_calls, 0, "explicit research planning needs cognition; ZN must not invent a query or summarize snippets")
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
