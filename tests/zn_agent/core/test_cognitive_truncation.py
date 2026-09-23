from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.cognitive_resource import (
    CognitiveIncrement,
    CognitiveResourceWorker,
    CognitiveResourceWorkerFactory,
    OpenAICompatibleCognitiveResource,
)
from zn_agent.core.critic import DefaultCritic
from zn_agent.core.models import Goal, GoalStatus, ModelRoute


_PARTIAL = 'private partial answer {"zn_work_step":{"kind":"write_file"}}'


def _route(provider="custom"):
    return ModelRoute(
        "truncation", provider, "fixture-model", {"general": 1.0},
        metadata={
            "api_key": "synthetic-no-network-key",
            "base_url": "https://provider.invalid/v1",
            "max_tokens": 32,
        },
    )


def _increment(text=_PARTIAL, finish_reason="length"):
    return CognitiveIncrement(
        text=text, provider="fixture", model="fixture-model",
        finish_reason=finish_reason,
        usage={"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
    )


class _Resource:
    def __init__(self, increment=None, error=None):
        self.increment = increment or _increment()
        self.error = error
        self.calls = []

    def invoke(self, *, question, context):
        self.calls.append((question, context))
        if self.error is not None:
            raise self.error
        return self.increment


class CognitiveTruncationTests(unittest.TestCase):
    def test_truncated_text_cannot_become_answer_or_proposal_but_usage_survives(self):
        for text in (_PARTIAL, '{"result":"done"}', "Everything is complete."):
            with self.subTest(text=text):
                resource = _Resource(_increment(text))
                observations = []
                worker = CognitiveResourceWorker(
                    resource, route=_route(),
                    health_observer=lambda route, error: observations.append(error),
                )
                result = worker.run(Goal("limited", "current question"), "bounded context")
                self.assertFalse(result.success)
                self.assertEqual(result.response, "")
                self.assertIn("truncated", result.error)
                self.assertNotIn(text, result.error)
                self.assertIsNone(result.verification_passed)
                self.assertEqual(result.metrics["finish_reason"], "length")
                self.assertIs(result.metrics["response_truncated"], True)
                self.assertEqual(result.metrics["prompt_tokens"], 2)
                self.assertEqual(result.metrics["completion_tokens"], 3)
                self.assertEqual(result.metrics["total_tokens"], 5)
                self.assertEqual(result.metrics["provider"], "fixture")
                self.assertEqual(result.metrics["model"], "fixture-model")
                self.assertEqual(result.metrics["resource_owner"], "zn")
                self.assertIs(result.metrics["model_invoked"], True)
                self.assertEqual(resource.calls, [("current question", "bounded context")])
                self.assertEqual(observations, [None], "valid transport is not a route outage")
                self.assertEqual(resource.increment.text, text, "do not mutate the provider increment")

    def test_existing_critic_rejects_nonempty_but_token_limited_cognition(self):
        goal = Goal("limited", "explain")
        result = CognitiveResourceWorker(_Resource()).run(goal, "bounded")
        self.assertFalse(DefaultCritic().assess(goal, result).success)

    def test_normal_or_unspecified_finish_keeps_existing_behavior(self):
        for reason in ("stop", None):
            with self.subTest(reason=reason):
                resource = _Resource(_increment("complete answer", reason))
                result = CognitiveResourceWorker(resource).run(Goal("normal", "explain"), "ctx")
                self.assertTrue(result.success)
                self.assertEqual(result.response, "complete answer")
                self.assertIsNone(result.error)
                self.assertNotIn("response_truncated", result.metrics)
                self.assertEqual(result.metrics["total_tokens"], 5)
                self.assertEqual(len(resource.calls), 1)

    def test_later_explicit_call_can_succeed_without_automatic_continuation(self):
        resource = _Resource()
        worker = CognitiveResourceWorker(resource)
        first = worker.run(Goal("first", "first question"), "first context")
        self.assertFalse(first.success)
        self.assertEqual(len(resource.calls), 1)
        resource.increment = _increment("complete next answer", "stop")
        second = worker.run(Goal("second", "second question"), "second context")
        self.assertTrue(second.success)
        self.assertEqual(second.response, "complete next answer")
        self.assertEqual(resource.calls, [
            ("first question", "first context"), ("second question", "second context"),
        ])

    def test_secondary_health_failure_cannot_promote_partial_response(self):
        def unavailable_health(route, error):
            raise OSError("health journal unavailable")
        result = CognitiveResourceWorker(
            _Resource(), route=_route(), health_observer=unavailable_health,
        ).run(Goal("health", "explain"), "ctx")
        self.assertFalse(result.success)
        self.assertEqual(result.response, "")
        self.assertEqual(result.metrics["total_tokens"], 5)
        self.assertNotIn("health journal", result.error)

    def test_provider_exception_keeps_existing_failure_observation(self):
        error = TimeoutError("fixture timeout")
        resource = _Resource(error=error)
        observations = []
        result = CognitiveResourceWorker(
            resource, route=_route(),
            health_observer=lambda route, observed: observations.append(observed),
        ).run(Goal("exception", "explain"), "ctx")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "TimeoutError: fixture timeout")
        self.assertEqual(observations, [error])
        self.assertNotIn("response_truncated", result.metrics)
        self.assertEqual(len(resource.calls), 1)


class _ProtocolClient:
    """Injected wire response, not a provider or model-quality simulation."""

    def __init__(self, response):
        self.response = response
        self.chat = SimpleNamespace(completions=self)
        self.messages = self
        self.requests = []
        self.closed = 0

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.response

    def close(self):
        self.closed += 1


