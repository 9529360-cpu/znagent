from __future__ import annotations

"""One ZN-owned lifecycle for explicitly approved MCP Body read capabilities.

This is NOT a plugin installer, prompt-facing command launcher, or second Agent.
Approvals are constructed only by a trusted host after a user reviews the exact
server, command assets and tool allowlist. RPC requests can name those approved
entries but can never supply an executable, arguments, environment or grant.
"""

import hashlib
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .mcp_capability_adapter import (
    McpReadOnlyAttachment,
    attach_approved_mcp_read_tools,
)
from .stdio_mcp import StdioMcpClient, StdioMcpCommand


_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_PROVIDER_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
_INTERPRETERS = {
    "node", "node.exe", "python", "python.exe", "python3", "python3.exe",
    "pythonw.exe", "bun", "bun.exe",
}
_UNSAFE_LAUNCHERS = {
    "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
    "sh", "bash", "zsh", "fish", "npx", "npx.cmd", "npm", "npm.cmd",
}


@dataclass(frozen=True, slots=True)
class PinnedMcpFile:
    path: Path
    sha256: str

    def __post_init__(self) -> None:
        if not self.path.is_absolute() or not _SHA256_RE.fullmatch(self.sha256):
            raise ValueError("MCP approved file needs an absolute path and SHA-256")


@dataclass(frozen=True, slots=True)
class ApprovedMcpReadProvider:
    """Trusted approval data, never accepted from an Agent/RPC message.

    Executable and script files are hash-checked immediately before launch.
    This is version pinning/integrity, not a substitute for OS sandboxing.
    """

    provider_id: str
    expected_server_name: str
    expected_server_version: str
    approved_tool_names: tuple[str, ...]
    command: StdioMcpCommand
    pinned_files: tuple[PinnedMcpFile, ...]
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        if not _PROVIDER_RE.fullmatch(self.provider_id):
            raise ValueError("approved MCP provider needs a stable lowercase ID")
        if not self.expected_server_name or not self.expected_server_version:
            raise ValueError("approved MCP requires exact server name and version")
        if (
            not self.approved_tool_names
            or len(self.approved_tool_names) > 32
            or len(set(self.approved_tool_names)) != len(self.approved_tool_names)
        ):
            raise ValueError("approved MCP tools must be unique and bounded")
        argv = self.command.argv
        if not argv or len(argv) > 32 or any(not x or len(x) > 2048 for x in argv):
            raise ValueError("approved MCP command must have bounded exact arguments")
        executable = Path(argv[0])
        if not executable.is_absolute() or not self.command.cwd.is_absolute():
            raise ValueError("approved MCP command/cwd must be absolute")
        if executable.name.lower() in _UNSAFE_LAUNCHERS:
            raise ValueError("MCP shell/package-manager commands are not admissible")
        if not self.pinned_files or len(self.pinned_files) > 16:
            raise ValueError("approved MCP requires bounded pinned code assets")
        pinned = {str(item.path) for item in self.pinned_files}
        if len(pinned) != len(self.pinned_files) or str(executable) not in pinned:
            raise ValueError("approved MCP executable must be pinned exactly")
        if executable.name.lower() in _INTERPRETERS:
            scripts = {str(item.path) for item in self.pinned_files if item.path != executable}
            if not scripts.intersection(argv[1:]):
                raise ValueError("interpreted MCP server needs a pinned script argument")
            if any(item in {"-e", "-c", "-m", "--eval"} for item in argv[1:]):
                raise ValueError("inline/module code invocation is not approved")
        if not 1.0 <= self.timeout_seconds <= 60.0:
            raise ValueError("approved MCP timeout must be between 1 and 60 seconds")
        if len(self.command.env) > 64:
            raise ValueError("approved MCP environment is too large")


def _verify_approved_files(approval: ApprovedMcpReadProvider) -> None:
    if not approval.command.cwd.is_dir():
        raise RuntimeError("approved MCP working directory is unavailable")
    for pin in approval.pinned_files:
        if pin.path.is_symlink() or not pin.path.is_file():
            raise RuntimeError("approved MCP asset missing or symbolic link")
        with pin.path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != pin.sha256:
            raise RuntimeError("approved MCP executable or asset integrity changed")


