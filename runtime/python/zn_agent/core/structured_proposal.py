from __future__ import annotations

"""Strict normalization for bounded model-proposed structured payloads.

This module deliberately does not extract JSON from prose. A cognitive response
may be either one complete JSON value or one complete Markdown ``json`` fence,
with whitespace outside the value/fence only. Parsing also rejects duplicate
object keys so ambiguous model output never silently chooses one proposal.

Normalization grants no action authority. Callers must still validate their
owned schema, plan version, workspace confinement, acceptance contract and
permissions before materializing any NativeActionIntent.
"""

import json
from typing import Any


class _DuplicateObjectKey(ValueError):
    pass


def normalize_exact_json_payload(content: str) -> str | None:
    """Return the exact JSON payload for a bare value or one complete json fence."""

    text = str(content or "").strip()
    if not text:
        return None

    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        if len(lines) < 3 or lines[0].strip().lower() != "```json":
            return None
        if lines[-1].strip() != "```":
            return None
        if any(line.strip().startswith("```") for line in lines[1:-1]):
            return None
        payload = "\n".join(lines[1:-1]).strip()
        return payload or None

    # A non-fenced response containing a fence marker is not a bare JSON value.
    if "```" in text:
        return None
    return text


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateObjectKey(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def parse_exact_json_payload(content: str) -> Any | None:
    """Parse one exact normalized JSON payload, rejecting ambiguity."""

    payload = normalize_exact_json_payload(content)
    if payload is None:
        return None
    try:
        return json.loads(payload, object_pairs_hook=_unique_object)
    except (TypeError, ValueError, json.JSONDecodeError, _DuplicateObjectKey):
        return None


def looks_like_structured_payload(content: str, *, top_level_key: str) -> bool:
    """Detect an exact structured candidate for fail-closed routing only.

    This predicate never returns parsed action data and therefore cannot grant
    execution authority. It exists so malformed/ambiguous exact proposals do
    not fall through to generic cognition completion.
    """

    payload = normalize_exact_json_payload(content)
    if payload is None:
        return False
    parsed = parse_exact_json_payload(content)
    if isinstance(parsed, dict):
        return top_level_key in parsed

    # Malformed or duplicate-key JSON that still clearly presents itself as one
    # object proposal is rejected by the structured boundary instead of being
    # treated as ordinary prose. We do not search prose or extract substrings.
    stripped = payload.lstrip()
    return stripped.startswith("{") and f'"{top_level_key}"' in payload
