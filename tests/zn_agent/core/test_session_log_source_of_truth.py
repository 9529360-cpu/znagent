from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.anthropic_resource import (
    AnthropicCognitiveResource,
    AnthropicToolLoopClient,
)
from zn_agent.core.cognitive_resource import (
    CognitiveResourceWorker,
    OpenAICompatibleCognitiveResource,
)
from zn_agent.core.gemini_resource import GeminiCognitiveResource
from zn_agent.core.models import Goal, ModelRoute
from zn_agent.core.runtime import ZNKernelRuntime
from zn_agent.core.session_log import (
    SessionLog,
    content_fingerprint,
    rebuild_model_request,
)
from zn_agent.core.store import KernelStore


def _openai_route(**overrides):
    values = {
        "route_id": "r1",
        "provider": "openrouter",
        "model": "example/model",
        "capabilities": {"general": 0.8},
        "metadata": {
            "api_key": "k",
            "base_url": "https://example.test/v1",
            "temperature": 0.2,
            "max_tokens": 512,
        },
    }
    values.update(overrides)
    return ModelRoute(**values)


def _anthropic_route(**overrides):
    values = {
        "route_id": "claude",
        "provider": "anthropic",
        "model": "claude-test",
        "capabilities": {"general": 0.9},
        "metadata": {"api_key": "test-key", "max_tokens": 2048},
    }
    values.update(overrides)
    return ModelRoute(**values)


def _gemini_route(**overrides):
    values = {
        "route_id": "gemini",
        "provider": "gemini",
        "model": "google/gemini-3.1-pro",
        "capabilities": {"general": 0.9},
        "metadata": {"api_key": "test-key"},
    }
    values.update(overrides)
    return ModelRoute(**values)


class _OpenAICompletions:
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
                prompt_tokens=11, completion_tokens=7, total_tokens=18
            ),
        )


class _OpenAIClient:
    def __init__(self):
        self.request = None
        self.chat = SimpleNamespace(completions=_OpenAICompletions(self))

    def close(self):
        pass


class _AnthropicMessages:
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
            usage=SimpleNamespace(input_tokens=13, output_tokens=5),
        )


class _AnthropicClient:
    def __init__(self):
        self.request = None
        self.messages = _AnthropicMessages(self)

    def close(self):
        pass


class _GeminiResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class _GeminiClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def _gemini_ok_payload(text="bounded Gemini answer"):
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": text}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 12,
            "candidatesTokenCount": 6,
            "totalTokenCount": 18,
        },
    }


