from __future__ import annotations

import unittest

from zn_agent.core.web_resource import FailoverWebResource, WebDocument


class _RedirectResource:
    name = "firecrawl"

    def __init__(self):
        self.calls = []

    def search(self, query, *, limit=5):
        return []

    def extract(self, urls):
        self.calls.append(list(urls))
        requested = urls[0]
        return [
            WebDocument(
                url="https://final.example/article",
                content="redirected content",
                metadata={
                    "requestedURL": requested,
                    "sourceURL": "https://final.example/article",
                },
            )
        ]


class _ShouldNotRun:
    name = "tavily"

    def __init__(self):
        self.calls = []

    def search(self, query, *, limit=5):
        return []

    def extract(self, urls):
        self.calls.append(list(urls))
        raise AssertionError("settled redirected URL must not fall through")


class RedirectIdentityTests(unittest.TestCase):
    def test_redirected_success_settles_original_request(self):
        first = _RedirectResource()
        second = _ShouldNotRun()
        resource = FailoverWebResource([first, second])

        docs = resource.extract(["https://start.example/article"])

        self.assertEqual(first.calls, [["https://start.example/article"]])
        self.assertEqual(second.calls, [])
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].url, "https://final.example/article")
        self.assertEqual(docs[0].metadata["requestedURL"], "https://start.example/article")
        self.assertEqual(docs[0].metadata["provider"], "firecrawl")


if __name__ == "__main__":
    unittest.main()
