from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.agentic_tool_loop import (
    AgenticToolLoop,
    ToolLoopError,
    execute_tool_call,
)
from zn_agent.core.terminal import ZNLocalTerminal


class _ScriptedClient:
    """A model stub that plays back a fixed sequence of turns.

    Each entry is either a callable ``(messages) -> dict`` for turns that
    need to inspect what the loop actually sent (e.g. tool_result content),
    or a plain dict returned as-is.
    """

    def __init__(self, turns):
        self._turns = list(turns)
        self.calls = []

    def create_turn(self, *, messages, system, tools):
        self.calls.append({"messages": messages, "system": system, "tools": tools})
        turn = self._turns.pop(0)
        if callable(turn):
            return turn(messages)
        return turn


def _tool_use_turn(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "text": "",
        "tool_calls": [{"id": call_id, "name": name, "arguments": arguments}],
        "stop_reason": "tool_use",
        "raw_content": [
            {"type": "tool_use", "id": call_id, "name": name, "input": arguments}
        ],
    }


def _final_turn(text: str) -> dict:
    return {"text": text, "tool_calls": [], "stop_reason": "end_turn"}


class AgenticToolLoopTests(unittest.TestCase):
    def test_empty_objective_rejected(self):
        loop = AgenticToolLoop(_ScriptedClient([]))
        with self.assertRaises(ToolLoopError):
            loop.run("   ")

    def test_single_tool_call_then_completion(self):
        client = _ScriptedClient(
            [
                _tool_use_turn("t1", "run_terminal", {"command": "echo hi_from_loop"}),
                _final_turn("done: printed hi_from_loop"),
            ]
        )
        loop = AgenticToolLoop(client, max_turns=5)
        result = loop.run("print hi_from_loop via the terminal")

        self.assertTrue(result.completed)
        self.assertEqual(result.turns_used, 2)
        self.assertEqual(result.stopped_reason, "end_turn")
        self.assertIn("hi_from_loop", result.final_text)
        self.assertEqual(len(result.steps), 2)
        self.assertEqual(len(result.steps[0].tool_results), 1)
        self.assertIn("hi_from_loop", result.steps[0].tool_results[0].output)

        # the second call to the model must have seen the real tool output
        second_call_messages = client.calls[1]["messages"]
        last_message = second_call_messages[-1]
        self.assertEqual(last_message["role"], "user")
        tool_result_block = last_message["content"][0]
        self.assertEqual(tool_result_block["type"], "tool_result")
        self.assertEqual(tool_result_block["tool_use_id"], "t1")
        self.assertIn("hi_from_loop", tool_result_block["content"])

    def test_direct_answer_without_any_tool_call(self):
        client = _ScriptedClient([_final_turn("2 + 2 = 4")])
        loop = AgenticToolLoop(client, max_turns=5)
        result = loop.run("what is 2 + 2?")

        self.assertTrue(result.completed)
        self.assertEqual(result.turns_used, 1)
        self.assertEqual(result.final_text, "2 + 2 = 4")
        self.assertEqual(len(client.calls), 1)

    def test_multi_step_read_then_write_then_done(self):
        workdir = Path(tempfile.mkdtemp())
        source = workdir / "in.txt"
        target = workdir / "out.txt"
        source.write_text("hello world\n", encoding="utf-8")

        client = _ScriptedClient(
            [
                _tool_use_turn("t1", "read_file", {"path": str(source)}),
                _tool_use_turn(
                    "t2",
                    "write_file",
                    {"path": str(target), "content": "hello world\n"},
                ),
                _final_turn("copied in.txt to out.txt"),
            ]
        )
        loop = AgenticToolLoop(client, max_turns=10)
        result = loop.run(f"copy {source} to {target}")

        self.assertTrue(result.completed)
        self.assertEqual(result.turns_used, 3)
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "hello world\n")

    def test_max_turns_is_enforced_without_running_forever(self):
        # the model keeps calling a tool and never stops on its own
        turns = [_tool_use_turn(f"t{i}", "run_terminal", {"command": "true"}) for i in range(10)]
        client = _ScriptedClient(turns)
        loop = AgenticToolLoop(client, max_turns=3)
        result = loop.run("loop forever")

        self.assertFalse(result.completed)
        self.assertEqual(result.turns_used, 3)
        self.assertEqual(result.stopped_reason, "max_turns_exceeded")
        self.assertEqual(len(client.calls), 3)

    def test_unknown_tool_reports_error_but_loop_continues(self):
        client = _ScriptedClient(
            [
                _tool_use_turn("t1", "does_not_exist", {}),
                _final_turn("gave up, tool did not exist"),
            ]
        )
        loop = AgenticToolLoop(client, max_turns=5)
        result = loop.run("call a made-up tool")

        self.assertTrue(result.completed)
        self.assertIn("unknown tool", result.steps[0].tool_results[0].output)


class ExecuteToolCallTests(unittest.TestCase):
    def setUp(self):
        self.terminal = ZNLocalTerminal()

    def test_run_terminal_executes_real_command(self):
        output = execute_tool_call(
            "run_terminal", {"command": "echo direct_tool_call"}, terminal=self.terminal
        )
        self.assertIn("success=True", output)
        self.assertIn("direct_tool_call", output)

    def test_run_terminal_requires_command(self):
        output = execute_tool_call("run_terminal", {}, terminal=self.terminal)
        self.assertTrue(output.startswith("error:"))

    def test_read_write_round_trip(self):
        workdir = Path(tempfile.mkdtemp())
        target = workdir / "nested" / "file.txt"

        write_output = execute_tool_call(
            "write_file",
            {"path": str(target), "content": "round trip content\n"},
            terminal=self.terminal,
        )
        self.assertTrue(write_output.startswith("wrote"))

        read_output = execute_tool_call(
            "read_file", {"path": str(target)}, terminal=self.terminal
        )
        self.assertEqual(read_output, "round trip content\n")

    def test_read_missing_file_reports_error(self):
        output = execute_tool_call(
            "read_file", {"path": "/definitely/not/a/real/path.txt"}, terminal=self.terminal
        )
        self.assertTrue(output.startswith("error:"))

    def test_write_file_rejects_non_string_content(self):
        output = execute_tool_call(
            "write_file", {"path": "/tmp/x.txt", "content": 123}, terminal=self.terminal
        )
        self.assertTrue(output.startswith("error:"))


if __name__ == "__main__":
    unittest.main()
