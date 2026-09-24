from __future__ import annotations

"""Model-driven multi-step tool loop (Codex/Claude-Code style).

Phase 1 of moving ZN's user-turn handling away from the older pattern where
ZN's local nervous system/impasse machinery borrows one bounded model answer
at a time and decides almost everything else itself, toward a loop where the
model sees real tool output each turn and decides -- itself -- what to do
next and when the objective is finished. That is how mainstream coding
agents (Claude Code, Codex, etc.) actually operate, and it is the concrete
mechanism behind "closing the loop" for ZN.

Scope of this phase: a small set of low-risk, easily reversible local
capabilities (shell commands, local text file read/write) so the loop can be
exercised and tested end-to-end without depending on ZN's heavier Body/
Action Fabric authority stack, browser/desktop automation, or the durable
Work/side-effect-journal/completion-truth system. Those remain the ownership
boundary for anything higher-risk; this module does not touch them. See
docs/ZN-NEXT-PHASE.md / ZN-IMPLEMENTATION-STATUS.md for that boundary and
follow-up phases (relaxing fail-closed for reversible actions, wider
capability coverage, durable-Work integration).
"""

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .terminal import TerminalRequest, ZNLocalTerminal, get_zn_local_terminal


class ToolLoopError(RuntimeError):
    pass


MAX_FILE_READ_CHARS = 200_000
MAX_FILE_WRITE_CHARS = 2_000_000
DEFAULT_MAX_TURNS = 25

