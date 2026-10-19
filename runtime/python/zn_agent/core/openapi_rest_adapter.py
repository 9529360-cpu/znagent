from __future__ import annotations

"""OpenAPI spec -> ActionDescriptor generic REST tool wiring (M-8).

One approved OpenAPI document becomes ZN tools on the SAME Action
Fabric/Body as every other capability. Read operations (GET/HEAD) are
registered as read-only tools. Write operations (POST/PUT/PATCH/DELETE)
are registered ONLY when the host supplies a per-tool approval through
the M-7 write contract (``ApprovedRestWriteTool`` subclasses
``ApprovedMcpWriteTool``: per-tool explicit approval + replay identity +
host-supplied postcondition probe). An unapproved write operation is
never registered, never gets a Body handler, and stays uncallable.

Deliberate limits, mirroring the MCP adapter's shallow-schema honesty:

- Only OpenAPI 3.x documents, only local ``#/components/...`` ``$ref``s,
  only shallow scalar parameter/body schemas (string/number/integer/
  boolean). Anything more complex is an explicit ``ValueError``, never a
  silently lossy conversion.
- Only ``application/json`` request bodies; GET/HEAD operations must not
  declare one.
- No automatic authorization: the spec's ``security`` declarations are
  never turned into credentials. When the caller needs auth, it supplies
  an opaque ``credential_ref`` plus a resolver that returns request
  headers at call time; the adapter never sees, stores, or logs a
  credential value.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.parse import quote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionEffectClass,
    ActionFabricRegistry,
)
from .body import BodyAction, BodyActionResult, NativeBody
from .credential_isolation import is_credential_reference
from .mcp_capability_adapter import (
    ApprovedMcpWriteTool,
    McpWritePostcondition,
    McpWritePostconditionProbe,
    mcp_write_replay_identity,
)
from .models import utc_now

__all__ = [
    "ApprovedRestWriteTool",
    "OpenApiOperation",
    "OpenApiRestAttachment",
    "ParsedOpenApiSpec",
    "RestHttpClient",
    "RestHttpResponse",
    "UrllibRestHttpClient",
    "attach_openapi_rest_tools",
    "parse_openapi_spec",
]

_PROVIDER_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
_NAME_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{0,63}")
_OPERATION_ID_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_.-]{0,79}")
_HTTP_METHODS = ("get", "head", "post", "put", "patch", "delete")
_READ_METHODS = frozenset({"get", "head"})
_WRITE_METHODS = frozenset({"post", "put", "patch", "delete"})
_SCALAR_TYPES = frozenset({"string", "number", "integer", "boolean"})
_COMPLEX_SCHEMA_KEYS = frozenset(
    {"allOf", "anyOf", "oneOf", "not", "items", "properties", "patternProperties"}
)
_MAX_ARGS_STRING = 16_384
_MAX_OUTPUT_CHARS = 12_000
_MAX_RESPONSE_BYTES = 1_000_000

_REST_WRITE_REVERSIBILITY: dict[str, str] = {
    "reversible_side_effect": "reversible",
    "potential_side_effect": "unknown",
    "irreversible_side_effect": "irreversible",
}


class ApprovedRestWriteTool(ApprovedMcpWriteTool):
    """REST spelling of the M-7 write approval contract.

    Inherits every validation from ``ApprovedMcpWriteTool`` (stable tool
    name, explicit non-read-only effect class, validated approval kind,
    at least one named postcondition) so the approval contract exists in
    exactly one place. ``tool_name`` is the operation id from
    :func:`parse_openapi_spec`.
    """


@dataclass(frozen=True, slots=True)
class OpenApiOperation:
    """One validated OpenAPI operation, ready to become a tool."""

    operation_id: str
    method: str
    path: str
    summary: str
    input_schema: Mapping[str, Any]
    path_params: tuple[str, ...] = ()
    query_params: tuple[str, ...] = ()
    header_params: tuple[str, ...] = ()
    body_params: tuple[str, ...] = ()

    @property
    def is_read(self) -> bool:
        return self.method in _READ_METHODS


@dataclass(frozen=True, slots=True)
class ParsedOpenApiSpec:
    """A validated OpenAPI document: operations + declared server URLs."""

    title: str
    servers: tuple[str, ...]
    operations: tuple[OpenApiOperation, ...]


@dataclass(frozen=True, slots=True)
class RestHttpResponse:
    """One HTTP response, including error statuses (not exceptions)."""

    status_code: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    @property
    def json_value(self) -> Any:
        try:
            return json.loads(self.text) if self.text.strip() else None
        except (ValueError, UnicodeDecodeError):
            return None


class RestHttpClient(Protocol):
    """Synchronous HTTP transport, injectable for tests and mock services."""

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any],
        headers: Mapping[str, str],
        json_body: Mapping[str, Any] | None,
        timeout_seconds: float,
    ) -> RestHttpResponse: ...


class UrllibRestHttpClient:
    """Stdlib ``urllib`` transport: no new dependency, bounded reads.

    HTTP error statuses are returned as responses (the caller decides
    what a non-2xx status means); only transport failures raise.
    """

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any],
        headers: Mapping[str, str],
        json_body: Mapping[str, Any] | None,
        timeout_seconds: float,
    ) -> RestHttpResponse:
        query = urlencode(
            {str(key): _scalar_text(value) for key, value in dict(params).items()},
            doseq=False,
        )
        full_url = f"{url}?{query}" if query else url
        payload = (
            json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            if json_body is not None
            else None
        )
        request = Request(
            full_url,
            data=payload,
            method=str(method or "GET").upper(),
        )
        for name, value in dict(headers).items():
            request.add_header(str(name), str(value))
        if payload is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=float(timeout_seconds)) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)[: _MAX_RESPONSE_BYTES + 1]
                return RestHttpResponse(
                    status_code=int(response.status),
                    headers={
                        str(k): str(v) for k, v in response.headers.items()
                    },
                    body=bytes(raw),
                )
        except HTTPError as exc:
            raw = exc.read(_MAX_RESPONSE_BYTES + 1)[: _MAX_RESPONSE_BYTES + 1]
            return RestHttpResponse(
                status_code=int(exc.code),
                headers={str(k): str(v) for k, v in exc.headers.items()},
                body=bytes(raw),
            )
        except URLError as exc:
            raise RuntimeError(
                f"REST transport failed: {type(exc).__name__}"
            ) from exc


def _scalar_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


# ---------------------------------------------------------------------------
# Spec parsing
# ---------------------------------------------------------------------------


def _resolve_ref(
    node: Any, root: Mapping[str, Any], *, seen: tuple[str, ...]
) -> Any:
    """Resolve one local ``#/components/...`` $ref, with a cycle guard."""
    if not isinstance(node, Mapping):
        return node
    ref = node.get("$ref")
    if ref is None:
        return node
    if not isinstance(ref, str) or not ref.startswith("#/"):
        raise ValueError(
            "OpenAPI spec uses an unsupported non-local $ref; "
            "only local #/components/... references are supported"
        )
    if ref in seen:
        raise ValueError(f"OpenAPI spec contains a cyclic $ref: {ref}")
    target: Any = root
    for part in ref[2:].split("/"):
        if not isinstance(target, Mapping) or part not in target:
            raise ValueError(f"OpenAPI spec $ref target is missing: {ref}")
        target = target[part]
    resolved = _resolve_ref(target, root, seen=(*seen, ref))
    extra = {key: value for key, value in node.items() if key != "$ref"}
    if extra:
        if not isinstance(resolved, Mapping):
            raise ValueError("OpenAPI spec $ref sibling keys need an object target")
        merged = dict(resolved)
        merged.update(extra)
        return merged
    return resolved


