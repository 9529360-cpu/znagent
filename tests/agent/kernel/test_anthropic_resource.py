from __future__ import annotations

import unittest
from types import SimpleNamespace

from agent.kernel.anthropic_resource import (
    AnthropicCognitiveResource,
    resolve_anthropic_route,
)
from agent.kernel.cognitive_factory import (
    ZNCognitiveResourceWorkerFactory,
    resolve_zn_cognitive_route,
)
from agent.kernel.models import Goal, ModelRoute


def route(**overrides):
    values = {
        "route_id": "claude",
        "provider": "anthropic",
        "model": "claude-test",
        "capabilities": {"general": 0.9},
        "metadata": {"api_key": "test-key"},
    }
    values.update(overrides)
    return ModelRoute(**values)


class _Messages:
    def __init__(self, owner):
        self.owner = owner

    def create(self, **kwargs):
        self.owner.request = kwargs
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking="private reasoning"),
                SimpleNamespace(type="text", text="bounded Claude answer"),
            ],
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=13,
                output_tokens=5,
                cache_read_input_tokens=7,
                cache_creation_input_tokens=3,
            ),
        )


class _Client:
    def __init__(self):
        self.request = None
        self.messages = _Messages(self)


class AnthropicResourceTests(unittest.TestCase):
    def test_route_is_resolved_without_legacy_provider_registry(self):
        resolved = resolve_anthropic_route(
            route(metadata={}),
            environ={"ANTHROPIC_API_KEY": "env-key"},
        )
        self.assertEqual(resolved.provider, "anthropic")
        self.assertEqual(resolved.metadata["api_mode"], "anthropic_messages")
        self.assertEqual(resolved.metadata["api_key"], "env-key")

    def test_native_messages_request_is_bounded_and_normalized(self):
        client = _Client()
        built = {}

        def builder(**kwargs):
            built.update(kwargs)
            return client

        resource = AnthropicCognitiveResource(
            route(metadata={"api_key": "k", "max_tokens": 2048}),
            client_builder=builder,
        )
        increment = resource.invoke(question="what is missing?", context="ZN bounded context")

        self.assertEqual(built["api_key"], "k")
        self.assertEqual(client.request["system"], "ZN bounded context")
        self.assertEqual(
            client.request["messages"],
            [{"role": "user", "content": "what is missing?"}],
        )
        self.assertEqual(client.request["max_tokens"], 2048)
        self.assertEqual(increment.text, "bounded Claude answer")
        self.assertEqual(increment.finish_reason, "stop")
        self.assertEqual(increment.usage["prompt_tokens"], 13)
        self.assertEqual(increment.usage["completion_tokens"], 5)
        self.assertEqual(increment.usage["cache_read_input_tokens"], 7)
        self.assertEqual(increment.metadata["reasoning"], "private reasoning")

    def test_empty_terminal_end_turn_is_protocol_valid(self):
        class EmptyMessages:
            def create(self, **_kwargs):
                return SimpleNamespace(
                    content=[],
                    stop_reason="end_turn",
                    usage=SimpleNamespace(input_tokens=1, output_tokens=0),
                )

        client = SimpleNamespace(messages=EmptyMessages())
        increment = AnthropicCognitiveResource(
            route(), client_builder=lambda **_kwargs: client
        ).invoke(question="q", context="ctx")
        self.assertEqual(increment.text, "")
        self.assertEqual(increment.finish_reason, "stop")

    def test_factory_dispatches_anthropic_without_constructing_old_agent(self):
        resolved = resolve_zn_cognitive_route(route())
        client = _Client()
        factory = ZNCognitiveResourceWorkerFactory(
            anthropic_client_builder=lambda **_kwargs: client
        )
        worker = factory.create(resolved)
        result = worker.run(Goal(goal_id="g", task="bounded question"), "ctx")
        self.assertTrue(result.success)
        self.assertEqual(result.response, "bounded Claude answer")
        self.assertEqual(result.metrics["resource_owner"], "zn")
        self.assertEqual(result.metrics["provider"], "anthropic")


if __name__ == "__main__":
    unittest.main()
