from __future__ import annotations

"""CM-3 follow-ups: F1 (completion summary + nickname bypass), F2 (Work
ledger / journal_message bypass), W-2 (egress redaction at model-call
boundaries).

All secrets in this file are obviously fake (``sk-test-fake-...``).
"""

import base64
import dataclasses
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core import (
    anthropic_resource as anthropic_module,
)
from zn_agent.core import (
    cognitive_resource as cognitive_module,
)
from zn_agent.core import (
    gemini_resource as gemini_module,
)
from zn_agent.core import (
    completion_summary as completion_summary_module,
)
from zn_agent.core import (
    project_team as project_team_module,
)
from zn_agent.core import (
    two_level_memory as two_level_module,
)
from zn_agent.core import (
    work as work_module,
)
from zn_agent.core.anthropic_resource import (
    AnthropicCognitiveResource,
    AnthropicToolLoopClient,
)
from zn_agent.core.cognitive_resource import OpenAICompatibleCognitiveResource
from zn_agent.core.completion_summary import (
    recall_summary_for_event,
    save_completion_summary,
)
from zn_agent.core.gemini_resource import GeminiCognitiveResource
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.models import ModelRoute
from zn_agent.core.privacy_choke import redact_for_egress, strip_tags
from zn_agent.core.project_team import journal_message
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.store import KernelStore
from zn_agent.core.two_level_memory import (
    capture_nickname,
    list_nicknames,
    resolve_nickname,
)
from zn_agent.core.work import ResidentWorkLedger

FAKE_KEY = "sk-test-fake-9f8e7d6c5b4a"
FAKE_ASSIGNMENT = f"api_key={FAKE_KEY}"


def _route(**overrides):
    values = {
        "route_id": "r1",
        "provider": "custom",
        "model": "fixture-model",
        "capabilities": {"general": 0.8},
        "metadata": {"api_key": "test-key", "base_url": "https://provider.invalid/v1"},
    }
    values.update(overrides)
    return ModelRoute(**values)


def _openai_route(**overrides):
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
                prompt_tokens=11, completion_tokens=7, total_tokens=18
            ),
        )


class _FakeOpenAIClient:
    def __init__(self):
        self.request = None
        self.chat = SimpleNamespace(completions=_FakeCompletions(self))


class _FakeAnthropicMessages:
    def __init__(self, owner):
        self.owner = owner

    def create(self, **kwargs):
        self.owner.request = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="bounded Claude answer")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=13, output_tokens=5),
        )


class _FakeAnthropicClient:
    def __init__(self):
        self.request = None
        self.messages = _FakeAnthropicMessages(self)


class _FakeGeminiResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class _FakeGeminiClient:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeGeminiResponse(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "bounded Gemini answer"}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 12,
                    "candidatesTokenCount": 6,
                    "totalTokenCount": 18,
                },
            }
        )


class F1CompletionSummaryTests(unittest.TestCase):
    def test_save_completion_summary_chokes_raw_summary(self):
        """save_ must choke even when the summary was NOT built by build_."""
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "memory.db")
            try:
                memory = StructuredMemory(store)
                summary = {
                    "memory_category": "project_summary",
                    "source": "work_completion_summary",
                    "thread_id": "t1",
                    "thread_title": "Do the thing",
                    "event_id": "evt-f1",
                    "goal": f"Deploy with {FAKE_ASSIGNMENT} in config",
                    "success": True,
                    "completed_at": "2026-10-15T00:00:00Z",
                    "key_decisions": [],
                    "deliverables": [],
                    "pitfalls": [
                        {
                            "text": f"Failed while using {FAKE_ASSIGNMENT}",
                            "evidence_refs": ["event:evt-f1"],
                        }
                    ],
                    "open_items": [],
                    "evidence_refs": ["event:evt-f1"],
                    "dropped_decisions": 0,
                }
                save_completion_summary(memory, summary)
                stored = recall_summary_for_event(memory, "evt-f1")
                self.assertIsNotNone(stored)
                self.assertNotIn(FAKE_KEY, json.dumps(stored, ensure_ascii=False))
                self.assertIn("api_key <redacted>", stored["goal"])
            finally:
                store.close()


