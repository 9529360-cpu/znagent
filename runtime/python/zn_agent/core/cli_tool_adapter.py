from __future__ import annotations

"""Declarative CLI tool generic wrapper (M-9).

One host-approved declaration becomes a ZN tool on the SAME Action
Fabric/Body as every other capability::

    CliToolDeclaration(
        name="git_version",
        command="git",
        argv_template=("--version",),
        ...
    )

Read-only tools (``effect_class="read_only"``) register directly.
Tools with a side effect register ONLY when the host supplies a per-tool
approval through the M-7 write contract (``ApprovedCliWriteTool``
subclasses ``ApprovedMcpWriteTool``: per-tool explicit approval + replay
identity + host-supplied postcondition probe). An unapproved write tool
is never registered, never gets a Body handler, and stays uncallable.

Deliberate limits, mirroring the M-7/M-8 shallow-schema honesty:

- The declaration is trusted host configuration, never model-supplied.
  The model only supplies argument *values*, which are validated
  against the declared parameter schema before anything runs.
- No shell, ever: the process is spawned with an argv list
  (``subprocess.run(..., shell=False)``), stdin is always DEVNULL, and
  argument values are passed as single argv elements. A value that
  looks like an option (starts with ``-``) is refused unless the
  declaration explicitly opts in with ``allow_option_like_values``,
  because a model-supplied ``--help``/``--exec=...`` must not be able to
  turn a declared tool into a different command.
- Only shallow scalar parameters (string/number/integer/boolean), at
  most 32 parameters and 32 argv segments. A segment that is exactly
  ``{param}`` substitutes one declared parameter; every other segment
  is a literal (so ``-c`` code may contain braces). A placeholder that
  names an undeclared parameter fails at declaration time, so a
  misspelled ``{mesage}`` cannot silently become a literal.
- Credentials never ride in a declaration: ``env`` is literal
  host configuration and refuses secret-looking names; there is no
  credential mechanism here at all.
- stdout is parsed by the declared output spec (text/json/lines/regex)
  and bounded; stderr is kept only as a bounded tail for failure
  diagnosis. A timeout or an unexpected exit code is an explicit
  failure, never a silent empty result.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionEffectClass,
    ActionFabricRegistry,
)
from .body import BodyAction, BodyActionResult, NativeBody
from .mcp_capability_adapter import (
    ApprovedMcpWriteTool,
    McpWritePostcondition,
    McpWritePostconditionProbe,
    mcp_write_replay_identity,
)
from .models import utc_now

__all__ = [
    "ApprovedCliWriteTool",
    "CliOutputSpec",
    "CliRunResult",
    "CliRunner",
    "CliToolAttachment",
    "CliToolDeclaration",
    "SubprocessCliRunner",
    "attach_cli_tools",
    "example_git_version_tool",
]

_PROVIDER_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
_NAME_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{0,63}")
_TOOL_NAME_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_.-]{0,79}")
_PARAM_NAME_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{0,63}")
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z][a-zA-Z0-9_]{0,63})\}")
_BARE_COMMAND_RE = re.compile(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}")
_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_SECRET_ENV_RE = re.compile(r"token|secret|password|private_key|credential", re.I)
_SCALAR_TYPES = frozenset({"string", "number", "integer", "boolean"})
_OUTPUT_MODES = frozenset({"text", "json", "lines", "regex"})
_MAX_ARGS_STRING = 16_384
_MAX_OUTPUT_CHARS = 12_000
_MAX_OUTPUT_BYTES = 1_000_000
_MAX_STDERR_CHARS = 2_000

_CLI_WRITE_REVERSIBILITY: dict[str, str] = {
    "reversible_side_effect": "reversible",
    "potential_side_effect": "unknown",
    "irreversible_side_effect": "irreversible",
}


class ApprovedCliWriteTool(ApprovedMcpWriteTool):
    """CLI spelling of the M-7 write approval contract.

    Inherits every validation from ``ApprovedMcpWriteTool`` (stable tool
    name, explicit non-read-only effect class, validated approval kind,
    at least one named postcondition) so the approval contract exists in
    exactly one place. ``tool_name`` is the declaration name.
    """


@dataclass(frozen=True, slots=True)
class CliOutputSpec:
    """How to parse one CLI tool's stdout into structured evidence."""

    mode: str = "text"
    pattern: str = ""

    def __post_init__(self) -> None:
        mode = str(self.mode or "").strip()
        if mode not in _OUTPUT_MODES:
            raise ValueError(
                f"CLI output mode {mode!r} is unsupported; "
                f"expected one of {sorted(_OUTPUT_MODES)}"
            )
        object.__setattr__(self, "mode", mode)
        pattern = str(self.pattern or "")
        if mode == "regex":
            if not pattern:
                raise ValueError("CLI regex output needs a pattern")
            if len(pattern) > 1_024:
                raise ValueError("CLI regex output pattern exceeds bounded size")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"CLI regex output pattern is invalid: {exc}") from exc
        elif pattern:
            raise ValueError("CLI output pattern is only meaningful for regex mode")
        object.__setattr__(self, "pattern", pattern)


