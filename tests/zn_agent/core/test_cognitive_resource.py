from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.cognitive_resource import (
    CognitiveResourceWorker,
    OpenAICompatibleCognitiveResource,
    resolve_openai_compatible_route,
)
from zn_agent.core.models import Goal, ModelRoute


def route(**overrides):
    values = {
        "route_id": "r1",
        "provider": "openrouter",
        "model": "example/model",
        "capabilities": {"general": 0.8},
        "metadata": {},
    }
    values.update(overrides)
    return ModelRoute(**values)


class _FakeCompletions:
    def __init__(self, owner):
        self.owner = owner

    def create(self, **kwargs):
        self.owner.request = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="bounded answer"),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=11,
                completion_tokens=7,
                total_tokens=18,
            ),
        )


class _FakeClient:
    def __init__(self):
        self.request = None
        self.chat = SimpleNamespace(completions=_FakeCompletions(self))


class CognitiveResourceTests(unittest.TestCase):
    def test_resolves_openrouter_without_legacy_provider_registry(self):
        resolved = resolve_openai_compatible_route(
            route(),
            environ={"OPENROUTER_API_KEY": "secret"},
        )
        self.assertEqual(resolved.provider, "openrouter")
        self.assertEqual(resolved.metadata["base_url"], "https://openrouter.ai/api/v1")
        self.assertEqual(resolved.metadata["api_key"], "secret")
        self.assertEqual(resolved.metadata["api_mode"], "chat_completions")

    def test_local_compatible_endpoint_does_not_require_remote_credential(self):
        resolved = resolve_openai_compatible_route(
            route(
                provider="custom",
                metadata={"base_url": "http://127.0.0.1:9000/v1"},
            ),
            environ={},
        )
        self.assertEqual(resolved.metadata["api_key"], "zn-local-noauth")

    def test_resource_sends_only_bounded_context_and_question(self):
        client = _FakeClient()
        built = {}

        def builder(**kwargs):
            built.update(kwargs)
            return client

        resource = OpenAICompatibleCognitiveResource(
            route(metadata={"api_key": "k", "base_url": "https://example.test/v1"}),
            client_builder=builder,
        )
        result = resource.invoke(question="what is missing?", context="bounded resident context")

        self.assertEqual(result.text, "bounded answer")
        self.assertEqual(result.usage["total_tokens"], 18)
        self.assertEqual(built["api_key"], "k")
        self.assertEqual(built["base_url"], "https://example.test/v1")
        self.assertEqual(
            client.request["messages"],
            [
                {"role": "system", "content": "bounded resident context"},
                {"role": "user", "content": "what is missing?"},
            ],
        )

    def test_worker_adapts_increment_without_constructing_old_agent(self):
        client = _FakeClient()
        resource = OpenAICompatibleCognitiveResource(
            route(metadata={"api_key": "k", "base_url": "https://example.test/v1"}),
            client_builder=lambda **_kwargs: client,
        )
        worker = CognitiveResourceWorker(resource)
        result = worker.run(Goal(goal_id="g1", task="solve bounded gap"), "ctx")

        self.assertTrue(result.success)
        self.assertEqual(result.response, "bounded answer")
        self.assertEqual(result.metrics["resource_owner"], "zn")
        self.assertEqual(result.metrics["model_invoked"], True)
        self.assertEqual(result.metrics["prompt_tokens"], 11)

    def test_non_chat_protocol_requires_separate_zn_transport(self):
        with self.assertRaisesRegex(ValueError, "dedicated ZN transport"):
            resolve_openai_compatible_route(
                route(metadata={"api_mode": "anthropic_messages"}),
                environ={"OPENROUTER_API_KEY": "secret"},
            )


if __name__ == "__main__":
    unittest.main()
