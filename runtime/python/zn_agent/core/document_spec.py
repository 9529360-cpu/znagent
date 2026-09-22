from __future__ import annotations

"""Bounded state model for the native ZN Document v1 product."""

import json
import re
from typing import Any, Mapping, Sequence

SPEC_VERSION = 1
MAX_DOCUMENT_SECTIONS = 12
MAX_TITLE_CHARS = 160
MAX_SUBTITLE_CHARS = 240
MAX_HEADING_CHARS = 120
MAX_PARAGRAPHS_PER_SECTION = 4
MAX_PARAGRAPH_CHARS = 1600
MAX_BULLETS_PER_SECTION = 8
MAX_BULLET_CHARS = 360

_DOCUMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_SECTION_ID_RE = re.compile(r"^section-[1-9][0-9]?$")


def _text(value: Any, *, field: str, limit: int, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    text = " ".join(value.strip().split())
    if required and not text:
        raise ValueError(f"{field} must not be empty")
    if len(text) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return text


def _text_list(
    value: Any,
    *,
    field: str,
    max_items: int,
    max_chars: int,
) -> list[str]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be an ordered list of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} supports at most {max_items} items")
    return [
        _text(item, field=f"{field}[{index}]", limit=max_chars, required=True)
        for index, item in enumerate(value)
    ]


def normalize_document_section(raw: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"section {index} must be an object")
    if set(raw) != {"id", "heading", "paragraphs", "bullets"}:
        raise ValueError(
            f"section {index} must contain exactly id, heading, paragraphs and bullets"
        )
    expected_id = f"section-{index}"
    section_id = _text(raw.get("id"), field=f"section {index} id", limit=20, required=True)
    if section_id != expected_id or not _SECTION_ID_RE.fullmatch(section_id):
        raise ValueError(f"section {index} must keep stable id {expected_id}")
    heading = _text(
        raw.get("heading"),
        field=f"section {index} heading",
        limit=MAX_HEADING_CHARS,
        required=True,
    )
    paragraphs = _text_list(
        raw.get("paragraphs", []),
        field=f"section {index} paragraphs",
        max_items=MAX_PARAGRAPHS_PER_SECTION,
        max_chars=MAX_PARAGRAPH_CHARS,
    )
    bullets = _text_list(
        raw.get("bullets", []),
        field=f"section {index} bullets",
        max_items=MAX_BULLETS_PER_SECTION,
        max_chars=MAX_BULLET_CHARS,
    )
    if not paragraphs and not bullets:
        raise ValueError(f"section {index} must contain paragraph or bullet content")
    return {
        "id": section_id,
        "heading": heading,
        "paragraphs": paragraphs,
        "bullets": bullets,
    }


def normalize_document_spec(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("DocumentSpec must be one object")
    if set(raw) != {"version", "document_id", "title", "subtitle", "sections"}:
        raise ValueError(
            "DocumentSpec v1 must contain exactly version, document_id, title, subtitle and sections"
        )
    if int(raw.get("version") or 0) != SPEC_VERSION:
        raise ValueError(f"DocumentSpec version must be {SPEC_VERSION}")
    document_id = _text(
        raw.get("document_id"),
        field="document_id",
        limit=64,
        required=True,
    )
    if not _DOCUMENT_ID_RE.fullmatch(document_id):
        raise ValueError("document_id is not a safe stable identifier")
    title = _text(raw.get("title"), field="document title", limit=MAX_TITLE_CHARS, required=True)
    subtitle = _text(raw.get("subtitle", ""), field="document subtitle", limit=MAX_SUBTITLE_CHARS)
    raw_sections = raw.get("sections")
    if isinstance(raw_sections, (str, bytes, Mapping)) or not isinstance(raw_sections, Sequence):
        raise ValueError("DocumentSpec sections must be an ordered list")
    if not 1 <= len(raw_sections) <= MAX_DOCUMENT_SECTIONS:
        raise ValueError(f"DocumentSpec supports 1..{MAX_DOCUMENT_SECTIONS} sections")
    sections = [
        normalize_document_section(section, index=index)
        for index, section in enumerate(raw_sections, start=1)
    ]
    return {
        "version": SPEC_VERSION,
        "document_id": document_id,
        "title": title,
        "subtitle": subtitle,
        "sections": sections,
    }


def document_visible_texts(spec: Mapping[str, Any]) -> list[str]:
    normalized = normalize_document_spec(spec)
    texts = [normalized["title"]]
    if normalized["subtitle"]:
        texts.append(normalized["subtitle"])
    for section in normalized["sections"]:
        texts.append(section["heading"])
        texts.extend(section["paragraphs"])
        texts.extend(section["bullets"])
    return texts


def document_spec_json(spec: Mapping[str, Any]) -> str:
    return json.dumps(
        normalize_document_spec(spec),
        ensure_ascii=False,
        separators=(",", ":"),
    )
