from __future__ import annotations

"""Sentence-aware document chunking, ZN-owned.

Pipeline: soft line-break merging -> fine sentence split -> greedy merge to a
target size -> drop too-short chunks. All lengths are rune (character) counts,
never bytes, so CJK text is not systematically under-chunked.

Adapted from the mechanism design of RAGFlow's chunk pipeline
(`internal/parser/chunk/`): fine-split-then-merge preserves sentence
integrity better than one-shot windowing, and repeating a table's header row
in every chunk keeps each chunk self-describing.

Tables are chunked row-wise: the detected header row is repeated at the top
of every chunk so a chunk never loses its column meanings.
"""

import re

from .document_ir import Element, render_table

DEFAULT_TARGET_CHARS = 500
DEFAULT_MIN_CHARS = 50
DEFAULT_MAX_CHARS = 2000

# Sentence-terminal punctuation, CJK-aware. A split happens after one of
# these when followed by whitespace, end of text, or the start of the next
# sentence (CJK char / letter / digit) — CJK text rarely uses spaces.
_SENTENCE_END = re.compile(
    r"([。！？；….!?;]+[\"'\"'」』）)】〉]?)(?=\s|$|[\u4e00-\u9fffA-Za-z0-9])",
)
# Soft line break: a newline NOT preceded by sentence-terminal punctuation is
# a layout artifact (PDF/docx line wrap), merge it into a space.
_SOFT_BREAK = re.compile(r"(?<![。！？；…\.!?;\"'\"'」』）)】〉])\n(?!\n)")


def split_sentences(text: str) -> list[str]:
    """Split text into sentences on CJK and Latin terminal punctuation."""
    text = _SOFT_BREAK.sub(" ", text)
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        end = match.end(1)
        piece = text[start:end].strip()
        if piece:
            sentences.append(piece)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences or ([text.strip()] if text.strip() else [])


def detect_header_row(rows: list[list[str]]) -> int:
    """Return the header row index. Defaults to 0; never raises.

    Minimal heuristic: the first non-empty row is the header unless it looks
    like pure data (all cells numeric) while a later row looks like labels.
    RAGFlow does a 3-level confidence cascade; this keeps level 1 (default)
    plus the cheap numeric-row veto.
    """
    if not rows:
        return 0
    first = rows[0]
    if not any(cell and not _looks_numeric(cell) for cell in first):
        for index in range(1, min(len(rows), 4)):
            if any(cell and not _looks_numeric(cell) for cell in rows[index]):
                return index
    return 0


def _looks_numeric(value: str) -> bool:
    cleaned = value.strip().replace(",", "").replace("%", "")
    if not cleaned:
        return False
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def chunk_table(
    element: Element,
    *,
    target_chars: int = DEFAULT_TARGET_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> list[str]:
    """Chunk a table row-wise, repeating the header row in every chunk."""
    rows: list[list[str]] = element.meta.get("rows") or []
    if not rows:
        return []
    header_index = detect_header_row(rows)
    header = rows[header_index]
    data = rows[:header_index] + rows[header_index + 1 :]
    header_line = " | ".join(header)
    chunks: list[str] = []
    current = [header_line]
    current_len = len(header_line)
    for row in data:
        line = " | ".join((list(row) + [""] * len(header))[: len(header)])
        if current_len + len(line) + 1 > target_chars and len(current) > 1:
            chunks.append("\n".join(current))
            current = [header_line]
            current_len = len(header_line)
        current.append(line)
        current_len += len(line) + 1
    if len(current) > 1 or (len(current) == 1 and current_len >= min_chars):
        chunks.append("\n".join(current))
    sheet = element.meta.get("sheet")
    if sheet:
        chunks = [f"[table: {sheet}]\n{chunk}" for chunk in chunks]
    return chunks


def chunk_elements(
    elements: list[Element],
    *,
    target_chars: int = DEFAULT_TARGET_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[str]:
    """Chunk an element stream: fine split, greedy merge, drop short chunks."""
    target_chars = max(100, min(8000, target_chars))
    min_chars = max(1, min(target_chars, min_chars))
    chunks: list[str] = []
    pending: list[str] = []
    pending_len = 0

    def flush() -> None:
        nonlocal pending, pending_len
        if not pending:
            return
        text = "\n".join(pending).strip()
        pending = []
        pending_len = 0
        if len(text) >= min_chars:
            chunks.append(text[:max_chars])

    for element in elements:
        if element.type == "table":
            flush()
            chunks.extend(
                chunk_table(element, target_chars=target_chars, min_chars=min_chars)
            )
            continue
        if element.type == "heading":
            flush()
        text = element.text.strip()
        if not text:
            continue
        if element.type == "heading":
            text = f"## {text}"
        for sentence in split_sentences(text):
            if pending_len + len(sentence) + 1 > target_chars and pending:
                flush()
            pending.append(sentence)
            pending_len += len(sentence) + 1
    flush()
    return chunks


def chunk_document_text(
    text: str,
    *,
    target_chars: int = DEFAULT_TARGET_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> list[str]:
    """Chunk plain text (convenience wrapper over chunk_elements)."""
    return chunk_elements(
        [Element(type="paragraph", text=text)],
        target_chars=target_chars,
        min_chars=min_chars,
    )


__all__ = [
    "DEFAULT_TARGET_CHARS",
    "DEFAULT_MIN_CHARS",
    "DEFAULT_MAX_CHARS",
    "split_sentences",
    "detect_header_row",
    "chunk_table",
    "chunk_elements",
    "chunk_document_text",
]