TOOL_SCHEMA: tuple[dict[str, Any], ...] = (
    {
        "name": "run_terminal",
        "description": (
            "Run one non-interactive shell command on the local machine and "
            "get back its combined output, exit code and whether it timed "
            "out. Use it for inspecting files, running builds/tests, git, "
            "package managers, and any other command-line work."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to run.",
                },
                "workdir": {
                    "type": "string",
                    "description": (
                        "Working directory for the command. Defaults to the "
                        "current session working directory."
                    ),
                },
                "timeout": {
                    "type": "number",
                    "description": "Seconds before the command is killed. Default 60.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a local text file and return its contents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file."},
                "max_chars": {
                    "type": "integer",
                    "description": f"Max characters to return (default/cap {MAX_FILE_READ_CHARS}).",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write complete text content to a local file, creating it or "
            "atomically overwriting it. This always writes the FULL file "
            "content passed in; there is no partial/patch edit. Read the "
            "file first if you need to preserve existing content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
)


@dataclass(frozen=True, slots=True)
class ToolCallResult:
    tool_use_id: str
    name: str
    output: str


@dataclass(frozen=True, slots=True)
class ToolLoopStep:
    turn: int
    assistant_text: str
    tool_calls: tuple[Mapping[str, Any], ...]
    tool_results: tuple[ToolCallResult, ...]


@dataclass(frozen=True, slots=True)
class ToolLoopResult:
    completed: bool
    final_text: str
    turns_used: int
    steps: tuple[ToolLoopStep, ...]
    stopped_reason: str


class SupportsToolCall(Protocol):
    """What AgenticToolLoop needs from a model client for one turn.

    Implementations translate a provider's native tool-calling wire format
    (Anthropic Messages content blocks, OpenAI tool_calls, ...) into this
    shape, and translate tool results back for the next request. See
    AnthropicToolLoopClient in anthropic_resource.py for the reference
    implementation.
    """

    def create_turn(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        system: str,
        tools: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]: ...


def _atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".zn-tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return len(content)


def _execute_run_terminal(arguments: Mapping[str, Any], *, terminal: ZNLocalTerminal) -> str:
    command = str(arguments.get("command") or "").strip()
    if not command:
        return "error: run_terminal requires a non-empty command"
    workdir = arguments.get("workdir")
    timeout = arguments.get("timeout")
    try:
        timeout_value = float(timeout) if timeout is not None else 60.0
    except (TypeError, ValueError):
        timeout_value = 60.0
    request = TerminalRequest(
        command=command,
        workdir=str(workdir) if workdir else None,
        timeout=timeout_value,
    )
    result = terminal.execute(request)
    lines = [
        f"status={result.status} success={result.success} exit_code={result.exit_code}"
    ]
    if result.timed_out:
        lines.append("timed_out=true")
    if result.error:
        lines.append(f"error={result.error}")
    lines.append("--- output ---")
    lines.append(result.output or "(no output)")
    return "\n".join(lines)


def _execute_read_file(arguments: Mapping[str, Any]) -> str:
    raw_path = str(arguments.get("path") or "").strip()
    if not raw_path:
        return "error: read_file requires a non-empty path"
    max_chars = arguments.get("max_chars")
    try:
        max_chars_value = int(max_chars) if max_chars is not None else MAX_FILE_READ_CHARS
    except (TypeError, ValueError):
        max_chars_value = MAX_FILE_READ_CHARS
    max_chars_value = max(1, min(MAX_FILE_READ_CHARS, max_chars_value))
    path = Path(raw_path).expanduser()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return f"error: file not found: {path}"
    except IsADirectoryError:
        return f"error: path is a directory, not a file: {path}"
    except OSError as exc:
        return f"error: could not read {path}: {exc}"
    truncated = len(text) > max_chars_value
    if truncated:
        text = text[:max_chars_value]
    return text + ("\n...[truncated]" if truncated else "")


def _execute_write_file(arguments: Mapping[str, Any]) -> str:
    raw_path = str(arguments.get("path") or "").strip()
    if not raw_path:
        return "error: write_file requires a non-empty path"
    content = arguments.get("content")
    if not isinstance(content, str):
        return "error: write_file requires string content"
    if len(content) > MAX_FILE_WRITE_CHARS:
        return f"error: content too large ({len(content)} chars, limit {MAX_FILE_WRITE_CHARS})"
    path = Path(raw_path).expanduser()
    try:
        written = _atomic_write_text(path, content)
    except OSError as exc:
        return f"error: could not write {path}: {exc}"
    return f"wrote {written} chars to {path}"


def execute_tool_call(
    name: str,
    arguments: Mapping[str, Any],
    *,
    terminal: ZNLocalTerminal,
) -> str:
    if name == "run_terminal":
        return _execute_run_terminal(arguments, terminal=terminal)
    if name == "read_file":
        return _execute_read_file(arguments)
    if name == "write_file":
        return _execute_write_file(arguments)
    return f"error: unknown tool '{name}'"


DEFAULT_SYSTEM_PROMPT = (
    "You are ZN, operating directly on the user's machine through the tools "
    "provided. Work the objective through to completion yourself: call "
    "tools as many times as you need, read their real output, and keep "
    "going after a setback instead of stopping to ask the user -- unless "
    "you are genuinely blocked on a decision only they can make, or about "
    "to do something destructive or irreversible (deleting data, sending "
    "something, spending money, publishing something) that was not clearly "
    "part of the objective. When the objective is done, reply with plain "
    "text summarizing what you did and stop calling tools."
)


class AgenticToolLoop:
    """Runs a bounded model-driven tool-calling loop to completion.

    Each turn hands the model the full conversation so far, including real
    tool output. The model decides the next tool call, or replies with plain
    text (no tool call) to signal it is done. ZN does not intercept or
    second-guess that per-turn decision the way the older
    generic_action_loop "one proposal per impasse" protocol did; it only
    bounds total turns and executes the concrete tool calls the model made.
    """

    def __init__(
        self,
        client: SupportsToolCall,
        *,
        terminal: ZNLocalTerminal | None = None,
        tools: Sequence[Mapping[str, Any]] = TOOL_SCHEMA,
        max_turns: int = DEFAULT_MAX_TURNS,
    ) -> None:
        self._client = client
        self._terminal = terminal or get_zn_local_terminal()
        self._tools = tuple(tools)
        self._max_turns = max(1, int(max_turns))

    def run(
        self,
        objective: str,
        *,
        system: str = DEFAULT_SYSTEM_PROMPT,
    ) -> ToolLoopResult:
        text = str(objective or "").strip()
        if not text:
            raise ToolLoopError("objective must not be empty")

        messages: list[dict[str, Any]] = [{"role": "user", "content": text}]
        steps: list[ToolLoopStep] = []

        for turn in range(1, self._max_turns + 1):
            response = self._client.create_turn(
                messages=messages, system=system, tools=self._tools
            )
            assistant_text = str(response.get("text") or "")
            tool_calls = tuple(response.get("tool_calls") or ())
            stop_reason = str(response.get("stop_reason") or "") or "end_turn"

            if not tool_calls:
                steps.append(
                    ToolLoopStep(
                        turn=turn,
                        assistant_text=assistant_text,
                        tool_calls=(),
                        tool_results=(),
                    )
                )
                return ToolLoopResult(
                    completed=True,
                    final_text=assistant_text,
                    turns_used=turn,
                    steps=tuple(steps),
                    stopped_reason=stop_reason,
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": response.get("raw_content", assistant_text),
                }
            )

            tool_results: list[ToolCallResult] = []
            result_blocks: list[dict[str, Any]] = []
            for call in tool_calls:
                call_id = str(call.get("id") or "")
                call_name = str(call.get("name") or "")
                call_args = call.get("arguments") or {}
                if not isinstance(call_args, Mapping):
                    call_args = {}
                output = execute_tool_call(call_name, call_args, terminal=self._terminal)
                tool_results.append(
                    ToolCallResult(tool_use_id=call_id, name=call_name, output=output)
                )
                result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "content": output,
                    }
                )

            messages.append({"role": "user", "content": result_blocks})
            steps.append(
                ToolLoopStep(
                    turn=turn,
                    assistant_text=assistant_text,
                    tool_calls=tool_calls,
                    tool_results=tuple(tool_results),
                )
            )

        return ToolLoopResult(
            completed=False,
            final_text=steps[-1].assistant_text if steps else "",
            turns_used=self._max_turns,
            steps=tuple(steps),
            stopped_reason="max_turns_exceeded",
        )
