from __future__ import annotations

"""Document artifact connector (R8): deliverable .docx/.xlsx/.pptx generation
plus Markdown-to-PDF, on the existing Fabric/Body capability path.

Four write tools — ``doc.generate_docx``, ``doc.generate_xlsx``,
``doc.generate_pptx``, ``doc.generate_pdf`` — built on the dependencies the
repository already pins (``python-docx``, ``openpyxl``, ``python-pptx``) plus a
stdlib-only minimal PDF writer for the Markdown-to-PDF leg (no PDF library is
pinned, so this module ships its own small writer rather than adding a
dependency).

Every tool is an approval-gated Body write (``approval:production_change``,
replay-identity refusal, independent postcondition re-verification), the same
contract as the calendar and mail connectors. Every generation runs a
read-back verification before success is reported: the file must open with
the real format library, and structural counts (paragraphs/tables, sheets and
rows, slides, PDF page count) must match what the builder reported. A
generation whose verification fails raises instead of reporting success.

Named templates give the standard shapes the backlog asks for: ``report``
(docx), ``data_table`` (xlsx), ``briefing_deck`` (pptx). Templates decide
structure and styling; the action's ``content`` argument supplies the data.
Unknown template names and malformed content fail explicitly with
:class:`DocArtifactError` — nothing here invents structure.

Bad parameters fail explicitly, never silently: unsafe output names (path
separators, ``..``, wrong suffix), targets outside the configured output
directory, oversized inputs, mismatched table rows, and CJK text in the PDF
leg (the stdlib writer only covers WinAnsi; ``doc.generate_docx`` is the
honest alternative for CJK).
"""

import hashlib
import json
import os
import re
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from docx import Document as DocxDocument
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.opc.exceptions import PackageNotFoundError as DocxPackageNotFoundError
from docx.shared import Pt, RGBColor
from openpyxl import Workbook as XlsxWorkbook
from openpyxl import load_workbook as xlsx_load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from pptx import Presentation as PptxPresentation
from pptx.exc import PackageNotFoundError as PptxPackageNotFoundError
from pptx.util import Inches, Pt as PptxPt

from .action_execution import (
    ActionExecutionRuntime,
    ActionObservation,
    ActionRequest,
    ActionVerification,
)
from .action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
)
from .approval_cards import APPROVAL_KINDS
from .body import BodyAction, BodyActionResult, NativeBody
from .mcp_capability_adapter import mcp_write_replay_identity
from .models import utc_now

__all__ = [
    "APPROVAL_KIND",
    "DOCX_ACTION_ID",
    "DOCX_TEMPLATE_NAMES",
    "PDF_ACTION_ID",
    "PPTX_ACTION_ID",
    "PPTX_TEMPLATE_NAMES",
    "PROVIDER_ID",
    "XLSX_ACTION_ID",
    "XLSX_TEMPLATE_NAMES",
    "DocArtifactAttachment",
    "DocArtifactError",
    "GeneratedArtifact",
    "attach_doc_artifact_tools",
    "build_docx_bytes",
    "build_pdf_bytes_from_markdown",
    "build_pptx_bytes",
    "build_xlsx_bytes",
    "register_doc_artifacts_runtime",
    "render_docx_template",
    "render_pptx_template",
    "render_xlsx_template",
    "verify_docx",
    "verify_pdf",
    "verify_pptx",
    "verify_xlsx",
    "write_docx",
    "write_pdf_from_markdown",
    "write_pptx",
    "write_xlsx",
]

PROVIDER_ID = "zn_doc_artifacts"
DOCX_ACTION_ID = "doc.generate_docx"
XLSX_ACTION_ID = "doc.generate_xlsx"
PPTX_ACTION_ID = "doc.generate_pptx"
PDF_ACTION_ID = "doc.generate_pdf"

APPROVAL_KIND = "production_change"
assert APPROVAL_KIND in APPROVAL_KINDS

DOCX_TEMPLATE_NAMES = ("report",)
XLSX_TEMPLATE_NAMES = ("data_table",)
PPTX_TEMPLATE_NAMES = ("briefing_deck",)

# ---------------------------------------------------------------------------
# Bounds: generation inputs are bounded so one call cannot run away.
# ---------------------------------------------------------------------------

MAX_FILENAME_LEN = 120
MAX_DOCX_SECTIONS = 50
MAX_DOCX_PARAGRAPHS_PER_SECTION = 200
MAX_DOCX_TABLES = 20
MAX_DOCX_TEXT_CHARS = 20_000
MAX_TABLE_ROWS = 1_000
MAX_TABLE_COLS = 32
MAX_CELL_CHARS = 4_000
MAX_XLSX_SHEETS = 20
MAX_XLSX_ROWS = 5_000
MAX_XLSX_COLS = 64
MAX_PPTX_SLIDES = 80
MAX_PPTX_BULLETS = 60
MAX_MARKDOWN_CHARS = 200_000


class DocArtifactError(Exception):
    """Explicit failure for document artifact generation/verification."""


# ---------------------------------------------------------------------------
# Output path safety
# ---------------------------------------------------------------------------


def _validate_output_name(name: Any, expected_suffix: str) -> str:
    """A plain filename only: no separators, no traversal, right suffix."""
    text = str(name or "").strip()
    if not text:
        raise DocArtifactError("output_name must not be empty")
    if len(text) > MAX_FILENAME_LEN:
        raise DocArtifactError(
            f"output_name is too long ({len(text)} > {MAX_FILENAME_LEN})"
        )
    if "/" in text or "\\" in text or text in (".", ".."):
        raise DocArtifactError(
            f"output_name must be a plain filename, got {text!r}"
        )
    if ".." in text:
        raise DocArtifactError(
            f"output_name must not contain '..', got {text!r}"
        )
    if "\x00" in text:
        raise DocArtifactError("output_name must not contain NUL bytes")
    lowered = text.lower()
    if lowered.endswith(expected_suffix):
        return text
    if "." in Path(text).name and Path(text).suffix:
        raise DocArtifactError(
            f"output_name must end with {expected_suffix}, got {text!r}"
        )
    return text + expected_suffix


def _resolve_target(output_dir: Any, output_name: str) -> Path:
    root = Path(str(output_dir or "")).expanduser()
    if not str(output_dir or "").strip():
        raise DocArtifactError("no output directory configured")
    if not root.is_dir():
        raise DocArtifactError(
            f"output directory does not exist or is not a directory: {root}"
        )
    resolved_root = root.resolve()
    target = (resolved_root / output_name).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError:
        raise DocArtifactError(
            f"output_name {output_name!r} escapes the output directory"
        ) from None
    return target


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=".zn-doc-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, target)
    except OSError as exc:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise DocArtifactError(
            f"cannot write artifact to {target}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Small validation helpers (explicit failures, never silent defaults)
# ---------------------------------------------------------------------------


def _require_text(mapping: Mapping[str, Any], key: str, *, what: str) -> str:
    value = mapping.get(key)
    text = str(value or "").strip()
    if not text:
        raise DocArtifactError(f"{what} requires a non-empty '{key}'")
    return text


def _optional_text(mapping: Mapping[str, Any], key: str) -> str:
    return str(mapping.get(key) or "").strip()


def _bounded_text(text: str, *, what: str, limit: int = MAX_DOCX_TEXT_CHARS) -> str:
    if len(text) > limit:
        raise DocArtifactError(
            f"{what} is too long ({len(text)} > {limit} characters)"
        )
    return text


def _require_list(mapping: Mapping[str, Any], key: str, *, what: str) -> list:
    value = mapping.get(key)
    if not isinstance(value, list):
        raise DocArtifactError(f"{what} requires '{key}' to be a list")
    return value


class GeneratedArtifact:
    """A generated file plus the structural report used for verification."""

    def __init__(
        self, path: Path, *, report: Mapping[str, Any], byte_size: int
    ) -> None:
        self.path = path
        self.report = dict(report)
        self.byte_size = byte_size

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "byte_size": self.byte_size,
            "report": dict(self.report),
        }


# ---------------------------------------------------------------------------
# .docx generation + read-back verification (python-docx, already pinned)
# ---------------------------------------------------------------------------


def _validate_docx_table(table: Mapping[str, Any], index: int) -> tuple[list[str], list[list[str]]]:
    headers_raw = table.get("headers")
    if not isinstance(headers_raw, list) or not headers_raw:
        raise DocArtifactError(
            f"docx table {index}: 'headers' must be a non-empty list"
        )
    if len(headers_raw) > MAX_TABLE_COLS:
        raise DocArtifactError(
            f"docx table {index}: too many columns "
            f"({len(headers_raw)} > {MAX_TABLE_COLS})"
        )
    headers = [
        _bounded_text(str(cell or ""), what=f"docx table {index} header",
                      limit=MAX_CELL_CHARS)
        for cell in headers_raw
    ]
    rows_raw = table.get("rows", [])
    if not isinstance(rows_raw, list):
        raise DocArtifactError(
            f"docx table {index}: 'rows' must be a list of lists"
        )
    if len(rows_raw) > MAX_TABLE_ROWS:
        raise DocArtifactError(
            f"docx table {index}: too many rows "
            f"({len(rows_raw)} > {MAX_TABLE_ROWS})"
        )
    rows: list[list[str]] = []
    for row_index, row in enumerate(rows_raw):
        if not isinstance(row, list):
            raise DocArtifactError(
                f"docx table {index} row {row_index}: must be a list"
            )
        if len(row) != len(headers):
            raise DocArtifactError(
                f"docx table {index} row {row_index}: has {len(row)} cells "
                f"but the header has {len(headers)} — every row must match"
            )
        rows.append([
            _bounded_text(str(cell if cell is not None else ""),
                          what=f"docx table {index} cell",
                          limit=MAX_CELL_CHARS)
            for cell in row
        ])
    return headers, rows


