from __future__ import annotations

"""Privacy-safe deterministic features for ZN Body action results.

The failure-pattern shapes are source-adapted from the inherited Hermes
``tools/terminal_hints.py`` quarry documented in ZN-SOURCE-EXTRACTION.md.
This module deliberately returns bounded categorical evidence only; it never
persists the command, output, matched token, path, or recovery-hint text.
"""

import re
from collections.abc import Mapping
from typing import Any

_SCAN_CHARS = 4000

_OBSERVATION_ONLY_KINDS = frozenset(
    {
        "sense",
        "inspect_path",
        "path",
        "read_text",
        "read_file",
        "list_directory",
        "list_dir",
        "process_state",
        "process",
        "git_state",
        "git",
        "terminal_poll",
        "command_poll",
    }
)

_PASSTHROUGH_CONSUMERS = r"(?:tail|head|cat|tee|less|more|wc|sort|uniq)"
_MASKING_PIPE_RE = re.compile(
    r"(?<!\|)\|(?!\|)\s*" + _PASSTHROUGH_CONSUMERS + r"\b[^|]*$"
)
_MASKING_OR_RE = re.compile(r"\|\|\s*(?:echo\b|printf\b|true\b|:\s*(?:$|[;&]))")
_READONLY_HEADS = frozenset(
    {
        "grep",
        "rg",
        "ag",
        "find",
        "ls",
        "cat",
        "head",
        "tail",
        "jq",
        "awk",
        "sed",
        "strings",
        "zcat",
        "journalctl",
        "dmesg",
        "echo",
        "printf",
    }
)
_FAILURE_SHAPES = re.compile(
    r"(?:"
    r"error\[E\d+\]"
    r"|error: could not compile"
    r"|error: aborting due to"
    r"|Traceback \(most recent call last\)"
    r"|(?m:^(?:=+ )?\d+ failed)"
    r"|(?m:^FAILED (?:\S+::|\S+\.py))"
    r"|compilation terminated\."
    r"|npm ERR!"
    r"|BUILD FAILED|Build FAILED"
    r"|FAILED: "
    r"|(?m:^make(?:\[\d+\])?: \*\*\*)"
    r"|command not found"
    r"|(?:ModuleNotFoundError|ImportError): No module named"
    r"|Permission denied|\bEACCES\b"
    r"|(?m:^CONFLICT )|Automatic merge failed|needs merge"
    r"|API rate limit|was submitted too quickly"
    r")"
)

_FAILURE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("unknown_json_field", re.compile(r'Unknown JSON field: "?\w+')),
    ("merge_conflict", re.compile(r"^CONFLICT |Automatic merge failed|needs merge", re.M)),
    ("command_not_found", re.compile(r"(?:bash: line \d+: |bash: |sh: \d*:? ?)?[\w.+-]+: command not found")),
    ("module_not_found", re.compile(r"(?:ModuleNotFoundError|ImportError): No module named '?[\w.]+")),
    ("already_exists", re.compile(r"(?:fatal|error):.*?'[^']+' already exists")),
    ("rate_limited", re.compile(r"API rate limit|was submitted too quickly")),
    ("permission_denied", re.compile(r"Permission denied|\bEACCES\b")),
)


def _first_token(command: str) -> str:
    for token in str(command or "").strip().split():
        if "=" in token and not token.startswith(("=", "./", "/")):
            continue
        return token.rsplit("/", 1)[-1]
    return ""


def detect_masked_success(command: str, output: str) -> str | None:
    """Return a safe category when shell composition can hide a real failure."""

    cmd = str(command or "")
    window = str(output or "")[:_SCAN_CHARS]
    if not cmd or not window:
        return None
    if _first_token(cmd) in _READONLY_HEADS:
        return None
    if not _FAILURE_SHAPES.search(window):
        return None
    if _MASKING_PIPE_RE.search(cmd):
        return "pipeline_passthrough"
    if _MASKING_OR_RE.search(cmd):
        return "fallback_swallow"
    return None


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _terminal_failure_class(
    *,
    output: str,
    exit_code: int | None,
    timed_out: bool,
    masked_success: str | None,
    body_success: bool,
) -> str | None:
    if masked_success:
        return "masked_success"
    if timed_out:
        return "timeout"

    window = str(output or "")[:_SCAN_CHARS]
    for name, pattern in _FAILURE_PATTERNS:
        if pattern.search(window):
            return name

    if exit_code == 124:
        return "timeout"
    if exit_code == 126:
        return "not_executable"
    if exit_code == 137:
        return "killed"
    if exit_code is not None and exit_code != 0:
        return "nonzero_exit"
    if not body_success:
        return "body_error"
    return None


def normalize_action_result(
    raw: Mapping[str, Any] | None,
    *,
    command: str | None = None,
) -> dict[str, Any]:
    """Reduce a raw BodyActionResult dictionary to privacy-safe learning features."""

    item = dict(raw or {})
    data_raw = item.get("data")
    data = dict(data_raw) if isinstance(data_raw, Mapping) else {}
    kind = str(item.get("kind") or "unknown").strip().lower() or "unknown"
    body_success = bool(item.get("success"))
    output = str(item.get("output") or "")
    exit_code = _int_or_none(data.get("exit_code"))
    timed_out = bool(data.get("timed_out", False))
    truncated = bool(data.get("truncated", False))

    masked_kind = None
    if exit_code == 0 and not timed_out and command:
        masked_kind = detect_masked_success(command, output)

    failure_class = _terminal_failure_class(
        output=output,
        exit_code=exit_code,
        timed_out=timed_out,
        masked_success=masked_kind,
        body_success=body_success,
    )

    status = str(data.get("status") or "").strip().lower()
    if status not in {"running", "completed", "failed", "stopped", "timeout"}:
        status = None

    return {
        "kind": kind,
        "effect_class": (
            "observation_only" if kind in _OBSERVATION_ONLY_KINDS else "potential_side_effect"
        ),
        "body_success": body_success,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "truncated": truncated,
        "status": status,
        "output_chars": len(output),
        "error_present": bool(str(item.get("error") or "").strip()),
        "failure_class": failure_class,
        "masked_success": bool(masked_kind),
        "masked_success_kind": masked_kind,
    }