class SessionLogRebuildTests(unittest.TestCase):
    def test_openai_sent_request_rebuilds_exactly(self):
        log = SessionLog()
        client = _OpenAIClient()
        resource = OpenAICompatibleCognitiveResource(
            _openai_route(),
            client_builder=lambda **kwargs: client,
            session_sink=log,
        )
        resource.invoke(
            question="what is missing?",
            context="ZN bounded context",
            request_id="req-openai-1",
        )
        rebuilt = rebuild_model_request(log, "req-openai-1")
        # The log rebuilds the exact wire body the fake client received.
        self.assertEqual(rebuilt["request"], client.request)
        self.assertEqual(rebuilt["provider"], "openrouter")
        self.assertEqual(rebuilt["api_mode"], "chat_completions")
        self.assertEqual(rebuilt["response"]["text"], "bounded answer")
        self.assertEqual(rebuilt["response"]["finish_reason"], "stop")
        self.assertIsNone(rebuilt["failure"])
        # No credentials anywhere in the logged events.
        dumped = json.dumps([e.to_dict() for e in log.events_for_request("req-openai-1")])
        self.assertNotIn("api_key", dumped)
        self.assertNotIn("secret", dumped)

    def test_openai_log_holds_redacted_form_not_raw_secret(self):
        log = SessionLog()
        client = _OpenAIClient()
        resource = OpenAICompatibleCognitiveResource(
            _openai_route(),
            client_builder=lambda **kwargs: client,
            session_sink=log,
        )
        resource.invoke(
            question="Explain api_key=hunter2-secret-value handling",
            context="plain context",
            request_id="req-openai-redacted",
        )
        rebuilt = rebuild_model_request(log, "req-openai-redacted")
        # Wire and log agree, and both hold the scrubbed form only.
        self.assertEqual(rebuilt["request"], client.request)
        user_text = rebuilt["request"]["messages"][-1]["content"]
        self.assertNotIn("hunter2", user_text)
        self.assertIn("api_key", user_text)
        dumped = json.dumps([e.to_dict() for e in log.events_for_request("req-openai-redacted")])
        self.assertNotIn("hunter2", dumped)

    def test_openai_failed_send_still_rebuilds_request(self):
        log = SessionLog()

        class _FailingCompletions:
            def create(self, **kwargs):
                raise RuntimeError("connection reset")

        class _FailingClient:
            def __init__(self):
                self.chat = SimpleNamespace(completions=_FailingCompletions())

            def close(self):
                pass

        resource = OpenAICompatibleCognitiveResource(
            _openai_route(),
            client_builder=lambda **kwargs: _FailingClient(),
            session_sink=log,
        )
        with self.assertRaises(RuntimeError):
            resource.invoke(
                question="what is missing?",
                context="ctx",
                request_id="req-openai-failed",
            )
        # Sent was logged before the failure; the request is reconstructable
        # even though the provider outcome is unknown (DSH-3 shape).
        rebuilt = rebuild_model_request(log, "req-openai-failed")
        self.assertEqual(
            rebuilt["request"]["messages"][-1]["content"], "what is missing?"
        )
        self.assertIsNone(rebuilt["response"])
        self.assertEqual(rebuilt["failure"]["error_type"], "RuntimeError")

    def test_anthropic_sent_request_rebuilds_exactly(self):
        log = SessionLog()
        client = _AnthropicClient()
        resource = AnthropicCognitiveResource(
            _anthropic_route(metadata={"api_key": "k", "max_tokens": 2048}),
            client_builder=lambda **kwargs: client,
            session_sink=log,
        )
        resource.invoke(
            question="what is missing?",
            context="ZN bounded context",
            request_id="req-anthropic-1",
        )
        rebuilt = rebuild_model_request(log, "req-anthropic-1")
        self.assertEqual(rebuilt["request"], client.request)
        self.assertEqual(rebuilt["api_mode"], "anthropic_messages")
        self.assertEqual(rebuilt["response"]["text"], "bounded Claude answer")
        # Model thinking is returned on the increment but never logged.
        dumped = json.dumps([e.to_dict() for e in log.events_for_request("req-anthropic-1")])
        self.assertNotIn("private reasoning", dumped)

    def test_anthropic_tool_turn_logs_messages_tools_and_system(self):
        log = SessionLog()
        client = _AnthropicClient()
        tool_client = AnthropicToolLoopClient(
            _anthropic_route(metadata={"api_key": "k"}),
            client_builder=lambda **kwargs: client,
            session_sink=log,
        )

        class _ToolMessages:
            def __init__(self, owner):
                self.owner = owner

            def create(self, **kwargs):
                self.owner.request = kwargs
                return SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            type="tool_use",
                            id="toolu-1",
                            name="read_file",
                            input={"path": "notes.txt"},
                        )
                    ],
                    stop_reason="tool_use",
                    usage=SimpleNamespace(input_tokens=9, output_tokens=4),
                )

        client.messages = _ToolMessages(client)
        result = tool_client.create_turn(
            messages=[{"role": "user", "content": "read the file"}],
            system="tool loop system",
            tools=(
                {
                    "name": "read_file",
                    "description": "read a file",
                    "input_schema": {"type": "object"},
                },
            ),
            request_id="req-tool-turn-1",
        )
        self.assertEqual(result["tool_calls"][0]["name"], "read_file")
        rebuilt = rebuild_model_request(log, "req-tool-turn-1")
        self.assertEqual(rebuilt["request"], client.request)
        self.assertEqual(rebuilt["api_mode"], "anthropic_messages_tool_loop")
        self.assertEqual(rebuilt["request"]["tools"][0]["name"], "read_file")
        self.assertEqual(
            rebuilt["request"]["messages"][0]["content"], "read the file"
        )
        self.assertEqual(rebuilt["response"]["tool_calls"][0]["name"], "read_file")

    def test_gemini_sent_payload_rebuilds_exactly_without_key(self):
        log = SessionLog()
        client = _GeminiClient([_GeminiResponse(_gemini_ok_payload())])
        resource = GeminiCognitiveResource(
            _gemini_route(),
            client=client,
            session_sink=log,
        )
        resource.invoke(
            question="what is missing?",
            context="ZN bounded context",
            request_id="req-gemini-1",
        )
        rebuilt = rebuild_model_request(log, "req-gemini-1")
        sent_json = client.calls[0][1]["json"]
        self.assertEqual(rebuilt["request"], sent_json)
        self.assertEqual(rebuilt["api_mode"], "gemini_native")
        self.assertEqual(rebuilt["response"]["text"], "bounded Gemini answer")
        # The api key travels as a URL param, never in the logged body.
        dumped = json.dumps([e.to_dict() for e in log.events_for_request("req-gemini-1")])
        self.assertNotIn("test-key", dumped)
        self.assertNotIn("api_key", dumped)

    def test_gemini_image_logged_by_hash_not_bytes(self):
        log = SessionLog()
        client = _GeminiClient([_GeminiResponse(_gemini_ok_payload("visual answer"))])
        resource = GeminiCognitiveResource(
            _gemini_route(),
            client=client,
            session_sink=log,
        )
        image = b"\x89PNG-fake-screenshot-bytes"
        resource.invoke_image(
            question="Current stage instruction: click the button",
            context="visual system context",
            image_bytes=image,
            mime_type="image/png",
            request_id="req-gemini-image-1",
        )
        rebuilt = rebuild_model_request(log, "req-gemini-image-1")
        parts = rebuilt["request"]["contents"][0]["parts"]
        inline = parts[0]["inlineData"]
        self.assertEqual(inline["mimeType"], "image/png")
        self.assertEqual(inline["data"]["sha256"], hashlib.sha256(image).hexdigest())
        self.assertEqual(inline["data"]["bytes"], len(image))
        # Raw base64 never lands in the log.
        dumped = json.dumps([e.to_dict() for e in log.events_for_request("req-gemini-image-1")])
        self.assertNotIn(base64.b64encode(image).decode("ascii"), dumped)
        # But the wire call itself still carried the real bytes.
        wire = client.calls[0][1]["json"]
        self.assertEqual(
            wire["contents"][0]["parts"][0]["inlineData"]["data"],
            base64.b64encode(image).decode("ascii"),
        )

    def test_rebuild_missing_request_raises(self):
        log = SessionLog()
        with self.assertRaises(KeyError):
            rebuild_model_request(log, "req-never-logged")

    def test_worker_planned_event_links_to_sent_without_raw_text(self):
        log = SessionLog()
        client = _OpenAIClient()
        resource = OpenAICompatibleCognitiveResource(
            _openai_route(),
            client_builder=lambda **kwargs: client,
            session_sink=log,
        )
        worker = CognitiveResourceWorker(
            resource, route=_openai_route(), session_sink=log
        )
        goal = Goal(
            goal_id="goal-1",
            task="secret question api_key=hunter2-secret-value",
            required_capabilities=("general",),
            metadata={
                "resident_event_id": "evt-1",
                "cognition_request": {"request_id": "cog-abc", "context": {}},
            },
        )
        result = worker.run(goal, "kernel context with api_key=hunter2-secret-value")
        self.assertTrue(result.success)
        events = log.events_for_request(
            next(
                e.request_id
                for e in log.events_for_session("evt-1")
                if e.kind == "model_request_planned"
            )
        )
        kinds = [e.kind for e in events]
        self.assertEqual(
            kinds, ["model_request_planned", "model_request_sent", "model_response"]
        )
        planned = next(e for e in events if e.kind == "model_request_planned")
        # Correlation without raw pre-redaction text: hashes + lengths only.
        self.assertEqual(planned.payload["goal_id"], "goal-1")
        self.assertEqual(planned.payload["cognition_request_id"], "cog-abc")
        self.assertEqual(
            planned.payload["question_sha256"],
            content_fingerprint("secret question api_key=hunter2-secret-value"),
        )
        self.assertEqual(
            planned.payload["context_sha256"],
            content_fingerprint("kernel context with api_key=hunter2-secret-value"),
        )
        dumped = json.dumps([e.to_dict() for e in events])
        self.assertNotIn("hunter2", dumped)
        # Session listing resolves planned -> sent -> response for the session.
        session_events = log.events_for_session("evt-1")
        self.assertEqual(
            [e.kind for e in session_events],
            ["model_request_planned", "model_request_sent", "model_response"],
        )
        # Rebuild carries the planned correlation through.
        rebuilt = rebuild_model_request(log, planned.request_id)
        self.assertEqual(rebuilt["planned"]["goal_id"], "goal-1")
        self.assertEqual(rebuilt["session_id"], "evt-1")

    def test_worker_passes_request_id_only_when_supported(self):
        # Legacy-style resources without a request_id parameter still work:
        # the worker must not force the kwarg onto them.
        log = SessionLog()

        class _LegacyResource:
            def invoke(self, *, question, context):
                return SimpleNamespace(
                    text="legacy answer",
                    provider="legacy",
                    model="legacy-model",
                    finish_reason="stop",
                    usage={},
                )

        worker = CognitiveResourceWorker(
            _LegacyResource(), route=None, session_sink=log
        )
        result = worker.run(Goal(goal_id="g", task="q"), "ctx")
        self.assertTrue(result.success)
        self.assertEqual(result.response, "legacy answer")
        # Planned event still logged; no sent event (legacy resource logs none).
        planned = [
            e for e in log.events_for_session("g") if e.kind == "model_request_planned"
        ]
        self.assertEqual(len(planned), 1)

    def test_logging_failure_never_breaks_cognition(self):
        class _BrokenLog:
            def emit(self, *args, **kwargs):
                raise RuntimeError("store unavailable")

        client = _OpenAIClient()
        resource = OpenAICompatibleCognitiveResource(
            _openai_route(),
            client_builder=lambda **kwargs: client,
            session_sink=_BrokenLog(),
        )
        increment = resource.invoke(question="what is missing?", context="ctx")
        self.assertEqual(increment.text, "bounded answer")