def _validate_docx_content(content: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(content, Mapping):
        raise DocArtifactError("docx 'content' must be an object")
    title = _require_text(content, "title", what="docx")
    _bounded_text(title, what="docx title")
    author = _optional_text(content, "author")
    summary = _optional_text(content, "summary")
    _bounded_text(summary, what="docx summary")
    sections_raw = _require_list(content, "sections", what="docx") if "sections" in content else []
    if len(sections_raw) > MAX_DOCX_SECTIONS:
        raise DocArtifactError(
            f"docx: too many sections ({len(sections_raw)} > {MAX_DOCX_SECTIONS})"
        )
    sections: list[dict[str, Any]] = []
    for index, section in enumerate(sections_raw):
        if not isinstance(section, Mapping):
            raise DocArtifactError(f"docx section {index}: must be an object")
        heading = _require_text(section, "heading", what=f"docx section {index}")
        _bounded_text(heading, what=f"docx section {index} heading")
        paragraphs_raw = section.get("paragraphs", [])
        if not isinstance(paragraphs_raw, list):
            raise DocArtifactError(
                f"docx section {index}: 'paragraphs' must be a list"
            )
        if len(paragraphs_raw) > MAX_DOCX_PARAGRAPHS_PER_SECTION:
            raise DocArtifactError(
                f"docx section {index}: too many paragraphs "
                f"({len(paragraphs_raw)} > {MAX_DOCX_PARAGRAPHS_PER_SECTION})"
            )
        paragraphs = [
            _bounded_text(str(paragraph or ""),
                          what=f"docx section {index} paragraph")
            for paragraph in paragraphs_raw
        ]
        sections.append({"heading": heading, "paragraphs": paragraphs})
    tables_raw = content.get("tables", [])
    if not isinstance(tables_raw, list):
        raise DocArtifactError("docx 'tables' must be a list")
    if len(tables_raw) > MAX_DOCX_TABLES:
        raise DocArtifactError(
            f"docx: too many tables ({len(tables_raw)} > {MAX_DOCX_TABLES})"
        )
    tables: list[dict[str, Any]] = []
    for index, table in enumerate(tables_raw):
        if not isinstance(table, Mapping):
            raise DocArtifactError(f"docx table {index}: must be an object")
        headers, rows = _validate_docx_table(table, index)
        tables.append({
            "caption": _optional_text(table, "caption"),
            "headers": headers,
            "rows": rows,
        })
    return {
        "title": title,
        "author": author,
        "summary": summary,
        "sections": sections,
        "tables": tables,
    }


def build_docx_bytes(content: Mapping[str, Any]) -> tuple[bytes, dict[str, Any]]:
    """Build a .docx in memory; returns (bytes, structural report)."""
    spec = _validate_docx_content(content)
    document = DocxDocument()
    core = document.core_properties
    core.title = spec["title"]
    if spec["author"]:
        core.author = spec["author"]

    document.add_heading(spec["title"], level=0)
    meta_bits = []
    if spec["author"]:
        meta_bits.append(f"作者：{spec['author']}")
    meta_bits.append(f"日期：{date.today().isoformat()}")
    meta_paragraph = document.add_paragraph(" ｜ ".join(meta_bits))
    for run in meta_paragraph.runs:
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    paragraph_count = 1  # the meta line
    if spec["summary"]:
        document.add_heading("摘要", level=1)
        document.add_paragraph(spec["summary"])
        paragraph_count += 1

    for section in spec["sections"]:
        document.add_heading(section["heading"], level=1)
        for text in section["paragraphs"]:
            document.add_paragraph(text)
        paragraph_count += len(section["paragraphs"])

    table_reports: list[dict[str, int]] = []
    for table in spec["tables"]:
        if table["caption"]:
            caption = document.add_paragraph()
            run = caption.add_run(table["caption"])
            run.italic = True
            run.font.size = Pt(9)
            paragraph_count += 1
        grid = document.add_table(rows=1 + len(table["rows"]),
                                  cols=len(table["headers"]))
        grid.style = "Table Grid"
        for col, header in enumerate(table["headers"]):
            cell = grid.cell(0, col)
            cell.text = ""
            run = cell.paragraphs[0].add_run(header)
            run.bold = True
        for row_index, row in enumerate(table["rows"], start=1):
            for col, value in enumerate(row):
                grid.cell(row_index, col).text = value
        table_reports.append({
            "rows": len(table["rows"]),
            "cols": len(table["headers"]),
        })

    import io
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue(), {
        "title": spec["title"],
        "paragraph_count": paragraph_count,
        "table_count": len(table_reports),
        "tables": table_reports,
    }


def write_docx(
    content: Mapping[str, Any],
    output_dir: str | Path,
    output_name: str,
) -> GeneratedArtifact:
    """Validate, build, atomically write, and read-back-verify a .docx."""
    name = _validate_output_name(output_name, ".docx")
    data, report = build_docx_bytes(content)
    target = _resolve_target(output_dir, name)
    _atomic_write_bytes(target, data)
    verification = verify_docx(target, report)
    return GeneratedArtifact(target, report=report, byte_size=len(data))


def verify_docx(path: str | Path, expected: Mapping[str, Any]) -> dict[str, Any]:
    """Open a .docx with python-docx and check structural counts match.

    Raises DocArtifactError on unreadable files or count mismatches.
    Returns the observed structural report.
    """
    source = Path(path)
    try:
        document = DocxDocument(str(source))
        paragraphs = [p for p in document.paragraphs if p.text.strip()]
        tables = document.tables
        observed_tables = [
            {"rows": len(table.rows) - 1, "cols": len(table.columns)}
            for table in tables
        ]
    except (zipfile.BadZipFile, OSError, ValueError, KeyError,
            TypeError, AttributeError,
            DocxPackageNotFoundError) as exc:
        raise DocArtifactError(
            f"{source} is not a readable .docx: {type(exc).__name__}: {exc}"
        ) from exc
    observed = {
        "paragraph_count": len(paragraphs),
        "table_count": len(tables),
        "tables": observed_tables,
    }
    # Paragraph check is a lower bound: table cells legitimately add
    # paragraphs beyond the ones the builder counted.
    if len(paragraphs) < int(expected.get("paragraph_count", 0)):
        raise DocArtifactError(
            f"docx verification failed for {source}: expected at least "
            f"{expected.get('paragraph_count')} paragraphs, found "
            f"{len(paragraphs)}"
        )
    expected_title = str(expected.get("title") or "")
    if expected_title and not any(
        expected_title in paragraph.text for paragraph in paragraphs
    ):
        raise DocArtifactError(
            f"docx verification failed for {source}: title "
            f"{expected_title!r} not found in the document body"
        )
    expected_tables = list(expected.get("tables", []))
    if len(tables) != int(expected.get("table_count", -1)):
        raise DocArtifactError(
            f"docx verification failed for {source}: expected "
            f"{expected.get('table_count')} tables, found {len(tables)}"
        )
    if len(observed_tables) != len(expected_tables):
        raise DocArtifactError(
            f"docx verification failed for {source}: table dimension "
            f"report mismatch"
        )
    for index, (seen, want) in enumerate(zip(observed_tables, expected_tables)):
        if seen["rows"] != int(want.get("rows", -1)) or seen["cols"] != int(
            want.get("cols", -1)
        ):
            raise DocArtifactError(
                f"docx verification failed for {source}: table {index} is "
                f"{seen['rows']}x{seen['cols']}, expected "
                f"{want.get('rows')}x{want.get('cols')}"
            )
    return observed


# ---------------------------------------------------------------------------
# .xlsx generation + read-back verification (openpyxl, already pinned)
# ---------------------------------------------------------------------------

_XLSX_SHEET_NAME_FORBIDDEN = re.compile(r"[/\\?*\[\]:]")
_HEADER_FILL = PatternFill(
    start_color="D9E2F3", end_color="D9E2F3", fill_type="solid"
)
_HEADER_FONT = Font(bold=True)
_WRAP_ALIGNMENT = Alignment(vertical="top", wrap_text=True)


def _validate_sheet_name(name: Any, index: int) -> str:
    text = str(name or "").strip()
    if not text:
        raise DocArtifactError(f"xlsx sheet {index}: 'name' must not be empty")
    if len(text) > 31:
        raise DocArtifactError(
            f"xlsx sheet {index}: name {text!r} exceeds 31 characters"
        )
    if _XLSX_SHEET_NAME_FORBIDDEN.search(text):
        raise DocArtifactError(
            f"xlsx sheet {index}: name {text!r} contains a forbidden "
            "character (one of / \\ ? * [ ] :)"
        )
    return text


def _validate_xlsx_content(content: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(content, Mapping):
        raise DocArtifactError("xlsx 'content' must be an object")
    sheets_raw = _require_list(content, "sheets", what="xlsx")
    if not sheets_raw:
        raise DocArtifactError("xlsx requires at least one sheet")
    if len(sheets_raw) > MAX_XLSX_SHEETS:
        raise DocArtifactError(
            f"xlsx: too many sheets ({len(sheets_raw)} > {MAX_XLSX_SHEETS})"
        )
    sheets: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, sheet in enumerate(sheets_raw):
        if not isinstance(sheet, Mapping):
            raise DocArtifactError(f"xlsx sheet {index}: must be an object")
        name = _validate_sheet_name(sheet.get("name"), index)
        if name in seen_names:
            raise DocArtifactError(
                f"xlsx sheet {index}: duplicate sheet name {name!r}"
            )
        seen_names.add(name)
        headers_raw = sheet.get("headers")
        if not isinstance(headers_raw, list) or not headers_raw:
            raise DocArtifactError(
                f"xlsx sheet {index}: 'headers' must be a non-empty list"
            )
        if len(headers_raw) > MAX_XLSX_COLS:
            raise DocArtifactError(
                f"xlsx sheet {index}: too many columns "
                f"({len(headers_raw)} > {MAX_XLSX_COLS})"
            )
        headers = [
            _bounded_text(str(cell if cell is not None else ""),
                          what=f"xlsx sheet {index} header",
                          limit=MAX_CELL_CHARS)
            for cell in headers_raw
        ]
        rows_raw = sheet.get("rows", [])
        if not isinstance(rows_raw, list):
            raise DocArtifactError(
                f"xlsx sheet {index}: 'rows' must be a list of lists"
            )
        if len(rows_raw) > MAX_XLSX_ROWS:
            raise DocArtifactError(
                f"xlsx sheet {index}: too many rows "
                f"({len(rows_raw)} > {MAX_XLSX_ROWS})"
            )
        rows: list[list[Any]] = []
        for row_index, row in enumerate(rows_raw):
            if not isinstance(row, list):
                raise DocArtifactError(
                    f"xlsx sheet {index} row {row_index}: must be a list"
                )
            if len(row) != len(headers):
                raise DocArtifactError(
                    f"xlsx sheet {index} row {row_index}: has {len(row)} "
                    f"cells but the header has {len(headers)} — every row "
                    "must match"
                )
            cleaned: list[Any] = []
            for cell in row:
                if cell is None or isinstance(cell, (bool, int, float, str)):
                    cleaned.append(cell)
                else:
                    cleaned.append(
                        _bounded_text(str(cell),
                                      what=f"xlsx sheet {index} cell",
                                      limit=MAX_CELL_CHARS)
                    )
            rows.append(cleaned)
        sheets.append({"name": name, "headers": headers, "rows": rows})
    return sheets


def build_xlsx_bytes(content: Mapping[str, Any]) -> tuple[bytes, dict[str, Any]]:
    """Build an .xlsx in memory; returns (bytes, structural report)."""
    sheets = _validate_xlsx_content(content)
    workbook = XlsxWorkbook()
    # Drop the default sheet; we create our own below.
    default = workbook.active
    if default is not None:
        workbook.remove(default)
    sheet_reports: list[dict[str, Any]] = []
    for sheet in sheets:
        worksheet = workbook.create_sheet(title=sheet["name"])
        headers: list[str] = sheet["headers"]
        rows: list[list[Any]] = sheet["rows"]
        for col, header in enumerate(headers, start=1):
            cell = worksheet.cell(row=1, column=col, value=header)
            cell.font = _HEADER_FONT
            cell.fill = _HEADER_FILL
            cell.alignment = _WRAP_ALIGNMENT
        for row_index, row in enumerate(rows, start=2):
            for col, value in enumerate(row, start=1):
                cell = worksheet.cell(row=row_index, column=col, value=value)
                cell.alignment = _WRAP_ALIGNMENT
        last_column = worksheet.cell(row=1, column=len(headers)).column_letter
        worksheet.auto_filter.ref = f"A1:{last_column}{1 + len(rows)}"
        worksheet.freeze_panes = "A2"
        widths: list[int] = []
        for col in range(len(headers)):
            longest = len(headers[col])
            for row in rows:
                value = row[col]
                longest = max(longest, len(str(value) if value is not None else ""))
            widths.append(min(60, max(10, longest + 2)))
        for col, width in enumerate(widths, start=1):
            worksheet.column_dimensions[
                worksheet.cell(row=1, column=col).column_letter
            ].width = width
        sheet_reports.append({
            "name": sheet["name"],
            "header_cols": len(headers),
            "data_rows": len(rows),
        })
    import io
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue(), {"sheets": sheet_reports}


def write_xlsx(
    content: Mapping[str, Any],
    output_dir: str | Path,
    output_name: str,
) -> GeneratedArtifact:
    """Validate, build, atomically write, and read-back-verify an .xlsx."""
    name = _validate_output_name(output_name, ".xlsx")
    data, report = build_xlsx_bytes(content)
    target = _resolve_target(output_dir, name)
    _atomic_write_bytes(target, data)
    verify_xlsx(target, report)
    return GeneratedArtifact(target, report=report, byte_size=len(data))


def verify_xlsx(path: str | Path, expected: Mapping[str, Any]) -> dict[str, Any]:
    """Open an .xlsx with openpyxl and check sheets/rows/cols match."""
    source = Path(path)
    try:
        workbook = xlsx_load_workbook(str(source), read_only=True,
                                      data_only=True)
        try:
            observed_names = list(workbook.sheetnames)
            observed: list[dict[str, Any]] = []
            for name in observed_names:
                worksheet = workbook[name]
                observed.append({
                    "name": name,
                    "header_cols": worksheet.max_column or 0,
                    "data_rows": max(0, (worksheet.max_row or 1) - 1),
                })
        finally:
            workbook.close()
    except (zipfile.BadZipFile, OSError, ValueError, KeyError,
            TypeError) as exc:
        raise DocArtifactError(
            f"{source} is not a readable .xlsx: {type(exc).__name__}: {exc}"
        ) from exc
    expected_sheets = list(expected.get("sheets", []))
    if [item["name"] for item in observed] != [
        str(item.get("name")) for item in expected_sheets
    ]:
        raise DocArtifactError(
            f"xlsx verification failed for {source}: sheets "
            f"{[item['name'] for item in observed]} do not match expected "
            f"{[item.get('name') for item in expected_sheets]}"
        )
    for seen, want in zip(observed, expected_sheets):
        if (seen["header_cols"] != int(want.get("header_cols", -1))
                or seen["data_rows"] != int(want.get("data_rows", -1))):
            raise DocArtifactError(
                f"xlsx verification failed for {source}: sheet "
                f"{seen['name']!r} is {seen['header_cols']} cols x "
                f"{seen['data_rows']} data rows, expected "
                f"{want.get('header_cols')} x {want.get('data_rows')}"
            )
    return {"sheets": observed}


# ---------------------------------------------------------------------------
# .pptx generation + read-back verification (python-pptx, already pinned)
# ---------------------------------------------------------------------------


def _validate_pptx_content(content: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(content, Mapping):
        raise DocArtifactError("pptx 'content' must be an object")
    title = _require_text(content, "title", what="pptx deck")
    _bounded_text(title, what="pptx deck title")
    subtitle = _optional_text(content, "subtitle")
    _bounded_text(subtitle, what="pptx deck subtitle")
    closing = _optional_text(content, "closing")
    _bounded_text(closing, what="pptx deck closing")
    slides_raw = _require_list(content, "slides", what="pptx deck")
    if len(slides_raw) > MAX_PPTX_SLIDES:
        raise DocArtifactError(
            f"pptx: too many slides ({len(slides_raw)} > {MAX_PPTX_SLIDES})"
        )
    slides: list[dict[str, Any]] = []
    for index, slide in enumerate(slides_raw):
        if not isinstance(slide, Mapping):
            raise DocArtifactError(f"pptx slide {index}: must be an object")
        slide_title = _require_text(
            slide, "title", what=f"pptx slide {index}"
        )
        _bounded_text(slide_title, what=f"pptx slide {index} title")
        bullets_raw = slide.get("bullets", [])
        body = _optional_text(slide, "body")
        if bullets_raw and body:
            raise DocArtifactError(
                f"pptx slide {index}: give either 'bullets' or 'body', "
                "not both"
            )
        bullets: list[str] = []
        if bullets_raw:
            if not isinstance(bullets_raw, list):
                raise DocArtifactError(
                    f"pptx slide {index}: 'bullets' must be a list of strings"
                )
            if len(bullets_raw) > MAX_PPTX_BULLETS:
                raise DocArtifactError(
                    f"pptx slide {index}: too many bullets "
                    f"({len(bullets_raw)} > {MAX_PPTX_BULLETS})"
                )
            bullets = [
                _bounded_text(str(item or ""),
                              what=f"pptx slide {index} bullet")
                for item in bullets_raw
            ]
            if not any(bullets):
                raise DocArtifactError(
                    f"pptx slide {index}: 'bullets' must not be all empty"
                )
        _bounded_text(body, what=f"pptx slide {index} body")
        if not bullets and not body:
            raise DocArtifactError(
                f"pptx slide {index}: needs 'bullets' or 'body'"
            )
        slides.append({
            "title": slide_title,
            "bullets": bullets,
            "body": body,
        })
    return {
        "title": title,
        "subtitle": subtitle,
        "closing": closing,
        "slides": slides,
    }


def build_pptx_bytes(content: Mapping[str, Any]) -> tuple[bytes, dict[str, Any]]:
    """Build a .pptx in memory; returns (bytes, structural report)."""
    spec = _validate_pptx_content(content)
    presentation = PptxPresentation()
    title_layout = presentation.slide_layouts[0]
    content_layout = presentation.slide_layouts[1]
    title_only_layout = presentation.slide_layouts[5]

    title_slide = presentation.slides.add_slide(title_layout)
    title_slide.shapes.title.text = spec["title"]
    if spec["subtitle"]:
        title_slide.placeholders[1].text = spec["subtitle"]

    for slide in spec["slides"]:
        content_slide = presentation.slides.add_slide(content_layout)
        content_slide.shapes.title.text = slide["title"]
        body_shape = content_slide.placeholders[1]
        text_frame = body_shape.text_frame
        text_frame.clear()
        if slide["bullets"]:
            for position, bullet in enumerate(slide["bullets"]):
                paragraph = (
                    text_frame.paragraphs[0]
                    if position == 0
                    else text_frame.add_paragraph()
                )
                paragraph.text = bullet
                paragraph.level = 0
        else:
            text_frame.paragraphs[0].text = slide["body"]

    if spec["closing"]:
        closing_slide = presentation.slides.add_slide(title_only_layout)
        closing_slide.shapes.title.text = spec["closing"]

    slide_count = 1 + len(spec["slides"]) + (1 if spec["closing"] else 0)
    import io
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue(), {
        "title": spec["title"],
        "slide_count": slide_count,
        "content_slides": len(spec["slides"]),
    }


def write_pptx(
    content: Mapping[str, Any],
    output_dir: str | Path,
    output_name: str,
) -> GeneratedArtifact:
    """Validate, build, atomically write, and read-back-verify a .pptx."""
    name = _validate_output_name(output_name, ".pptx")
    data, report = build_pptx_bytes(content)
    target = _resolve_target(output_dir, name)
    _atomic_write_bytes(target, data)
    verify_pptx(target, report)
    return GeneratedArtifact(target, report=report, byte_size=len(data))


def verify_pptx(path: str | Path, expected: Mapping[str, Any]) -> dict[str, Any]:
    """Open a .pptx with python-pptx and check the slide count matches."""
    source = Path(path)
    try:
        presentation = PptxPresentation(str(source))
        slide_count = len(presentation.slides._sldIdLst)
        titles = [
            shape.text.strip()
            for slide in presentation.slides
            for shape in slide.shapes
            if shape.has_text_frame and shape.text.strip()
        ]
    except (zipfile.BadZipFile, OSError, ValueError, KeyError,
            TypeError, AttributeError,
            PptxPackageNotFoundError) as exc:
        raise DocArtifactError(
            f"{source} is not a readable .pptx: {type(exc).__name__}: {exc}"
        ) from exc
    observed = {"slide_count": slide_count}
    if slide_count != int(expected.get("slide_count", -1)):
        raise DocArtifactError(
            f"pptx verification failed for {source}: expected "
            f"{expected.get('slide_count')} slides, found {slide_count}"
        )
    expected_title = str(expected.get("title") or "")
    if expected_title and not any(expected_title in text for text in titles):
        raise DocArtifactError(
            f"pptx verification failed for {source}: deck title "
            f"{expected_title!r} not found on any slide"
        )
    return observed


# ---------------------------------------------------------------------------
# Markdown -> PDF (stdlib-only). No PDF library is pinned in the repository,
# so this module ships a small, honest writer: base-14 Type1 fonts
# (Helvetica / Helvetica-Bold / Courier), uncompressed content streams so
# the bytes stay inspectable, and an explicit failure for text the WinAnsi
# encoding cannot represent (CJK and friends -> use doc.generate_docx).
# ---------------------------------------------------------------------------

_PDF_PAGE_WIDTH = 595.28   # A4
_PDF_PAGE_HEIGHT = 841.89  # A4
_PDF_MARGIN_X = 56.7        # 2 cm
_PDF_MARGIN_TOP = 72.0
_PDF_MARGIN_BOTTOM = 72.0
_PDF_TEXT_WIDTH = _PDF_PAGE_WIDTH - 2 * _PDF_MARGIN_X

_PDF_NARROW_CHARS = set("ilI1!|;:,.'`\"()[]{}")
_PDF_WIDE_CHARS = set("mwMW")


def _pdf_glyph_width(char: str) -> float:
    """Conservative Helvetica advance width in 1/1000 em (over-estimates)."""
    if char == " ":
        return 278.0
    if char in _PDF_NARROW_CHARS:
        return 333.0
    if char in _PDF_WIDE_CHARS:
        return 833.0
    if "0" <= char <= "9":
        return 556.0
    if char.isupper():
        return 700.0
    if char.islower():
        return 590.0
    return 620.0


def _pdf_text_width(text: str, size: float) -> float:
    return sum(_pdf_glyph_width(char) for char in text) * size / 1000.0 * 1.08


def _pdf_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    )


def _encode_winansi(text: str, *, what: str) -> bytes:
    try:
        return text.encode("cp1252")
    except UnicodeEncodeError as exc:
        bad = text[exc.start:exc.end]
        code = f"U+{ord(bad[0]):04X}" if bad else "U+????"
        raise DocArtifactError(
            f"{what}: character {bad!r} ({code}) is not representable in "
            "the PDF WinAnsi encoding — use doc.generate_docx for CJK or "
            "other non-Latin text"
        ) from exc


def _inline_runs(text: str) -> list[tuple[str, bool]]:
    """Split 'a **b** c' into [(text, bold)] runs."""
    runs: list[tuple[str, bool]] = []
    pattern = re.compile(r"\*\*(.+?)\*\*")
    position = 0
    for match in pattern.finditer(text):
        if match.start() > position:
            runs.append((text[position:match.start()], False))
        runs.append((match.group(1), True))
        position = match.end()
    if position < len(text):
        runs.append((text[position:], False))
    return [(part, bold) for part, bold in runs if part]


def _parse_markdown(text: str) -> list[tuple]:
    """Parse a documented Markdown subset into layout blocks."""
    if not isinstance(text, str) or not text.strip():
        raise DocArtifactError("pdf 'markdown' must be a non-empty string")
    if len(text) > MAX_MARKDOWN_CHARS:
        raise DocArtifactError(
            f"pdf markdown is too long ({len(text)} > {MAX_MARKDOWN_CHARS})"
        )
    lines = text.splitlines()
    blocks: list[tuple] = []
    index = 0
    total = len(lines)

    def is_special(stripped: str) -> bool:
        return (
            not stripped
            or stripped.startswith("```")
            or re.match(r"^#{1,3}\s+", stripped) is not None
            or stripped in ("---", "***", "___")
            or stripped.startswith("|")
            or re.match(r"^\d+\.\s+", stripped) is not None
            or re.match(r"^[-*]\s+", stripped) is not None
        )

    while index < total:
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        if stripped.startswith("```"):
            index += 1
            code_lines: list[str] = []
            while index < total and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index].rstrip("\n"))
                index += 1
            if index >= total:
                raise DocArtifactError(
                    "pdf markdown: code fence opened but never closed"
                )
            index += 1
            blocks.append(("code", code_lines))
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if heading:
            blocks.append(("heading", len(heading.group(1)),
                            heading.group(2).strip()))
            index += 1
            continue
        if stripped in ("---", "***", "___"):
            blocks.append(("rule",))
            index += 1
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            table_lines: list[str] = []
            start_line = index + 1
            while index < total:
                candidate = lines[index].strip()
                if candidate.startswith("|") and candidate.endswith("|"):
                    table_lines.append(candidate)
                    index += 1
                else:
                    break
            blocks.append(_parse_markdown_table(table_lines, start_line))
            continue
        numbered = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if numbered:
            items: list[tuple[int, str]] = []
            while index < total:
                item = re.match(r"^(\d+)\.\s+(.*)$", lines[index].strip())
                if item is None:
                    break
                items.append((int(item.group(1)), item.group(2).strip()))
                index += 1
            blocks.append(("numbered", items))
            continue
        if re.match(r"^[-*]\s+", stripped):
            items_text: list[str] = []
            while index < total:
                item = re.match(r"^[-*]\s+(.*)$", lines[index].strip())
                if item is None:
                    break
                items_text.append(item.group(1).strip())
                index += 1
            blocks.append(("bullets", items_text))
            continue
        paragraph_lines: list[str] = []
        while index < total and not is_special(lines[index].strip()):
            paragraph_lines.append(lines[index].strip())
            index += 1
        blocks.append(("paragraph", " ".join(paragraph_lines)))
    if not blocks:
        raise DocArtifactError("pdf markdown has no renderable content")
    return blocks