def _scalar_property(name: str, spec: Any, root: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one shallow scalar schema property; reject complex trees."""
    resolved = _resolve_ref(spec, root, seen=())
    if not isinstance(resolved, Mapping):
        raise ValueError(f"OpenAPI schema for parameter {name!r} is malformed")
    if _COMPLEX_SCHEMA_KEYS.intersection(resolved):
        raise ValueError(
            f"OpenAPI schema for parameter {name!r} uses an unsupported "
            "complex schema (objects/arrays/composition are not supported)"
        )
    schema_type = resolved.get("type", "string")
    if schema_type not in _SCALAR_TYPES:
        raise ValueError(
            f"OpenAPI schema for parameter {name!r} has unsupported type "
            f"{schema_type!r}; only string/number/integer/boolean are supported"
        )
    safe: dict[str, Any] = {"type": schema_type}
    for key in ("description", "enum", "default", "format"):
        if key in resolved:
            safe[key] = resolved[key]
    return safe


def _object_schema(
    properties: Mapping[str, Any],
    required: Sequence[str],
    root: Mapping[str, Any],
    *,
    context: str,
) -> dict[str, Any]:
    if len(properties) > 64:
        raise ValueError(f"OpenAPI {context} declares too many inputs (max 64)")
    safe_props: dict[str, Any] = {}
    for name, spec in properties.items():
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise ValueError(
                f"OpenAPI {context} parameter name {name!r} is unsupported; "
                "names must match [a-zA-Z][a-zA-Z0-9_]{0,63}"
            )
        safe_props[name] = _scalar_property(name, spec, root)
    required_list = list(required or [])
    if len(required_list) != len(set(required_list)) or not set(
        required_list
    ).issubset(safe_props):
        raise ValueError(f"OpenAPI {context} required inputs must name unique inputs")
    schema = {
        "type": "object",
        "properties": safe_props,
        "required": required_list,
        "additionalProperties": False,
    }
    if len(json.dumps(schema, ensure_ascii=False, default=str)) > 16_384:
        raise ValueError(f"OpenAPI {context} schema exceeds bounded size")
    return schema


def _parse_parameters(
    raw_params: Any, root: Mapping[str, Any], *, context: str
) -> list[dict[str, Any]]:
    if raw_params is None:
        return []
    if not isinstance(raw_params, list):
        raise ValueError(f"OpenAPI {context} parameters must be a list")
    parsed: list[dict[str, Any]] = []
    for entry in raw_params:
        resolved = _resolve_ref(entry, root, seen=())
        if not isinstance(resolved, Mapping):
            raise ValueError(f"OpenAPI {context} parameter is malformed")
        name = resolved.get("name")
        location = resolved.get("in")
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise ValueError(
                f"OpenAPI {context} parameter name {name!r} is unsupported; "
                "names must match [a-zA-Z][a-zA-Z0-9_]{0,63}"
            )
        if location not in {"path", "query", "header", "cookie"}:
            raise ValueError(
                f"OpenAPI {context} parameter {name!r} has unsupported location "
                f"{location!r}"
            )
        if location == "cookie":
            raise ValueError(
                f"OpenAPI {context} cookie parameter {name!r} is not supported; "
                "cookies must never carry credentials or session state"
            )
        if "content" in resolved:
            raise ValueError(
                f"OpenAPI {context} parameter {name!r} uses content-style "
                "serialization, which is not supported"
            )
        schema = resolved.get("schema")
        if schema is None:
            raise ValueError(
                f"OpenAPI {context} parameter {name!r} needs a schema"
            )
        parsed.append(
            {
                "name": name,
                "in": location,
                "required": bool(resolved.get("required", False)),
                "schema": schema,
            }
        )
    return parsed


def _derived_operation_id(method: str, path: str) -> str:
    slug = path.strip("/").replace("{", "by_").replace("}", "")
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    candidate = f"{method}_{slug}" if slug else method
    if not _OPERATION_ID_RE.fullmatch(candidate):
        raise ValueError(
            f"OpenAPI operation {method.upper()} {path} has no usable operation id"
        )
    return candidate


def parse_openapi_spec(spec: Mapping[str, Any] | str | bytes) -> ParsedOpenApiSpec:
    """Parse and validate an OpenAPI 3.x document into operations.

    Accepts a mapping or a JSON document (``str``/``bytes``). Raises
    ``ValueError`` with an explicit reason for any illegal spec: wrong
    version, missing paths, duplicate operation ids, unsupported complex
    schemas, unresolved $refs, GET-with-body, or a write operation
    without a declared 2xx response.
    """
    if isinstance(spec, (str, bytes)):
        try:
            parsed_json = json.loads(spec)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("OpenAPI spec is not valid JSON") from exc
        if not isinstance(parsed_json, Mapping):
            raise ValueError("OpenAPI spec must be a JSON object")
        spec = parsed_json
    if not isinstance(spec, Mapping):
        raise ValueError("OpenAPI spec must be a mapping")
    version = spec.get("openapi")
    if not isinstance(version, str) or not version.startswith("3."):
        raise ValueError(
            "OpenAPI spec must declare an OpenAPI 3.x version; "
            f"got {version!r}"
        )
    info = spec.get("info")
    if not isinstance(info, Mapping) or not str(info.get("title") or "").strip():
        raise ValueError("OpenAPI spec needs info.title")
    title = " ".join(str(info.get("title")).split())
    raw_servers = spec.get("servers", [])
    if raw_servers is None:
        raw_servers = []
    if not isinstance(raw_servers, list):
        raise ValueError("OpenAPI spec servers must be a list")
    servers: list[str] = []
    for entry in raw_servers:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("url"), str):
            raise ValueError("OpenAPI spec server entry needs a url string")
        servers.append(entry["url"])
    paths = spec.get("paths")
    if not isinstance(paths, Mapping) or not paths:
        raise ValueError("OpenAPI spec needs a non-empty paths object")
    operations: list[OpenApiOperation] = []
    seen_ids: set[str] = set()
    for raw_path, path_item in paths.items():
        if not isinstance(raw_path, str) or not raw_path.startswith("/"):
            raise ValueError(f"OpenAPI path {raw_path!r} must start with '/'")
        if not isinstance(path_item, Mapping):
            raise ValueError(f"OpenAPI path {raw_path!r} is malformed")
        path_level_params = _parse_parameters(
            path_item.get("parameters"), spec, context=f"{raw_path} parameters"
        )
        template_params = set(re.findall(r"\{([^{}]+)\}", raw_path))
        for method in _HTTP_METHODS:
            raw_operation = path_item.get(method)
            if raw_operation is None:
                continue
            if not isinstance(raw_operation, Mapping):
                raise ValueError(
                    f"OpenAPI operation {method.upper()} {raw_path} is malformed"
                )
            context = f"{method.upper()} {raw_path}"
            declared_id = raw_operation.get("operationId")
            if declared_id is not None:
                if not isinstance(declared_id, str) or not _OPERATION_ID_RE.fullmatch(
                    declared_id
                ):
                    raise ValueError(
                        f"OpenAPI {context} operationId {declared_id!r} is not a "
                        "stable identifier"
                    )
                operation_id = declared_id
            else:
                operation_id = _derived_operation_id(method, raw_path)
            if operation_id in seen_ids:
                raise ValueError(
                    f"OpenAPI spec contains duplicate operationId {operation_id!r}"
                )
            seen_ids.add(operation_id)
            # Responses: at least one declared 2xx (or "default").
            responses = raw_operation.get("responses")
            if not isinstance(responses, Mapping) or not responses:
                raise ValueError(f"OpenAPI {context} needs a responses object")
            if not any(
                str(code) in ("default",) or str(code).startswith("2")
                for code in responses
            ):
                raise ValueError(
                    f"OpenAPI {context} must declare a 2xx response"
                )
            # Parameters: operation-level overrides path-level by (name, in).
            merged: dict[tuple[str, str], dict[str, Any]] = {
                (item["name"], item["in"]): item for item in path_level_params
            }
            for item in _parse_parameters(
                raw_operation.get("parameters"), spec, context=f"{context} parameters"
            ):
                merged[(item["name"], item["in"])] = item
            params = list(merged.values())
            declared_path = {
                item["name"] for item in params if item["in"] == "path"
            }
            if declared_path != template_params:
                raise ValueError(
                    f"OpenAPI {context} path parameters must exactly match "
                    f"the path template {sorted(template_params)}"
                )
            for item in params:
                if item["in"] == "path" and not item["required"]:
                    raise ValueError(
                        f"OpenAPI {context} path parameter {item['name']!r} "
                        "must be required"
                    )
            request_body = raw_operation.get("requestBody")
            body_props: dict[str, Any] = {}
            body_required: list[str] = []
            if request_body is not None:
                if method in _READ_METHODS:
                    raise ValueError(
                        f"OpenAPI {context} is a read operation and must not "
                        "declare a requestBody"
                    )
                resolved_body = _resolve_ref(request_body, spec, seen=())
                if not isinstance(resolved_body, Mapping):
                    raise ValueError(f"OpenAPI {context} requestBody is malformed")
                content = resolved_body.get("content")
                if not isinstance(content, Mapping):
                    raise ValueError(
                        f"OpenAPI {context} requestBody needs a content object"
                    )
                json_media = content.get("application/json")
                if json_media is None:
                    raise ValueError(
                        f"OpenAPI {context} requestBody must declare "
                        "application/json; only JSON request bodies are supported"
                    )
                if not isinstance(json_media, Mapping):
                    raise ValueError(
                        f"OpenAPI {context} requestBody JSON media entry is malformed"
                    )
                body_schema = _resolve_ref(
                    json_media.get("schema"), spec, seen=()
                )
                if not isinstance(body_schema, Mapping):
                    raise ValueError(
                        f"OpenAPI {context} requestBody needs an object schema"
                    )
                if body_schema.get("type", "object") != "object":
                    raise ValueError(
                        f"OpenAPI {context} requestBody schema must be an object"
                    )
                additional = body_schema.get("additionalProperties", False)
                if additional is not False:
                    raise ValueError(
                        f"OpenAPI {context} requestBody must not allow "
                        "undeclared arguments (additionalProperties must be false)"
                    )
                raw_props = body_schema.get("properties", {})
                if not isinstance(raw_props, Mapping):
                    raise ValueError(
                        f"OpenAPI {context} requestBody properties must be an object"
                    )
                body_props = dict(raw_props)
                raw_required = body_schema.get("required", [])
                if not isinstance(raw_required, list) or not all(
                    isinstance(item, str) for item in raw_required
                ):
                    raise ValueError(
                        f"OpenAPI {context} requestBody required must be string names"
                    )
                body_required = list(raw_required)
            param_props = {
                item["name"]: item["schema"] for item in params
            }
            if set(param_props).intersection(body_props):
                raise ValueError(
                    f"OpenAPI {context} has colliding parameter/body names: "
                    f"{sorted(set(param_props).intersection(body_props))}"
                )
            all_props = {**param_props, **body_props}
            all_required = [
                item["name"] for item in params if item["required"]
            ] + body_required
            schema = _object_schema(
                all_props, all_required, spec, context=context
            )
            summary = " ".join(
                str(
                    raw_operation.get("summary")
                    or raw_operation.get("description")
                    or f"{method.upper()} {raw_path}"
                ).split()
            )[:600]
            operations.append(
                OpenApiOperation(
                    operation_id=operation_id,
                    method=method,
                    path=raw_path,
                    summary=summary,
                    input_schema=schema,
                    path_params=tuple(
                        item["name"] for item in params if item["in"] == "path"
                    ),
                    query_params=tuple(
                        item["name"] for item in params if item["in"] == "query"
                    ),
                    header_params=tuple(
                        item["name"] for item in params if item["in"] == "header"
                    ),
                    body_params=tuple(body_props),
                )
            )
    if not operations:
        raise ValueError("OpenAPI spec declares no supported operations")
    return ParsedOpenApiSpec(
        title=title, servers=tuple(servers), operations=tuple(operations)
    )


# ---------------------------------------------------------------------------
# Attach
# ---------------------------------------------------------------------------


def _validate_base_url(base_url: str) -> str:
    normalized = str(base_url or "").strip()
    if not normalized:
        raise ValueError("OpenAPI REST tools need a base URL")
    if "{" in normalized or "}" in normalized:
        raise ValueError("OpenAPI server URL variables are not supported")
    parts = urlsplit(normalized)
    if parts.scheme not in {"http", "https"}:
        raise ValueError("OpenAPI REST base URL must be http or https")
    if parts.username or parts.password:
        raise ValueError(
            "OpenAPI REST base URL must not embed credentials; "
            "use credential_ref instead"
        )
    if parts.fragment or parts.query:
        raise ValueError("OpenAPI REST base URL must not carry a fragment or query")
    if not parts.netloc:
        raise ValueError("OpenAPI REST base URL must be absolute")
    return normalized.rstrip("/")


def _validate_args(operation: OpenApiOperation, args: Mapping[str, Any]) -> None:
    schema = dict(operation.input_schema or {})
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    provided = dict(args or {})
    unknown = sorted(set(provided) - set(properties))
    if unknown:
        raise ValueError(
            f"REST arguments name undeclared inputs: {unknown}"
        )
    missing = [name for name in required if name not in provided]
    if missing:
        raise ValueError(f"REST arguments are missing required inputs: {missing}")
    for name, value in provided.items():
        if isinstance(value, str) and len(value) > _MAX_ARGS_STRING:
            raise ValueError("REST arguments exceed bounded size")
        expected = (properties.get(name) or {}).get("type", "string")
        if expected == "string" and not isinstance(value, str):
            raise ValueError(f"REST argument {name!r} must be a string")
        if expected == "boolean" and not isinstance(value, bool):
            raise ValueError(f"REST argument {name!r} must be a boolean")
        if expected == "integer" and (
            isinstance(value, bool) or not isinstance(value, int)
        ):
            raise ValueError(f"REST argument {name!r} must be an integer")
        if expected == "number" and (
            isinstance(value, bool) or not isinstance(value, (int, float))
        ):
            raise ValueError(f"REST argument {name!r} must be a number")


def _response_output(response: RestHttpResponse) -> tuple[str, bool]:
    parsed = response.json_value
    if parsed is not None:
        text = json.dumps(parsed, ensure_ascii=False, default=str)
    else:
        text = response.text
    return text[:_MAX_OUTPUT_CHARS], len(text) > _MAX_OUTPUT_CHARS


@dataclass(slots=True)
class OpenApiRestAttachment:
    """Disconnect one OpenAPI provider without changing ZN Work/Memory."""

    fabric: ActionFabricRegistry
    body: NativeBody
    descriptors: tuple[ActionDescriptor, ...]
    probes: Mapping[str, McpWritePostconditionProbe]
    disabled_write_operations: tuple[str, ...] = ()
    _closed: bool = False

    def detach(self) -> None:
        if self._closed:
            return
        self._closed = True
        for descriptor in self.descriptors:
            self.fabric.unregister(descriptor.action_id)
            assert descriptor.body_action_kind is not None
            if descriptor.effect_class == "read_only":
                self.body.unregister_external_read_handler(
                    descriptor.body_action_kind
                )
            else:
                self.body.unregister_external_write_handler(
                    descriptor.body_action_kind
                )

    def register_verifications(self, runtime: Any) -> None:
        """Wire each approved write tool's probe into an ActionExecutionRuntime.

        Same fail-closed rule as the M-7 contract: without this wiring the
        runtime reports "no independent postcondition verifier" instead of
        treating Body success as proof.
        """
        for descriptor in self.descriptors:
            if descriptor.effect_class == "read_only":
                continue
            probe = self.probes[descriptor.action_id]
            runtime.register_verification(
                descriptor.action_id,
                observe=_rest_write_observer(probe),
                verify=_rest_write_verifier,
            )


def _rest_write_observer(
    probe: McpWritePostconditionProbe,
) -> Callable[[Any, BodyActionResult | None], Any]:
    from .action_execution import ActionObservation

    def observe(request: Any, result: BodyActionResult | None) -> ActionObservation:
        if result is None:
            raise RuntimeError("REST write postcondition needs a Body result")
        outcome = probe(dict(request.args or {}), result)
        if not isinstance(outcome, McpWritePostcondition):
            raise ValueError(
                "REST write postcondition probe returned a malformed outcome"
            )
        return ActionObservation(
            request.action_id,
            "rest_write_postcondition",
            data={
                "verified": bool(outcome.verified),
                "reason": outcome.reason,
                "evidence": dict(outcome.evidence or {}),
            },
            observed_at=result.completed_at or utc_now(),
        )

    return observe


def _rest_write_verifier(request: Any, observation: Any, result: BodyActionResult | None) -> Any:
    from .action_execution import ActionVerification

    data = dict(observation.data or {})
    if data.get("verified") is True:
        return ActionVerification(
            "verified",
            str(data.get("reason") or "REST write postcondition verified"),
            evidence={
                "body_action_id": result.action_id if result is not None else None,
                "postcondition": data.get("evidence") or {},
            },
            observed_at=observation.observed_at,
        )
    return ActionVerification(
        "failed",
        str(data.get("reason") or "REST write postcondition not met"),
        evidence={
            "body_action_id": result.action_id if result is not None else None,
            "postcondition": data.get("evidence") or {},
        },
        observed_at=observation.observed_at,
    )


def attach_openapi_rest_tools(
    *,
    fabric: ActionFabricRegistry,
    body: NativeBody,
    spec: Mapping[str, Any] | str | bytes,
    provider_id: str,
    base_url: str | None = None,
    http_client: RestHttpClient | None = None,
    timeout_seconds: float = 10.0,
    credential_ref: str | None = None,
    credential_resolver: Callable[[str], Mapping[str, str]] | None = None,
    approved_write_tools: Sequence[ApprovedRestWriteTool] = (),
    postcondition_probes: Mapping[str, McpWritePostconditionProbe] | None = None,
) -> OpenApiRestAttachment:
    """Attach one approved OpenAPI provider to the SAME ZN Body and Fabric.

    ``spec`` is trusted host configuration, never model-supplied: the host
    has reviewed the document, the base URL, and (for writes) each
    per-tool approval. Unapproved write operations are listed on the
    attachment as ``disabled_write_operations`` and stay uncallable.
    """
    provider_id = str(provider_id or "").strip().lower()
    if not _PROVIDER_RE.fullmatch(provider_id):
        raise ValueError("provider_id must be a stable lowercase namespace")
    parsed = parse_openapi_spec(spec)
    if not 1.0 <= float(timeout_seconds) <= 60.0:
        raise ValueError("OpenAPI REST timeout must be between 1 and 60 seconds")
    timeout = float(timeout_seconds)
    if base_url is not None:
        resolved_base = _validate_base_url(base_url)
    elif parsed.servers:
        resolved_base = _validate_base_url(parsed.servers[0])
    else:
        raise ValueError(
            "OpenAPI spec declares no servers and no explicit base_url was given"
        )
    if credential_ref is not None:
        if not is_credential_reference(credential_ref):
            raise ValueError(
                "credential_ref must be an opaque credential reference, "
                "never a credential value"
            )
        if not callable(credential_resolver):
            raise ValueError(
                "credential_ref needs a credential_resolver that returns "
                "request headers at call time"
            )
    elif credential_resolver is not None:
        raise ValueError(
            "credential_resolver without a credential_ref is refused"
        )
    client: RestHttpClient = http_client or UrllibRestHttpClient()

    approved = tuple(approved_write_tools or ())
    if len(approved) > 32:
        raise ValueError("approved REST write tools must be a bounded allowlist")
    approved_names = [item.tool_name for item in approved]
    if len(set(approved_names)) != len(approved_names):
        raise ValueError("approved REST write tools must be unique")
    probes = dict(postcondition_probes or {})
    if set(probes) != set(approved_names):
        raise ValueError(
            "REST write tools need exactly one postcondition probe each: "
            "missing or unapproved probes are refused"
        )
    for probe in probes.values():
        if not callable(probe):
            raise TypeError("REST write postcondition probe must be callable")

    by_id = {op.operation_id: op for op in parsed.operations}
    write_ops = {op.operation_id for op in parsed.operations if not op.is_read}
    unknown_approved = sorted(set(approved_names) - write_ops)
    if unknown_approved:
        raise ValueError(
            "approved REST write tools must name write operations from "
            f"this spec: {unknown_approved}"
        )
    disabled = tuple(
        sorted(
            op.operation_id
            for op in parsed.operations
            if not op.is_read and op.operation_id not in set(approved_names)
        )
    )
    approvals = {item.tool_name: item for item in approved}

    # In-process record of write occurrences that already reached the
    # provider (M-7 replay rule): any HTTP response counts, transport
    # failure counts as unreached.
    completed_identities: set[str] = set()
    spec_fingerprint = hashlib.sha256(
        json.dumps(
            {"title": parsed.title, "servers": list(parsed.servers),
             "operations": [op.operation_id for op in parsed.operations]},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()

    prepared: list[
        tuple[ActionDescriptor, OpenApiOperation, ApprovedRestWriteTool | None]
    ] = []
    for operation in parsed.operations:
        action_id = f"rest.{provider_id}.{operation.operation_id}"
        digest = hashlib.sha256(action_id.encode("utf-8")).hexdigest()[:24]
        if operation.is_read:
            kind = f"zn_rest_read_{digest}"
            descriptor = ActionDescriptor(
                action_id=action_id,
                provider=f"zn.rest.{provider_id}",
                description=f"Approved external REST read: {operation.summary}",
                body_action_kind=kind,
                input_schema=dict(operation.input_schema),
                effect_class="read_only",
                required_authority=("explicit_openapi_rest_approval",),
                sensitivity="external",
                preconditions=("approved OpenAPI spec and base URL",),
                verification=(
                    "fresh read-only Body observation; not goal completion",
                ),
                replay_semantics="read_only",
                tags=("rest", "openapi", "external", "read_only", provider_id),
            )
            prepared.append((descriptor, operation, None))
        else:
            approval = approvals.get(operation.operation_id)
            if approval is None:
                continue  # Default disabled: never registered, never callable.
            kind = f"zn_rest_write_{digest}"
            descriptor = ActionDescriptor(
                action_id=action_id,
                provider=f"zn.rest.{provider_id}",
                description=f"Approved external REST write: {operation.summary}",
                body_action_kind=kind,
                input_schema=dict(operation.input_schema),
                effect_class=approval.effect_class,
                required_authority=(
                    "explicit_openapi_rest_approval",
                    "explicit_rest_write_tool_approval",
                ),
                sensitivity="external",
                preconditions=(
                    "approved OpenAPI spec and base URL",
                    "per-tool explicit write approval",
                    "stable event_id for the write occurrence",
                ),
                postconditions=tuple(approval.verification),
                verification=(
                    "independent postcondition probe must verify the effect; "
                    "Body success is dispatch evidence only",
                    *approval.verification,
                ),
                reversibility=_REST_WRITE_REVERSIBILITY[approval.effect_class],
                replay_semantics="verify_before_replay",
                tags=(
                    "rest",
                    "openapi",
                    "external",
                    "rest_write",
                    provider_id,
                    f"approval:{approval.approval_kind}",
                ),
            )
            prepared.append((descriptor, operation, approval))

    for descriptor, _, _ in prepared:
        if fabric.descriptor(descriptor.action_id) is not None:
            raise ValueError(
                f"Action Fabric already owns action {descriptor.action_id}"
            )
        assert descriptor.body_action_kind is not None
        handlers = (
            body._external_read_handlers
            if descriptor.effect_class == "read_only"
            else body._external_write_handlers
        )
        if descriptor.body_action_kind in handlers:
            raise ValueError("Body extension identifier collision")

    registered: list[ActionDescriptor] = []
    attached_kinds: list[tuple[str, bool]] = []
    try:
        for descriptor, operation, approval in prepared:
            assert descriptor.body_action_kind is not None
            is_read = operation.is_read

            def call_rest(
                action: BodyAction,
                started: str,
                *,
                op=operation,
                read=is_read,
            ) -> BodyActionResult:
                _validate_args(op, action.args)
                path = op.path
                for name in op.path_params:
                    path = path.replace(
                        "{" + name + "}",
                        quote(_scalar_text(action.args.get(name)), safe=""),
                    )
                query = {
                    name: action.args[name]
                    for name in op.query_params
                    if name in action.args
                }
                headers: dict[str, str] = {
                    name: _scalar_text(action.args[name])
                    for name in op.header_params
                    if name in action.args
                }
                if credential_ref is not None:
                    assert credential_resolver is not None
                    extra = credential_resolver(credential_ref)
                    if not isinstance(extra, Mapping):
                        raise RuntimeError(
                            "credential resolver returned a malformed value"
                        )
                    for header_name, header_value in dict(extra).items():
                        if not isinstance(header_name, str) or not isinstance(
                            header_value, str
                        ):
                            raise RuntimeError(
                                "credential resolver returned a malformed value"
                            )
                        if "\r" in header_value or "\n" in header_value:
                            raise RuntimeError(
                                "credential resolver returned a malformed value"
                            )
                    headers.update(
                        {str(k): str(v) for k, v in dict(extra).items()}
                    )
                json_body: dict[str, Any] | None = None
                if op.body_params:
                    json_body = {
                        name: action.args[name]
                        for name in op.body_params
                        if name in action.args
                    }
                url = urljoin(resolved_base + "/", path.lstrip("/"))
                try:
                    response = client.request(
                        op.method,
                        url,
                        params=query,
                        headers=headers,
                        json_body=json_body,
                        timeout_seconds=timeout,
                    )
                except Exception as exc:
                    # No response: the provider may not have been reached.
                    raise RuntimeError(
                        f"approved REST call failed: {type(exc).__name__}"
                    ) from exc
                if not isinstance(response, RestHttpResponse):
                    raise RuntimeError("REST client returned a malformed response")
                if not read:
                    # Any HTTP response means the provider processed the
                    # dispatch, so the identity is recorded even on an
                    # error status: the effect may already have been applied.
                    identity = mcp_write_replay_identity(
                        provider_id=provider_id,
                        tool_name=op.operation_id,
                        args=action.args,
                        event_id=action.event_id,
                    )
                    completed_identities.add(identity)
                    if not 200 <= response.status_code < 300:
                        raise RuntimeError(
                            "REST write returned a failed HTTP status; "
                            "effect state is uncertain, re-observe with the "
                            "postcondition probe instead of redispatching"
                        )
                else:
                    identity = None
                    if not 200 <= response.status_code < 300:
                        raise RuntimeError(
                            f"REST read failed with HTTP {response.status_code}"
                        )
                text, truncated = _response_output(response)
                data: dict[str, Any] = {
                    "provider_id": provider_id,
                    "tool": op.operation_id,
                    "method": op.method,
                    "status_code": response.status_code,
                    "text": text,
                    "untrusted_external_evidence": True,
                    "truncated": truncated,
                }
                if not read:
                    assert identity is not None
                    data["replay_identity"] = identity
                    data["replayed"] = False
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=True,
                    output=text,
                    data=data,
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )

            def call_write_guarded(
                action: BodyAction,
                started: str,
                *,
                op=operation,
                inner=call_rest,
            ) -> BodyActionResult:
                identity = mcp_write_replay_identity(
                    provider_id=provider_id,
                    tool_name=op.operation_id,
                    args=action.args,
                    event_id=action.event_id,
                )
                if identity in completed_identities:
                    raise RuntimeError(
                        "REST write replay refused: this exact write occurrence "
                        "already reached the provider; re-observe with the "
                        "postcondition probe instead of redispatching"
                    )
                return inner(action, started)

            if is_read:
                body.register_external_read_handler(
                    descriptor.body_action_kind, call_rest
                )
                attached_kinds.append((descriptor.body_action_kind, True))
            else:
                body.register_external_write_handler(
                    descriptor.body_action_kind, call_write_guarded
                )
                attached_kinds.append((descriptor.body_action_kind, False))
            fabric.register(
                descriptor,
                availability_probe=lambda item, fingerprint=spec_fingerprint: ActionAvailability(
                    item.action_id,
                    "available",
                    reason="approved OpenAPI REST endpoint configured",
                    evidence={
                        "provider_id": provider_id,
                        "spec_fingerprint": fingerprint,
                    },
                ),
            )
            registered.append(descriptor)
    except Exception:
        for descriptor in registered:
            fabric.unregister(descriptor.action_id)
        for kind, was_read in attached_kinds:
            if was_read:
                body.unregister_external_read_handler(kind)
            else:
                body.unregister_external_write_handler(kind)
        raise
    return OpenApiRestAttachment(
        fabric,
        body,
        tuple(registered),
        {
            descriptor.action_id: probes[operation.operation_id]
            for descriptor, operation, _ in prepared
            if not operation.is_read
        },
        disabled_write_operations=disabled,
    )
