from __future__ import annotations

"""Explicitly approved MCP read tools inside ZN's existing Action Fabric/Body.

This is an adapter, not an agent runtime, plugin gateway or permission grant.
The caller must already have started and approved a pinned MCP server. MCP
tool annotations are advisory and NEVER authorize a tool on their own.
Side-effecting tools are intentionally unsupported in this first contract.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from .action_fabric import ActionAvailability, ActionDescriptor, ActionFabricRegistry
from .body import BodyAction, BodyActionResult, NativeBody
from .models import utc_now


class McpReadOnlyClient(Protocol):
    @property
    def running(self) -> bool: ...

    @property
    def server_name(self) -> str: ...

    @property
    def server_version(self) -> str: ...

    @property
    def tool_names(self) -> frozenset[str]: ...

    @property
    def tool_definitions(self) -> tuple[dict[str, Any], ...]: ...

    def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None = None
    ) -> dict[str, Any]: ...


@dataclass(slots=True)
class McpReadOnlyAttachment:
    """Disconnect a provider without changing ZN Work, Memory or ModelRouter."""

    fabric: ActionFabricRegistry
    body: NativeBody
    descriptors: tuple[ActionDescriptor, ...]
    _closed: bool = False

    def detach(self) -> None:
        if self._closed:
            return
        self._closed = True
        for descriptor in self.descriptors:
            self.fabric.unregister(descriptor.action_id)
            assert descriptor.body_action_kind is not None
            self.body.unregister_external_read_handler(descriptor.body_action_kind)


def _validated_schema(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("MCP tool must advertise an object input schema")
    # The existing Action Fabric validator currently supports shallow object
    # arguments. Do not pretend it validates arbitrary MCP JSON Schema trees.
    schema = dict(value)
    if schema.get("type") != "object":
        raise ValueError("MCP tool input schema must be a JSON object")
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping) or len(properties) > 32:
        raise ValueError("MCP tool properties must be a bounded object")
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(x, str) for x in required):
        raise ValueError("MCP required inputs must be string names")
    if len(required) != len(set(required)) or not set(required).issubset(properties):
        raise ValueError("MCP required inputs must name unique properties")
    if schema.get("additionalProperties", False) is not False:
        raise ValueError("MCP tool cannot allow undeclared arguments")
    forbidden = {"$ref", "$defs", "definitions", "allOf", "anyOf", "oneOf", "patternProperties"}
    if forbidden.intersection(schema):
        raise ValueError("MCP tool uses unsupported complex schema")
    safe_props: dict[str, Any] = {}
    for name, spec in properties.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,63}", name):
            raise ValueError("MCP tool property name is unsupported")
        if not isinstance(spec, Mapping) or spec.get("type") not in {"string", "number"}:
            raise ValueError("MCP read adapter supports scalar string/number inputs only")
        if forbidden.intersection(spec):
            raise ValueError("MCP tool property uses unsupported complex schema")
        safe_props[name] = dict(spec)
    result = {
        "type": "object",
        "properties": safe_props,
        "required": list(required),
        "additionalProperties": False,
    }
    if len(json.dumps(result, ensure_ascii=False, default=str)) > 16_384:
        raise ValueError("MCP tool schema exceeds bounded size")
    return result


def _catalog_matches(client: McpReadOnlyClient, name: str, expected_digest: str) -> bool:
    """Do not dispatch under a stale tool definition after provider changes."""
    for item in client.tool_definitions:
        if str(item.get("name") or "") != name:
            continue
        raw = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest() == expected_digest
    return False


def _response_text(response: Mapping[str, Any]) -> tuple[str, bool]:
    chunks = []
    for part in response.get("content", []) or []:
        if isinstance(part, Mapping) and part.get("type") == "text":
            chunks.append(str(part.get("text") or ""))
    if chunks:
        text = "\n".join(chunks)
    elif response.get("structuredContent") is not None:
        text = json.dumps(response["structuredContent"], ensure_ascii=False, default=str)
    else:
        text = ""
    return text[:12_000], len(text) > 12_000


def attach_approved_mcp_read_tools(
    *,
    fabric: ActionFabricRegistry,
    body: NativeBody,
    client: McpReadOnlyClient,
    provider_id: str,
    expected_server_name: str,
    expected_server_version: str,
    approved_tool_names: Sequence[str],
) -> McpReadOnlyAttachment:
    """Attach reviewed read tools to the SAME ZN Body and Action Fabric.

    Never starts an untrusted process, installs software or infers permission
    from MCP-supplied descriptions/annotations. The ZN caller must explicitly
    approve the exact server identity/version and tools beforehand.
    """
    provider_id = str(provider_id or "").strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", provider_id):
        raise ValueError("provider_id must be a stable lowercase namespace")
    if not expected_server_name or not expected_server_version:
        raise ValueError("approved MCP server identity and version are required")
    if not client.running:
        raise RuntimeError("MCP client must already be explicitly connected")
    if (
        client.server_name != expected_server_name
        or client.server_version != expected_server_version
    ):
        raise RuntimeError("MCP server identity/version does not match approval")

    approved = tuple(str(item or "").strip() for item in approved_tool_names)
    if not approved or len(approved) > 32 or len(set(approved)) != len(approved):
        raise ValueError("approved MCP tools must be a unique bounded allowlist")
    definitions = client.tool_definitions
    catalog: dict[str, Mapping[str, Any]] = {}
    for raw in definitions:
        if not isinstance(raw, Mapping):
            raise ValueError("MCP tool metadata is malformed")
        name = str(raw.get("name") or "").strip()
        if not name or name in catalog:
            raise ValueError("MCP tool catalog contains missing or duplicate names")
        catalog[name] = raw
    if not set(approved).issubset(catalog) or not set(approved).issubset(client.tool_names):
        raise ValueError("approved MCP tool not present in current connected catalog")

    prepared: list[tuple[ActionDescriptor, str, str]] = []
    for tool_name in approved:
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]{0,79}", tool_name):
            raise ValueError("MCP tool name is not a stable identifier")
        raw = catalog[tool_name]
        annotation = raw.get("annotations")
        if (
            not isinstance(annotation, Mapping)
            or annotation.get("readOnlyHint") is not True
            or annotation.get("destructiveHint") is True
        ):
            raise ValueError("only separately approved, MCP-annotated read tools are supported")
        schema = _validated_schema(raw.get("inputSchema"))
        action_id = f"mcp.{provider_id}.{tool_name}"
        # The stable kind carries NO tool-supplied free-form fields to Body.
        digest = hashlib.sha256(action_id.encode("utf-8")).hexdigest()[:24]
        kind = f"zn_mcp_read_{digest}"
        if fabric.descriptor(action_id) is not None:
            raise ValueError(f"Action Fabric already owns action {action_id}")
        if kind in body._external_read_handlers:
            raise ValueError("Body extension identifier collision")
        description = " ".join(str(raw.get("description") or tool_name).split())[:600]
        descriptor = ActionDescriptor(
            action_id=action_id,
            provider=f"zn.mcp.{provider_id}",
            description=f"Approved external read tool: {description}",
            body_action_kind=kind,
            input_schema=schema,
            effect_class="read_only",
            required_authority=("explicit_mcp_provider_approval",),
            sensitivity="external",
            preconditions=("approved connected MCP server identity and version",),
            verification=("fresh read-only Body observation; not goal completion",),
            replay_semantics="read_only",
            tags=("mcp", "external", "read_only", provider_id),
        )
        fingerprint = hashlib.sha256(
            json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        prepared.append((descriptor, tool_name, fingerprint))

    registered: list[ActionDescriptor] = []
    attached_kinds: list[str] = []
    try:
        for descriptor, tool_name, fingerprint in prepared:
            assert descriptor.body_action_kind is not None

            def call_read(
                action: BodyAction, started: str, *, name=tool_name, digest=fingerprint
            ) -> BodyActionResult:
                if (
                    not client.running
                    or client.server_name != expected_server_name
                    or client.server_version != expected_server_version
                    or name not in client.tool_names
                    or not _catalog_matches(client, name, digest)
                ):
                    raise RuntimeError("approved MCP connection is no longer current")
                if any(
                    isinstance(value, str) and len(value) > 16_384
                    for value in action.args.values()
                ):
                    raise ValueError("MCP read arguments exceed bounded size")
                try:
                    response = client.call_tool(name, dict(action.args))
                except Exception as exc:
                    # Provider errors can contain private returned content.
                    raise RuntimeError(
                        f"approved MCP read failed: {type(exc).__name__}"
                    ) from exc
                if not isinstance(response, Mapping) or bool(response.get("isError")):
                    raise RuntimeError("MCP tool returned a failed or malformed read result")
                text, truncated = _response_text(response)
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=True,
                    output=text,
                    data={
                        "provider_id": provider_id,
                        "tool": name,
                        "text": text,
                        "untrusted_external_evidence": True,
                        "truncated": truncated,
                    },
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )

            body.register_external_read_handler(descriptor.body_action_kind, call_read)
            attached_kinds.append(descriptor.body_action_kind)
            fabric.register(
                descriptor,
                availability_probe=lambda item, name=tool_name, digest=fingerprint: ActionAvailability(
                    item.action_id,
                    "available" if (
                        client.running
                        and client.server_name == expected_server_name
                        and client.server_version == expected_server_version
                        and name in client.tool_names
                        and _catalog_matches(client, name, digest)
                    ) else "unavailable",
                    reason="fresh approved MCP client state",
                    evidence={"provider_id": provider_id, "tool": name},
                ),
            )
            registered.append(descriptor)
    except Exception:
        for descriptor in registered:
            fabric.unregister(descriptor.action_id)
        for kind in attached_kinds:
            body.unregister_external_read_handler(kind)
        raise
    return McpReadOnlyAttachment(fabric, body, tuple(registered))
