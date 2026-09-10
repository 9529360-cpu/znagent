from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from zn_agent.core.models import ModelRoute, WorkerResult
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.research_information_work import source_identity
from zn_agent.core.web_resource import WebDocument, WebSearchItem


class _Handler(BaseHTTPRequestHandler):
    pages = {
        "/official": "Alpha One current list price is $99. Alpha One emphasizes battery life. Beta Two current list price is $129.",
        "/review": "Alpha One price observed is $99. Review testing says Beta Two emphasizes portability.",
        "/retailer": "Alpha One listed price is $119. Retailer listing says Beta Two current price is $129.",
    }

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        body = self.pages.get(path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        raw = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args):
        return


class _HttpFixtureWebResource:
    name = "fixture-http"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.search_calls = 0
        self.extract_calls = 0
        self.extracted_urls: list[str] = []

    def search(self, query: str, *, limit: int = 5):
        self.search_calls += 1
        rows = [
            ("Official Alpha/Beta pricing", f"{self.base_url}/official?utm_source=search", "2026-09-10"),
            ("Duplicate official result", f"{self.base_url}/official#pricing", "2026-09-10"),
            ("Independent review", f"{self.base_url}/review", "2026-09-09"),
            ("Retailer listing", f"{self.base_url}/retailer", None),
        ]
        return [
            WebSearchItem(
                title=title,
                url=url,
                description="discovery snippet must not become final evidence",
                position=index + 1,
                metadata={"provider": "fixture-search", **({"published_date": published} if published else {})},
            )
            for index, (title, url, published) in enumerate(rows[:limit])
        ]

    def extract(self, urls: list[str]):
        self.extract_calls += 1
        documents = []
        for requested in urls:
            self.extracted_urls.append(requested)
            try:
                with urlopen(requested, timeout=3) as response:
                    content = response.read().decode("utf-8")
                    observed = response.geturl()
                documents.append(
                    WebDocument(
                        url=observed,
                        title=observed.rsplit("/", 1)[-1],
                        content=content,
                        metadata={
                            "requestedURL": requested,
                            "sourceURL": observed,
                            "provider": "fixture-extract",
                        },
                    )
                )
            except Exception as exc:
                documents.append(
                    WebDocument(
                        url=requested,
                        error=f"{type(exc).__name__}: {exc}",
                        metadata={"requestedURL": requested, "sourceURL": requested, "provider": "fixture-extract"},
                    )
                )
        return documents


class _SequenceWorker:
    def __init__(self, factory):
        self.factory = factory

    def run(self, goal, kernel_context):
        if not self.factory.responses:
            return WorkerResult(success=False, response="", verification_passed=False, error="fixture response queue exhausted", metrics={"model_invoked": True})
        response = self.factory.responses.pop(0)
        self.factory.calls += 1
        return WorkerResult(success=True, response=response, verification_passed=True, metrics={"model_invoked": True})


class _SequenceFactory:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def create(self, route):
        return _SequenceWorker(self)


class E2E01MultiSourceResearchTests(unittest.TestCase):
    def test_normal_user_research_extracts_independent_sources_preserves_conflict_and_rejects_unsupported_claim(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            official_id = source_identity(f"{base}/official")
            review_id = source_identity(f"{base}/review")
            retailer_id = source_identity(f"{base}/retailer")
            plan = json.dumps(
                {"research_plan": {"subject": "Alpha One 和 Beta Two", "queries": ["Alpha One Beta Two current price comparison"]}},
                ensure_ascii=False,
            )
            synthesis = json.dumps(
                {
                    "research_synthesis": {
                        "claims": [
                            {
                                "text": "Alpha One is observed at $99 in two independent sources.",
                                "supports": [
                                    {"source_id": official_id, "quote": "Alpha One current list price is $99."},
                                    {"source_id": review_id, "quote": "Alpha One price observed is $99."},
                                ],
                            },
                            {
                                "text": "Beta Two is observed at $999 in the evidence set.",
                                "supports": [{"source_id": official_id, "quote": "Beta Two current list price is $129."}],
                            },
                            {
                                "text": "Beta Two emphasizes portability in the independent review.",
                                "supports": [{"source_id": review_id, "quote": "Review testing says Beta Two emphasizes portability."}],
                            },
                        ],
                        "conflicts": [
                            {
                                "field": "Alpha One price",
                                "claims": [
                                    {"value": "$99", "source_id": official_id, "quote": "Alpha One current list price is $99."},
                                    {"value": "$119", "source_id": retailer_id, "quote": "Alpha One listed price is $119."},
                                ],
                                "status": "unresolved",
                            }
                        ],
                        "recommendation": {
                            "text": "Prefer Alpha One if the $99 observed price applies to your purchase context.",
                            "supports": [{"source_id": official_id, "quote": "Alpha One current list price is $99."}],
                        },
                        "unknowns": ["The retailer and official Alpha One prices may reflect different purchase contexts."],
                        "follow_up_queries": [],
                    }
                },
                ensure_ascii=False,
            )

            with tempfile.TemporaryDirectory() as tmp:
                resident = build_resident_runtime(config={"model": {}}, store_path=Path(tmp) / "kernel.db")
                resource = _HttpFixtureWebResource(base)
                factory = _SequenceFactory([plan, synthesis])
                resident.configure_research_web_resource(resource)
                resident.kernel.reconfigure_resources(
                    routes=[ModelRoute(route_id="fixture", provider="fixture", model="fixture-model", capabilities={"general": 1.0, "research": 1.0, "reasoning": 1.0})],
                    worker_factory=factory,
                    max_attempts=1,
                    resource_status={"available": True, "error": None},
                )
                try:
                    ledger = resident.work_ledger
                    ledger.create_thread(thread_id="e2e-01", title="Research")
                    snapshot, run = ledger.submit(
                        "e2e-01",
                        "帮我查一下 Alpha One 和 Beta Two 现在的价格和主要区别，别只看一个来源，最后给我一个建议。",
                    )
                    self.assertTrue(run.success, run.response)
                    self.assertGreaterEqual(resource.search_calls, 1)
                    self.assertEqual(resource.extract_calls, 1)
                    self.assertEqual(len(resource.extracted_urls), 3, "duplicate canonical source must not be extracted/count twice")
                    self.assertIn("冲突 / 不确定性", run.response)
                    self.assertIn("$99", run.response)
                    self.assertIn("$119", run.response)
                    self.assertNotIn("$999", run.response)
                    self.assertIn(official_id, run.response)
                    self.assertIn(review_id, run.response)
                    self.assertIn(retailer_id, run.response)

                    evidence_items = [
                        item for item in ledger.list_work_items("e2e-01", limit=64)
                        if "research_bundle:v1" in item.acceptance_criteria
                    ]
                    self.assertEqual(len(evidence_items), 1)
                    bundle = json.loads(evidence_items[0].result or "{}")
                    self.assertEqual(bundle["status"], "complete")
                    self.assertEqual(len([source for source in bundle["sources"] if source["extraction_status"] == "read"]), 3)
                    self.assertEqual(len(bundle["conflicts"]), 1)
                    self.assertEqual(bundle["rejected_claim_count"], 1)
                    self.assertEqual({source["source_id"] for source in bundle["sources"]}, {official_id, review_id, retailer_id})
                    self.assertEqual(bundle["sources"][2]["published_at"], None)
                    self.assertEqual(bundle["sources"][2]["freshness_status"], "capture_only")
                finally:
                    resident.store.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