class _ActiveMcpSession:
    """Serializes calls and shutdown, and NEVER restarts a disconnected child."""

    def __init__(self, client: Any):
        self._client = client
        self._lock = threading.RLock()
        self._stopped = False

    def start(self) -> "_ActiveMcpSession":
        with self._lock:
            if self._stopped:
                raise RuntimeError("approved MCP session has been stopped")
            self._client.start()
        return self

    @property
    def running(self) -> bool:
        with self._lock:
            return not self._stopped and bool(self._client.running)

    @property
    def server_name(self) -> str:
        with self._lock:
            return str(self._client.server_name) if not self._stopped else ""

    @property
    def server_version(self) -> str:
        with self._lock:
            return str(self._client.server_version) if not self._stopped else ""

    @property
    def tool_names(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._client.tool_names) if not self._stopped else frozenset()

    @property
    def tool_definitions(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(self._client.tool_definitions) if not self._stopped else ()

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            if self._stopped or not self._client.running:
                raise RuntimeError("approved MCP session was disconnected")
            return self._client.call_tool(name, arguments)

    def close(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self._client.close()


@dataclass(slots=True)
class _Connection:
    session: _ActiveMcpSession
    attachment: McpReadOnlyAttachment


class McpReadCapabilityHost:
    """Trusted optional Body extension hosted by the existing ZN Resident."""

    def __init__(
        self,
        resident: Any,
        *,
        approvals: Sequence[ApprovedMcpReadProvider] = (),
        client_factory: Callable[..., Any] = StdioMcpClient,
    ) -> None:
        self._fabric = resident.action_fabric
        self._body = resident.body
        self._lock = threading.RLock()
        self._closed = False
        self._approved: dict[str, ApprovedMcpReadProvider] = {}
        self._active: dict[str, _Connection] = {}
        for approval in approvals:
            if approval.provider_id in self._approved:
                raise ValueError("duplicate approved MCP provider")
            self._approved[approval.provider_id] = approval
        self._client_factory = client_factory

    def catalog(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._status(provider_id) for provider_id in sorted(self._approved)]

    def _status(self, provider_id: str) -> dict[str, Any]:
        approval = self._approved[provider_id]
        connection = self._active.get(provider_id)
        running = bool(connection and connection.session.running)
        return {
            "provider_id": provider_id,
            "server_name": approval.expected_server_name,
            "server_version": approval.expected_server_version,
            "approved_tools": list(approval.approved_tool_names),
            "connected": running,
            "action_ids": (
                [item.action_id for item in connection.attachment.descriptors]
                if running and connection else []
            ),
        }

    def connect(self, provider_id: str) -> dict[str, Any]:
        with self._lock:
            if self._closed:
                raise RuntimeError("MCP Body capability host is shut down")
            approval = self._approved.get(provider_id)
            if approval is None:
                raise ValueError("MCP provider has no preapproved host capability")
            old = self._active.get(provider_id)
            if old and old.session.running:
                return self._status(provider_id)
            if old is not None:
                self._disconnect(provider_id)
            _verify_approved_files(approval)
            session: _ActiveMcpSession | None = None
            try:
                session = _ActiveMcpSession(self._client_factory(
                    command=approval.command,
                    expected_server_names=(approval.expected_server_name,),
                    required_tools=approval.approved_tool_names,
                    timeout_seconds=approval.timeout_seconds,
                )).start()
                attachment = attach_approved_mcp_read_tools(
                    fabric=self._fabric,
                    body=self._body,
                    client=session,
                    provider_id=provider_id,
                    expected_server_name=approval.expected_server_name,
                    expected_server_version=approval.expected_server_version,
                    approved_tool_names=approval.approved_tool_names,
                )
            except Exception as exc:
                if session is not None:
                    session.close()
                # Never expose untrusted provider stderr/transport secrets over RPC.
                raise RuntimeError(
                    f"approved MCP admission failed: {type(exc).__name__}"
                ) from exc
            self._active[provider_id] = _Connection(session, attachment)
            return self._status(provider_id)

    def disconnect(self, provider_id: str) -> dict[str, Any]:
        with self._lock:
            if provider_id not in self._approved:
                raise ValueError("MCP provider has no preapproved host capability")
            self._disconnect(provider_id)
            return self._status(provider_id)

    def _disconnect(self, provider_id: str) -> None:
        connection = self._active.pop(provider_id, None)
        if connection is None:
            return
        try:
            connection.attachment.detach()
        finally:
            connection.session.close()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for provider_id in tuple(self._active):
                self._disconnect(provider_id)