def _validate_param_schema(name: str, schema: Any) -> dict[str, Any]:
    if not isinstance(schema, Mapping):
        raise ValueError(f"CLI parameter {name!r} needs a schema object")
    raw_type = schema.get("type", "string")
    if raw_type not in _SCALAR_TYPES:
        raise ValueError(
            f"CLI parameter {name!r} has unsupported type {raw_type!r}; "
            "only string/number/integer/boolean are supported"
        )
    safe: dict[str, Any] = {"type": raw_type}
    required = schema.get("required", False)
    if not isinstance(required, bool):
        raise ValueError(f"CLI parameter {name!r} required must be a boolean")
    safe["required"] = required
    if "description" in schema:
        description = schema["description"]
        if not isinstance(description, str):
            raise ValueError(f"CLI parameter {name!r} description must be a string")
        safe["description"] = description[:500]
    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or not enum:
            raise ValueError(f"CLI parameter {name!r} enum must be a non-empty list")
        for value in enum:
            _check_scalar_value(name, raw_type, value, context="enum")
        if len(set(json.dumps(v, sort_keys=True, default=str) for v in enum)) != len(enum):
            raise ValueError(f"CLI parameter {name!r} enum must be unique")
        safe["enum"] = list(enum)
    if "default" in schema:
        default = schema["default"]
        _check_scalar_value(name, raw_type, default, context="default")
        if "enum" in safe and default not in safe["enum"]:
            raise ValueError(
                f"CLI parameter {name!r} default must be one of its enum values"
            )
        safe["default"] = default
    if required and "default" in safe:
        raise ValueError(
            f"CLI parameter {name!r} cannot be both required and defaulted"
        )
    unknown = sorted(set(schema) - {"type", "required", "description", "enum", "default"})
    if unknown:
        raise ValueError(
            f"CLI parameter {name!r} uses unsupported schema keys: {unknown}"
        )
    return safe


def _check_scalar_value(
    name: str, expected: str, value: Any, *, context: str
) -> None:
    if expected == "string" and not isinstance(value, str):
        raise ValueError(f"CLI parameter {name!r} {context} must be a string")
    if expected == "boolean" and not isinstance(value, bool):
        raise ValueError(f"CLI parameter {name!r} {context} must be a boolean")
    if expected == "integer" and (
        isinstance(value, bool) or not isinstance(value, int)
    ):
        raise ValueError(f"CLI parameter {name!r} {context} must be an integer")
    if expected == "number" and (
        isinstance(value, bool) or not isinstance(value, (int, float))
    ):
        raise ValueError(f"CLI parameter {name!r} {context} must be a number")


