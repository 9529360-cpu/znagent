from __future__ import annotations

import unittest

from zn_agent.core.firecrawl_web_resource import FirecrawlWebResource
from zn_agent.core.web_resource import FailoverWebResource, build_zn_web_resource


class _Response:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


class _Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class FirecrawlWebResourceTests(unittest.TestCase):
    def test_search_normalizes_nested_web_shape(self):
        client = _Client(
            [
                _Response(
                    {
                        "success": True,
                        "data": {
                            "web": [
                                {
                                    "title": "A",
                                    "url": "https://a.test",
                                    "description": "evidence",
                                    "score": 0.8,
                                }
                            ]
                        },
                    }
                )
            ]
        )
        resource = FirecrawlWebResource(api_key="key", client=client)

        items = resource.search("query", limit=4)

        self.assertEqual(items[0].title, "A")
        self.assertEqual(items[0].description, "evidence")
        self.assertEqual(items[0].metadata["score"], 0.8)
        url, call = client.calls[0]
        self.assertEqual(url, "https://api.firecrawl.dev/v2/search")
        self.assertEqual(call["json"]["limit"], 4)
        self.assertEqual(call["headers"]["Authorization"], "Bearer key")

    def test_keyless_firecrawl_sends_no_authorization_header(self):
        client = _Client([_Response({"success": True, "data": []})])
        resource = FirecrawlWebResource(client=client)
        resource.search("query")
        self.assertNotIn("Authorization", client.calls[0][1]["headers"])

    def test_extract_blocks_unsafe_initial_url_before_provider_call(self):
        client = _Client([])
        resource = FirecrawlWebResource(
            client=client,
            safety_check=lambda url: False,
        )

        docs = resource.extract(["http://127.0.0.1/private"])

        self.assertEqual(client.calls, [])
        self.assertIsNotNone(docs[0].error)
        self.assertIn("Blocked", docs[0].error)

    def test_extract_rechecks_redirected_final_url(self):
        client = _Client(
            [
                _Response(
                    {
                        "success": True,
                        "data": {
                            "markdown": "secret",
                            "metadata": {
                                "title": "Redirected",
                                "sourceURL": "http://10.0.0.8/internal",
                            },
                        },
                    }
                )
            ]
        )

        def safety(url):
            return url == "https://public.test/start"

        resource = FirecrawlWebResource(client=client, safety_check=safety)
        docs = resource.extract(["https://public.test/start"])

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(docs[0].url, "http://10.0.0.8/internal")
        self.assertIn("redirected URL", docs[0].error)
        self.assertEqual(docs[0].content, "")

    def test_extract_prefers_markdown_and_preserves_metadata(self):
        client = _Client(
            [
                _Response(
                    {
                        "success": True,
                        "data": {
                            "markdown": "# body",
                            "html": "<h1>body</h1>",
                            "metadata": {
                                "title": "Page",
                                "sourceURL": "https://public.test/final",
                            },
                        },
                    }
                )
            ]
        )
        resource = FirecrawlWebResource(
            client=client,
            safety_check=lambda url: True,
        )

        docs = resource.extract(["https://public.test/start"])

        self.assertEqual(docs[0].url, "https://public.test/final")
        self.assertEqual(docs[0].content, "# body")
        self.assertEqual(docs[0].metadata["title"], "Page")

    def test_explicit_builder_uses_zn_firecrawl_config(self):
        client = _Client([])
        resource = build_zn_web_resource(
            {
                "web": {
                    "backend": "firecrawl",
                    "firecrawl": {
                        "api_url": "https://firecrawl.example",
                        "timeout": 12,
                    },
                }
            },
            environ={"FIRECRAWL_API_KEY": "env-key"},
            client=client,
        )
        self.assertIsInstance(resource, FirecrawlWebResource)
        self.assertEqual(resource.api_key, "env-key")
        self.assertEqual(resource.api_url, "https://firecrawl.example")
        self.assertEqual(resource.timeout, 12.0)

    def test_auto_can_include_keyless_firecrawl_only_when_requested(self):
        resource = build_zn_web_resource(
            {
                "web": {
                    "backend": "auto",
                    "provider_order": ["firecrawl", "tavily"],
                }
            },
            environ={},
        )
        self.assertIsInstance(resource, FailoverWebResource)
        self.assertEqual(
            [item.name for item in resource.resources],
            ["firecrawl", "tavily"],
        )


if __name__ == "__main__":
    unittest.main()
