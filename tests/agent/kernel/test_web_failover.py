from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from agent.kernel.web_resource import (
    FailoverWebResource,
    TavilyWebResource,
    WebDocument,
    WebResourceError,
    WebSearchItem,
    build_zn_web_resource,
    web_search_json,
)


class _Resource:
    def __init__(self, name, *, search=None, extract=None):
        self.name = name
        self._search = search
        self._extract = extract
        self.search_calls = []
        self.extract_calls = []

    def search(self, query, *, limit=5):
        self.search_calls.append((query, limit))
        if isinstance(self._search, Exception):
            raise self._search
        return list(self._search or [])

    def extract(self, urls):
        self.extract_calls.append(list(urls))
        if isinstance(self._extract, Exception):
            raise self._extract
        if callable(self._extract):
            return list(self._extract(urls))
        return list(self._extract or [])


class WebFailoverTests(unittest.TestCase):
    def test_search_fails_over_on_provider_error(self):
        first = _Resource("exa", search=WebResourceError("quota"))
        second = _Resource(
            "tavily",
            search=[WebSearchItem(title="B", url="https://b.test")],
        )
        resource = FailoverWebResource([first, second])

        items = resource.search("query", limit=3)

        self.assertEqual(resource.last_provider, "tavily")
        self.assertEqual(items[0].title, "B")
        self.assertEqual(items[0].metadata["provider"], "tavily")
        self.assertEqual(len(first.search_calls), 1)
        self.assertEqual(len(second.search_calls), 1)

    def test_empty_search_is_valid_evidence_and_does_not_fail_over(self):
        first = _Resource("exa", search=[])
        second = _Resource(
            "tavily",
            search=[WebSearchItem(title="should not run", url="https://b.test")],
        )
        resource = FailoverWebResource([first, second])

        self.assertEqual(resource.search("nothing found"), [])
        self.assertEqual(resource.last_provider, "exa")
        self.assertEqual(len(second.search_calls), 0)

    def test_search_reports_all_provider_failures(self):
        resource = FailoverWebResource(
            [
                _Resource("exa", search=WebResourceError("exa down")),
                _Resource("tavily", search=RuntimeError("tavily down")),
            ]
        )
        with self.assertRaisesRegex(WebResourceError, "all ZN web search resources failed"):
            resource.search("query")

    def test_extract_fails_over_only_unsettled_urls_and_preserves_order(self):
        urls = ["https://a.test", "https://b.test", "https://c.test"]

        first = _Resource(
            "exa",
            extract=[
                WebDocument(url=urls[0], title="A", content="a"),
                WebDocument(url=urls[1], error="blocked"),
            ],
        )

        def second_extract(requested):
            self.assertEqual(requested, [urls[1], urls[2]])
            return [
                WebDocument(url=urls[1], title="B", content="b"),
                WebDocument(url=urls[2], title="C", content="c"),
            ]

        second = _Resource("tavily", extract=second_extract)
        resource = FailoverWebResource([first, second])

        docs = resource.extract(urls)

        self.assertEqual([doc.url for doc in docs], urls)
        self.assertEqual([doc.content for doc in docs], ["a", "b", "c"])
        self.assertEqual(docs[0].metadata["provider"], "exa")
        self.assertEqual(docs[1].metadata["provider"], "tavily")
        self.assertEqual(first.extract_calls, [urls])
        self.assertEqual(second.extract_calls, [[urls[1], urls[2]]])

    def test_extract_all_failures_remain_explicit_evidence(self):
        url = "https://missing.test"
        resource = FailoverWebResource(
            [
                _Resource(
                    "exa",
                    extract=[WebDocument(url=url, error="exa denied")],
                ),
                _Resource("tavily", extract=RuntimeError("network down")),
            ]
        )

        docs = resource.extract([url])

        self.assertEqual(len(docs), 1)
        self.assertIsNotNone(docs[0].error)
        self.assertIn("exa denied", docs[0].error)
        self.assertIn("network down", docs[0].error)

    def test_explicit_provider_remains_pinned(self):
        resource = build_zn_web_resource(
            {"web": {"backend": "tavily"}},
            environ={"EXA_API_KEY": "should-not-matter"},
        )
        self.assertIsInstance(resource, TavilyWebResource)
        self.assertEqual(resource.name, "tavily")

    @patch("agent.kernel.exa_web_resource.ExaWebResource")
    def test_auto_skips_unavailable_keyed_provider_and_keeps_order(self, exa_type):
        resource = build_zn_web_resource(
            {
                "web": {
                    "backend": "auto",
                    "provider_order": ["exa", "tavily"],
                }
            },
            environ={},
        )

        self.assertIsInstance(resource, FailoverWebResource)
        self.assertEqual([item.name for item in resource.resources], ["tavily"])
        exa_type.assert_not_called()

    def test_world_json_surfaces_actual_provider_not_failover_wrapper(self):
        resource = FailoverWebResource(
            [
                _Resource("exa", search=WebResourceError("down")),
                _Resource(
                    "tavily",
                    search=[WebSearchItem(title="A", url="https://a.test")],
                ),
            ]
        )
        payload = json.loads(web_search_json("query", resource=resource))
        self.assertEqual(payload["provider"], "tavily")
        self.assertEqual(payload["data"]["web"][0]["metadata"]["provider"], "tavily")


if __name__ == "__main__":
    unittest.main()
