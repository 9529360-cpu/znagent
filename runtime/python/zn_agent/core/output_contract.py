from __future__ import annotations

"""Declared output contracts for bounded cognition calls, ZN-owned.

Call sites that need exactly-one-JSON from a cognitive resource declare an
OutputContract: the expected shape lives in one place, is validated at
construction (fail fast on a bad contract instead of after a wasted model
call), renders the format instruction (no drift between prompt wording and
parser), and validates the parsed payload (required keys, value dtypes).

Adapted from sglang's client-side ideas: declare constraints at the call
site, validate the constraint itself before sending, and keep a dtype-aware
fallback when the strict parse fails. ZN does not serve models, so there is
no constrained-decoding engine here — just contract discipline on the
consuming side.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .structured_proposal import parse_exact_json_payload

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Minimal dtype table: contract-declared value types checked after parsing.
# Mirrors the spirit of sglang's dtype->regex mapping — a cheap typed
# fallback when the provider cannot do native schema enforcement.
_DTYPE_CHECKS = ("str", "int", "float", "bool", "list", "dict")


def _check_dtype(value: Any, dtype: str) -> bool:
    if dtype == "str":
        return isinstance(value, str)
    if dtype == "bool":
        return isinstance(value, bool)
    if dtype == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if dtype == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if dtype == "list":
        return isinstance(value, list)
    if dtype == "dict":
        return isinstance(value, dict)
    return False


@dataclass(frozen=True, slots=True)
class OutputContract:
    """One declared shape for exactly-one-JSON cognition output."""

    top_level_key: str
    shape_example: str
    required_keys: tuple[str, ...] = ()
    # field name -> dtype, checked inside the top-level object.
    field_types: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _KEY_RE.match(self.top_level_key):
            raise ValueError(f"invalid top_level_key: {self.top_level_key!r}")
        try:
            shape = json.loads(self.shape_example)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"shape_example is not valid JSON: {exc}") from exc
        if not isinstance(shape, dict) or self.top_level_key not in shape:
            raise ValueError(
                "shape_example must be a JSON object containing top_level_key"
            )
        for key in self.required_keys:
            if not _KEY_RE.match(key):
                raise ValueError(f"invalid required key: {key!r}")
        for name, dtype in self.field_types.items():
            if not _KEY_RE.match(name):
                raise ValueError(f"invalid field name: {name!r}")
            if dtype not in _DTYPE_CHECKS:
                raise ValueError(f"unknown dtype {dtype!r} for field {name!r}")

    def instruction(self) -> str:
        """Stable format instruction. Keep it verbatim across calls so
        provider-side prompt caching can hit on the static prefix."""
        return (
            "Return ONLY one JSON object shaped exactly as "
            f"{self.shape_example}."
        )

    def extract(self, text: str) -> dict[str, Any] | None:
        """Extract the top-level object from model output.

        Strict JSON parse first; on failure, a best-effort regex salvage for
        the top-level key's object (dtype-aware fallback, not a second
        parser).
        """
        parsed = parse_exact_json_payload(text)
        if isinstance(parsed, dict) and self.top_level_key in parsed:
            inner = parsed[self.top_level_key]
            return inner if isinstance(inner, dict) else None
        return self._salvage(text)

    def _salvage(self, text: str) -> dict[str, Any] | None:
        # Find "top_level_key": { ... } with balanced braces, first match.
        pattern = re.compile(
            rf'"{re.escape(self.top_level_key)}"\s*:\s*\{{', re.DOTALL
        )
        match = pattern.search(text)
        if not match:
            return None
        depth = 0
        start = match.end() - 1
        for index in range(start, len(text)):
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        inner = json.loads(text[start : index + 1])
                    except (json.JSONDecodeError, ValueError):
                        return None
                    return inner if isinstance(inner, dict) else None
        return None

    def validate(self, payload: dict[str, Any]) -> list[str]:
        """Return human-readable violations; empty means the payload fits."""
        violations: list[str] = []
        for key in self.required_keys:
            if key not in payload:
                violations.append(f"missing required key: {key}")
        for name, dtype in self.field_types.items():
            if name in payload and not _check_dtype(payload[name], dtype):
                violations.append(
                    f"field {name!r} should be {dtype}, "
                    f"got {type(payload[name]).__name__}"
                )
        return violations
