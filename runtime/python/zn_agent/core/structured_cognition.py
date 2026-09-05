from __future__ import annotations

"""Strict decoding for model-generated structured cognition contracts.

Models that understand a JSON-only contract sometimes wrap the exact object in
one Markdown code fence. ZN may remove that transport-only wrapper, but it must
never search arbitrary prose for a convenient object or accept trailing text.
This helper therefore accepts exactly one of two envelopes:

1. one raw JSON object, or
2. one complete fenced block (```json or ```) whose body is one JSON object.

Everything else fails closed.
"""

import json
from typing import Any


def decode_structured_cognition_object(content: str) -> dict[str, Any] | None:
    text = str(content or "").strip()
    if not text:
        return None

    candidate = text
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 3:
            return None
        opener = lines[0].strip().lower()
        if opener not in {"```", "```json"}:
            return None
        if lines[-1].strip() != "```":
            return None
        if any(line.strip().startswith("```") for line in lines[1:-1]):
            return None
        candidate = "\n".join(lines[1:-1]).strip()
        if not candidate:
            return None
    elif "```" in text:
        return None

    try:
        value = json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None