def _parse_markdown_table(table_lines: list[str], start_line: int) -> tuple:
    def cells(row: str) -> list[str]:
        return [cell.strip() for cell in row.strip().strip("|").split("|")]

    if len(table_lines) < 2:
        raise DocArtifactError(
            f"pdf markdown table at line {start_line}: a table needs a "
            "header row and a separator row (| --- | --- |)"
        )
    separator = cells(table_lines[1])
    if not separator or not all(
        re.fullmatch(r":?-+:?", cell) for cell in separator
    ):
        raise DocArtifactError(
            f"pdf markdown table at line {start_line}: second row must be "
            "a separator row like | --- | --- |"
        )
    headers = cells(table_lines[0])
    width = len(headers)
    rows: list[list[str]] = []
    for line_number, row in enumerate(table_lines[2:], start=start_line + 2):
        row_cells = cells(row)
        if len(row_cells) != width:
            raise DocArtifactError(
                f"pdf markdown table at line {line_number}: has "
                f"{len(row_cells)} cells but the header has {width}"
            )
        rows.append(row_cells)
    return ("table", headers, rows)


class _PdfContent:
    """One page's content-stream operations."""

    def __init__(self) -> None:
        self.ops: list[str] = []

    def text_runs(
        self, x: float, y: float, segments: list[tuple[str, str]], size: float
    ) -> None:
        """Draw [(font_key, text)] segments left to right from (x, y)."""
        self.ops.append(f"BT {x:.2f} {y:.2f} Td")
        for font_key, text in segments:
            self.ops.append(f"/{font_key} {size:g} Tf ({_pdf_escape(text)}) Tj")
        self.ops.append("ET")

    def gray_text(
        self, x: float, y: float, font_key: str, size: float, text: str,
        gray: float,
    ) -> None:
        self.ops.append(f"{gray:g} g")
        self.text_runs(x, y, [(font_key, text)], size)
        self.ops.append("0 g")

    def rect_fill(
        self, x: float, y: float, width: float, height: float, gray: float
    ) -> None:
        self.ops.append(
            f"{gray:g} g {x:.2f} {y:.2f} {width:.2f} {height:.2f} re f 0 g"
        )

    def rect_stroke(
        self, x: float, y: float, width: float, height: float
    ) -> None:
        self.ops.append(
            f"{x:.2f} {y:.2f} {width:.2f} {height:.2f} re S"
        )

    def hline(self, x1: float, x2: float, y: float) -> None:
        self.ops.append(f"{x1:.2f} {y:.2f} m {x2:.2f} {y:.2f} l S")


