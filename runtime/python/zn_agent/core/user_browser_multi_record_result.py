from __future__ import annotations

"""Bounded read-only interpretation for plural USER Browser result sets.

The existing USER Browser semantic lookup already owns authorization, exact tab
identity, fresh control grounding, guarded input, submit verification and fresh
anchored result sensing. This module only recognizes a narrow user request for a
small plural result set and validates that bounded cognition copied every record
verbatim from the freshly observed context. It creates no browser authority and
performs no side effect.
"""

import json
import re
from typing import Any


_ZH_COUNT = {"二": 2, "两": 2, "三": 3, "四": 4, "五": 5}
_ZH_MULTI_RECORD_RE = re.compile(
    r"(?:最近|最新)\s*([2-5二两三四五])\s*(?:笔|条|个)\s*(?:订单|记录|消息|结果|项目|事项)"
)
_EN_MULTI_RECORD_RE = re.compile(
    r"\b(?:latest|last|recent)\s+([2-5])\s+"
    r"(?:orders?|records?|messages?|results?|items?)\b",
    re.IGNORECASE,
)
_MAX_RECORD_CHARS = 600


def requested_multi_record_count(task: str) -> int | None:
    """Return one explicit bounded plural count, otherwise keep legacy semantics."""

    text = " ".join(str(task or "").strip().split())
    if not text:
        return None
    counts: list[int] = []
    for match in _ZH_MULTI_RECORD_RE.finditer(text):
        raw = match.group(1)
        counts.append(_ZH_COUNT.get(raw, int(raw) if raw.isdigit() else 0))
    for match in _EN_MULTI_RECORD_RE.finditer(text):
        counts.append(int(match.group(1)))
    counts = [value for value in counts if 2 <= value <= 5]
    if not counts or len(set(counts)) != 1:
        return None
    return counts[0]


def parse_verified_record_excerpts(
    model_text: str,
    *,
    context: str,
    expected_count: int,
) -> tuple[str, ...] | None:
    """Accept only ordered, distinct, verbatim excerpts from fresh page evidence."""

    if expected_count < 2 or expected_count > 5:
        return None
    raw = str(model_text or "").strip()
    if raw.startswith("```") and raw.endswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3:
            raw = "\n".join(lines[1:-1]).strip()
    try:
        value: Any = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict) or set(value).difference({"status", "records"}):
        return None
    if str(value.get("status") or "").strip().lower() != "verified":
        return None
    records = value.get("records")
    if not isinstance(records, list) or len(records) != expected_count:
        return None

    normalized_context = " ".join(str(context or "").strip().split())
    if not normalized_context:
        return None

    accepted: list[str] = []
    search_from = 0
    for item in records:
        if not isinstance(item, str):
            return None
        record = " ".join(item.strip().split())
        if (
            not record
            or record != item
            or len(record) > _MAX_RECORD_CHARS
            or any(ord(char) < 32 or ord(char) == 127 for char in record)
            or record in accepted
        ):
            return None
        position = normalized_context.find(record, search_from)
        if position < 0:
            return None
        accepted.append(record)
        search_from = position + len(record)
    return tuple(accepted)