@dataclass(frozen=True, slots=True)
class CliToolDeclaration:
    """One host-approved CLI tool, declared rather than hand-adapted."""

    name: str
    description: str
    command: str
    argv_template: tuple[str, ...] = ()
    params: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    effect_class: ActionEffectClass = "read_only"
    timeout_seconds: float = 10.0
    output: CliOutputSpec = field(default_factory=CliOutputSpec)
    expected_exit_codes: tuple[int, ...] = (0,)
    working_dir: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    allow_option_like_values: bool = False

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not _TOOL_NAME_RE.fullmatch(name):
            raise ValueError("CLI tool name is not a stable identifier")
        object.__setattr__(self, "name", name)
        description = " ".join(str(self.description or "").split())
        if not description:
            raise ValueError("CLI tool needs a description")
        object.__setattr__(self, "description", description)
        command = str(self.command or "")
        if not command or "\x00" in command or "\n" in command or "\r" in command:
            raise ValueError("CLI tool command must be a single clean token or path")
        if any(ch in command for ch in " \t;|&$`><!()"):
            raise ValueError(
                "CLI tool command must not contain whitespace or shell metacharacters"
            )
        if "/" in command or "\\" in command:
            if not os.path.isabs(command):
                raise ValueError(
                    "CLI tool command with a path separator must be an absolute path"
                )
        elif not _BARE_COMMAND_RE.fullmatch(command):
            raise ValueError("CLI tool command is not a stable bare executable name")
        object.__setattr__(self, "command", command)

        raw_params = dict(self.params or {})
        if len(raw_params) > 32:
            raise ValueError("CLI tool declares too many parameters (max 32)")
        validated_params: dict[str, dict[str, Any]] = {}
        for param_name, schema in raw_params.items():
            if not isinstance(param_name, str) or not _PARAM_NAME_RE.fullmatch(param_name):
                raise ValueError(
                    f"CLI parameter name {param_name!r} is unsupported; "
                    "names must match [a-zA-Z][a-zA-Z0-9_]{0,63}"
                )
            validated_params[param_name] = _validate_param_schema(param_name, schema)
        object.__setattr__(self, "params", validated_params)

        template = tuple(self.argv_template or ())
        if len(template) > 32:
            raise ValueError("CLI tool argv template has too many segments (max 32)")
        for segment in template:
            if not isinstance(segment, str) or not segment or len(segment) > 1_024:
                raise ValueError("CLI argv segment must be a non-empty bounded string")
            if "\x00" in segment or "\n" in segment or "\r" in segment:
                raise ValueError("CLI argv segment must not contain NUL or newlines")
            match = _PLACEHOLDER_RE.fullmatch(segment)
            if match is not None and match.group(1) not in validated_params:
                raise ValueError(
                    f"CLI argv segment {segment!r} names undeclared "
                    f"parameter {match.group(1)!r}"
                )
        object.__setattr__(self, "argv_template", template)

        if self.effect_class not in {
            "read_only",
            "reversible_side_effect",
            "potential_side_effect",
            "irreversible_side_effect",
        }:
            raise ValueError(f"CLI tool has invalid effect class {self.effect_class!r}")
        if not 1.0 <= float(self.timeout_seconds) <= 60.0:
            raise ValueError("CLI tool timeout must be between 1 and 60 seconds")
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))
        if not isinstance(self.output, CliOutputSpec):
            raise ValueError("CLI tool output must be a CliOutputSpec")
        codes = tuple(self.expected_exit_codes or ())
        if not 1 <= len(codes) <= 8 or len(set(codes)) != len(codes):
            raise ValueError("CLI tool expected exit codes must be 1-8 unique codes")
        for code in codes:
            if isinstance(code, bool) or not isinstance(code, int) or not 0 <= code <= 255:
                raise ValueError("CLI tool expected exit codes must be integers 0-255")
        object.__setattr__(self, "expected_exit_codes", codes)
        if self.working_dir is not None:
            working_dir = str(self.working_dir)
            if not os.path.isabs(working_dir) or "\x00" in working_dir:
                raise ValueError("CLI tool working_dir must be an absolute path")
            object.__setattr__(self, "working_dir", working_dir)
        env = dict(self.env or {})
        if len(env) > 16:
            raise ValueError("CLI tool env has too many entries (max 16)")
        for key, value in env.items():
            if not isinstance(key, str) or not _ENV_NAME_RE.fullmatch(key):
                raise ValueError(f"CLI tool env name {key!r} is unsupported")
            if _SECRET_ENV_RE.search(key):
                raise ValueError(
                    f"CLI tool env {key!r} looks like a credential; "
                    "credentials must never ride in a CLI declaration"
                )
            if not isinstance(value, str) or len(value) > 4_096 or "\x00" in value:
                raise ValueError(f"CLI tool env value for {key!r} is unsupported")
        object.__setattr__(self, "env", env)
        tags = tuple(
            dict.fromkeys(
                str(item or "").strip() for item in (self.tags or ()) if str(item or "").strip()
            )
        )
        object.__setattr__(self, "tags", tags)
        object.__setattr__(self, "allow_option_like_values", bool(self.allow_option_like_values))

    @property
    def input_schema(self) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for name, schema in dict(self.params or {}).items():
            entry: dict[str, Any] = {"type": schema["type"]}
            for key in ("description", "enum", "default"):
                if key in schema:
                    entry[key] = schema[key]
            properties[name] = entry
            if schema.get("required"):
                required.append(name)
        schema = {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }
        return schema

    @property
    def is_read(self) -> bool:
        return self.effect_class == "read_only"