def _merge_run_words(
    line: list[tuple[str, bool]],
) -> list[tuple[str, str]]:
    """[(word, bold)] -> [(font_key, 'w1 w2 ...')] segments."""
    segments: list[list[str]] = []
    for word, bold in line:
        font_key = "F2" if bold else "F1"
        if segments and segments[-1][0] == font_key:
            segments[-1][1] += " " + word
        else:
            segments.append([font_key, word])
    return [(font_key, text) for font_key, text in segments]


def _wrap_runs(
    runs: list[tuple[str, bool]], size: float, width: float
) -> list[list[tuple[str, bool]]]:
    """Greedy word wrap; returns lines of [(word, bold)]."""
    words: list[tuple[str, bool]] = []
    for text, bold in runs:
        for word in text.split(" "):
            if word:
                words.append((word, bold))
    if not words:
        return []
    space_width = _pdf_text_width(" ", size)
    lines: list[list[tuple[str, bool]]] = []
    current: list[tuple[str, bool]] = []
    current_width = 0.0
    for word, bold in words:
        word_width = _pdf_text_width(word, size)
        if current and current_width + space_width + word_width > width:
            lines.append(current)
            current = []
            current_width = 0.0
        if current:
            current_width += space_width
        current.append((word, bold))
        current_width += word_width
    if current:
        lines.append(current)
    return lines


