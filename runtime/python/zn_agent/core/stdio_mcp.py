from __future__ import annotations

"""Thin synchronous facade over the official MCP Python SDK.

ZN owns provider policy and evidence. The upstream SDK owns stdio transport,
JSON-RPC framing, lifecycle, protocol negotiation, validation, and subprocess
cleanup.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence



class StdioMcpError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StdioMcpCommand:
    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]


class StdioMcpClient:
    """Keep one official MCP Client alive behind ZN's synchronous runtime."""

    def __init__(
        self,
        *,
        command: StdioMcpCommand,
        expected_server_names: Sequence[str] = (),
        required_tools: Sequence[str] = (),
        timeout_seconds: float = 30.0,
        **_ignored: Any,
    ) -> None:
        if not command.argv:
            raise ValueError("MCP command argv must not be empty")
        self.command = command
        self.expected_server_names = frozenset(
            str(item).strip() for item in expected_server_names if str(item).strip()
        )
        self.required_tools = frozenset(
            str(item).strip() for item in required_tools if str(item).strip()
        )
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 300.0))
        self._portal_cm = None
        self._portal = None
        self._client_cm = None
        self._client: Any | None = None
        self._tool_names: frozenset[str] = frozenset()
        self._server_name = ""
        self._server_version = ""

    @property
    def running(self) -> bool:
        return self._client is not None

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
        try:
            from anyio.from_thread import start_blocking_portal
            from mcp import Client, StdioServerParameters

            params = StdioServerParameters(
                command=self.command.argv[0],
                args=list(self.command.argv[1:]),
                env=dict(self.command.env),
                cwd=self.command.cwd,
            )
            self._portal_cm = start_blocking_portal(
                backend="asyncio",
                name="zn-mcp-client",
            )
            self._portal = self._portal_cm.__enter__()
            client = Client(
                params,
                mode="legacy",
                read_timeout_seconds=self.timeout_seconds,
                cache=None,
            )
            self._client_cm = self._portal.wrap_async_context_manager(client)
            self._client = self._client_cm.__enter__()

            server_info = self._client.server_info
            if server_info is not None:
                self._server_name = str(server_info.name or "").strip()
                self._server_version = str(server_info.version or "").strip()
            if (
                self.expected_server_names
                and self._server_name not in self.expected_server_names
            ):
                raise StdioMcpError(
                    "unexpected MCP server identity: "
                    f"{self._server_name or '<missing>'}"
                )

            listed = self._portal.call(self._client.list_tools)
            self._tool_names = frozenset(
                str(tool.name or "").strip()
                for tool in listed.tools
                if str(tool.name or "").strip()
            )
            missing = self.required_tools.difference(self._tool_names)
            if missing:
                raise StdioMcpError(
                    "MCP runtime is missing required tools: "
                    + ", ".join(sorted(missing))
                )
            return self
        except BaseException as exc:
            self.close()
            if isinstance(exc, StdioMcpError):
                raise
            raise StdioMcpError(f"MCP client startup failed: {exc}") from exc

    def close(self) -> None:
        client_cm, portal_cm = self._client_cm, self._portal_cm
        self._client = None
        self._client_cm = None
        self._portal = None
        self._portal_cm = None
        self._tool_names = frozenset()
        self._server_name = ""
        self._server_version = ""
        if client_cm is not None:
            try:
                client_cm.__exit__(None, None, None)
            except Exception:
                pass
        if portal_cm is not None:
            try:
                portal_cm.__exit__(None, None, None)
            except Exception:
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
        self.start()
        if self._client is None or self._portal is None:
            raise StdioMcpError("MCP client is not running")
        tool = str(name or "").strip()
        if not tool:
            raise StdioMcpError("MCP tool name must not be empty")
        if self._tool_names and tool not in self._tool_names:
            raise StdioMcpError(f"MCP runtime does not expose tool: {tool}")
        try:
            result = self._portal.call(
                self._client.call_tool,
                tool,
                dict(arguments or {}),
            )
        except Exception as exc:
            raise StdioMcpError(f"MCP tool {tool} failed: {exc}") from exc
        payload = result.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )
        if bool(payload.get("isError")):
            raise StdioMcpError(self._tool_error_message(tool, payload))
        return payload

    def call_tool_text(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> str:
        result = self.call_tool(name, arguments)
        parts = [
            str(item.get("text") or "")
            for item in result.get("content", [])
            if isinstance(item, dict)
            and item.get("type") == "text"
            and str(item.get("text") or "")
        ]
        if parts:
            return "\n".join(parts)
        structured = result.get("structuredContent")
        if structured is None:
            return ""
        return json.dumps(
            structured,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _tool_error_message(name: str, result: Mapping[str, Any]) -> str:
        for item in result.get("content", []):
            if isinstance(item, dict) and str(item.get("text") or "").strip():
                return f"MCP tool {name} failed: {str(item['text'])[:2000]}"
        return f"MCP tool {name} failed"