class F1NicknameTests(unittest.TestCase):
    def test_capture_nickname_chokes_name_and_canonical(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "memory.db")
            try:
                memory = StructuredMemory(store)
                self.assertTrue(
                    capture_nickname(
                        memory,
                        f"小李 {FAKE_ASSIGNMENT}",
                        f"李工 {FAKE_ASSIGNMENT}",
                        source=f"note {FAKE_ASSIGNMENT}",
                    )
                )
                stored = json.dumps(
                    [f for f in store.list_facts()], ensure_ascii=False
                )
                self.assertNotIn(FAKE_KEY, stored)
                # A choked nickname still resolves via the same choked lookup.
                resolved = resolve_nickname(memory, f"小李 {FAKE_ASSIGNMENT}")
                self.assertIsNotNone(resolved)
                self.assertNotIn(FAKE_KEY, resolved)
                self.assertIn("李工", resolved)
                nicknames = list_nicknames(memory)
                self.assertNotIn(FAKE_KEY, json.dumps(nicknames, ensure_ascii=False))
            finally:
                store.close()

    def test_capture_nickname_normal_round_trip_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "memory.db")
            try:
                memory = StructuredMemory(store)
                self.assertTrue(capture_nickname(memory, "阿豪", "用户"))
                self.assertEqual(resolve_nickname(memory, "阿豪"), "用户")
            finally:
                store.close()


class F2JournalTests(unittest.TestCase):
    def test_journal_message_chokes_text_and_identifiers(self):
        payload = journal_message(
            "team-1", "dev", f"Rotated {FAKE_ASSIGNMENT} after deploy"
        )
        self.assertNotIn(FAKE_KEY, json.dumps(payload, ensure_ascii=False))
        self.assertIn("api_key <redacted>", payload["text"])

    def test_journal_message_normal_text_unchanged(self):
        payload = journal_message("team-1", "dev", "Shipped the report.")
        self.assertEqual(payload["text"], "Shipped the report.")
        self.assertEqual(payload["role"], "team:team-1:dev")


class F2LedgerTests(unittest.TestCase):
    def _ledger(self, tmp):
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )
        return resident, ResidentWorkLedger(resident)

    def test_append_message_chokes_text_and_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger = self._ledger(tmp)
            try:
                thread = ledger.create_thread(thread_id="work-f2")
                ledger.append_message(
                    thread.thread_id,
                    role="team:team-1:dev",
                    text=f"Found {FAKE_ASSIGNMENT} in the log",
                    detail={"kind": "note", "note": FAKE_ASSIGNMENT},
                )
                messages = ledger.list_messages(thread.thread_id)
                self.assertEqual(len(messages), 1)
                self.assertNotIn(
                    FAKE_KEY,
                    json.dumps(
                        dataclasses.asdict(messages[0]), ensure_ascii=False
                    ),
                )
                self.assertIn("api_key <redacted>", messages[0].text)
            finally:
                resident.store.close()

    def test_append_message_normal_text_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger = self._ledger(tmp)
            try:
                thread = ledger.create_thread(thread_id="work-f2-normal")
                ledger.append_message(
                    thread.thread_id,
                    role="team:team-1:dev",
                    text="Shipped the report.",
                    detail={"kind": "note"},
                )
                messages = ledger.list_messages(thread.thread_id)
                self.assertEqual(messages[0].text, "Shipped the report.")
            finally:
                resident.store.close()

    def test_create_thread_chokes_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger = self._ledger(tmp)
            try:
                thread = ledger.create_thread(
                    thread_id="work-f2-title",
                    title=f"Deploy {FAKE_ASSIGNMENT}",
                )
                self.assertNotIn(FAKE_KEY, thread.title)
                self.assertIn("api_key <redacted>", thread.title)
            finally:
                resident.store.close()