@dataclass(frozen=True, slots=True)
class CliRunResult:
    """One finished child process: exit code plus raw byte streams."""

    exit_code: int
    stdout: bytes = b""
    stderr: bytes = b""


class CliRunner(Protocol):
    """Process spawner, injectable for tests and sandboxed hosts."""

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        working_dir: str | None,
        env: Mapping[str, str],
    ) -> CliRunResult: ...


class SubprocessCliRunner:
    """Real runner: ``subprocess.run`` with no shell and no stdin."""

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        working_dir: str | None,
        env: Mapping[str, str],
    ) -> CliRunResult:
        merged_env = dict(os.environ)
        merged_env.update(dict(env or {}))
        completed = subprocess.run(
            [str(item) for item in argv],
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=float(timeout_seconds),
            cwd=working_dir,
            env=merged_env,
        )
        return CliRunResult(
            exit_code=int(completed.returncode),
            stdout=bytes(completed.stdout or b""),
            stderr=bytes(completed.stderr or b""),
        )


def _scalar_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _validate_args(declaration: CliToolDeclaration, args: Mapping[str, Any]) -> dict[str, Any]:
    provided = dict(args or {})
    unknown = sorted(set(provided) - set(declaration.params))
    if unknown:
        raise ValueError(f"CLI arguments name undeclared inputs: {unknown}")
    resolved: dict[str, Any] = {}
    for name, schema in dict(declaration.params).items():
        if name in provided:
            resolved[name] = provided[name]
        elif "default" in schema:
            resolved[name] = schema["default"]
        elif schema.get("required"):
            raise ValueError(f"CLI arguments are missing required input: {name}")
    for name, value in resolved.items():
        schema = dict(declaration.params)[name]
        if isinstance(value, str) and len(value) > _MAX_ARGS_STRING:
            raise ValueError("CLI arguments exceed bounded size")
        if isinstance(value, str) and "\x00" in value:
            raise ValueError(f"CLI argument {name!r} must not contain NUL")
        _check_scalar_value(name, schema["type"], value, context="argument")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(
                f"CLI argument {name!r} must be one of {schema['enum']}"
            )
    return resolved


def _build_argv(declaration: CliToolDeclaration, args: Mapping[str, Any]) -> list[str]:
    argv = [declaration.command]
    for segment in declaration.argv_template:
        match = _PLACEHOLDER_RE.fullmatch(segment)
        if match is None:
            argv.append(segment)
            continue
        value = _scalar_text(args[match.group(1)])
        if (
            not declaration.allow_option_like_values
            and value.startswith("-")
            and value != "-"
        ):
            raise ValueError(
                f"CLI argument {match.group(1)!r} looks like an option "
                f"({value!r}); option-like values are refused unless the "
                "declaration explicitly allows them"
            )
        argv.append(value)
    return argv


def _parse_stdout(
    declaration: CliToolDeclaration, raw: bytes
) -> tuple[str, Any]:
    text = raw[: _MAX_OUTPUT_BYTES + 1].decode("utf-8", errors="replace")
    truncated = len(raw) > _MAX_OUTPUT_BYTES
    text = text[:_MAX_OUTPUT_CHARS]
    truncated = truncated or len(raw.decode("utf-8", errors="replace")) > _MAX_OUTPUT_CHARS
    mode = declaration.output.mode
    if mode == "text":
        return text, None
    if mode == "lines":
        lines = text.splitlines()[:1_000]
        return text, lines
    if mode == "json":
        try:
            parsed = json.loads(text)
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError(
                "CLI tool stdout is not valid JSON for its declared output"
            ) from exc
        return text, parsed
    # regex: the declared shape must match, or the run is an explicit failure.
    match = re.search(declaration.output.pattern, text)
    if match is None:
        raise RuntimeError(
            "CLI tool stdout did not match its declared output pattern"
        )
    groups = match.groupdict()
    parsed: Any = groups if groups else list(match.groups())
    return text, parsed