class _PdfLayout:
    def __init__(self) -> None:
        self.pages: list[_PdfContent] = [_PdfContent()]
        self.y = _PDF_PAGE_HEIGHT - _PDF_MARGIN_TOP

    def _page(self) -> _PdfContent:
        return self.pages[-1]

    def _new_page(self) -> None:
        self.pages.append(_PdfContent())
        self.y = _PDF_PAGE_HEIGHT - _PDF_MARGIN_TOP

    def _need(self, height: float) -> None:
        if self.y - height < _PDF_MARGIN_BOTTOM:
            self._new_page()

    def _draw_wrapped_lines(
        self, x: float, lines: list[list[tuple[str, bool]]], size: float
    ) -> None:
        line_height = size * 1.35
        for line in lines:
            self._need(line_height)
            self._page().text_runs(
                x, self.y - size, _merge_run_words(line), size
            )
            self.y -= line_height

    def heading(self, level: int, text: str) -> None:
        size = {1: 18.0, 2: 14.0, 3: 12.0}[level]
        space_before = {1: 16.0, 2: 12.0, 3: 10.0}[level]
        runs = _inline_runs(text)
        lines = _wrap_runs(runs, size, _PDF_TEXT_WIDTH)
        if not lines:
            return
        self._need(space_before + len(lines) * size * 1.35)
        self.y -= space_before
        for line in lines:
            self._page().text_runs(
                _PDF_MARGIN_X, self.y - size, _merge_run_words(line), size
            )
            self.y -= size * 1.35
        self.y -= 4.0

    def paragraph(self, text: str) -> None:
        lines = _wrap_runs(_inline_runs(text), 11.0, _PDF_TEXT_WIDTH)
        self._draw_wrapped_lines(_PDF_MARGIN_X, lines, 11.0)
        self.y -= 4.0

    def bullet_list(self, items: list[str]) -> None:
        for item in items:
            lines = _wrap_runs(_inline_runs(item), 11.0, _PDF_TEXT_WIDTH - 20)
            if not lines:
                continue
            line_height = 11.0 * 1.35
            self._need(line_height)
            self._page().text_runs(
                _PDF_MARGIN_X, self.y - 11.0, [("F1", "\u2022")], 11.0
            )
            for line in lines:
                self._need(line_height)
                self._page().text_runs(
                    _PDF_MARGIN_X + 18, self.y - 11.0,
                    _merge_run_words(line), 11.0,
                )
                self.y -= line_height
        self.y -= 4.0

    def numbered_list(self, items: list[tuple[int, str]]) -> None:
        for number, item in items:
            lines = _wrap_runs(_inline_runs(item), 11.0, _PDF_TEXT_WIDTH - 24)
            if not lines:
                continue
            line_height = 11.0 * 1.35
            self._need(line_height)
            marker = f"{number}."
            self._page().text_runs(
                _PDF_MARGIN_X, self.y - 11.0, [("F1", marker)], 11.0
            )
            for line in lines:
                self._need(line_height)
                self._page().text_runs(
                    _PDF_MARGIN_X + 22, self.y - 11.0,
                    _merge_run_words(line), 11.0,
                )
                self.y -= line_height
        self.y -= 4.0

    def code_block(self, code_lines: list[str]) -> None:
        size = 9.5
        line_height = size * 1.4
        height = max(1, len(code_lines)) * line_height + 10.0
        self._need(height)
        top = self.y
        self._page().rect_fill(
            _PDF_MARGIN_X, top - height, _PDF_TEXT_WIDTH, height, 0.94
        )
        cursor = top - 5.0 - size
        for raw in code_lines or [""]:
            self._page().text_runs(
                _PDF_MARGIN_X + 6, cursor, [("F3", raw or " ")], size
            )
            cursor -= line_height
        self.y = top - height - 6.0

    def rule(self) -> None:
        self._need(16.0)
        self.y -= 8.0
        self._page().hline(
            _PDF_MARGIN_X, _PDF_MARGIN_X + _PDF_TEXT_WIDTH, self.y
        )
        self.y -= 8.0

    def _table_row_plan(
        self, cells: Sequence[str], col_widths: Sequence[float], bold: bool
    ) -> tuple[list[list[list[tuple[str, bool]]]], float]:
        size = 10.0
        pad = 5.0
        wrapped: list[list[list[tuple[str, bool]]]] = []
        for cell, width in zip(cells, col_widths):
            wrapped.append(_wrap_runs([(cell, bold)], size, width - 2 * pad))
        line_count = max([len(lines) for lines in wrapped] + [1])
        return wrapped, line_count * size * 1.35 + 6.0

    def _draw_table_row(
        self,
        wrapped: list[list[list[tuple[str, bool]]]],
        col_widths: Sequence[float],
        height: float,
        bold: bool,
    ) -> None:
        size = 10.0
        pad = 5.0
        line_height = size * 1.35
        top = self.y
        cursor_x = _PDF_MARGIN_X
        for cell_lines, width in zip(wrapped, col_widths):
            self._page().rect_stroke(cursor_x, top - height, width, height)
            text_y = top - 3.0 - size
            for line in cell_lines:
                self._page().text_runs(
                    cursor_x + pad, text_y, _merge_run_words(line), size
                )
                text_y -= line_height
            cursor_x += width
        self.y = top - height

    def table(self, headers: list[str], rows: list[list[str]]) -> None:
        pad = 5.0
        natural: list[float] = []
        for column, header in enumerate(headers):
            width = _pdf_text_width(header, 10.0)
            for row in rows:
                width = max(width, _pdf_text_width(row[column], 10.0))
            natural.append(width + 2 * pad)
        total = sum(natural)
        if total > _PDF_TEXT_WIDTH:
            scale = _PDF_TEXT_WIDTH / total
            col_widths = [width * scale for width in natural]
        else:
            col_widths = natural
        header_wrapped, header_height = self._table_row_plan(
            headers, col_widths, True
        )
        self._need(header_height)
        self._draw_table_row(header_wrapped, col_widths, header_height, True)
        for row in rows:
            wrapped, height = self._table_row_plan(row, col_widths, False)
            if self.y - height < _PDF_MARGIN_BOTTOM:
                self._new_page()
                self._draw_table_row(
                    header_wrapped, col_widths, header_height, True
                )
            else:
                self._need(height)
            self._draw_table_row(wrapped, col_widths, height, False)
        self.y -= 6.0


