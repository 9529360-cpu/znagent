from __future__ import annotations

"""Unified document intermediate representation (IR), ZN-owned.

Different formats (docx, xlsx, txt, md) parse into one element stream so all
downstream consumers — chunking, table handling, text rendering — are written
once against the IR instead of once per format.

Adapted from the mechanism design of RAGFlow's document pipeline (unified IR,
never silently drop a block, images keep their stream position with
surrounding context). This is a minimal ZN-owned reimplementation: no ONNX
models, no layout analysis, no external services — just structure that the
format libraries already expose.

An Element is one of:
  paragraph | heading | list_item | table | image_ref
Tables carry `rows` (list of list of str) in meta; headings carry `level`.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

MAX_IR_TEXT_CHARS = 200_000
MAX_TABLE_ROWS = 5_000
MAX_TABLE_COLS = 100


@dataclass(slots=True)
class Element:
    type: str  # paragraph | heading | list_item | table | image_ref
    text: str = ""
    children: list["Element"] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def _clean(value: object, *, limit: int = MAX_IR_TEXT_CHARS) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit] if len(text) > limit else text


def parse_document(path: str | Path) -> list[Element]:
    """Parse a document file into a unified element stream.

    Never raises on a readable file: unparsable content becomes a single
    paragraph noting the failure instead of silently vanishing.
    """
    source = Path(path)
    suffix = source.suffix.lower()
    try:
        if suffix == ".docx":
            return _parse_docx(source)
        if suffix in (".xlsx", ".xlsm"):
            return _parse_xlsx(source)
        if suffix in (".txt", ".md", ".markdown"):
            return _parse_text(source)
        return [Element(type="paragraph", text=f"[unsupported format: {suffix}]")]
    except Exception as exc:
        return [
            Element(
                type="paragraph",
                text=f"[could not parse {source.name}: {type(exc).__name__}]",
            )
        ]


def _parse_docx(source: Path) -> list[Element]:
    from docx import Document

    document = Document(source)
    elements: list[Element] = []
    # Walk body children in document order so tables keep their position
    # relative to surrounding paragraphs (never silently dropped, never
    # reordered to the end).
    body = document.element.body
    for child in body.iterchildren():
        tag = _local(child.tag)
        if tag == "p":
            el = _docx_paragraph(child, document)
            if el is not None:
                elements.append(el)
        elif tag == "tbl":
            el = _docx_table(child)
            if el is not None:
                elements.append(el)
    return elements or [Element(type="paragraph", text="[empty document]")]


def _docx_paragraph(p_el: Any, document: Any) -> Element | None:
    from docx.text.paragraph import Paragraph

    para = Paragraph(p_el, document)
    text = _clean(para.text)
    if not text:
        return None
    style_name = (para.style.name or "").lower()
    if style_name.startswith("heading"):
        try:
            level = int("".join(c for c in style_name if c.isdigit()) or 1)
        except ValueError:
            level = 1
        return Element(type="heading", text=text, meta={"level": min(level, 6)})
    if "list" in style_name or "bullet" in style_name:
        return Element(type="list_item", text=text)
    return Element(type="paragraph", text=text)


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _docx_table(tbl_el: Any) -> Element | None:
    # Read cell text straight from the XML: robust without a python-docx
    # parent object, and keeps merged-cell text in reading order.
    # Only direct children are walked so nested tables are not double-counted.
    try:
        rows: list[list[str]] = []
        for tr in tbl_el:
            if _local(tr.tag) != "tr":
                continue
            cells: list[str] = []
            for tc in tr:
                if _local(tc.tag) != "tc":
                    continue
                parts = [t.text for t in tc.iter() if _local(t.tag) == "t" and t.text]
                cells.append(_clean("".join(parts)))
            if any(cells):
                rows.append(cells[:MAX_TABLE_COLS])
            if len(rows) >= MAX_TABLE_ROWS:
                break
    except Exception:
        return None
    if not rows:
        return None
    return Element(type="table", meta={"rows": rows})


def _parse_xlsx(source: Path) -> list[Element]:
    from openpyxl import load_workbook

    workbook = load_workbook(source, read_only=True, data_only=True)
    elements: list[Element] = []
    for sheet in workbook.worksheets:
        rows: list[list[str]] = []
        for row in sheet.iter_rows(values_only=True):
            cells = [_clean(value) for value in row]
            # Trim trailing empties but keep interior structure.
            while cells and not cells[-1]:
                cells.pop()
            if any(cells):
                rows.append(cells[:MAX_TABLE_COLS])
            if len(rows) >= MAX_TABLE_ROWS:
                break
        if rows:
            elements.append(
                Element(
                    type="table",
                    meta={"rows": rows, "sheet": _clean(sheet.title, limit=128)},
                )
            )
    workbook.close()
    return elements or [Element(type="paragraph", text="[empty workbook]")]


def _parse_text(source: Path) -> list[Element]:
    raw = source.read_text(encoding="utf-8", errors="replace")
    elements: list[Element] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            elements.append(
                Element(
                    type="heading",
                    text=_clean(stripped.lstrip("#").strip()),
                    meta={"level": min(max(level, 1), 6)},
                )
            )
        elif stripped[:2] in ("- ", "* ", "+ ") or (
            len(stripped) > 2 and stripped[0].isdigit() and stripped[1] == "."
        ):
            elements.append(Element(type="list_item", text=_clean(stripped[2:].strip())))
        else:
            elements.append(Element(type="paragraph", text=_clean(stripped)))
    return elements or [Element(type="paragraph", text="[empty document]")]


def iter_text_blocks(elements: list[Element]) -> Iterator[str]:
    """Yield each element's readable text in stream order (tables included)."""
    for el in elements:
        if el.type == "table":
            yield render_table(el)
        elif el.text:
            yield el.text
        yield from iter_text_blocks(el.children)


def render_table(element: Element) -> str:
    """Render a table element as markdown-ish text with its header row."""
    rows: list[list[str]] = element.meta.get("rows") or []
    if not rows:
        return "[empty table]"
    header = rows[0]
    lines = [" | ".join(header), " | ".join("---" for _ in header)]
    for row in rows[1:]:
        padded = list(row) + [""] * (len(header) - len(row))
        lines.append(" | ".join(padded[: len(header)]))
    sheet = element.meta.get("sheet")
    prefix = f"[table: {sheet}]\n" if sheet else ""
    return prefix + "\n".join(lines)


def flatten_elements(elements: list[Element]) -> str:
    """Render the whole IR to plain text, preserving stream order."""
    return "\n\n".join(iter_text_blocks(elements))
