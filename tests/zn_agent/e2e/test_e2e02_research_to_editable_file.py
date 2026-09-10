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
        "/industry": "Acme Robotics industry adoption is expanding. Manufacturers report more pilot deployments.",
        "/market": "Acme Robotics market discussion emphasizes lower deployment cost and broader factory use.",
        "/analysis": "Independent analysis says robotics buyers increasingly compare integration effort before purchase.",
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
        urls = [f"{self.base}/industry", f"{self.base}/market", f"{self.base}/analysis"]
        return [
            WebSearchItem(title=f"Trend {index}", url=url, description="discovery only", position=index, metadata={"provider": "fixture-search", "published_date": f"2026-09-0{index + 6}"})
            for index, url in enumerate(urls, start=1)
        ][:limit]

    def extract(self, urls: list[str]):
        self.extract_calls += 1
        documents = []
        for requested in urls:
            with urlopen(requested, timeout=3) as response:
                content = response.read().decode("utf-8")
                observed = response.geturl()
            documents.append(WebDocument(url=observed, title=observed.rsplit("/", 1)[-1], content=content, metadata={"requestedURL": requested, "sourceURL": observed, "provider": "fixture-extract"}))
        return documents


class _Worker:
    def __init__(self, factory):
        self.factory = factory

    def run(self, goal, kernel_context):
        if not self.factory.responses:
            return WorkerResult(success=False, response="", verification_passed=False, error="fixture response queue exhausted", metrics={"model_invoked": True})
        response = self.factory.responses.pop(0)
        self.factory.calls += 1
        return WorkerResult(success=True, response=response, verification_passed=True, metrics={"model_invoked": True})


class _Factory:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def create(self, route):
        return _Worker(self)


class E2E02ResearchToEditableFileTests(unittest.TestCase):
    def test_normal_research_goal_creates_real_editable_markdown_in_exact_workspace_and_freshly_verifies_it(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            industry_id = source_identity(f"{base}/industry")
            market_id = source_identity(f"{base}/market")
            analysis_id = source_identity(f"{base}/analysis")
            plan = json.dumps({"research_plan": {"subject": "Acme Robotics", "queries": ["Acme Robotics recent industry trends"]}}, ensure_ascii=False)
            synthesis = json.dumps(
                {
                    "research_synthesis": {
                        "claims": [
                            {"text": "Acme Robotics industry adoption is expanding.", "supports": [{"source_id": industry_id, "quote": "Acme Robotics industry adoption is expanding."}]},
                            {"text": "Market discussion emphasizes lower deployment cost and broader factory use.", "supports": [{"source_id": market_id, "quote": "Acme Robotics market discussion emphasizes lower deployment cost and broader factory use."}]},
                            {"text": "Buyers increasingly compare integration effort before purchase.", "supports": [{"source_id": analysis_id, "quote": "Independent analysis says robotics buyers increasingly compare integration effort before purchase."}]},
                        ],
                        "conflicts": [],
                        "recommendation": None,
                        "unknowns": [],
                        "follow_up_queries": [],
                    }
                },
                ensure_ascii=False,
            )

            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                workspace = root / "project"
                workspace.mkdir()
                unrelated = workspace / "keep-me.txt"
                unrelated.write_text("unchanged", encoding="utf-8")
                resident = build_resident_runtime(config={"model": {}}, store_path=root / "kernel.db")
                resource = _WebResource(base)
                factory = _Factory([plan, synthesis])
                resident.configure_research_web_resource(resource)
                resident.kernel.reconfigure_resources(
                    routes=[ModelRoute(route_id="fixture", provider="fixture", model="fixture-model", capabilities={"general": 1.0, "research": 1.0, "reasoning": 1.0})],
                    worker_factory=factory,
                    max_attempts=1,
                    resource_status={"available": True, "error": None},
                )
                try:
                    ledger = resident.work_ledger
                    ledger.create_thread(thread_id="e2e-02", title="Research deliverable")
                    ledger.attach_workspace("e2e-02", workspace, name="Project")
                    snapshot, run = ledger.submit(
                        "e2e-02",
                        "查一下最近 Acme Robotics 行业的趋势，然后整理成一份我能继续编辑的文档放进项目文件夹。",
                    )
                    self.assertTrue(run.success, run.response)
                    self.assertEqual(unrelated.read_text(encoding="utf-8"), "unchanged")
                    markdown_files = list(workspace.glob("research-*.md"))
                    self.assertEqual(len(markdown_files), 1)
                    artifact = markdown_files[0]
                    text = artifact.read_text(encoding="utf-8")
                    self.assertIn("## Summary", text)
                    self.assertIn("## Key findings", text)
                    self.assertIn("## Conflicting evidence / uncertainty", text)
                    self.assertIn("## Sources", text)
                    self.assertIn(industry_id, text)
                    self.assertIn(market_id, text)
                    self.assertIn(analysis_id, text)
                    self.assertIn("Acme Robotics industry adoption is expanding.", text)
                    self.assertIn(str(artifact), run.response)

                    evidence_items = [item for item in ledger.list_work_items("e2e-02", limit=64) if "research_bundle:v1" in item.acceptance_criteria]
                    self.assertEqual(len(evidence_items), 1)
                    bundle = json.loads(evidence_items[0].result or "{}")
                    self.assertTrue(bundle["artifact"]["fresh_reread_verified"])
                    self.assertTrue(bundle["artifact"]["identity_exact_after_reread"])
                    self.assertEqual(Path(bundle["artifact"]["path"]), artifact)
                    verification_items = [item for item in ledger.list_work_items("e2e-02", limit=64) if "research_artifact_verification:v1" in item.acceptance_criteria]
                    self.assertEqual(len(verification_items), 1)
                    self.assertEqual(resource.extract_calls, 1)
                finally:
                    resident.store.close()
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)

    def test_ambiguous_or_unbound_project_destination_blocks_before_file_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "project-a"
            second = root / "project-b"
            first.mkdir()
            second.mkdir()
            resident = build_resident_runtime(config={"model": {}}, store_path=root / "kernel.db")
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="e2e-02-no-destination", title="Ambiguous destination")
                snapshot, run = ledger.submit(
                    "e2e-02-no-destination",
                    "查一下最近 Acme Robotics 行业的趋势，然后整理成一份我能继续编辑的文档放进项目文件夹。",
                )
                self.assertFalse(run.success)
                self.assertIn("项目目录", run.response)
                self.assertEqual(list(first.iterdir()), [])
                self.assertEqual(list(second.iterdir()), [])
                self.assertEqual(len(resident.body.recent_actions(20)), 0)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
