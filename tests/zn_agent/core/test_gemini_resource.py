from __future__ import annotations

import unittest

from zn_agent.core.cognitive_factory import (
    ZNCognitiveResourceWorkerFactory,
    resolve_zn_cognitive_route,
)
from zn_agent.core.gemini_resource import (
    GeminiCognitiveResource,
    bare_gemini_model_id,
    gemini_major_version,
    resolve_gemini_route,
)
from zn_agent.core.models import Goal, ModelRoute


def route(**overrides):
    values = {
        "route_id": "gemini",
        "provider": "gemini",
        "model": "google/gemini-3.1-pro",
        "capabilities": {"general": 0.9},
        "metadata": {"api_key": "test-key"},
    }
    values.update(overrides)
    return ModelRoute(**values)


class _Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class _Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class GeminiResourceTests(unittest.TestCase):
    def test_model_id_and_major_version_follow_native_adapter_semantics(self):
        self.assertEqual(bare_gemini_model_id("google/gemini-3.1-pro"), "gemini-3.1-pro")
        self.assertEqual(bare_gemini_model_id("gemini/gemini-2.5-flash"), "gemini-2.5-flash")
        self.assertEqual(gemini_major_version("gemini-3.1-pro"), 3)

    def test_route_uses_native_google_endpoint_and_zn_credentials(self):
        resolved = resolve_gemini_route(
            route(metadata={}),
            environ={"GEMINI_API_KEY": "env-key"},
        )
        self.assertEqual(resolved.provider, "gemini")
        self.assertEqual(resolved.model, "gemini-3.1-pro")
        self.assertEqual(resolved.metadata["api_mode"], "gemini_native")
        self.assertEqual(resolved.metadata["api_key"], "env-key")

    def test_native_generate_content_normalizes_text_thoughts_and_usage(self):
        client = _Client(
            [
                _Response(
                    {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {"text": "reason", "thought": True, "thoughtSignature": "sig"},
                                        {"text": "bounded Gemini answer"},
                                    ]
                                },
                                "finishReason": "STOP",
                            }
                        ],
                        "usageMetadata": {
                            "promptTokenCount": 12,
                            "candidatesTokenCount": 6,
                            "thoughtsTokenCount": 4,
                            "totalTokenCount": 22,
                            "cachedContentTokenCount": 3,
                        },
                    }
                )
            ]
        )
        resource = GeminiCognitiveResource(
            route(metadata={"api_key": "k", "max_tokens": 2048}),
            client=client,
        )
        increment = resource.invoke(question="question", context="ZN bounded context")

        url, call = client.calls[0]
        self.assertIn("/models/gemini-3.1-pro:generateContent", url)
        self.assertEqual(call["params"], {"key": "k"})
        self.assertEqual(
            call["json"]["systemInstruction"],
            {"parts": [{"text": "ZN bounded context"}]},
        )
        self.assertEqual(call["json"]["generationConfig"]["maxOutputTokens"], 2048)
        self.assertEqual(increment.text, "bounded Gemini answer")
        self.assertEqual(increment.metadata["reasoning"], "reason")
        self.assertEqual(increment.metadata["thought_signatures"], ["sig"])
        self.assertEqual(increment.usage["reasoning_tokens"], 4)
        self.assertEqual(increment.usage["cached_tokens"], 3)

    def test_factory_dispatches_gemini_without_openai_compat_or_old_agent(self):
        client = _Client(
            [
                _Response(
                    {
                        "candidates": [
                            {
                                "content": {"parts": [{"text": "answer"}]},
                                "finishReason": "STOP",
                            }
                        ],
                        "usageMetadata": {},
                    }
                )
            ]
        )
        resolved = resolve_zn_cognitive_route(route())
        factory = ZNCognitiveResourceWorkerFactory(gemini_client=client)
        worker = factory.create(resolved)
        result = worker.run(Goal(goal_id="g", task="bounded q"), "ctx")
        self.assertTrue(result.success)
        self.assertEqual(result.response, "answer")
        self.assertEqual(result.metrics["provider"], "gemini")
        self.assertEqual(result.metrics["resource_owner"], "zn")


if __name__ == "__main__":
    unittest.main()