class SessionLogDurabilityTests(unittest.TestCase):
    def test_store_backed_log_survives_new_log_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            log = SessionLog(store)
            client = _OpenAIClient()
            resource = OpenAICompatibleCognitiveResource(
                _openai_route(),
                client_builder=lambda **kwargs: client,
                session_sink=log,
            )
            resource.invoke(
                question="what is missing?",
                context="ctx",
                request_id="req-durable-1",
            )
            store.close()

            reopened = KernelStore(Path(tmp) / "kernel.db")
            rebuilt = rebuild_model_request(SessionLog(reopened), "req-durable-1")
            self.assertEqual(rebuilt["request"], client.request)
            self.assertEqual(rebuilt["response"]["text"], "bounded answer")
            # Append-only: seqs are monotonic across instances.
            first = reopened.session_events(limit=10)
            self.assertTrue(all(row["seq"] > 0 for row in first))
            reopened.close()

    def test_kernel_run_goal_request_rebuilds_from_log(self):
        # End-to-end: kernel -> worker -> real resource -> fake wire -> log
        # -> rebuild. The rebuilt request must contain the exact assembled
        # kernel context (identity preamble + bounded context JSON).
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            log = SessionLog(store)
            client = _OpenAIClient()

            class _Factory:
                def create(self, route):
                    resource = OpenAICompatibleCognitiveResource(
                        route,
                        client_builder=lambda **kwargs: client,
                        session_sink=log,
                    )
                    return CognitiveResourceWorker(
                        resource, route=route, session_sink=log
                    )

            kernel = ZNKernelRuntime(
                store=store,
                routes=[_openai_route()],
                worker_factory=_Factory(),
                max_attempts=1,
            )
            result = kernel.run_goal(
                "what is missing?",
                metadata={
                    "resident_event_id": "evt-kernel-1",
                    "cognition_request": {
                        "request_id": "cog-kernel-1",
                        "context": {"event_kind": "user_task", "task_excerpt": "do thing"},
                    },
                },
            )
            self.assertTrue(result.assessment.success)
            session_events = log.events_for_session("evt-kernel-1")
            sent = next(
                e for e in session_events if e.kind == "model_request_sent"
            )
            rebuilt = rebuild_model_request(log, sent.request_id)
            self.assertEqual(rebuilt["request"], client.request)
            system_text = rebuilt["request"]["messages"][0]["content"]
            # The assembled kernel context is what the model saw: identity
            # preamble plus the bounded-context JSON with the task excerpt.
            self.assertIn("You are ZN", system_text)
            self.assertIn("do thing", system_text)
            self.assertIn("BOUNDED CONTEXT", system_text)
            self.assertEqual(rebuilt["response"]["text"], "bounded answer")
            store.close()

    def test_unknown_kind_and_empty_request_id_rejected(self):
        log = SessionLog()
        with self.assertRaises(ValueError):
            log.emit("not_a_kind", request_id="req-x")
        with self.assertRaises(ValueError):
            log.emit("model_response", request_id="")
        with self.assertRaises(ValueError):
            log.emit("model_response", request_id="req-x", payload={"bad": object()})


if __name__ == "__main__":
    unittest.main()
