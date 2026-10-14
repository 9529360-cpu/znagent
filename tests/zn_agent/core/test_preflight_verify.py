from __future__ import annotations

"""Tests for verify-before-acting preflight (Muse pattern M9, ZN implementation).

Covers the three required cases -- connection not ready, skill missing,
preflight pass -- plus the choke-point wiring: a not-ready verdict must
reach the caller with reason + recovery and must NOT execute the tool or
send any request.
"""

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.agentic_tool_loop import AgenticToolLoop, execute_tool_call
from zn_agent.core.preflight import (
    PreflightChecker,
    PreflightNotReadyError,
    PreflightResult,
    ready_if,
)
from zn_agent.core.skills import SkillStore
from zn_agent.core.stdio_mcp import StdioMcpClient, StdioMcpCommand, StdioMcpError
from zn_agent.core.terminal import TerminalRequest, ZNLocalTerminal


def _write_skill(root: Path, name: str, *, description: str = "A skill.", body: str = "Body.") -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    front = f"---\nname: {name}\ndescription: {description}\nversion: 1.0.0\n---\n\n"
    path = directory / "skill.md"
    path.write_text(front + body, encoding="utf-8")
    return path


def _not_ready(reason: str = "connection down", recovery: str = "reconnect first") -> PreflightResult:
    return PreflightResult(
        ready=False, kind="connection", target="test-conn", reason=reason, recovery=recovery
    )


def _ready() -> PreflightResult:
    return PreflightResult(ready=True, kind="connection", target="test-conn")


class _CountingTerminal(ZNLocalTerminal):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def execute(self, request: TerminalRequest):  # type: ignore[override]
        self.calls += 1
        return super().execute(request)


class _ScriptedClient:
    def __init__(self, turns):
        self._turns = list(turns)

    def create_turn(self, *, messages, system, tools):
        return self._turns.pop(0)


def _tool_use_turn(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "text": "",
        "tool_calls": [{"id": call_id, "name": name, "arguments": arguments}],
        "stop_reason": "tool_use",
        "raw_content": [],
    }


def _final_turn(text: str) -> dict:
    return {"text": text, "tool_calls": [], "stop_reason": "end_turn"}


class PreflightCheckerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = SkillStore(self.root)
        self.checker = PreflightChecker(skill_store=self.store)

    def test_connection_not_ready_reports_reason_and_recovery(self):
        self.checker.register_connection("mcp", lambda: _not_ready())
        result = self.checker.check_connection("mcp")
        self.assertFalse(result.ready)
        self.assertIn("connection down", result.reason)
        self.assertIn("reconnect first", result.recovery)
        self.assertIn("not ready", result.message)
        self.assertIn("recovery", result.message)

    def test_unknown_connection_is_not_ready_not_guessed(self):
        result = self.checker.check_connection("never-registered")
        self.assertFalse(result.ready)
        self.assertIn("no readiness checker", result.reason)
        self.assertIn("register", result.recovery)

    def test_checker_exception_becomes_not_ready_not_crash(self):
        def _boom() -> PreflightResult:
            raise RuntimeError("probe exploded")

        self.checker.register_connection("flaky", _boom)
        result = self.checker.check_connection("flaky")
        self.assertFalse(result.ready)
        self.assertIn("probe exploded", result.reason)

    def test_ready_if_helper_builds_checker(self):
        state = {"up": False}
        checker = ready_if(
            lambda: state["up"],
            target="mcp",
            reason="MCP client is not started",
            recovery="call start() first",
        )
        self.assertFalse(checker().ready)
        self.assertIn("call start()", checker().recovery)
        state["up"] = True
        self.assertTrue(checker().ready)

    def test_skill_missing_reports_no_such_skill_with_alternatives(self):
        _write_skill(self.root, "good-skill", description="Do good things.")
        result = self.checker.check_skill("missing-skill")
        self.assertFalse(result.ready)
        self.assertIn("no such skill", result.reason)
        self.assertIn("good-skill", result.recovery)
        self.assertNotIn("Body.", result.recovery)  # alternatives are names only

    def test_skill_missing_with_no_skills_installed(self):
        result = self.checker.check_skill("anything")
        self.assertFalse(result.ready)
        self.assertIn("no such skill", result.reason)
        self.assertIn("no skills are installed", result.recovery)

    def test_skill_corrupt_reports_invalid_bundle_not_missing(self):
        # Bundle file exists but fails SkillStore validation (empty body).
        _write_skill(self.root, "broken", description="Broken.", body="   ")
        result = self.checker.check_skill("broken")
        self.assertFalse(result.ready)
        self.assertIn("failed SkillStore validation", result.reason)
        self.assertIn("skill.md", result.recovery)
        self.assertNotIn("no such skill", result.reason)

    def test_skill_present_and_usable_is_ready(self):
        _write_skill(self.root, "good-skill", description="Do good things.")
        result = self.checker.check_skill("good-skill")
        self.assertTrue(result.ready)

    def test_verify_passes_when_connection_and_skill_ready(self):
        _write_skill(self.root, "good-skill", description="Do good things.")
        self.checker.register_connection("mcp", _ready)
        result = self.checker.verify(connection="mcp", skill="good-skill")
        self.assertTrue(result.ready)

    def test_verify_returns_first_failure_connection_before_skill(self):
        self.checker.register_connection("mcp", lambda: _not_ready())
        result = self.checker.verify(connection="mcp", skill="also-missing")
        self.assertFalse(result.ready)
        self.assertEqual(result.kind, "connection")
        self.assertIn("connection down", result.reason)

    def test_require_raises_with_result(self):
        self.checker.register_connection("mcp", lambda: _not_ready())
        with self.assertRaises(PreflightNotReadyError) as ctx:
            self.checker.require(connection="mcp")
        self.assertFalse(ctx.exception.result.ready)
        self.assertIn("connection down", str(ctx.exception))


