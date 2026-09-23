from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.anthropic_resource import AnthropicCognitiveResource
from zn_agent.core.cognitive_resource import (
    CognitiveResourceWorker,
    OpenAICompatibleCognitiveResource,
)
from zn_agent.core.models import Goal, ModelRoute


_ADAPTERS = (
    ("openai", OpenAICompatibleCognitiveResource),
    ("anthropic", AnthropicCognitiveResource),
)


def _route(provider):
    return ModelRoute(
        "lifecycle", provider, "bounded-test-model", {"general": 1.0},
        metadata={
            "api_key": "synthetic-no-network-key",
            "base_url": "https://provider.invalid/v1",
            "timeout": 17.5,
            "max_tokens": 32,
        },
    )


class _Client:
    """Protocol fault fixture; no model, remote endpoint, or shared SDK state."""

    def __init__(self, *, error=None, malformed=False, close_error=None):
        self.error = error
        self.malformed = malformed
        self.close_error = close_error
        self.close_count = 0
        self.requests = []
        self.chat = SimpleNamespace(completions=self)
        self.messages = self

    def create(self, **request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.malformed:
            return SimpleNamespace(choices=[], content=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="bounded response"), finish_reason="stop",
            )],
            content=[{"type": "text", "text": "bounded response"}],
            stop_reason="end_turn",
            usage=SimpleNamespace(
                prompt_tokens=2, completion_tokens=3, total_tokens=5,
                input_tokens=2, output_tokens=3,
            ),
        )

    def close(self):
        self.close_count += 1
        if self.close_error is not None:
            raise self.close_error


class CognitiveClientLifecycleTests(unittest.TestCase):
    def test_success_closes_client_and_disables_hidden_sdk_retries(self):
        for provider, adapter in _ADAPTERS:
            with self.subTest(provider=provider):
                client = _Client()
                options = {}

                def builder(**kwargs):
                    options.update(kwargs)
                    return client

                result = adapter(_route(provider), client_builder=builder).invoke(
                    question="Explain this", context="current bounded evidence",
                )
                self.assertEqual(result.text, "bounded response")
                self.assertEqual(result.usage["total_tokens"], 5)
                self.assertEqual(options.get("max_retries"), 0)
                self.assertEqual(options["timeout"], 17.5)
                self.assertEqual(options["base_url"], "https://provider.invalid/v1")
                self.assertEqual(client.close_count, 1)
                self.assertEqual(len(client.requests), 1)
                self.assertEqual(client.requests[0]["messages"][-1]["content"], "Explain this")

    def test_transport_failure_and_interruption_keep_exact_exception_and_cleanup(self):
        for provider, adapter in _ADAPTERS:
            for error in (TimeoutError("request interrupted"), KeyboardInterrupt()):
                with self.subTest(provider=provider, error=type(error).__name__):
                    client = _Client(error=error)
                    resource = adapter(_route(provider), client_builder=lambda **_: client)
                    with self.assertRaises(type(error)) as caught:
                        resource.invoke(question="current request", context="bounded")
                    self.assertIs(caught.exception, error)
                    self.assertEqual(client.close_count, 1)
                    self.assertEqual(len(client.requests), 1)

    def test_malformed_response_is_rejected_after_client_is_closed(self):
        for provider, adapter in _ADAPTERS:
            with self.subTest(provider=provider):
                client = _Client(malformed=True)
                resource = adapter(_route(provider), client_builder=lambda **_: client)
                with self.assertRaises(RuntimeError):
                    resource.invoke(question="current request", context="bounded")
                self.assertEqual(client.close_count, 1)
                self.assertEqual(len(client.requests), 1)

    def test_later_explicit_invocation_uses_a_new_client_not_closed_pool(self):
        for provider, adapter in _ADAPTERS:
            with self.subTest(provider=provider):
                clients = []

                def builder(**kwargs):
                    client = _Client()
                    clients.append(client)
                    return client

                resource = adapter(_route(provider), client_builder=builder)
                for _ in range(3):
                    self.assertEqual(resource.invoke(question="request", context="ctx").text, "bounded response")
                self.assertEqual(len(clients), 3)
                self.assertTrue(all(c.close_count == 1 and len(c.requests) == 1 for c in clients))

    def test_cleanup_failure_does_not_replace_result_or_expose_exception_text(self):
        for provider, adapter in _ADAPTERS:
            with self.subTest(provider=provider):
                client = _Client(close_error=OSError("synthetic-private-close-detail"))
                resource = adapter(_route(provider), client_builder=lambda **_: client)
                with self.assertLogs("zn_agent.core.cognitive_resource", level="WARNING") as logs:
                    result = resource.invoke(question="request", context="ctx")
                self.assertEqual(result.text, "bounded response")
                self.assertEqual(client.close_count, 1)
                self.assertIn("OSError", " ".join(logs.output))
                self.assertNotIn("synthetic-private-close-detail", " ".join(logs.output))

    def test_cleanup_failure_keeps_provider_exception_and_health_observation(self):
        for provider, adapter in _ADAPTERS:
            with self.subTest(provider=provider):
                original = TimeoutError("provider timeout")
                client = _Client(error=original, close_error=OSError("private-close-detail"))
                resource = adapter(_route(provider), client_builder=lambda **_: client)
                observations = []
                worker = CognitiveResourceWorker(
                    resource, route=_route(provider),
                    health_observer=lambda route, error: observations.append(error),
                )
                with self.assertLogs("zn_agent.core.cognitive_resource", level="WARNING"):
                    result = worker.run(Goal("lifecycle-goal", "request"), "ctx")
                self.assertFalse(result.success)
                self.assertEqual(result.error, "TimeoutError: provider timeout")
                self.assertEqual(observations, [original])
                self.assertEqual(client.close_count, 1)
                self.assertEqual(len(client.requests), 1)
                self.assertTrue(result.metrics["model_invoked"])

    def test_empty_request_does_not_allocate_client(self):
        for provider, adapter in _ADAPTERS:
            with self.subTest(provider=provider):
                def builder(**kwargs):
                    self.fail("empty question allocated an SDK client")
                with self.assertRaises(ValueError):
                    adapter(_route(provider), client_builder=builder).invoke(question=" ", context="ctx")

    def test_client_construction_error_is_not_retried_or_replaced(self):
        for provider, adapter in _ADAPTERS:
            with self.subTest(provider=provider):
                calls = []
                error = RuntimeError("client unavailable")
                def builder(**kwargs):
                    calls.append(kwargs)
                    raise error
                with self.assertRaises(RuntimeError) as caught:
                    adapter(_route(provider), client_builder=builder).invoke(question="request", context="ctx")
                self.assertIs(caught.exception, error)
                self.assertEqual(len(calls), 1)