@dataclass(slots=True)
class CliToolAttachment:
    """Disconnect one CLI provider without changing ZN Work/Memory."""

    fabric: ActionFabricRegistry
    body: NativeBody
    descriptors: tuple[ActionDescriptor, ...]
    probes: Mapping[str, McpWritePostconditionProbe]
    disabled_write_tools: tuple[str, ...] = ()
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
                observe=_cli_write_observer(probe),
                verify=_cli_write_verifier,
            )


def _cli_write_observer(
    probe: McpWritePostconditionProbe,
) -> Callable[[Any, BodyActionResult | None], Any]:
    from .action_execution import ActionObservation

    def observe(request: Any, result: BodyActionResult | None) -> ActionObservation:
        if result is None:
            raise RuntimeError("CLI write postcondition needs a Body result")
        outcome = probe(dict(request.args or {}), result)
        if not isinstance(outcome, McpWritePostcondition):
            raise ValueError(
                "CLI write postcondition probe returned a malformed outcome"
            )
        return ActionObservation(
            request.action_id,
            "cli_write_postcondition",
            data={
                "verified": bool(outcome.verified),
                "reason": outcome.reason,
                "evidence": dict(outcome.evidence or {}),
            },
            observed_at=result.completed_at or utc_now(),
        )

    return observe


def _cli_write_verifier(request: Any, observation: Any, result: BodyActionResult | None) -> Any:
    from .action_execution import ActionVerification

    data = dict(observation.data or {})
    if data.get("verified") is True:
        return ActionVerification(
            "verified",
            str(data.get("reason") or "CLI write postcondition verified"),
            evidence={
                "body_action_id": result.action_id if result is not None else None,
                "postcondition": data.get("evidence") or {},
            },
            observed_at=observation.observed_at,
        )
    return ActionVerification(
        "failed",
        str(data.get("reason") or "CLI write postcondition not met"),
        evidence={
            "body_action_id": result.action_id if result is not None else None,
            "postcondition": data.get("evidence") or {},
        },
        observed_at=observation.observed_at,
    )


def example_git_version_tool() -> CliToolDeclaration:
    """The shipped example: real, read-only ``git --version``.

    ``git`` is present wherever ZN itself is developed or deployed from a
    checkout, and ``--version`` has no side effects. The version string is
    parsed with a named ``version`` group so callers get structured
    evidence instead of raw text.
    """
    return CliToolDeclaration(
        name="git_version",
        description="Report the installed git version (read-only git --version)",
        command="git",
        argv_template=("--version",),
        output=CliOutputSpec(
            mode="regex", pattern=r"git version (?P<version>\S+)"
        ),
        tags=("cli", "git", "version", "read_only"),
    )