class ToolLoopPreflightTests(unittest.TestCase):
    def test_connection_not_ready_blocks_tool_call_without_executing(self):
        terminal = _CountingTerminal()
        output = execute_tool_call(
            "run_terminal",
            {"command": "echo must-not-run"},
            terminal=terminal,
            preflight=lambda _name: _not_ready(),
        )
        self.assertTrue(output.startswith("error: preflight not ready"))
        self.assertIn("connection down", output)
        self.assertIn("reconnect first", output)
        self.assertEqual(terminal.calls, 0)

    def test_preflight_pass_allows_tool_call(self):
        terminal = _CountingTerminal()
        output = execute_tool_call(
            "run_terminal",
            {"command": "echo preflight-ok"},
            terminal=terminal,
            preflight=lambda _name: _ready(),
        )
        self.assertIn("preflight-ok", output)
        self.assertEqual(terminal.calls, 1)

    def test_preflight_none_keeps_old_behaviour(self):
        terminal = _CountingTerminal()
        output = execute_tool_call(
            "run_terminal", {"command": "echo no-hook"}, terminal=terminal
        )
        self.assertIn("no-hook", output)
        self.assertEqual(terminal.calls, 1)

    def test_loop_passes_preflight_to_tool_calls(self):
        terminal = _CountingTerminal()
        client = _ScriptedClient(
            [
                _tool_use_turn("t1", "run_terminal", {"command": "echo must-not-run"}),
                _final_turn("blocked, did not run"),
            ]
        )
        loop = AgenticToolLoop(
            client, terminal=terminal, max_turns=5, preflight=lambda _name: _not_ready()
        )
        result = loop.run("run a command")
        self.assertTrue(result.completed)
        self.assertIn("preflight not ready", result.steps[0].tool_results[0].output)
        self.assertEqual(terminal.calls, 0)


class McpPreflightTests(unittest.TestCase):
    def _client(self, checker: PreflightChecker) -> StdioMcpClient:
        return StdioMcpClient(
            command=StdioMcpCommand(argv=("true",), cwd=Path(tempfile.gettempdir()), env={}),
            preflight=checker,
        )

    def test_mcp_call_tool_does_not_start_when_preflight_not_ready(self):
        checker = PreflightChecker()
        checker.register_connection("mcp", lambda: _not_ready())
        client = self._client(checker)
        started = []
        client.start = lambda: started.append(True)  # type: ignore[method-assign]
        with self.assertRaises(StdioMcpError) as ctx:
            client.call_tool("some_tool", {})
        self.assertEqual(started, [])  # no start -> no request sent
        self.assertIn("not called", str(ctx.exception))
        self.assertIn("connection down", str(ctx.exception))
        self.assertIn("reconnect first", str(ctx.exception))

    def test_mcp_default_checker_reports_not_started_without_registered_checker(self):
        checker = PreflightChecker()
        client = self._client(checker)
        result = checker.check_connection(
            "mcp",
            default=ready_if(
                lambda: client.running,
                target="mcp",
                reason="MCP client is not started",
                recovery="call start() first",
            ),
        )
        self.assertFalse(result.ready)
        self.assertIn("not started", result.reason)
        self.assertIn("call start()", result.recovery)


if __name__ == "__main__":
    unittest.main()
