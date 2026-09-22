from __future__ import annotations

"""Small ZN-owned stdio MCP client for replaceable local capability runtimes.

This is transport only. It does not own Work, action authority, completion, or
provider policy. The client speaks the 2025-11-25 handshake used by current
stdio MCP servers, keeps one request in flight, ignores unrelated notifications,
and bounds stdout/stderr before returning structured evidence to ZN.
"""

import json
import os
import queue
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


MCP_HANDSHAKE_PROTOCOL_VERSION = "2025-11-25"


class StdioMcpError(RuntimeError):
    """Bounded local MCP runtime/protocol failure."""


@dataclass(frozen=True, slots=True)
class StdioMcpCommand:
    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]


class StdioMcpClient:
    """Single-flight JSON-RPC MCP client over a local child process."""

    def __init__(
        self,
        *,
        command: StdioMcpCommand,
        client_name: str = "znagent",
        client_version: str = "0.17.0",
        expected_server_names: Sequence[str] = (),
        required_tools: Sequence[str] = (),
        timeout_seconds: float = 30.0,
        max_response_chars: int = 4_000_000,
        max_stderr_chars: int = 32_000,
    ) -> None:
        self.command = command
        self.client_name = str(client_name or "znagent").strip() or "znagent"
        self.client_version = str(client_version or "0.0.0").strip() or "0.0.0"
        self.expected_server_names = frozenset(
            str(item).strip() for item in expected_server_names if str(item).strip()
        )
        self.required_tools = frozenset(
            str(item).strip() for item in required_tools if str(item).strip()
        )
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 300.0))
        self.max_response_chars = max(4_096, int(max_response_chars))
        self.max_stderr_chars = max(1_024, int(max_stderr_chars))
        self._process: subprocess.Popen[str] | None = None
        self._stdout_queue: queue.Queue[str | None] = queue.Queue()
        self._stderr_parts: deque[str] = deque()
        self._stderr_chars = 0
        self._next_id = 1
        self._request_lock = threading.Lock()
        self._tool_names: frozenset[str] = frozenset()
        self._server_name = ""
        self._server_version = ""

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def tool_names(self) -> frozenset[str]:
        return self._tool_names

    @property
    def server_name(self) -> str:
        return self._server_name

    @property
    def server_version(self) -> str:
        return self._server_version

    def start(self) -> "StdioMcpClient":
        if self.running:
            return self
        env = dict(os.environ)
        env.update(dict(self.command.env))
        try:
            process = subprocess.Popen(
                list(self.command.argv),
                cwd=str(self.command.cwd),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
        except OSError as exc:
            raise StdioMcpError(f"failed to start MCP runtime: {exc}") from exc
        if process.stdin is None or process.stdout is None or process.stderr is None:
            process.kill()
            raise StdioMcpError("MCP runtime pipes were not created")
        self._process = process
        threading.Thread(
            target=self._read_stdout,
            args=(process.stdout,),
            daemon=True,
            name="zn-mcp-stdout",
        ).start()
        threading.Thread(
            target=self._read_stderr,
            args=(process.stderr,),
            daemon=True,
            name="zn-mcp-stderr",
        ).start()

        try:
            initialized = self._request_raw(
                "initialize",
                {
                    "protocolVersion": MCP_HANDSHAKE_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": self.client_name,
                        "version": self.client_version,
                    },
                },
            )
            negotiated = str(initialized.get("protocolVersion") or "").strip()
            if negotiated != MCP_HANDSHAKE_PROTOCOL_VERSION:
                raise StdioMcpError(
                    "MCP runtime negotiated unsupported protocol "
                    f"{negotiated or '<missing>'}"
                )
            server_info = initialized.get("serverInfo")
            if not isinstance(server_info, dict):
                raise StdioMcpError("MCP runtime returned no serverInfo")
            self._server_name = str(server_info.get("name") or "").strip()
            self._server_version = str(server_info.get("version") or "").strip()
            if (
                self.expected_server_names
                and self._server_name not in self.expected_server_names
            ):
                raise StdioMcpError(
                    "unexpected MCP server identity: "
                    f"{self._server_name or '<missing>'}"
                )
            self._send_notification("notifications/initialized", {})

            listed = self._request_raw("tools/list", {})
            tools = listed.get("tools")
            if not isinstance(tools, list):
                raise StdioMcpError("MCP tools/list returned no tool list")
            names = frozenset(
                str(item.get("name") or "").strip()
                for item in tools
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            )
            missing = self.required_tools.difference(names)
            if missing:
                raise StdioMcpError(
                    "MCP runtime is missing required tools: "
                    + ", ".join(sorted(missing))
                )
            self._tool_names = names
            return self
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        process = self._process
        self._process = None
        self._tool_names = frozenset()
        self._server_name = ""
        self._server_version = ""
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        for stream in (process.stdout, process.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass

    def __enter__(self) -> "StdioMcpClient":
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        tool = str(name or "").strip()
        if not tool:
            raise StdioMcpError("MCP tool name must not be empty")
        self.start()
        if self._tool_names and tool not in self._tool_names:
            raise StdioMcpError(f"MCP runtime does not expose tool: {tool}")
        result = self._request_raw(
            "tools/call",
            {"name": tool, "arguments": dict(arguments or {})},
        )
        if result.get("isError") is True:
            raise StdioMcpError(self._tool_error_message(tool, result))
        return result

    def call_tool_text(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> str:
        result = self.call_tool(name, arguments)
        content = result.get("content")
        parts: list[str] = []
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict) or item.get("type") != "text":
                    continue
                value = str(item.get("text") or "")
                if value:
                    parts.append(value)
        if parts:
            return "\n".join(parts)
        structured = result.get("structuredContent")
        if structured is not None:
            return json.dumps(
                structured,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        return ""

    def _request_raw(
        self,
        method: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._request_lock:
            process = self._process
            if process is None or process.poll() is not None or process.stdin is None:
                raise StdioMcpError(
                    "MCP runtime is not running" + self._stderr_suffix()
                )
            request_id = self._next_id
            self._next_id += 1
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params),
            }
            self._write_payload(payload)
            while True:
                line = self._next_stdout(method)
                try:
                    response = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise StdioMcpError("MCP runtime returned invalid JSON") from exc
                if not isinstance(response, dict):
                    continue
                if "id" not in response:
                    continue
                if response.get("id") != request_id:
                    raise StdioMcpError(
                        f"MCP response id mismatch for {method}: {response!r}"
                    )
                error = response.get("error")
                if isinstance(error, dict):
                    raise StdioMcpError(
                        f"MCP protocol error {error.get('code')}: "
                        f"{error.get('message')}"
                    )
                result = response.get("result")
                if not isinstance(result, dict):
                    raise StdioMcpError(
                        f"MCP response has no object result for {method}"
                    )
                return result

    def _send_notification(
        self,
        method: str,
        params: Mapping[str, Any],
    ) -> None:
        with self._request_lock:
            process = self._process
            if process is None or process.poll() is not None or process.stdin is None:
                raise StdioMcpError(
                    "MCP runtime is not running" + self._stderr_suffix()
                )
            self._write_payload(
                {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": dict(params),
                }
            )

    def _write_payload(self, payload: Mapping[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise StdioMcpError("MCP runtime stdin is unavailable")
        try:
            process.stdin.write(
                json.dumps(
                    dict(payload),
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                + "\n"
            )
            process.stdin.flush()
        except OSError as exc:
            raise StdioMcpError(
                f"failed writing to MCP runtime: {exc}" + self._stderr_suffix()
            ) from exc

    def _next_stdout(self, method: str) -> str:
        try:
            line = self._stdout_queue.get(timeout=self.timeout_seconds)
        except queue.Empty as exc:
            raise StdioMcpError(
                f"MCP runtime timed out waiting for {method}"
                + self._stderr_suffix()
            ) from exc
        if line is None:
            raise StdioMcpError(
                "MCP runtime closed stdout" + self._stderr_suffix()
            )
        if len(line) > self.max_response_chars:
            raise StdioMcpError(
                f"MCP response exceeded {self.max_response_chars} characters"
            )
        return line

    def _read_stdout(self, stream) -> None:
        try:
            for raw in stream:
                self._stdout_queue.put(raw.rstrip("\r\n"))
        finally:
            self._stdout_queue.put(None)

    def _read_stderr(self, stream) -> None:
        for raw in stream:
            value = raw.rstrip("\r\n")
            if not value:
                continue
            self._stderr_parts.append(value)
            self._stderr_chars += len(value)
            while self._stderr_parts and self._stderr_chars > self.max_stderr_chars:
                removed = self._stderr_parts.popleft()
                self._stderr_chars -= len(removed)

    def _stderr_suffix(self) -> str:
        if not self._stderr_parts:
            return ""
        return "; stderr=" + " | ".join(self._stderr_parts)[-self.max_stderr_chars :]

    @staticmethod
    def _tool_error_message(name: str, result: Mapping[str, Any]) -> str:
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or "").strip()
                if text:
                    return f"MCP tool {name} failed: {text[:2000]}"
        return f"MCP tool {name} failed"
