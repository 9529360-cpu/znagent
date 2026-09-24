from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class _FakeToolLoopClient:
    """Stands in for AnthropicToolLoopClient: no network, scripted turns."""

    def __init__(self, turns):
        self._turns = list(turns)
        self.calls = 0

    def create_turn(self, *, messages, system, tools):
        self.calls += 1
        turn = self._turns.pop(0)
        return turn(messages) if callable(turn) else turn


def _resident(tmp_dir: str, *, with_anthropic_route: bool):
    model_cfg = (
        {"model": "claude-test", "provider": "anthropic", "api_key": "test-key"}
        if with_anthropic_route
        else {}
    )
    return build_resident_runtime_from_existing_stack(
        config={"model": model_cfg},
        store_path=Path(tmp_dir) / "kernel.db",
    )


class DaemonAgentRunRpcTests(unittest.TestCase):
    def test_agent_run_requires_objective(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _resident(tmp, with_anthropic_route=True)
            try:
                server = ResidentRpcServer(
                    resident=resident,
                    input_stream=io.StringIO(),
                    output_stream=io.StringIO(),
                )
                with self.assertRaises(ValueError) as ctx:
                    server.handle(
                        {
                            "id": "a",
                            "method": "agent_run",
                            "params": {"objective": "  "},
                        }
                    )
                self.assertIn("objective", str(ctx.exception))
            finally:
                resident.store.close()

    def test_agent_run_without_configured_anthropic_route_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _resident(tmp, with_anthropic_route=False)
            try:
                server = ResidentRpcServer(
                    resident=resident,
                    input_stream=io.StringIO(),
                    output_stream=io.StringIO(),
                )
                with self.assertRaises(ValueError) as ctx:
                    server.handle(
                        {
                            "id": "a",
                            "method": "agent_run",
                            "params": {"objective": "do something"},
                        }
                    )
                self.assertIn("anthropic", str(ctx.exception).lower())
            finally:
                resident.store.close()

    def test_agent_run_drives_a_real_multi_step_tool_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _resident(tmp, with_anthropic_route=True)
            try:
                server = ResidentRpcServer(
                    resident=resident,
                    input_stream=io.StringIO(),
                    output_stream=io.StringIO(),
                )

                def second_turn(messages):
                    last = messages[-1]
                    assert last["role"] == "user"
                    block = last["content"][0]
                    assert block["type"] == "tool_result"
                    assert "agent_run_probe" in block["content"]
                    return {
                        "text": "finished: printed agent_run_probe",
                        "tool_calls": [],
                        "stop_reason": "end_turn",
                    }

                fake_client = _FakeToolLoopClient(
                    [
                        {
                            "text": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "name": "run_terminal",
                                    "arguments": {"command": "echo agent_run_probe"},
                                }
                            ],
                            "stop_reason": "tool_use",
                            "raw_content": [
                                {
                                    "type": "tool_use",
                                    "id": "call_1",
                                    "name": "run_terminal",
                                    "input": {"command": "echo agent_run_probe"},
                                }
                            ],
                        },
                        second_turn,
                    ]
                )

                with patch(
                    "zn_agent.core.daemon.AnthropicToolLoopClient",
                    return_value=fake_client,
                ):
                    response = server.handle(
                        {
                            "id": "a",
                            "method": "agent_run",
                            "params": {
                                "objective": "print agent_run_probe via the terminal",
                                "max_turns": 5,
                            },
                        }
                    )

                self.assertTrue(response["ok"], response)
                result = response["result"]
                self.assertTrue(result["completed"])
                self.assertEqual(result["turns_used"], 2)
                self.assertIn("agent_run_probe", result["final_text"])
                self.assertEqual(len(result["steps"]), 2)
                self.assertEqual(
                    result["steps"][0]["tool_results"][0]["name"], "run_terminal"
                )
                self.assertIn(
                    "agent_run_probe",
                    result["steps"][0]["tool_results"][0]["output"],
                )
            finally:
                resident.store.close()

    def test_agent_run_max_turns_must_be_an_integer(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _resident(tmp, with_anthropic_route=True)
            try:
                server = ResidentRpcServer(
                    resident=resident,
                    input_stream=io.StringIO(),
                    output_stream=io.StringIO(),
                )
                with self.assertRaises(ValueError) as ctx:
                    server.handle(
                        {
                            "id": "a",
                            "method": "agent_run",
                            "params": {
                                "objective": "do it",
                                "max_turns": "not-a-number",
                            },
                        }
                    )
                self.assertIn("max_turns", str(ctx.exception))
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