class W2OpenAITests(unittest.TestCase):
    def test_invoke_redacts_question_and_context_before_send(self):
        client = _FakeOpenAIClient()

        def builder(**kwargs):
            return client

        resource = OpenAICompatibleCognitiveResource(
            _openai_route(
                metadata={
                    "api_key": "k",
                    "base_url": "https://provider.invalid/v1",
                }
            ),
            client_builder=builder,
        )
        resource.invoke(
            question=f"Explain {FAKE_ASSIGNMENT}",
            context=f"System context mentions {FAKE_ASSIGNMENT}",
        )
        sent = json.dumps(client.request, ensure_ascii=False)
        self.assertNotIn(FAKE_KEY, sent)
        messages = client.request["messages"]
        self.assertIn("api_key <redacted>", messages[-1]["content"])
        self.assertIn("api_key <redacted>", messages[0]["content"])

    def test_invoke_normal_text_unchanged(self):
        client = _FakeOpenAIClient()

        def builder(**kwargs):
            return client

        resource = OpenAICompatibleCognitiveResource(
            _openai_route(
                metadata={
                    "api_key": "k",
                    "base_url": "https://provider.invalid/v1",
                }
            ),
            client_builder=builder,
        )
        resource.invoke(question="What is missing?", context="ZN bounded context")
        self.assertEqual(
            client.request["messages"],
            [
                {"role": "system", "content": "ZN bounded context"},
                {"role": "user", "content": "What is missing?"},
            ],
        )


class W2AnthropicTests(unittest.TestCase):
    def test_invoke_redacts_question_and_context_before_send(self):
        client = _FakeAnthropicClient()

        def builder(**kwargs):
            return client

        resource = AnthropicCognitiveResource(
            _route(metadata={"api_key": "k", "max_tokens": 2048}),
            client_builder=builder,
        )
        resource.invoke(
            question=f"Explain {FAKE_ASSIGNMENT}",
            context=f"System context mentions {FAKE_ASSIGNMENT}",
        )
        sent = json.dumps(client.request, ensure_ascii=False)
        self.assertNotIn(FAKE_KEY, sent)
        self.assertIn(
            "api_key <redacted>", client.request["messages"][0]["content"]
        )
        self.assertIn("api_key <redacted>", client.request["system"])

    def test_create_turn_redacts_tool_result_content_and_system(self):
        client = _FakeAnthropicClient()

        def builder(**kwargs):
            return client

        tool_loop = AnthropicToolLoopClient(
            _route(metadata={"api_key": "k"}), client_builder=builder
        )
        tool_loop.create_turn(
            messages=[
                {"role": "user", "content": "read the config"},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_1",
                            "content": f"config holds {FAKE_ASSIGNMENT}",
                        }
                    ],
                },
            ],
            system=f"Be helpful. Note {FAKE_ASSIGNMENT}",
            tools=(),
        )
        sent = json.dumps(client.request, ensure_ascii=False)
        self.assertNotIn(FAKE_KEY, sent)
        self.assertIn("api_key <redacted>", client.request["system"])

    def test_create_turn_keeps_long_benign_tool_result_intact(self):
        """Egress has no overlong-field replacement: a 40k benign tool
        result must reach the model whole (capture side still replaces)."""
        client = _FakeAnthropicClient()

        def builder(**kwargs):
            return client

        tool_loop = AnthropicToolLoopClient(
            _route(metadata={"api_key": "k"}), client_builder=builder
        )
        long_text = "y" * 40000
        tool_loop.create_turn(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_1",
                            "content": long_text,
                        }
                    ],
                },
            ],
            system="be helpful",
            tools=(),
        )
        sent_block = client.request["messages"][0]["content"][0]
        self.assertEqual(sent_block["content"], long_text)

    def test_create_turn_still_scrubs_secret_inside_long_text(self):
        client = _FakeAnthropicClient()

        def builder(**kwargs):
            return client

        tool_loop = AnthropicToolLoopClient(
            _route(metadata={"api_key": "k"}), client_builder=builder
        )
        long_text = "y" * 40000 + f" {FAKE_ASSIGNMENT}"
        tool_loop.create_turn(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_1",
                            "content": long_text,
                        }
                    ],
                },
            ],
            system="be helpful",
            tools=(),
        )
        sent_block = client.request["messages"][0]["content"][0]
        self.assertNotIn(FAKE_KEY, sent_block["content"])
        self.assertIn("api_key <redacted>", sent_block["content"])
        self.assertGreater(len(sent_block["content"]), 40000)


