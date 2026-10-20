from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core import KernelStore
from zn_agent.core.action_execution import ActionExecutionRuntime
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.body import NativeBody
from zn_agent.core.openapi_rest_adapter import (
    RestHttpResponse,
    parse_openapi_spec,
)
from zn_agent.core.skill_evals import eval_skills_root
from zn_agent.core.web_search_connector import (
    DEFAULT_INSTANCES,
    SEARCH_SPEC,
    WebSearchError,
    action_id_for_instance,
    attach_web_search_tools,
    provider_id_for_instance,
    search_web,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SKILLS_ROOT = REPO_ROOT / "skills"

_GOOD = "https://search.lumy.live"
_LIMITED = "https://limited.example"
_BOTCHECK = "https://botcheck.example"
_DOWN = "https://down.example"
_EMPTY = "https://empty.example"
_VERBOSE = "https://verbose.example"

_VERBOSE_PAYLOAD = {
    "query": "berlin weather",
    "results": [
        {
            "title": f"Result number {index}",
            "url": f"https://example.com/result-{index}",
            "content": "x" * 300,
            "engine": "duckduckgo",
        }
        for index in range(40)
    ],
}

_RESULTS_PAYLOAD = {
    "query": "berlin weather",
    "number_of_results": 4,
    "results": [
        {
            "title": "Berlin Weather Forecast",
            "url": "https://example.com/berlin-weather",
            "content": "Sunny spells with a high of 21 degrees.",
            "engine": "duckduckgo",
        },
        {
            "title": "Berlin Travel Guide",
            "url": "https://example.org/berlin-guide",
            "content": "What to see in Berlin.",
            "engine": "brave",
        },
        {"title": "Missing its URL", "content": "must be skipped"},
        "not-a-mapping",
    ],
}


class _FakeSearXNG:
    """Mock SearXNG instances: records calls, answers per host."""

    def __init__(self):
        self.calls = []
        self.limited_status = 429

    def request(self, method, url, *, params, headers, json_body, timeout_seconds):
        self.calls.append({"method": method, "url": url, "params": dict(params)})
        if "down.example" in url:
            raise ConnectionError("network down")
        if "limited.example" in url:
            return RestHttpResponse(self.limited_status, {}, b"Too Many Requests")
        if "botcheck.example" in url:
            return RestHttpResponse(
                200, {}, b"<!doctype html><title>Verifying your browser</title>"
            )
        if "empty.example" in url:
            return RestHttpResponse(
                200, {}, json.dumps({"results": []}).encode("utf-8")
            )
        if "verbose.example" in url:
            return RestHttpResponse(
                200, {}, json.dumps(_VERBOSE_PAYLOAD).encode("utf-8")
            )
        if "search.lumy.live" in url:
            return RestHttpResponse(
                200, {}, json.dumps(_RESULTS_PAYLOAD).encode("utf-8")
            )
        return RestHttpResponse(404, {}, b"not found")


class WebSearchConnectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(
            store=KernelStore(Path(self.tmp.name) / "kernel.db")
        )
        self.client = _FakeSearXNG()
        self.runtime = ActionExecutionRuntime(self.fabric, self.body)

    def tearDown(self):
        self.body.store.close()
        self.tmp.cleanup()

    def attach(self, instances):
        return attach_web_search_tools(
            self.fabric, self.body, instances=instances, http_client=self.client
        )

    def test_spec_parses_into_one_read_only_operation(self):
        parsed = parse_openapi_spec(SEARCH_SPEC)
        self.assertEqual(
            [op.operation_id for op in parsed.operations], ["web_search"]
        )
        self.assertTrue(all(op.is_read for op in parsed.operations))
        schema = parsed.operations[0].input_schema
        self.assertIn("q", schema["required"])
        self.assertEqual(schema["properties"]["format"]["enum"], ["json"])

    def test_default_instance_is_the_verified_one(self):
        self.assertEqual(DEFAULT_INSTANCES, ("https://search.lumy.live",))
        self.assertEqual(
            provider_id_for_instance(_GOOD), "searxng_search_lumy_live"
        )
        self.assertEqual(
            action_id_for_instance(_GOOD),
            "rest.searxng_search_lumy_live.web_search",
        )

    def test_attach_registers_one_read_only_tool_per_instance(self):
        attachment = self.attach([_GOOD, _LIMITED])
        try:
            self.assertEqual(
                attachment.action_ids,
                (
                    "rest.searxng_search_lumy_live.web_search",
                    "rest.searxng_limited_example.web_search",
                ),
            )
            for action_id in attachment.action_ids:
                descriptor = self.fabric.descriptor(action_id)
                self.assertIsNotNone(descriptor, action_id)
                self.assertEqual(descriptor.effect_class, "read_only")
                self.assertIn("rest", descriptor.tags)
        finally:
            attachment.detach()

    def test_detach_removes_every_tool(self):
        attachment = self.attach([_GOOD, _LIMITED])
        attachment.detach()
        for action_id in (
            "rest.searxng_search_lumy_live.web_search",
            "rest.searxng_limited_example.web_search",
        ):
            self.assertIsNone(self.fabric.descriptor(action_id))

    def test_attach_needs_at_least_one_instance(self):
        with self.assertRaises(WebSearchError):
            self.attach([])

    def test_search_returns_normalized_results_with_source(self):
        attachment = self.attach([_GOOD])
        try:
            answer = search_web(
                self.runtime,
                attachment,
                "berlin weather",
                event_id="evt-search-1",
            )
        finally:
            attachment.detach()
        self.assertEqual(answer["query"], "berlin weather")
        self.assertEqual(answer["instance"], _GOOD)
        self.assertIn("SearXNG", answer["source"])
        self.assertTrue(answer["retrieved_at"])
        self.assertFalse(answer["truncated"])
        # The malformed entries (missing URL, non-mapping) are skipped;
        # nothing is invented to replace them.
        self.assertEqual(len(answer["results"]), 2)
        first = answer["results"][0]
        self.assertEqual(first["title"], "Berlin Weather Forecast")
        self.assertEqual(first["url"], "https://example.com/berlin-weather")
        self.assertEqual(
            first["snippet"], "Sunny spells with a high of 21 degrees."
        )
        self.assertEqual(first["engine"], "duckduckgo")
        sent = self.client.calls[-1]
        self.assertEqual(sent["params"]["q"], "berlin weather")
        self.assertEqual(sent["params"]["format"], "json")

    def test_search_caps_results_at_max_results(self):
        attachment = self.attach([_GOOD])
        try:
            answer = search_web(
                self.runtime,
                attachment,
                "berlin weather",
                max_results=1,
                event_id="evt-search-2",
            )
        finally:
            attachment.detach()
        self.assertEqual(len(answer["results"]), 1)

    def test_search_falls_back_when_first_instance_is_rate_limited(self):
        attachment = self.attach([_LIMITED, _GOOD])
        try:
            answer = search_web(
                self.runtime,
                attachment,
                "berlin weather",
                event_id="evt-search-3",
            )
        finally:
            attachment.detach()
        self.assertEqual(answer["instance"], _GOOD)
        self.assertEqual(len(answer["results"]), 2)
        called_urls = [call["url"] for call in self.client.calls]
        self.assertTrue(any("limited.example" in url for url in called_urls))

    def test_search_botcheck_page_is_a_failure_not_results(self):
        attachment = self.attach([_BOTCHECK])
        try:
            with self.assertRaises(WebSearchError) as caught:
                search_web(
                    self.runtime,
                    attachment,
                    "berlin weather",
                    event_id="evt-search-4",
                )
        finally:
            attachment.detach()
        message = str(caught.exception)
        self.assertIn(_BOTCHECK, message)
        self.assertIn("malformed", message)

    def test_search_all_instances_down_lists_every_reason(self):
        attachment = self.attach([_LIMITED, _DOWN])
        try:
            with self.assertRaises(WebSearchError) as caught:
                search_web(
                    self.runtime,
                    attachment,
                    "berlin weather",
                    event_id="evt-search-5",
                )
        finally:
            attachment.detach()
        message = str(caught.exception)
        self.assertIn(_LIMITED, message)
        self.assertIn("429", message)
        self.assertIn(_DOWN, message)

    def test_search_recovers_complete_results_from_truncated_payload(self):
        # The verbose payload exceeds the Fabric's bounded tool output,
        # so it arrives cut mid-JSON; the connector must keep the
        # complete leading entries, drop the partial tail, and say so.
        attachment = self.attach([_VERBOSE])
        try:
            answer = search_web(
                self.runtime,
                attachment,
                "berlin weather",
                max_results=5,
                event_id="evt-search-10",
            )
        finally:
            attachment.detach()
        self.assertTrue(answer["truncated"])
        self.assertEqual(len(answer["results"]), 5)
        self.assertEqual(answer["results"][0]["title"], "Result number 0")
        self.assertEqual(answer["results"][4]["title"], "Result number 4")

    def test_search_zero_results_is_an_explicit_empty_answer(self):
        attachment = self.attach([_EMPTY])
        try:
            answer = search_web(
                self.runtime,
                attachment,
                "an extremely obscure query",
                event_id="evt-search-6",
            )
        finally:
            attachment.detach()
        self.assertEqual(answer["results"], [])
        self.assertEqual(answer["instance"], _EMPTY)

    def test_search_rejects_bad_inputs(self):
        attachment = self.attach([_GOOD])
        try:
            with self.assertRaises(WebSearchError):
                search_web(
                    self.runtime, attachment, "  ", event_id="evt-search-7"
                )
            with self.assertRaises(WebSearchError):
                search_web(
                    self.runtime,
                    attachment,
                    "berlin weather",
                    max_results=0,
                    event_id="evt-search-8",
                )
            with self.assertRaises(WebSearchError):
                search_web(
                    self.runtime,
                    attachment,
                    "berlin weather",
                    max_results=21,
                    event_id="evt-search-9",
                )
        finally:
            attachment.detach()


class WebSearchSkillEvalTests(unittest.TestCase):
    def test_repo_web_search_skill_passes_skill_evals(self):
        report = eval_skills_root(REPO_SKILLS_ROOT)
        found = [
            item for item in report.tier1 if item.skill_name == "web-search"
        ]
        self.assertEqual(len(found), 1, report.to_dict())
        self.assertTrue(found[0].passed, found[0].violations)
        self.assertTrue(report.tier2.passed, report.to_dict()["tier2"])
        self.assertTrue(report.passed, report.to_dict())


if __name__ == "__main__":
    unittest.main()
