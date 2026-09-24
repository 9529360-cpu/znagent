from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.agentic_tool_loop import AgenticToolLoop, TOOL_SCHEMA
from zn_agent.core.anthropic_resource import AnthropicToolLoopClient
from zn_agent.core.models import ModelRoute


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


class _RecordingMessages:
    def __init__(self, scripted_responses):
        self._scripted = list(scripted_responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self._scripted.pop(0)


class _RecordingClient:
    def __init__(self, scripted_responses):
        self.messages = _RecordingMessages(scripted_responses)


def _usage():
    return SimpleNamespace(
        input_tokens=10,
        output_tokens=5,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )


class AnthropicToolLoopClientTests(unittest.TestCase):
    def test_create_turn_sends_tool_schema_and_parses_tool_use(self):
        fake = _RecordingClient(
            [
                SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            type="tool_use",
                            id="call_1",
                            name="run_terminal",
                            input={"command": "echo hi"},
                        )
                    ],
                    stop_reason="tool_use",
                    usage=_usage(),
                )
            ]
        )
        client = AnthropicToolLoopClient(route(), client_builder=lambda **kw: fake)

        result = client.create_turn(
            messages=[{"role": "user", "content": "run echo hi"}],
            system="be helpful",
            tools=TOOL_SCHEMA,
        )

        sent = fake.messages.requests[0]
        self.assertIn("tools", sent)
        self.assertTrue(any(t["name"] == "run_terminal" for t in sent["tools"]))
        self.assertEqual(sent["system"], "be helpful")

        self.assertEqual(result["text"], "")
        self.assertEqual(len(result["tool_calls"]), 1)
        self.assertEqual(result["tool_calls"][0]["name"], "run_terminal")
        self.assertEqual(result["tool_calls"][0]["arguments"], {"command": "echo hi"})
        self.assertEqual(result["stop_reason"], "tool_use")

    def test_create_turn_parses_plain_text_completion(self):
        fake = _RecordingClient(
            [
                SimpleNamespace(
                    content=[SimpleNamespace(type="text", text="all done")],
                    stop_reason="end_turn",
                    usage=_usage(),
                )
            ]
        )
        client = AnthropicToolLoopClient(route(), client_builder=lambda **kw: fake)

        result = client.create_turn(
            messages=[{"role": "user", "content": "hello"}],
            system="",
            tools=TOOL_SCHEMA,
        )

        self.assertEqual(result["text"], "all done")
        self.assertEqual(result["tool_calls"], [])
        self.assertEqual(result["stop_reason"], "end_turn")

    def test_full_loop_end_to_end_against_scripted_anthropic_client(self):
        fake = _RecordingClient(
            [
                SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            type="tool_use",
                            id="call_1",
                            name="run_terminal",
                            input={"command": "echo ping_pong"},
                        )
                    ],
                    stop_reason="tool_use",
                    usage=_usage(),
                ),
                SimpleNamespace(
                    content=[
                        SimpleNamespace(type="text", text="Done, printed ping_pong.")
                    ],
                    stop_reason="end_turn",
                    usage=_usage(),
                ),
            ]
        )
        client = AnthropicToolLoopClient(route(), client_builder=lambda **kw: fake)
        loop = AgenticToolLoop(client, max_turns=5)

        result = loop.run("print ping_pong via the terminal")

        self.assertTrue(result.completed)
        self.assertEqual(result.turns_used, 2)
        self.assertIn("ping_pong", result.final_text)

        # the second real request to Anthropic must carry the tool_result
        second_request = fake.messages.requests[1]
        last_message = second_request["messages"][-1]
        self.assertEqual(last_message["role"], "user")
        self.assertEqual(last_message["content"][0]["type"], "tool_result")
        self.assertIn("ping_pong", last_message["content"][0]["content"])


if __name__ == "__main__":
    unittest.main()