def _render_markdown_to_layout(blocks: list[tuple]) -> _PdfLayout:
    # Fail fast on unrepresentable characters before any layout work.
    for block in blocks:
        kind = block[0]
        texts: list[str] = []
        if kind == "heading":
            texts.append(block[2])
        elif kind == "paragraph":
            texts.append(block[1])
        elif kind == "bullets":
            texts.extend(block[1])
        elif kind == "numbered":
            texts.extend(item for _, item in block[1])
        elif kind == "code":
            texts.extend(block[1])
        elif kind == "table":
            texts.extend(block[1])
            for row in block[2]:
                texts.extend(row)
        for text in texts:
            for run_text, _bold in _inline_runs(text):
                _encode_winansi(run_text, what="pdf markdown")
            _encode_winansi(text, what="pdf markdown")
    layout = _PdfLayout()
    for block in blocks:
        kind = block[0]
        if kind == "heading":
            layout.heading(block[1], block[2])
        elif kind == "paragraph":
            layout.paragraph(block[1])
        elif kind == "bullets":
            layout.bullet_list(block[1])
        elif kind == "numbered":
            layout.numbered_list(block[1])
        elif kind == "code":
            layout.code_block(block[1])
        elif kind == "table":
            layout.table(block[1], block[2])
        elif kind == "rule":
            layout.rule()
    # Footers: page numbers, drawn after layout so the total is known.
    for page_number, page in enumerate(layout.pages, start=1):
        label = f"{page_number} / {len(layout.pages)}"
        label_width = _pdf_text_width(label, 9.0)
        page.gray_text(
            (_PDF_PAGE_WIDTH - label_width) / 2,
            _PDF_MARGIN_BOTTOM - 28.0,
            "F1",
            9.0,
            label,
            0.45,
        )
    return layout


def _assemble_pdf(layout: _PdfLayout, title: str) -> bytes:
    page_count = len(layout.pages)
    # Object numbering, 1-based:
    #   1: catalog, 2: pages,
    #   per page i: page object 3+2i, content object 4+2i,
    #   then /F1 /F2 /F3 font objects, then the info object.
    font_f1 = 3 + 2 * page_count
    font_f2 = font_f1 + 1
    font_f3 = font_f1 + 2
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(page_count))
    objects.append(
        f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode(
            "ascii"
        )
    )
    for page in layout.pages:
        content = "\n".join(page.ops).encode("cp1252")
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R "
                f"/MediaBox [0 0 {_PDF_PAGE_WIDTH:.2f} {_PDF_PAGE_HEIGHT:.2f}] "
                f"/Resources << /Font << /F1 {font_f1} 0 R "
                f"/F2 {font_f2} 0 R /F3 {font_f3} 0 R >> >> "
                f"/Contents {len(objects) + 2} 0 R >>"
            ).encode("ascii")
        )
        objects.append(
            b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n"
            + content + b"\nendstream"
        )
    for base in (b"/Helvetica", b"/Helvetica-Bold", b"/Courier"):
        objects.append(
            b"<< /Type /Font /Subtype /Type1 /BaseFont " + base + b" >>"
        )
    title_bytes = _encode_winansi(_pdf_escape(title), what="pdf title")
    objects.append(
        b"<< /Title (" + title_bytes + b") /Creator (ZN doc_artifacts R8) >>"
    )
    info_number = len(objects)  # 1-based

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for position, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{position} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R "
        f"/Info {info_number} 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)


def build_pdf_bytes_from_markdown(
    markdown: str, *, title: str | None = None
) -> tuple[bytes, dict[str, Any]]:
    """Render Markdown to PDF bytes; returns (bytes, structural report)."""
    blocks = _parse_markdown(markdown)
    resolved_title = str(title or "").strip() or "ZN document"
    _bounded_text(resolved_title, what="pdf title", limit=200)
    layout = _render_markdown_to_layout(blocks)
    data = _assemble_pdf(layout, resolved_title)
    return data, {
        "title": resolved_title,
        "page_count": len(layout.pages),
        "block_count": len(blocks),
    }


def write_pdf_from_markdown(
    markdown: str,
    output_dir: str | Path,
    output_name: str,
    *,
    title: str | None = None,
) -> GeneratedArtifact:
    """Validate, render, atomically write, and read-back-verify a PDF."""
    name = _validate_output_name(output_name, ".pdf")
    data, report = build_pdf_bytes_from_markdown(markdown, title=title)
    target = _resolve_target(output_dir, name)
    _atomic_write_bytes(target, data)
    verify_pdf(target, report)
    return GeneratedArtifact(target, report=report, byte_size=len(data))


def verify_pdf(path: str | Path, expected: Mapping[str, Any]) -> dict[str, Any]:
    """Check a PDF opens (magic + xref) and its page count matches."""
    source = Path(path)
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise DocArtifactError(
            f"{source} is not a readable PDF: {exc}"
        ) from exc
    if not data.startswith(b"%PDF-"):
        raise DocArtifactError(
            f"{source} is not a PDF: missing %PDF- magic header"
        )
    match = re.search(rb"/Count\s+(\d+)", data)
    if match:
        page_count = int(match.group(1))
    else:
        page_count = len(re.findall(rb"/Type\s*/Page(?!s)", data))
    if page_count <= 0:
        raise DocArtifactError(
            f"{source} is not a readable PDF: no page objects found"
        )
    if b"%%EOF" not in data[-128:]:
        raise DocArtifactError(
            f"{source} looks truncated: missing %%EOF trailer"
        )
    observed = {"page_count": page_count, "byte_size": len(data)}
    if page_count != int(expected.get("page_count", -1)):
        raise DocArtifactError(
            f"pdf verification failed for {source}: expected "
            f"{expected.get('page_count')} pages, found {page_count}"
        )
    return observed


# ---------------------------------------------------------------------------
# Standard templates: structure and styling; content supplies the data.
# ---------------------------------------------------------------------------


def render_docx_template(
    template: str, template_data: Mapping[str, Any]
) -> dict[str, Any]:
    """Render the named docx template with user data into a docx content spec."""
    name = str(template or "").strip().lower()
    if name not in DOCX_TEMPLATE_NAMES:
        raise DocArtifactError(
            f"unknown docx template {template!r}: known templates are "
            f"{', '.join(DOCX_TEMPLATE_NAMES)}"
        )
    if not isinstance(template_data, Mapping):
        raise DocArtifactError("docx 'template_data' must be an object")
    data = dict(template_data)
    # The 'report' template: title page metadata, an optional summary
    # section up front, then the user's sections, then styled tables.
    return {
        "title": data.get("title"),
        "author": data.get("author"),
        "summary": data.get("summary"),
        "sections": data.get("sections", []),
        "tables": data.get("tables", []),
    }


def render_xlsx_template(
    template: str, template_data: Mapping[str, Any]
) -> dict[str, Any]:
    """Render the named xlsx template with user data into an xlsx content spec."""
    name = str(template or "").strip().lower()
    if name not in XLSX_TEMPLATE_NAMES:
        raise DocArtifactError(
            f"unknown xlsx template {template!r}: known templates are "
            f"{', '.join(XLSX_TEMPLATE_NAMES)}"
        )
    if not isinstance(template_data, Mapping):
        raise DocArtifactError("xlsx 'template_data' must be an object")
    # The 'data_table' template: bold header row, frozen panes, autofilter,
    # and auto-sized columns applied by the builder.
    return {"sheets": template_data.get("sheets", [])}


