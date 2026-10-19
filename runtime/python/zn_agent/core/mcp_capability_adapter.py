from __future__ import annotations

"""Explicitly approved MCP tools inside ZN's existing Action Fabric/Body.

This is an adapter, not an agent runtime, plugin gateway or permission grant.
The caller must already have started and approved a pinned MCP server. MCP
tool annotations are advisory and NEVER authorize a tool on their own.

Read tools use the read-only contract below. Write-capable tools use the
separate M-7 contract (``attach_approved_mcp_write_tools``): per-tool explicit
approval (default off), a replay identity that refuses a blind second
dispatch of the same occurrence, and a host-supplied postcondition probe
that must verify the effect. Body success is dispatch evidence only, never
proof the effect holds.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from .action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionEffectClass,
    ActionFabricRegistry,
)
from .approval_cards import validate_approval_kind
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

# ---------------------------------------------------------------------------
# M-7 write-capable MCP contract: per-tool explicit approval + replay
# identity + postcondition verification.
# ---------------------------------------------------------------------------

# The client shape is the same transport protocol as the read contract; the
# difference is what ZN allows the caller to do with it, not the wire shape.
McpWriteCapableClient = McpReadOnlyClient

_MCP_WRITE_REVERSIBILITY: dict[str, str] = {
    "reversible_side_effect": "reversible",
    "potential_side_effect": "unknown",
    "irreversible_side_effect": "irreversible",
}


@dataclass(frozen=True, slots=True)
class ApprovedMcpWriteTool:
    """ZN-owned per-tool approval for one write-capable MCP tool.

    This is the explicit permission ZN.md requires before a write-capable
    plugin may be enabled. It is constructed by a trusted host, never from
    MCP-supplied metadata or a model proposal. ``verification`` names the
    postcondition the host's probe must observe; it is descriptive, and the
    probe itself is what enforces it.
    """

    tool_name: str
    effect_class: ActionEffectClass
    approval_kind: str
    verification: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        tool_name = str(self.tool_name or "").strip()
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]{0,79}", tool_name):
            raise ValueError("MCP write tool name is not a stable identifier")
        object.__setattr__(self, "tool_name", tool_name)
        if self.effect_class not in _MCP_WRITE_REVERSIBILITY:
            raise ValueError(
                "MCP write tool needs an explicit side-effect class, "
                "never read_only"
            )
        object.__setattr__(
            self, "approval_kind", validate_approval_kind(self.approval_kind)
        )
        verification = tuple(
            dict.fromkeys(
                value for value in (str(item or "").strip() for item in self.verification)
                if value
            )
        )
        if not verification:
            raise ValueError("MCP write tool needs at least one named postcondition")
        object.__setattr__(self, "verification", verification)


@dataclass(frozen=True, slots=True)
class McpWritePostcondition:
    """Outcome of one host-supplied postcondition probe."""

    verified: bool
    reason: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "verified", bool(self.verified))
        object.__setattr__(self, "reason", " ".join(str(self.reason or "").split()))
        object.__setattr__(self, "evidence", dict(self.evidence or {}))


class McpWritePostconditionProbe(Protocol):
    """Fresh observation of whether a dispatched write effect holds.

    The probe must observe through a path independent of the write tool's
    own success claim -- typically a read tool on the same provider, a
    local readback, or a trusted record -- never ``isError is False``.
    It receives the dispatched request args and the Body result; it must
    never redispatch the write itself.
    """

    def __call__(
        self, args: Mapping[str, Any], result: BodyActionResult
    ) -> McpWritePostcondition: ...


def mcp_write_replay_identity(
    *,
    provider_id: str,
    tool_name: str,
    args: Mapping[str, Any],
    event_id: str | None,
) -> str:
    """Stable identity of one write occurrence: provider + tool + args + event.

    Resident-applied ``__zn_*`` bindings (WorkerRun authority, workspace
    roots) are not part of the identity: they are plumbing, not the effect
    the user approved, mirroring the approval-snapshot rule that such keys
    may be added after approval. Two dispatches with the same identity are
    the same occurrence, and the second must not blindly re-apply it.
    """
    visible_args = {
        str(key): value
        for key, value in dict(args or {}).items()
        if not str(key).startswith("__zn_")
    }
    canonical = json.dumps(
        {
            "provider_id": str(provider_id or ""),
            "tool": str(tool_name or ""),
            "args": visible_args,
            "event_id": str(event_id or "").strip() or None,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_write_capable(annotation: Any) -> bool:
    """Classify one tool catalog entry as write-capable from annotations.

    Annotations are advisory, so ambiguity fails toward the stronger
    contract: a tool is treated as write-capable unless it is explicitly
    annotated read-only AND non-destructive. The caller must still approve
    it per tool; classification only decides which contract may admit it.
    """
    if not isinstance(annotation, Mapping):
        raise ValueError("MCP tool annotations are missing or malformed")
    if annotation.get("destructiveHint") is True:
        return True
    return annotation.get("readOnlyHint") is not True


@dataclass(slots=True)
class McpWriteAttachment:
    """Disconnect a write provider without changing ZN Work/Memory/ModelRouter."""

    fabric: ActionFabricRegistry
    body: NativeBody
    descriptors: tuple[ActionDescriptor, ...]
    probes: Mapping[str, McpWritePostconditionProbe]
    _closed: bool = False

    def detach(self) -> None:
        if self._closed:
            return
        self._closed = True
        for descriptor in self.descriptors:
            self.fabric.unregister(descriptor.action_id)
            assert descriptor.body_action_kind is not None
            self.body.unregister_external_write_handler(descriptor.body_action_kind)

    def register_verifications(self, runtime: Any) -> None:
        """Wire each tool's probe into an ActionExecutionRuntime.

        The runtime's observer runs the probe as the fresh postcondition
        observation and its verifier turns the probe outcome into the
        execution verdict. Without this wiring the runtime fails closed:
        a side-effect action with no verifier reports "no independent
        postcondition verifier" instead of treating Body success as proof.
        """
        for descriptor in self.descriptors:
            probe = self.probes[descriptor.action_id]
            runtime.register_verification(
                descriptor.action_id,
                observe=_mcp_write_observer(probe),
                verify=_mcp_write_verifier,
            )


def _mcp_write_observer(
    probe: McpWritePostconditionProbe,
) -> Callable[[Any, BodyActionResult | None], Any]:
    from .action_execution import ActionObservation

    def observe(request: Any, result: BodyActionResult | None) -> ActionObservation:
        if result is None:
            raise RuntimeError("MCP write postcondition needs a Body result")
        outcome = probe(dict(request.args or {}), result)
        if not isinstance(outcome, McpWritePostcondition):
            raise ValueError("MCP write postcondition probe returned a malformed outcome")
        return ActionObservation(
            request.action_id,
            "mcp_write_postcondition",
            data={
                "verified": bool(outcome.verified),
                "reason": outcome.reason,
                "evidence": dict(outcome.evidence or {}),
            },
            observed_at=result.completed_at or utc_now(),
        )

    return observe


def _mcp_write_verifier(request: Any, observation: Any, result: BodyActionResult | None) -> Any:
    from .action_execution import ActionVerification

    data = dict(observation.data or {})
    if data.get("verified") is True:
        return ActionVerification(
            "verified",
            str(data.get("reason") or "MCP write postcondition verified"),
            evidence={
                "body_action_id": result.action_id if result is not None else None,
                "postcondition": data.get("evidence") or {},
            },
            observed_at=observation.observed_at,
        )
    return ActionVerification(
        "failed",
        str(data.get("reason") or "MCP write postcondition not met"),
        evidence={
            "body_action_id": result.action_id if result is not None else None,
            "postcondition": data.get("evidence") or {},
        },
        observed_at=observation.observed_at,
    )


def attach_approved_mcp_write_tools(
    *,
    fabric: ActionFabricRegistry,
    body: NativeBody,
    client: McpWriteCapableClient,
    provider_id: str,
    expected_server_name: str,
    expected_server_version: str,
    approved_tools: Sequence[ApprovedMcpWriteTool],
    postcondition_probes: Mapping[str, McpWritePostconditionProbe],
) -> McpWriteAttachment:
    """Attach explicitly approved write-capable MCP tools to ZN Body/Fabric.

    Default is off: a write-capable tool in the provider catalog that is not
    in ``approved_tools`` is never registered, never gets a Body handler,
    and stays uncallable. Each approved tool needs its own approval record
    (effect class + approval kind + named postcondition) and its own
    postcondition probe; a missing or extra probe refuses the whole attach.

    Replay: the handler records the replay identity of every dispatch that
    reached the provider (any returned response, including ``isError`` --
    the provider may have applied the effect before reporting failure).
    A second dispatch with the same identity raises instead of calling the
    provider again; the caller re-observes with the probe rather than
    redispatching. A transport exception (no response) records nothing, so
    a genuinely unreached dispatch may be retried under the same identity.
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

    approved = tuple(approved_tools or ())
    if not approved or len(approved) > 32:
        raise ValueError("approved MCP write tools must be a unique bounded allowlist")
    approved_names = [item.tool_name for item in approved]
    if len(set(approved_names)) != len(approved_names):
        raise ValueError("approved MCP write tools must be a unique bounded allowlist")
    probes = dict(postcondition_probes or {})
    if set(probes) != set(approved_names):
        raise ValueError(
            "MCP write tools need exactly one postcondition probe each: "
            "missing or unapproved probes are refused"
        )
    for probe in probes.values():
        if not callable(probe):
            raise TypeError("MCP write postcondition probe must be callable")

    definitions = client.tool_definitions
    catalog: dict[str, Mapping[str, Any]] = {}
    for raw in definitions:
        if not isinstance(raw, Mapping):
            raise ValueError("MCP tool metadata is malformed")
        name = str(raw.get("name") or "").strip()
        if not name or name in catalog:
            raise ValueError("MCP tool catalog contains missing or duplicate names")
        catalog[name] = raw
    if not set(approved_names).issubset(catalog) or not set(approved_names).issubset(
        client.tool_names
    ):
        raise ValueError("approved MCP write tool not present in current connected catalog")

    # In-process record of occurrences that already reached the provider.
    # This is replay protection for one attachment lifetime, not durable
    # idempotency: the provider itself is never assumed idempotent, and a
    # fresh occurrence (new event_id) is a distinct, separately approved act.
    completed_identities: set[str] = set()

    prepared: list[tuple[ActionDescriptor, str, str, ApprovedMcpWriteTool]] = []
    for approval in approved:
        tool_name = approval.tool_name
        raw = catalog[tool_name]
        if not _is_write_capable(raw.get("annotations")):
            raise ValueError(
                f"MCP tool {tool_name!r} is annotated read-only; "
                "admit it through the read contract, not the write contract"
            )
        schema = _validated_schema(raw.get("inputSchema"))
        action_id = f"mcp.{provider_id}.{tool_name}"
        # The stable kind carries NO tool-supplied free-form fields to Body.
        digest = hashlib.sha256(action_id.encode("utf-8")).hexdigest()[:24]
        kind = f"zn_mcp_write_{digest}"
        if fabric.descriptor(action_id) is not None:
            raise ValueError(f"Action Fabric already owns action {action_id}")
        if kind in body._external_write_handlers:
            raise ValueError("Body extension identifier collision")
        description = " ".join(str(raw.get("description") or tool_name).split())[:600]
        descriptor = ActionDescriptor(
            action_id=action_id,
            provider=f"zn.mcp.{provider_id}",
            description=f"Approved external write tool: {description}",
            body_action_kind=kind,
            input_schema=schema,
            effect_class=approval.effect_class,
            required_authority=(
                "explicit_mcp_provider_approval",
                "explicit_mcp_write_tool_approval",
            ),
            sensitivity="external",
            preconditions=(
                "approved connected MCP server identity and version",
                "per-tool explicit write approval",
                "stable event_id for the write occurrence",
            ),
            postconditions=tuple(approval.verification),
            verification=(
                "independent postcondition probe must verify the effect; "
                "Body success is dispatch evidence only",
                *approval.verification,
            ),
            reversibility=_MCP_WRITE_REVERSIBILITY[approval.effect_class],
            replay_semantics="verify_before_replay",
            tags=(
                "mcp",
                "external",
                "mcp_write",
                provider_id,
                f"approval:{approval.approval_kind}",
            ),
        )
        fingerprint = hashlib.sha256(
            json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        prepared.append((descriptor, tool_name, fingerprint, approval))

    registered: list[ActionDescriptor] = []
    attached_kinds: list[str] = []
    try:
        for descriptor, tool_name, fingerprint, _approval in prepared:
            assert descriptor.body_action_kind is not None

            def call_write(
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
                    raise ValueError("MCP write arguments exceed bounded size")
                identity = mcp_write_replay_identity(
                    provider_id=provider_id,
                    tool_name=name,
                    args=action.args,
                    event_id=action.event_id,
                )
                if identity in completed_identities:
                    raise RuntimeError(
                        "MCP write replay refused: this exact write occurrence "
                        "already reached the provider; re-observe with the "
                        "postcondition probe instead of redispatching"
                    )
                try:
                    response = client.call_tool(name, dict(action.args))
                except Exception as exc:
                    # No response: ZN cannot know the provider was reached,
                    # so the identity is not recorded and a retry may proceed.
                    # Provider errors can contain private returned content.
                    raise RuntimeError(
                        f"approved MCP write failed: {type(exc).__name__}"
                    ) from exc
                # Any returned response means the provider processed the
                # dispatch, so the identity is recorded even on isError:
                # the effect may already have been applied.
                completed_identities.add(identity)
                if not isinstance(response, Mapping) or bool(response.get("isError")):
                    raise RuntimeError(
                        "MCP write tool returned a failed or malformed result; "
                        "effect state is uncertain, re-observe with the "
                        "postcondition probe instead of redispatching"
                    )
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
                        "replay_identity": identity,
                        "replayed": False,
                    },
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )

            body.register_external_write_handler(descriptor.body_action_kind, call_write)
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
            body.unregister_external_write_handler(kind)
        raise
    return McpWriteAttachment(
        fabric,
        body,
        tuple(registered),
        {
            descriptor.action_id: probes[tool_name]
            for descriptor, tool_name, _, _ in prepared
        },
    )
