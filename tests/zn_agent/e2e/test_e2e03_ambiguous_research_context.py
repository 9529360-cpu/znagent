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
from zn_agent.core.work import WorkMessage


class _Handler(BaseHTTPRequestHandler):
    pages = {
        "/one": "OpenAI Nova discussion increased after the launch note described a smaller latency target.",
        "/two": "Independent coverage discusses OpenAI Nova because developers are comparing deployment tradeoffs.",
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


class _WebResource:
    name = "fixture-http"

    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.search_calls = 0
        self.extract_calls = 0

    def search(self, query: str, *, limit: int = 5):
        self.search_calls += 1
        return [
            WebSearchItem(title="Launch note", url=f"{self.base}/one", description="discovery only", position=1, metadata={"provider": "fixture-search", "published_date": "2026-09-10"}),
            WebSearchItem(title="Independent coverage", url=f"{self.base}/two", description="discovery only", position=2, metadata={"provider": "fixture-search", "published_date": "2026-09-10"}),
        ][:limit]

    def extract(self, urls: list[str]):
        self.extract_calls += 1
        documents = []
        for requested in urls:
            with urlopen(requested, timeout=3) as response:
                text = response.read().decode("utf-8")
                observed = response.geturl()
            documents.append(WebDocument(url=observed, title=observed.rsplit("/", 1)[-1], content=text, metadata={"requestedURL": requested, "sourceURL": observed, "provider": "fixture-extract"}))
        return documents


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


def _configure(resident, resource, responses):
    factory = _Factory(responses)
    resident.configure_research_web_resource(resource)
    resident.kernel.reconfigure_resources(
        routes=[ModelRoute(route_id="fixture", provider="fixture", model="fixture-model", capabilities={"general": 1.0, "research": 1.0, "reasoning": 1.0})],
        worker_factory=factory,
        max_attempts=1,
        resource_status={"available": True, "error": None},
    )
    return factory


def _append_user_context(ledger, thread_id: str, text: str) -> None:
    thread = ledger.get_thread(thread_id) or ledger.create_thread(thread_id=thread_id, title="Context")
    ledger._append(thread, WorkMessage(message_id=f"fixture-{len(ledger.list_messages(thread_id)) + 1}", thread_id=thread_id, role="user", text=text))


class E2E03AmbiguousResearchContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)

    def _synthesis(self):
        first = source_identity(f"{self.base}/one")
        second = source_identity(f"{self.base}/two")
        return json.dumps(
            {
                "research_synthesis": {
                    "claims": [
                        {"text": "Discussion increased after a launch note described a smaller latency target.", "supports": [{"source_id": first, "quote": "OpenAI Nova discussion increased after the launch note described a smaller latency target."}]},
                        {"text": "Independent coverage says developers are comparing deployment tradeoffs.", "supports": [{"source_id": second, "quote": "Independent coverage discusses OpenAI Nova because developers are comparing deployment tradeoffs."}]},
                    ],
                    "conflicts": [],
                    "recommendation": None,
                    "unknowns": [],
                    "follow_up_queries": [],
                }
            },
            ensure_ascii=False,
        )

    def test_unique_current_referent_auto_resolves_without_clarification_then_researches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(config={"model": {}}, store_path=Path(tmp) / "kernel.db")
            resource = _WebResource(self.base)
            factory = _configure(resident, resource, [self._synthesis()])
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="unique", title="Unique context")
                _append_user_context(ledger, "unique", '我现在在看 "OpenAI Nova"。')
                snapshot, run = ledger.submit("unique", "看看大家最近为什么都在讨论这个东西，给我弄明白。")
                self.assertTrue(run.success, run.response)
                self.assertIn("研究对象：OpenAI Nova", run.response)
                self.assertEqual(resource.search_calls, 1)
                self.assertEqual(resource.extract_calls, 1)
                self.assertEqual(factory.calls, 1, "unique referent must skip a pointless model clarification/planning call")
            finally:
                resident.store.close()

    def test_two_equally_plausible_referents_asks_user_and_performs_zero_web_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(config={"model": {}}, store_path=Path(tmp) / "kernel.db")
            resource = _WebResource(self.base)
            factory = _configure(resident, resource, [])
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="ambiguous", title="Ambiguous context")
                _append_user_context(ledger, "ambiguous", '我在比较 "Product A" 和 "Product B"。')
                snapshot, run = ledger.submit("ambiguous", "看看大家最近为什么都在讨论这个东西。")
                self.assertFalse(run.success)
                self.assertIn("你指的是哪一个", run.response)
                self.assertEqual(resource.search_calls, 0)
                self.assertEqual(resource.extract_calls, 0)
                self.assertEqual(factory.calls, 0)
            finally:
                resident.store.close()

    def test_missing_referent_asks_user_and_performs_zero_web_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(config={"model": {}}, store_path=Path(tmp) / "kernel.db")
            resource = _WebResource(self.base)
            factory = _configure(resident, resource, [])
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="missing", title="No context")
                snapshot, run = ledger.submit("missing", "看看大家最近为什么都在讨论这个东西。")
                self.assertFalse(run.success)
                self.assertIn("请告诉我具体要研究的对象", run.response)
                self.assertEqual(resource.search_calls, 0)
                self.assertEqual(resource.extract_calls, 0)
                self.assertEqual(factory.calls, 0)
            finally:
                resident.store.close()

    def test_restart_continues_one_durable_research_work_without_reacquiring_fresh_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resource = _WebResource(self.base)
            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            plan = json.dumps({"research_plan": {"subject": "OpenAI Nova", "queries": ["OpenAI Nova discussion"]}}, ensure_ascii=False)
            first_factory = _configure(resident, resource, [plan])
            ledger = resident.work_ledger
            ledger.create_thread(thread_id="restart", title="Restart research")
            _, event = ledger.start("restart", "帮我研究 OpenAI Nova 为什么受关注，别只看一个来源。")
            try:
                for _ in range(12):
                    resident.live_once()
                    state = resident.store.get_working_state()
                    if state.current_event_id == event.event_id and state.stage == "research_synthesize":
                        break
                else:
                    self.fail(f"research did not reach persisted synthesis checkpoint: {resident.store.get_working_state().stage}")
                self.assertEqual(resource.search_calls, 1)
                self.assertEqual(resource.extract_calls, 1)
                evidence_items = [item for item in ledger.list_work_items("restart", limit=64) if "research_bundle:v1" in item.acceptance_criteria]
                self.assertEqual(len(evidence_items), 1)
                before = json.loads(evidence_items[0].result or "{}")
                self.assertEqual(len([source for source in before["sources"] if source["extraction_status"] == "read"]), 2)
            finally:
                resident.store.close()

            restarted = build_resident_runtime(config={"model": {}}, store_path=db)
            second_factory = _configure(restarted, resource, [self._synthesis()])
            try:
                result = None
                for _ in range(12):
                    candidate = restarted.live_once()
                    if candidate is not None and candidate.event.event_id == event.event_id:
                        result = candidate
                        break
                    candidate = restarted.result_for(event.event_id)
                    if candidate is not None:
                        result = candidate
                        break
                self.assertIsNotNone(result)
                self.assertTrue(result.success, result.response)
                self.assertEqual(resource.search_calls, 1, "restart must reuse still-fresh durable extracted sources")
                self.assertEqual(resource.extract_calls, 1)
                self.assertEqual(first_factory.calls, 1)
                self.assertEqual(second_factory.calls, 1)
                after_items = [item for item in restarted.work_ledger.list_work_items("restart", limit=64) if "research_bundle:v1" in item.acceptance_criteria]
                self.assertEqual(len(after_items), 1)
                after = json.loads(after_items[0].result or "{}")
                self.assertEqual(after["status"], "complete")
                self.assertEqual({source["source_id"] for source in after["sources"]}, {source_identity(f"{self.base}/one"), source_identity(f"{self.base}/two")})
            finally:
                restarted.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
