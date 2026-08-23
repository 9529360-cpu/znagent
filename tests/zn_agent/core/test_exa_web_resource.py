from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.exa_web_resource import ExaWebResource
from zn_agent.core.web_resource import build_zn_web_resource


class _Client:
    def __init__(self):
        self.search_calls = []
        self.extract_calls = []

    def search(self, query, **kwargs):
        self.search_calls.append((query, kwargs))
        return SimpleNamespace(
            results=[
                SimpleNamespace(
                    title="Exa result",
                    url="https://example.test/a",
                    highlights=["first", "second"],
                )
            ]
        )

    def get_contents(self, urls, **kwargs):
        self.extract_calls.append((list(urls), kwargs))
        return SimpleNamespace(
            results=[
                SimpleNamespace(
                    title="A",
                    url="https://example.test/a",
                    text="document body",
                )
            ]
        )


class ExaWebResourceTests(unittest.TestCase):
    def test_search_keeps_mature_highlight_normalization(self):
        client = _Client()
        resource = ExaWebResource(api_key="key", client=client)
        items = resource.search("query", limit=4)
        self.assertEqual(items[0].title, "Exa result")
        self.assertEqual(items[0].description, "first second")
        self.assertEqual(items[0].position, 1)
        self.assertEqual(client.search_calls[0][1]["num_results"], 4)
        self.assertEqual(client.search_calls[0][1]["contents"], {"highlights": True})

    def test_extract_marks_partial_batch_as_evidence_not_silent_success(self):
        client = _Client()
        docs = ExaWebResource(api_key="key", client=client).extract(
            ["https://example.test/a", "https://example.test/missing"]
        )
        self.assertEqual(docs[0].content, "document body")
        missing = [doc for doc in docs if doc.url.endswith("/missing")][0]
        self.assertIn("no document", missing.error.lower())
        self.assertEqual(client.extract_calls[0][1], {"text": True})

    def test_builder_selects_exa_from_zn_config_without_old_plugin_registry(self):
        client = _Client()
        resource = build_zn_web_resource(
            {"web": {"backend": "exa"}},
            environ={"EXA_API_KEY": "env-key"},
            client=client,
        )
        self.assertIsInstance(resource, ExaWebResource)
        self.assertEqual(resource.api_key, "env-key")


if __name__ == "__main__":
    unittest.main()
