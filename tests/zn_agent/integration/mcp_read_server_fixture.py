from __future__ import annotations

"""Disposal-only, statically pinned MCP stdio fixture for CI integration."""

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

mcp = MCPServer("approved-test-server", version="1.0.2")


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
    structured_output=False,
)
def read_status(query: str) -> str:
    """Read a harmless synthetic status without modifying anything."""
    return "real-mcp-status:" + query


if __name__ == "__main__":
    mcp.run(transport="stdio")