def attach_cli_tools(
    *,
    fabric: ActionFabricRegistry,
    body: NativeBody,
    tools: Sequence[CliToolDeclaration],
    provider_id: str,
    runner: CliRunner | None = None,
    approved_write_tools: Sequence[ApprovedCliWriteTool] = (),
    postcondition_probes: Mapping[str, McpWritePostconditionProbe] | None = None,
) -> CliToolAttachment:
    """Attach host-approved CLI declarations to the SAME ZN Body and Fabric.

    ``tools`` is trusted host configuration, never model-supplied: the
    host has reviewed each command, argv template, effect class, and (for
    writes) each per-tool approval. Unapproved write tools are listed on
    the attachment as ``disabled_write_tools`` and stay uncallable.
    """
    provider_id = str(provider_id or "").strip().lower()
    if not _PROVIDER_RE.fullmatch(provider_id):
        raise ValueError("provider_id must be a stable lowercase namespace")
    declared = tuple(tools or ())
    if not 1 <= len(declared) <= 32:
        raise ValueError("CLI tools must declare 1-32 tools per attach call")
    names = [item.name for item in declared]
    if len(set(names)) != len(names):
        raise ValueError("CLI tool names must be unique within one attach call")
    for item in declared:
        if not isinstance(item, CliToolDeclaration):
            raise TypeError("CLI tools must be CliToolDeclaration values")
        if item.working_dir is not None and not Path(item.working_dir).is_dir():
            raise ValueError(
                f"CLI tool {item.name!r} working_dir does not exist: "
                f"{item.working_dir!r}"
            )

    approved = tuple(approved_write_tools or ())
    if len(approved) > 32:
        raise ValueError("approved CLI write tools must be a bounded allowlist")
    approved_names = [item.tool_name for item in approved]
    if len(set(approved_names)) != len(approved_names):
        raise ValueError("approved CLI write tools must be unique")
    probes = dict(postcondition_probes or {})
    if set(probes) != set(approved_names):
        raise ValueError(
            "CLI write tools need exactly one postcondition probe each: "
            "missing or unapproved probes are refused"
        )
    for probe in probes.values():
        if not callable(probe):
            raise TypeError("CLI write postcondition probe must be callable")

    by_name = {item.name: item for item in declared}
    write_names = {item.name for item in declared if not item.is_read}
    unknown_approved = sorted(set(approved_names) - write_names)
    if unknown_approved:
        raise ValueError(
            "approved CLI write tools must name write tools from "
            f"this declaration set: {unknown_approved}"
        )
    disabled = tuple(
        sorted(
            item.name
            for item in declared
            if not item.is_read and item.name not in set(approved_names)
        )
    )
    approvals = {item.tool_name: item for item in approved}

    # In-process record of write occurrences that already spawned a child
    # process (M-7 replay rule): once the process has spawned, the effect
    # may already have been applied -- even on timeout or a non-zero exit.
    # A spawn failure (executable missing) counts as unreached.
    completed_identities: set[str] = set()
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "provider_id": provider_id,
                "tools": sorted(names),
                "commands": sorted(f"{item.name}:{item.command}" for item in declared),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    active_runner: CliRunner = runner or SubprocessCliRunner()

    prepared: list[
        tuple[ActionDescriptor, CliToolDeclaration, ApprovedCliWriteTool | None]
    ] = []
    for declaration in declared:
        action_id = f"cli.{provider_id}.{declaration.name}"
        digest = hashlib.sha256(action_id.encode("utf-8")).hexdigest()[:24]
        if declaration.is_read:
            kind = f"zn_cli_read_{digest}"
            descriptor = ActionDescriptor(
                action_id=action_id,
                provider=f"zn.cli.{provider_id}",
                description=f"Approved external CLI read: {declaration.description}",
                body_action_kind=kind,
                input_schema=declaration.input_schema,
                effect_class="read_only",
                required_authority=("explicit_cli_tool_approval",),
                sensitivity="external",
                preconditions=("approved CLI declaration",),
                verification=(
                    "fresh read-only Body observation; not goal completion",
                ),
                replay_semantics="read_only",
                tags=("cli", "external", "read_only", provider_id, *declaration.tags),
            )
            prepared.append((descriptor, declaration, None))
        else:
            approval = approvals.get(declaration.name)
            if approval is None:
                continue  # Default disabled: never registered, never callable.
            kind = f"zn_cli_write_{digest}"
            descriptor = ActionDescriptor(
                action_id=action_id,
                provider=f"zn.cli.{provider_id}",
                description=f"Approved external CLI write: {declaration.description}",
                body_action_kind=kind,
                input_schema=declaration.input_schema,
                effect_class=approval.effect_class,
                required_authority=(
                    "explicit_cli_tool_approval",
                    "explicit_cli_write_tool_approval",
                ),
                sensitivity="external",
                preconditions=(
                    "approved CLI declaration",
                    "per-tool explicit write approval",
                    "stable event_id for the write occurrence",
                ),
                postconditions=tuple(approval.verification),
                verification=(
                    "independent postcondition probe must verify the effect; "
                    "Body success is dispatch evidence only",
                    *approval.verification,
                ),
                reversibility=_CLI_WRITE_REVERSIBILITY[approval.effect_class],
                replay_semantics="verify_before_replay",
                tags=(
                    "cli",
                    "external",
                    "cli_write",
                    provider_id,
                    f"approval:{approval.approval_kind}",
                    *declaration.tags,
                ),
            )
            prepared.append((descriptor, declaration, approval))

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
        for descriptor, declaration, _approval in prepared:
            assert descriptor.body_action_kind is not None
            is_read = declaration.is_read

            def call_cli(
                action: BodyAction,
                started: str,
                *,
                decl=declaration,
                read=is_read,
            ) -> BodyActionResult:
                args = _validate_args(decl, action.args)
                argv = _build_argv(decl, args)
                try:
                    run = active_runner.run(
                        argv,
                        timeout_seconds=decl.timeout_seconds,
                        working_dir=decl.working_dir,
                        env=dict(decl.env),
                    )
                except (subprocess.TimeoutExpired, TimeoutError) as exc:
                    if not read:
                        completed_identities.add(
                            mcp_write_replay_identity(
                                provider_id=provider_id,
                                tool_name=decl.name,
                                args=action.args,
                                event_id=action.event_id,
                            )
                        )
                    raise RuntimeError(
                        f"CLI tool {decl.name!r} timed out after "
                        f"{decl.timeout_seconds:g} seconds; effect state is "
                        "uncertain, re-observe instead of redispatching"
                    ) from exc
                except FileNotFoundError as exc:
                    raise RuntimeError(
                        f"CLI tool {decl.name!r} executable not found: "
                        f"{decl.command!r}"
                    ) from exc
                except OSError as exc:
                    raise RuntimeError(
                        f"CLI tool {decl.name!r} failed to spawn: "
                        f"{type(exc).__name__}"
                    ) from exc
                if not isinstance(run, CliRunResult):
                    raise RuntimeError("CLI runner returned a malformed result")
                if not read:
                    # The process spawned: the effect may already be applied.
                    identity = mcp_write_replay_identity(
                        provider_id=provider_id,
                        tool_name=decl.name,
                        args=action.args,
                        event_id=action.event_id,
                    )
                    completed_identities.add(identity)
                stderr_tail = run.stderr.decode("utf-8", errors="replace")[
                    -_MAX_STDERR_CHARS:
                ]
                if run.exit_code not in decl.expected_exit_codes:
                    raise RuntimeError(
                        f"CLI tool {decl.name!r} exited with {run.exit_code}, "
                        f"expected one of {sorted(decl.expected_exit_codes)}; "
                        f"stderr: {stderr_tail}"
                    )
                text, parsed = _parse_stdout(decl, run.stdout)
                data: dict[str, Any] = {
                    "provider_id": provider_id,
                    "tool": decl.name,
                    "command": decl.command,
                    "exit_code": run.exit_code,
                    "text": text,
                    "untrusted_external_evidence": True,
                    "truncated": len(run.stdout) > _MAX_OUTPUT_BYTES,
                    "stderr_tail": stderr_tail,
                }
                if parsed is not None:
                    data["parsed"] = parsed
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
                decl=declaration,
                inner=call_cli,
            ) -> BodyActionResult:
                identity = mcp_write_replay_identity(
                    provider_id=provider_id,
                    tool_name=decl.name,
                    args=action.args,
                    event_id=action.event_id,
                )
                if identity in completed_identities:
                    raise RuntimeError(
                        "CLI write replay refused: this exact write occurrence "
                        "already spawned its process; re-observe with the "
                        "postcondition probe instead of redispatching"
                    )
                return inner(action, started)

            if is_read:
                body.register_external_read_handler(
                    descriptor.body_action_kind, call_cli
                )
                attached_kinds.append((descriptor.body_action_kind, True))
            else:
                body.register_external_write_handler(
                    descriptor.body_action_kind, call_write_guarded
                )
                attached_kinds.append((descriptor.body_action_kind, False))

            def availability_probe(
                item: ActionDescriptor,
                *,
                decl=declaration,
                digest=fingerprint,
            ) -> ActionAvailability:
                if "/" in decl.command or "\\" in decl.command:
                    path = Path(decl.command)
                    found = path.is_file()
                    reason = (
                        "declared CLI executable exists"
                        if found
                        else "declared CLI executable is missing"
                    )
                else:
                    found = shutil.which(decl.command) is not None
                    reason = (
                        "declared CLI executable resolves on PATH"
                        if found
                        else "declared CLI executable is not on PATH"
                    )
                return ActionAvailability(
                    item.action_id,
                    "available" if found else "unavailable",
                    reason=reason,
                    evidence={
                        "provider_id": provider_id,
                        "command": decl.command,
                        "spec_fingerprint": digest,
                    },
                )

            fabric.register(descriptor, availability_probe=availability_probe)
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
    return CliToolAttachment(
        fabric,
        body,
        tuple(registered),
        {
            descriptor.action_id: probes[declaration.name]
            for descriptor, declaration, _ in prepared
            if not declaration.is_read
        },
        disabled_write_tools=disabled,
    )
