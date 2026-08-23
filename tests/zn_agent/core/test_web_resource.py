from __future__ import annotations

import json
import unittest

from zn_agent.core.web_resource import (
    TavilyWebResource,
    WebResourceError,
    build_zn_web_resource,
    web_search_json,
)


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


class WebResourceTests(unittest.TestCase):
    def test_tavily_search_normalizes_mature_provider_shape(self):
        client = _Client(
            [
                _Response(
                    {
                        "results": [
                            {
                                "title": "ZN result",
                                "url": "https://example.test/a",
                                "content": "evidence",
                                "score": 0.9,
                            }
                        ]
                    }
                )
            ]
        )
        resource = TavilyWebResource(api_key="key", client=client)
        items = resource.search("zn query", limit=3)
        self.assertEqual(items[0].title, "ZN result")
        self.assertEqual(items[0].description, "evidence")
        self.assertEqual(items[0].position, 1)
        _url, call = client.calls[0]
        self.assertEqual(call["headers"]["Authorization"], "Bearer key")
        self.assertEqual(call["headers"]["X-Client-Name"], "zn-agent")
        self.assertEqual(call["json"]["max_results"], 3)

    def test_keyless_tavily_preserves_reference_access_mode(self):
        client = _Client([_Response({"results": []})])
        resource = TavilyWebResource(client=client)
        resource.search("query")
        headers = client.calls[0][1]["headers"]
        self.assertEqual(headers["X-Tavily-Access-Mode"], "keyless")
        self.assertNotIn("Authorization", headers)

    def test_extract_preserves_per_url_failures(self):
        client = _Client(
            [
                _Response(
                    {
                        "results": [
                            {
                                "url": "https://example.test/a",
                                "title": "A",
                                "raw_content": "body",
                            }
                        ],
                        "failed_results": [
                            {"url": "https://example.test/b", "error": "denied"}
                        ],
                    }
                )
            ]
        )
        docs = TavilyWebResource(api_key="key", client=client).extract(
            ["https://example.test/a", "https://example.test/b"]
        )
        self.assertEqual(docs[0].content, "body")
        self.assertEqual(docs[1].error, "denied")

    def test_http_failure_is_resource_error_not_fake_observation(self):
        client = _Client([_Response({}, status_code=429, text="rate limited")])
        with self.assertRaisesRegex(WebResourceError, "rate limited"):
            TavilyWebResource(api_key="key", client=client).search("query")

    def test_builder_uses_zn_config_and_env_not_legacy_registry(self):
        resource = build_zn_web_resource(
            {
                "web": {
                    "backend": "tavily",
                    "tavily": {"base_url": "https://search.example"},
                }
            },
            environ={"TAVILY_API_KEY": "env-key"},
            client=_Client([]),
        )
        self.assertEqual(resource.name, "tavily")
        self.assertEqual(resource.api_key, "env-key")
        self.assertEqual(resource.base_url, "https://search.example")

    def test_world_compat_json_has_structured_web_items(self):
        client = _Client(
            [
                _Response(
                    {
                        "results": [
                            {
                                "title": "A",
                                "url": "https://example.test",
                                "content": "B",
                            }
                        ]
                    }
                )
            ]
        )
        raw = web_search_json(
            "query",
            resource=TavilyWebResource(api_key="key", client=client),
        )
        payload = json.loads(raw)
        self.assertEqual(payload["provider"], "tavily")
        self.assertEqual(payload["data"]["web"][0]["description"], "B")


if __name__ == "__main__":
    unittest.main()