class CognitiveOpenAiSdkLifecycleTests(unittest.TestCase):
    """The pinned runtime SDK with an in-memory HTTP boundary; never a paid call."""

    def _worker(self, handler):
        import httpx
        from openai import OpenAI

        clients = []
        def builder(**kwargs):
            transport = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
            client = OpenAI(http_client=transport, **kwargs)
            clients.append(client)
            self.addCleanup(client.close)
            return client

        resource = OpenAICompatibleCognitiveResource(_route("openai"), client_builder=builder)
        return CognitiveResourceWorker(resource), clients

    def test_sdk_server_error_sends_one_request_and_closes_pool(self):
        import httpx
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(500, json={"error": {"message": "fixture failure", "type": "server_error"}})
        worker, clients = self._worker(handler)
        result = worker.run(Goal("sdk-failure", "request"), "bounded context")
        self.assertFalse(result.success)
        self.assertEqual(len(requests), 1, "SDK retried inside one durable Worker attempt")
        self.assertTrue(clients[0].is_closed())
        self.assertTrue(result.metrics["model_invoked"])

    def test_sdk_timeout_does_not_replay_and_closes_pool(self):
        import httpx
        requests = []
        def handler(request):
            requests.append(request)
            raise httpx.ReadTimeout("fixture timeout", request=request)
        worker, clients = self._worker(handler)
        result = worker.run(Goal("sdk-timeout", "request"), "bounded context")
        self.assertFalse(result.success)
        self.assertEqual(len(requests), 1)
        self.assertTrue(clients[0].is_closed())

    def test_sdk_success_retains_response_and_usage_after_close(self):
        import httpx
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={
                "id": "fixture-completion", "object": "chat.completion", "created": 1,
                "model": "bounded-test-model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "wire response"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            })
        worker, clients = self._worker(handler)
        result = worker.run(Goal("sdk-success", "request"), "bounded context")
        self.assertTrue(result.success)
        self.assertEqual(result.response, "wire response")
        self.assertEqual(result.metrics["total_tokens"], 5)
        self.assertEqual(len(requests), 1)
        self.assertTrue(clients[0].is_closed())


if __name__ == "__main__":
    unittest.main()
