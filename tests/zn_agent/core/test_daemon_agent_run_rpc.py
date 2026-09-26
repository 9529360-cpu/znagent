from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


_ANTHROPIC_ROUTE_CONFIG = {
    "model": {
        "provider": "anthropic",
        "model": "claude-test",
        "api_key": "test-key",
    }
}


class _FakeAnthropicToolLoopClient:
    """Stands in for AnthropicToolLoopClient so tests never hit the network.

    Scripts a fixed sequence of create_turn() responses (the same shape
    AnthropicToolLoopClient.create_turn returns) so AgenticToolLoop's real
    control flow -- including real local tool execution -- is exercised
    end-to-end through the daemon RPC surface.
    """

    def __init__(self, route, *, client_builder=None, max_tokens=None) -> None:
        self.route = route

    def create_turn(self, *, messages, system, tools):
        return self._scripted.pop(0)


def _make_server(tmp_dir: str, config: dict) -> ResidentRpcServer:
    resident = build_resident_runtime_from_existing_stack(
        config=config,
        store_path=Path(tmp_dir) / "kernel.db",
    )
    return ResidentRpcServer(
        resident=resident,
        input_stream=io.StringIO(),
        output_stream=io.StringIO(),
    )


class DaemonAgentRunRpcTests(unittest.TestCase):
    def test_agent_run_requires_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = _make_server(tmp, _ANTHROPIC_ROUTE_CONFIG)
            try:
                with self.assertRaises(ValueError) as ctx:
                    server.handle(
                        {"id": "1", "method": "agent_run", "params": {}}
                    )
                self.assertIn("task", str(ctx.exception))
            finally:
                server.resident.store.close()

    def test_agent_run_without_configured_anthropic_route_reports_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = _make_server(tmp, {"model": {}})
            try:
                with self.assertRaises(ValueError) as ctx:
                    server.handle(
                        {
                            "id": "2",
                            "method": "agent_run",
                            "params": {"task": "say hello"},
                        }
                    )
                self.assertIn("Anthropic route", str(ctx.exception))
            finally:
                server.resident.store.close()

    def test_agent_run_completes_without_tool_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = _make_server(tmp, _ANTHROPIC_ROUTE_CONFIG)
            try:
                fake = _FakeAnthropicToolLoopClient
                fake._scripted = [
                    {
                        "text": "4",
                        "tool_calls": (),
                        "stop_reason": "end_turn",
                        "raw_content": "4",
                    }
                ]
                with patch("zn_agent.core.daemon.AnthropicToolLoopClient", fake):
                    response = server.handle(
                        {
                            "id": "3",
                            "method": "agent_run",
                            "params": {"task": "what is 2+2?"},
                        }
                    )
                self.assertTrue(response["ok"], response.get("error"))
                result = response["result"]
                self.assertTrue(result["completed"])
                self.assertEqual(result["final_text"], "4")
                self.assertEqual(result["turns_used"], 1)
                self.assertEqual(result["stopped_reason"], "end_turn")
                self.assertEqual(len(result["steps"]), 1)
                self.assertEqual(result["steps"][0]["tool_calls"], [])
            finally:
                server.resident.store.close()

    def test_agent_run_executes_a_real_tool_call_before_finishing(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = _make_server(tmp, _ANTHROPIC_ROUTE_CONFIG)
            try:
                fake = _FakeAnthropicToolLoopClient
                fake._scripted = [
                    {
                        "text": "",
                        "tool_calls": (
                            {
                                "id": "call_1",
                                "name": "run_terminal",
                                "arguments": {"command": "echo hi"},
                            },
                        ),
                        "stop_reason": "tool_use",
                        "raw_content": "",
                    },
                    {
                        "text": "printed hi",
                        "tool_calls": (),
                        "stop_reason": "end_turn",
                        "raw_content": "printed hi",
                    },
                ]
                with patch("zn_agent.core.daemon.AnthropicToolLoopClient", fake):
                    response = server.handle(
                        {
                            "id": "4",
                            "method": "agent_run",
                            "params": {"task": "print hi via the shell"},
                        }
                    )
                self.assertTrue(response["ok"], response.get("error"))
                result = response["result"]
                self.assertTrue(result["completed"])
                self.assertEqual(result["final_text"], "printed hi")
                self.assertEqual(result["turns_used"], 2)
                first_step = result["steps"][0]
                self.assertEqual(first_step["tool_calls"][0]["name"], "run_terminal")
                self.assertEqual(len(first_step["tool_results"]), 1)
                self.assertIn("hi", first_step["tool_results"][0]["output"])
            finally:
                server.resident.store.close()

    def test_agent_run_respects_max_turns_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = _make_server(tmp, _ANTHROPIC_ROUTE_CONFIG)
            try:
                fake = _FakeAnthropicToolLoopClient
                fake._scripted = [
                    {
                        "text": "",
                        "tool_calls": (
                            {
                                "id": "call_1",
                                "name": "run_terminal",
                                "arguments": {"command": "echo loop"},
                            },
                        ),
                        "stop_reason": "tool_use",
                        "raw_content": "",
                    }
                ] * 2
                with patch("zn_agent.core.daemon.AnthropicToolLoopClient", fake):
                    response = server.handle(
                        {
                            "id": "5",
                            "method": "agent_run",
                            "params": {"task": "loop forever", "max_turns": 2},
                        }
                    )
                self.assertTrue(response["ok"], response.get("error"))
                result = response["result"]
                self.assertFalse(result["completed"])
                self.assertEqual(result["turns_used"], 2)
                self.assertEqual(result["stopped_reason"], "max_turns_exceeded")
            finally:
                server.resident.store.close()


if __name__ == "__main__":
    unittest.main()