class CognitiveTruncationAdapterTests(unittest.TestCase):
    def test_openai_wire_length_reaches_worker_without_budget_change_or_retry(self):
        client = _ProtocolClient(SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=_PARTIAL), finish_reason="length",
            )],
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
        ))
        options = {}
        def builder(**kwargs):
            options.update(kwargs)
            return client
        resource = OpenAICompatibleCognitiveResource(_route(), client_builder=builder)
        result = CognitiveResourceWorker(resource).run(Goal("wire", "explain"), "ctx")
        self.assertFalse(result.success)
        self.assertEqual(result.response, "")
        self.assertEqual(result.metrics["total_tokens"], 5)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(client.requests[0]["max_tokens"], 32)
        self.assertEqual(options["max_retries"], 0)
        self.assertEqual(client.closed, 1)

    def test_anthropic_output_and_context_limits_are_not_success(self):
        from zn_agent.core.anthropic_resource import AnthropicCognitiveResource
        for reason in ("max_tokens", "model_context_window_exceeded"):
            with self.subTest(reason=reason):
                client = _ProtocolClient(SimpleNamespace(
                    content=[{"type": "text", "text": _PARTIAL}], stop_reason=reason,
                    usage=SimpleNamespace(input_tokens=2, output_tokens=3),
                ))
                resource = AnthropicCognitiveResource(
                    _route("anthropic"), client_builder=lambda **_: client,
                )
                result = CognitiveResourceWorker(resource).run(Goal("native", "explain"), "ctx")
                self.assertFalse(result.success)
                self.assertEqual(result.response, "")
                self.assertEqual(result.metrics["finish_reason"], "length")
                self.assertEqual(result.metrics["total_tokens"], 5)
                self.assertEqual(len(client.requests), 1)
                self.assertEqual(client.requests[0]["max_tokens"], 32)
                self.assertEqual(client.closed, 1)

    def test_gemini_native_max_tokens_is_not_success(self):
        import httpx
        from zn_agent.core.gemini_resource import GeminiCognitiveResource
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={
                "candidates": [{
                    "content": {"parts": [{"text": _PARTIAL}]},
                    "finishReason": "MAX_TOKENS",
                }],
                "usageMetadata": {
                    "promptTokenCount": 2, "candidatesTokenCount": 3, "totalTokenCount": 5,
                },
            })
        with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
            resource = GeminiCognitiveResource(_route("gemini"), client=client)
            result = CognitiveResourceWorker(resource).run(Goal("native", "explain"), "ctx")
        self.assertFalse(result.success)
        self.assertEqual(result.response, "")
        self.assertEqual(result.metrics["finish_reason"], "length")
        self.assertEqual(result.metrics["total_tokens"], 5)
        self.assertEqual(len(requests), 1)


class CognitiveTruncationSdkTests(unittest.TestCase):
    def test_pinned_openai_sdk_keeps_token_limited_success_http_as_failed_cognition(self):
        import httpx
        from openai import OpenAI
        requests = []
        clients = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={
                "id": "fixture-limited", "object": "chat.completion", "created": 1,
                "model": "fixture-model",
                "choices": [{
                    "index": 0, "message": {"role": "assistant", "content": _PARTIAL},
                    "finish_reason": "length",
                }],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            })
        def builder(**kwargs):
            transport = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
            self.addCleanup(transport.close)
            client = OpenAI(http_client=transport, **kwargs)
            self.addCleanup(client.close)
            clients.append(client)
            return client
        resource = OpenAICompatibleCognitiveResource(_route(), client_builder=builder)
        result = CognitiveResourceWorker(resource).run(Goal("sdk", "explain"), "ctx")
        self.assertFalse(result.success)
        self.assertEqual(result.response, "")
        self.assertEqual(result.metrics["finish_reason"], "length")
        self.assertEqual(result.metrics["total_tokens"], 5)
        self.assertEqual(len(requests), 1)
        self.assertTrue(clients[0].is_closed())


class CognitiveTruncationDurabilityTests(unittest.TestCase):
    def test_failed_cognition_survives_kernel_reconstruction_without_provider_replay(self):
        from zn_agent.core.runtime import ZNKernelRuntime
        from zn_agent.core.store import KernelStore
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resource = _Resource()
            store = KernelStore(db)
            try:
                kernel = ZNKernelRuntime(
                    store=store, routes=[_route()], max_attempts=1,
                    worker_factory=CognitiveResourceWorkerFactory(lambda route: resource),
                )
                first = kernel.run_goal("explain", goal_id="durable-truncation")
                self.assertEqual(first.goal.status, GoalStatus.FAILED)
                self.assertFalse(first.assessment.success)
                self.assertEqual(first.worker_result.response, "")
                self.assertEqual(first.worker_result.metrics["total_tokens"], 5)
                self.assertEqual(len(resource.calls), 1)
                self.assertEqual(len(first.experiences), 1)
                self.assertFalse(first.experiences[0].assessment.success)
                self.assertEqual(first.experiences[0].response_excerpt, "")
            finally:
                store.close()

            factory_calls = []
            def no_replay(route):
                factory_calls.append(route)
                self.fail("terminal truncation was replayed after reconstruction")
            reopened = KernelStore(db)
            try:
                restored = ZNKernelRuntime(
                    store=reopened, routes=[_route()], max_attempts=1,
                    worker_factory=CognitiveResourceWorkerFactory(no_replay),
                ).run_goal("explain", goal_id="durable-truncation")
                self.assertEqual(factory_calls, [])
                self.assertEqual(restored.goal.status, GoalStatus.FAILED)
                self.assertFalse(restored.assessment.success)
                self.assertEqual(restored.worker_result.response, "")
                self.assertEqual(restored.worker_result.metrics, first.worker_result.metrics)
                self.assertEqual(
                    [item.experience_id for item in restored.experiences],
                    [item.experience_id for item in first.experiences],
                )
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