def render_pptx_template(
    template: str, template_data: Mapping[str, Any]
) -> dict[str, Any]:
    """Render the named pptx template with user data into a pptx content spec."""
    name = str(template or "").strip().lower()
    if name not in PPTX_TEMPLATE_NAMES:
        raise DocArtifactError(
            f"unknown pptx template {template!r}: known templates are "
            f"{', '.join(PPTX_TEMPLATE_NAMES)}"
        )
    if not isinstance(template_data, Mapping):
        raise DocArtifactError("pptx 'template_data' must be an object")
    # The 'briefing_deck' template: title slide, one content slide per
    # entry, and an optional closing slide.
    return {
        "title": template_data.get("title"),
        "subtitle": template_data.get("subtitle"),
        "slides": template_data.get("slides", []),
        "closing": template_data.get("closing"),
    }


# ---------------------------------------------------------------------------
# Fabric/Body attachment (R1/R5 shape: approval-gated writes)
# ---------------------------------------------------------------------------


def _body_kind(action_id: str) -> str:
    digest = hashlib.sha256(action_id.encode("utf-8")).hexdigest()[:24]
    return f"zn_rest_write_{digest}"


def _require_output_dir(args: Mapping[str, Any], default: str | None) -> str:
    raw = args.get("output_dir") or default
    if not str(raw or "").strip():
        raise DocArtifactError(
            "no output directory: pass 'output_dir' or attach with one"
        )
    return str(raw)


class DocArtifactAttachment:
    """Handle returned by :func:`attach_doc_artifact_tools`; call detach()."""

    def __init__(
        self,
        fabric: ActionFabricRegistry,
        body: NativeBody,
        kinds: list[str],
        action_ids: list[str],
    ) -> None:
        self._fabric = fabric
        self._body = body
        self._kinds = kinds
        self._action_ids = action_ids
        self._detached = False

    @property
    def action_ids(self) -> tuple[str, ...]:
        return tuple(self._action_ids)

    def detach(self) -> None:
        if self._detached:
            return
        self._detached = True
        for action_id in self._action_ids:
            self._fabric.unregister(action_id)
        for kind in self._kinds:
            self._body.unregister_external_write_handler(kind)


def _artifact_result_data(
    tool: str, artifact: GeneratedArtifact, verification: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "provider_id": PROVIDER_ID,
        "tool": tool,
        "path": str(artifact.path),
        "byte_size": artifact.byte_size,
        "verification": {
            "format": tool.rsplit(".", 1)[-1],
            "expected": dict(artifact.report),
            "observed": dict(verification),
        },
        "untrusted_external_evidence": False,
    }


def _output_probe(default_output_dir: str | None):
    def probe(item) -> ActionAvailability:
        if default_output_dir and Path(default_output_dir).is_dir():
            return ActionAvailability(
                item.action_id,
                "available",
                reason="document output directory configured",
                evidence={"output_dir": default_output_dir},
            )
        return ActionAvailability(
            item.action_id,
            "unavailable",
            reason=(
                "no output directory configured: attach with output_dir "
                "or pass 'output_dir' per call"
            ),
        )

    return probe