class W2GeminiTests(unittest.TestCase):
    def test_invoke_redacts_question_and_context_before_send(self):
        client = _FakeGeminiClient()
        resource = GeminiCognitiveResource(
            _route(metadata={"api_key": "k"}), client=client
        )
        resource.invoke(
            question=f"Explain {FAKE_ASSIGNMENT}",
            context=f"System context mentions {FAKE_ASSIGNMENT}",
        )
        sent = json.dumps(client.calls[0][1], ensure_ascii=False)
        self.assertNotIn(FAKE_KEY, sent)
        self.assertIn("api_key <redacted>", sent)

    def test_invoke_image_scrubs_text_but_preserves_image_bytes(self):
        client = _FakeGeminiClient()
        resource = GeminiCognitiveResource(
            _route(metadata={"api_key": "k"}), client=client
        )
        image = bytes(range(256)) * 4
        resource.invoke_image(
            question=f"Describe this. Note {FAKE_ASSIGNMENT}",
            context="vision context",
            image_bytes=image,
            mime_type="image/png",
        )
        payload = client.calls[0][1]["json"]
        sent = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(FAKE_KEY, sent)
        parts = payload["contents"][0]["parts"]
        image_part = next(p for p in parts if "inlineData" in p)
        self.assertEqual(
            image_part["inlineData"]["data"],
            base64.b64encode(image).decode("ascii"),
        )


class EgressHelperTests(unittest.TestCase):
    def test_redact_for_egress_keeps_long_benign_text_intact(self):
        long_text = "z" * 40000
        self.assertEqual(redact_for_egress(long_text), long_text)

    def test_redact_for_egress_still_scrubs_secrets(self):
        self.assertNotIn(FAKE_KEY, redact_for_egress(f"Use {FAKE_ASSIGNMENT}"))
        self.assertIn(
            "api_key <redacted>", redact_for_egress(f"Use {FAKE_ASSIGNMENT}")
        )

    def test_capture_still_replaces_overlong_fields(self):
        self.assertIn(
            "field exceeded", strip_tags("z" * 40000)
        )


class TripwireTests(unittest.TestCase):
    def test_followup_entry_points_call_choke(self):
        for fn in (
            save_completion_summary,
            capture_nickname,
            journal_message,
            ResidentWorkLedger.append_message,
            OpenAICompatibleCognitiveResource.invoke,
            AnthropicCognitiveResource.invoke,
            AnthropicToolLoopClient.create_turn,
            GeminiCognitiveResource._invoke_parts,
        ):
            source = inspect.getsource(fn)
            self.assertTrue(
                "strip_tags" in source or "redact_for_egress" in source,
                fn.__qualname__,
            )

    def test_wired_modules_import_choke(self):
        for module in (
            completion_summary_module,
            two_level_module,
            project_team_module,
            work_module,
            cognitive_module,
            anthropic_module,
            gemini_module,
        ):
            source = inspect.getsource(module)
            self.assertTrue(
                "strip_tags" in source or "redact_for_egress" in source,
                module.__name__,
            )


if __name__ == "__main__":
    unittest.main()