def attach_doc_artifact_tools(
    fabric: ActionFabricRegistry,
    body: NativeBody,
    *,
    output_dir: str | None = None,
) -> DocArtifactAttachment:
    """Attach the four document-generation tools to a Body/Fabric pair.

    All four are approval-gated writes (``approval:production_change``):
    the runtime opens an approval card before dispatch, and a denied or
    undecided generation never touches the disk. Each handler validates
    its inputs, writes atomically, and read-back-verifies the file before
    reporting success.
    """
    prepared: list[tuple[ActionDescriptor, Callable]] = []

    # -- .docx -----------------------------------------------------------
    def call_generate_docx(action: BodyAction, started: str) -> BodyActionResult:
        output = _require_output_dir(action.args, output_dir)
        name = _require_text(
            action.args, "output_name", what="doc.generate_docx"
        )
        template = str(action.args.get("template") or "report")
        template_data = action.args.get("template_data")
        if not isinstance(template_data, Mapping):
            raise DocArtifactError(
                "doc.generate_docx requires 'template_data' to be an object"
            )
        content = render_docx_template(template, template_data)
        artifact = write_docx(content, output, name)
        verification = verify_docx(artifact.path, artifact.report)
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=json.dumps(
                _artifact_result_data("generate_docx", artifact, verification),
                ensure_ascii=False,
                indent=2,
            ),
            data=_artifact_result_data(
                "generate_docx", artifact, verification
            ),
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    prepared.append((
        ActionDescriptor(
            action_id=DOCX_ACTION_ID,
            provider=PROVIDER_ID,
            description=(
                "Generate a .docx document from structured content "
                "(title, sections, tables) using the 'report' template. "
                "Requires user approval before dispatch."
            ),
            body_action_kind=_body_kind(DOCX_ACTION_ID),
            input_schema={
                "type": "object",
                "required": ["output_name", "template_data"],
                "properties": {
                    "output_name": {
                        "type": "string",
                        "description": (
                            "Plain filename ending in .docx, written under "
                            "output_dir"
                        ),
                    },
                    "output_dir": {
                        "type": "string",
                        "description": (
                            "Destination directory; defaults to the attached one"
                        ),
                    },
                    "template": {
                        "type": "string",
                        "description": "Template name; currently 'report'",
                    },
                    "template_data": {
                        "type": "object",
                        "description": (
                            "Report data: title (required), author, summary, "
                            "sections [{heading, paragraphs}], "
                            "tables [{caption, headers, rows}]"
                        ),
                    },
                },
                "additionalProperties": False,
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="user_documents",
            preconditions=("user approved the write via an approval card",),
            postconditions=(
                "the .docx is readable back with matching structure",
            ),
            verification=(
                "independent re-read of the file with python-docx",
            ),
            reversibility="delete the generated file",
            replay_semantics="verify_before_replay",
            tags=(
                "documents",
                "docx",
                "doc_artifact_write",
                f"approval:{APPROVAL_KIND}",
            ),
        ),
        call_generate_docx,
    ))

    # -- .xlsx -----------------------------------------------------------
    def call_generate_xlsx(action: BodyAction, started: str) -> BodyActionResult:
        output = _require_output_dir(action.args, output_dir)
        name = _require_text(
            action.args, "output_name", what="doc.generate_xlsx"
        )
        template = str(action.args.get("template") or "data_table")
        template_data = action.args.get("template_data")
        if not isinstance(template_data, Mapping):
            raise DocArtifactError(
                "doc.generate_xlsx requires 'template_data' to be an object"
            )
        content = render_xlsx_template(template, template_data)
        artifact = write_xlsx(content, output, name)
        verification = verify_xlsx(artifact.path, artifact.report)
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=json.dumps(
                _artifact_result_data("generate_xlsx", artifact, verification),
                ensure_ascii=False,
                indent=2,
            ),
            data=_artifact_result_data(
                "generate_xlsx", artifact, verification
            ),
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    prepared.append((
        ActionDescriptor(
            action_id=XLSX_ACTION_ID,
            provider=PROVIDER_ID,
            description=(
                "Generate an .xlsx workbook from structured sheets "
                "(name, headers, rows) using the 'data_table' template. "
                "Requires user approval before dispatch."
            ),
            body_action_kind=_body_kind(XLSX_ACTION_ID),
            input_schema={
                "type": "object",
                "required": ["output_name", "template_data"],
                "properties": {
                    "output_name": {
                        "type": "string",
                        "description": (
                            "Plain filename ending in .xlsx, written under "
                            "output_dir"
                        ),
                    },
                    "output_dir": {
                        "type": "string",
                        "description": (
                            "Destination directory; defaults to the attached one"
                        ),
                    },
                    "template": {
                        "type": "string",
                        "description": "Template name; currently 'data_table'",
                    },
                    "template_data": {
                        "type": "object",
                        "description": (
                            "Table data: sheets [{name, headers, rows}]"
                        ),
                    },
                },
                "additionalProperties": False,
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="user_documents",
            preconditions=("user approved the write via an approval card",),
            postconditions=(
                "the .xlsx is readable back with matching sheets",
            ),
            verification=(
                "independent re-read of the file with openpyxl",
            ),
            reversibility="delete the generated file",
            replay_semantics="verify_before_replay",
            tags=(
                "documents",
                "xlsx",
                "doc_artifact_write",
                f"approval:{APPROVAL_KIND}",
            ),
        ),
        call_generate_xlsx,
    ))

    # -- .pptx -----------------------------------------------------------
    def call_generate_pptx(action: BodyAction, started: str) -> BodyActionResult:
        output = _require_output_dir(action.args, output_dir)
        name = _require_text(
            action.args, "output_name", what="doc.generate_pptx"
        )
        template = str(action.args.get("template") or "briefing_deck")
        template_data = action.args.get("template_data")
        if not isinstance(template_data, Mapping):
            raise DocArtifactError(
                "doc.generate_pptx requires 'template_data' to be an object"
            )
        content = render_pptx_template(template, template_data)
        artifact = write_pptx(content, output, name)
        verification = verify_pptx(artifact.path, artifact.report)
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=json.dumps(
                _artifact_result_data("generate_pptx", artifact, verification),
                ensure_ascii=False,
                indent=2,
            ),
            data=_artifact_result_data(
                "generate_pptx", artifact, verification
            ),
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    prepared.append((
        ActionDescriptor(
            action_id=PPTX_ACTION_ID,
            provider=PROVIDER_ID,
            description=(
                "Generate a .pptx deck from structured slides "
                "(title, bullets or body) using the 'briefing_deck' "
                "template. Requires user approval before dispatch."
            ),
            body_action_kind=_body_kind(PPTX_ACTION_ID),
            input_schema={
                "type": "object",
                "required": ["output_name", "template_data"],
                "properties": {
                    "output_name": {
                        "type": "string",
                        "description": (
                            "Plain filename ending in .pptx, written under "
                            "output_dir"
                        ),
                    },
                    "output_dir": {
                        "type": "string",
                        "description": (
                            "Destination directory; defaults to the attached one"
                        ),
                    },
                    "template": {
                        "type": "string",
                        "description": (
                            "Template name; currently 'briefing_deck'"
                        ),
                    },
                    "template_data": {
                        "type": "object",
                        "description": (
                            "Deck data: title (required), subtitle, "
                            "slides [{title, bullets|body}], closing"
                        ),
                    },
                },
                "additionalProperties": False,
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="user_documents",
            preconditions=("user approved the write via an approval card",),
            postconditions=(
                "the .pptx is readable back with the expected slide count",
            ),
            verification=(
                "independent re-read of the file with python-pptx",
            ),
            reversibility="delete the generated file",
            replay_semantics="verify_before_replay",
            tags=(
                "documents",
                "pptx",
                "doc_artifact_write",
                f"approval:{APPROVAL_KIND}",
            ),
        ),
        call_generate_pptx,
    ))

    # -- PDF (Markdown -> PDF) --------------------------------------------
    def call_generate_pdf(action: BodyAction, started: str) -> BodyActionResult:
        output = _require_output_dir(action.args, output_dir)
        name = _require_text(
            action.args, "output_name", what="doc.generate_pdf"
        )
        markdown = action.args.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            raise DocArtifactError(
                "doc.generate_pdf requires 'markdown' to be a non-empty string"
            )
        title = action.args.get("title")
        artifact = write_pdf_from_markdown(
            markdown, output, name,
            title=str(title) if title is not None else None,
        )
        verification = verify_pdf(artifact.path, artifact.report)
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=json.dumps(
                _artifact_result_data("generate_pdf", artifact, verification),
                ensure_ascii=False,
                indent=2,
            ),
            data=_artifact_result_data(
                "generate_pdf", artifact, verification
            ),
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    prepared.append((
        ActionDescriptor(
            action_id=PDF_ACTION_ID,
            provider=PROVIDER_ID,
            description=(
                "Render Markdown to a PDF file with the stdlib-only writer "
                "(headings, paragraphs, lists, tables, code blocks). "
                "Latin-1/WinAnsi text only; CJK needs doc.generate_docx. "
                "Requires user approval before dispatch."
            ),
            body_action_kind=_body_kind(PDF_ACTION_ID),
            input_schema={
                "type": "object",
                "required": ["output_name", "markdown"],
                "properties": {
                    "output_name": {
                        "type": "string",
                        "description": (
                            "Plain filename ending in .pdf, written under "
                            "output_dir"
                        ),
                    },
                    "output_dir": {
                        "type": "string",
                        "description": (
                            "Destination directory; defaults to the attached one"
                        ),
                    },
                    "markdown": {
                        "type": "string",
                        "description": "Markdown source to render",
                    },
                    "title": {
                        "type": "string",
                        "description": "PDF document title metadata",
                    },
                },
                "additionalProperties": False,
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="user_documents",
            preconditions=("user approved the write via an approval card",),
            postconditions=(
                "the PDF is readable back with the expected page count",
            ),
            verification="independent re-read of the file bytes",
            reversibility="delete the generated file",
            replay_semantics="verify_before_replay",
            tags=(
                "documents",
                "pdf",
                "doc_artifact_write",
                f"approval:{APPROVAL_KIND}",
            ),
        ),
        call_generate_pdf,
    ))

    # -- registration with rollback ---------------------------------------
    registered: list[ActionDescriptor] = []
    attached_kinds: list[str] = []
    action_ids: list[str] = []
    try:
        for descriptor in [prepared_item[0] for prepared_item in prepared]:
            assert descriptor.body_action_kind is not None
            if descriptor.body_action_kind in body._external_write_handlers:
                raise ValueError("Body extension identifier collision")

        completed_identities: set[str] = set()
        probe = _output_probe(output_dir)

        for descriptor, handler in prepared:
            kind = descriptor.body_action_kind
            assert kind is not None

            def guarded(
                action: BodyAction,
                started: str,
                *,
                inner=handler,
                action_id=descriptor.action_id,
                tool=descriptor.action_id.split(".")[-1],
            ) -> BodyActionResult:
                identity = mcp_write_replay_identity(
                    provider_id=PROVIDER_ID,
                    tool_name=tool,
                    args=action.args,
                    event_id=action.event_id,
                )
                if identity in completed_identities:
                    raise RuntimeError(
                        "doc artifact write replay refused: this exact write "
                        "occurrence already completed; re-read the file "
                        "before retrying instead of redispatching"
                    )
                result = inner(action, started)
                completed_identities.add(identity)
                return result

            body.register_external_write_handler(kind, guarded)
            attached_kinds.append(kind)
            fabric.register(descriptor, availability_probe=probe)
            registered.append(descriptor)
            action_ids.append(descriptor.action_id)
    except Exception:
        for descriptor in registered:
            fabric.unregister(descriptor.action_id)
        for kind in attached_kinds:
            body.unregister_external_write_handler(kind)
        raise
    return DocArtifactAttachment(fabric, body, attached_kinds, action_ids)


# ---------------------------------------------------------------------------
# Runtime binding: approval scopes + postcondition verifiers
# ---------------------------------------------------------------------------


def _write_scope(action_id: str, default_output_dir: str | None):
    def resolver(args: Mapping[str, Any]) -> tuple[str, str, str]:
        output = str(args.get("output_dir") or default_output_dir or "")
        name = str(args.get("output_name") or "(no name)")
        target = f"{output}/{name}" if output else name
        return (
            "doc-artifact-file",
            target,
            f"generate {action_id} document {name!r} at {target}",
        )

    return resolver


def register_doc_artifacts_runtime(
    runtime: ActionExecutionRuntime,
    *,
    output_dir: str | None = None,
) -> None:
    """Bind approval scopes and postcondition verifiers.

    Canonical scopes keep an ``always_allow`` rule from blessing anything
    beyond the one output file; the verifiers re-read the generated file
    (magic/format check plus structural counts) so a Body success is never
    taken as proof of the effect.
    """
    verifiers: dict[str, Callable[[Path, Mapping[str, Any]], Mapping[str, Any]]] = {
        DOCX_ACTION_ID: verify_docx,
        XLSX_ACTION_ID: verify_xlsx,
        PPTX_ACTION_ID: verify_pptx,
        PDF_ACTION_ID: verify_pdf,
    }
    for action_id, verifier in verifiers.items():
        runtime.register_approval_scope(
            action_id, _write_scope(action_id, output_dir)
        )

        def observe(
            request: ActionRequest,
            result: BodyActionResult | None,
            *,
            _action_id=action_id,
            _verifier=verifier,
            _default_dir=output_dir,
        ) -> ActionObservation:
            data = dict((result.data or {}) if result is not None else {})
            args = dict(request.args or {})
            output = str(args.get("output_dir") or _default_dir or "")
            name = str(args.get("output_name") or "")
            observed: dict[str, Any] = {"path": f"{output}/{name}"}
            expected = ((data.get("verification") or {}).get("expected")) or {}
            try:
                target = _resolve_target(output, name) if name else None
                if target is not None and target.is_file():
                    observed["reread"] = dict(
                        _verifier(target, expected)
                    )
                    observed["byte_size"] = target.stat().st_size
            except DocArtifactError as exc:
                observed["reread_error"] = str(exc)
            return ActionObservation(
                _action_id, "doc_artifact_reread", data={**data, **observed}
            )

        def verify(
            request: ActionRequest,
            observation: ActionObservation,
            result: BodyActionResult | None,
            *,
            _action_id=action_id,
        ) -> ActionVerification:
            data = (observation.data or {})
            reread = data.get("reread")
            if isinstance(reread, dict) and reread:
                return ActionVerification(
                    "verified",
                    f"fresh re-read of the generated file at "
                    f"{data.get('path')} matches the expected structure",
                )
            return ActionVerification(
                "failed",
                f"fresh re-read of {data.get('path')} failed: "
                f"{data.get('reread_error', 'file missing or unreadable')}",
            )

        runtime.register_verification(
            action_id, observe=observe, verify=verify
        )
