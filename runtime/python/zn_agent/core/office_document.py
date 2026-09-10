from __future__ import annotations

"""Deterministic bounded DOCX inspection and run-aware copy mutation.

The model is intentionally absent from this module. It accepts one already-bound
source identity and one explicit normalized replacement date, mutates only a
standard WordprocessingML body/table-cell run span, reopens the package, and
proves source/destination invariants before reporting success.
"""

import hashlib
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterator
from xml.etree import ElementTree as ET

from docx import Document
from docx.document import Document as _Document
from docx.text.paragraph import Paragraph

from .file_identity import compare_file_identities, observe_file_identity

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_PARAGRAPHS = 512
MAX_VISIBLE_CHARS = 128 * 1024

_DATE = r"(?:\d{4}年\d{1,2}月\d{1,2}日|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})"
PAYMENT_DATE_RE = re.compile(rf"(?P<label>付款日期\s*[:：]?\s*)(?P<date>{_DATE})")

_UNSUPPORTED_PART_PREFIXES = (
    "word/embeddings/",
    "word/activeX/",
    "word/diagrams/",
    "word/charts/",
)
_UNSUPPORTED_PARTS = {
    "word/vbaProject.bin",
    "word/comments.xml",
    "word/footnotes.xml",
    "word/endnotes.xml",
}
_UNSUPPORTED_XML_LOCALNAMES = {
    "altChunk",
    "commentRangeStart",
    "commentRangeEnd",
    "commentReference",
    "del",
    "drawing",
    "fldChar",
    "fldSimple",
    "gridSpan",
    "ins",
    "instrText",
    "object",
    "pict",
    "sdt",
    "smartTag",
    "txbxContent",
    "vMerge",
}


def _block(identity: dict[str, Any], detail: str) -> dict[str, Any]:
    return {
        "ready": False,
        "blocker": "unsupported_document_structure",
        "detail": str(detail)[:1000],
        "identity": identity,
    }


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag.rsplit(":", 1)[-1]


def _xml_root(payload: bytes) -> ET.Element:
    return ET.fromstring(payload)


def _xml_visible_text(payload: bytes) -> str:
    root = _xml_root(payload)
    chunks: list[str] = []
    for element in root.iter():
        if _localname(element.tag) in {"t", "tab", "br", "cr"}:
            if _localname(element.tag) == "t":
                chunks.append(element.text or "")
            elif _localname(element.tag) == "tab":
                chunks.append("\t")
            else:
                chunks.append("\n")
    return "".join(chunks)


def _preflight(path: Path, identity: dict[str, Any]) -> tuple[bool, str | None]:
    if path.suffix.casefold() != ".docx":
        return False, "only standard .docx is supported"
    if (
        identity.get("exists") is not True
        or identity.get("type") != "file"
        or identity.get("stable") is not True
        or identity.get("digest_complete") is not True
    ):
        return False, "source file identity is not a stable complete regular-file observation"
    if int(identity.get("size_bytes") or 0) > MAX_FILE_BYTES:
        return False, "DOCX exceeds the bounded file-size limit"
    if not zipfile.is_zipfile(path):
        return False, "encrypted, legacy, corrupt, or non-OOXML Word packages are unsupported"
    try:
        with zipfile.ZipFile(path, "r") as package:
            names = set(package.namelist())
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                return False, "required WordprocessingML package parts are missing"
            for name in names:
                if name in _UNSUPPORTED_PARTS or any(name.startswith(prefix) for prefix in _UNSUPPORTED_PART_PREFIXES):
                    return False, f"unsupported DOCX package part: {name}"
            main_xml = package.read("word/document.xml")
            root = _xml_root(main_xml)
            bad = sorted({_localname(el.tag) for el in root.iter()} & _UNSUPPORTED_XML_LOCALNAMES)
            if bad:
                return False, "unsupported WordprocessingML structures: " + ", ".join(bad)
            for name in sorted(names):
                if not (name.startswith("word/header") or name.startswith("word/footer")) or not name.endswith(".xml"):
                    continue
                if PAYMENT_DATE_RE.search(_xml_visible_text(package.read(name))):
                    return False, "payment-date target occurs in a header/footer story"
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        return False, f"DOCX package preflight failed: {type(exc).__name__}: {exc}"
    return True, None


def _iter_paragraphs(document: _Document) -> Iterator[tuple[str, Paragraph]]:
    for index, paragraph in enumerate(document.paragraphs):
        yield f"body/p:{index}", paragraph
    for table_index, table in enumerate(document.tables):
        for row_index, row in enumerate(table.rows):
            for col_index, cell in enumerate(row.cells):
                if cell.tables:
                    raise ValueError("nested tables are outside DOCX v1 scope")
                for paragraph_index, paragraph in enumerate(cell.paragraphs):
                    yield f"table:{table_index}/cell:{row_index},{col_index}/p:{paragraph_index}", paragraph


def _run_format(run) -> dict[str, Any]:
    size = run.font.size
    return {
        "bold": run.bold,
        "italic": run.italic,
        "underline": str(run.underline) if run.underline is not None else None,
        "style": getattr(run.style, "name", None),
        "font_name": run.font.name,
        "font_size_pt": float(size.pt) if size is not None else None,
    }


def _records(document: _Document) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    total_chars = 0
    for location, paragraph in _iter_paragraphs(document):
        if len(records) >= MAX_PARAGRAPHS:
            raise ValueError("document exceeds bounded paragraph count")
        text = paragraph.text
        total_chars += len(text)
        if total_chars > MAX_VISIBLE_CHARS:
            raise ValueError("document exceeds bounded visible-text limit")
        records.append(
            {
                "location": location,
                "text": text,
                "run_text": [run.text for run in paragraph.runs],
                "run_format": [_run_format(run) for run in paragraph.runs],
            }
        )
    return records


def _structure_fingerprint(records: list[dict[str, Any]]) -> str:
    payload = [
        {
            "location": record["location"],
            "text": record["text"],
            "run_format": record["run_format"],
        }
        for record in records
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _target_occurrences(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    occurrences: list[dict[str, Any]] = []
    for record in records:
        text = str(record["text"])
        run_visible = "".join(str(value) for value in record["run_text"])
        for match in PAYMENT_DATE_RE.finditer(text):
            occurrences.append(
                {
                    "location": record["location"],
                    "date": match.group("date"),
                    "date_start": match.start("date"),
                    "date_end": match.end("date"),
                    "paragraph_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "run_mappable": run_visible == text,
                }
            )
    return occurrences


def inspect_docx(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve(strict=False)
    identity = observe_file_identity(source, max_hash_bytes=MAX_FILE_BYTES)
    ok, detail = _preflight(source, identity)
    if not ok:
        return _block(identity, detail or "unsupported DOCX")
    try:
        document = Document(source)
        records = _records(document)
        occurrences = _target_occurrences(records)
    except Exception as exc:
        return _block(identity, f"DOCX parse/structure inspection failed: {type(exc).__name__}: {exc}")
    if any(not item["run_mappable"] for item in occurrences):
        return _block(identity, "payment-date target crosses unsupported paragraph children such as hyperlinks")
    return {
        "ready": True,
        "blocker": None,
        "identity": identity,
        "paragraph_count": len(records),
        "table_count": len(document.tables),
        "payment_date_occurrence_count": len(occurrences),
        "payment_date_occurrences": occurrences,
        "structure_fingerprint": _structure_fingerprint(records),
    }


def replace_visible_span_across_runs(paragraph: Paragraph, start: int, end: int, replacement: str) -> None:
    """Replace one visible-text span without rebuilding the paragraph."""
    if start < 0 or end <= start:
        raise ValueError("replacement span is invalid")
    runs = list(paragraph.runs)
    visible = "".join(run.text for run in runs)
    if visible != paragraph.text:
        raise ValueError("paragraph contains unsupported visible children for run-aware replacement")
    if end > len(visible):
        raise ValueError("replacement span exceeds paragraph text")

    cursor = 0
    inserted = False
    touched = False
    for run in runs:
        text = run.text
        run_start, run_end = cursor, cursor + len(text)
        cursor = run_end
        overlap_start, overlap_end = max(start, run_start), min(end, run_end)
        if overlap_start >= overlap_end:
            continue
        touched = True
        before = text[: max(0, start - run_start)] if run_start < start else ""
        after = text[max(0, end - run_start) :] if run_end > end else ""
        middle = replacement if not inserted else ""
        run.text = before + middle + after
        inserted = True
    if not touched or not inserted:
        raise ValueError("replacement span did not map to ordinary text runs")


def _find_paragraph(document: _Document, location: str) -> Paragraph:
    for current, paragraph in _iter_paragraphs(document):
        if current == location:
            return paragraph
    raise ValueError("bound DOCX target location no longer exists")


def _publish_no_overwrite(temp_path: Path, destination: Path) -> None:
    try:
        os.link(temp_path, destination)
    except FileExistsError:
        raise FileExistsError("destination already exists; refusing overwrite")
    temp_path.unlink()


def write_docx_copy(
    source_path: str | Path,
    destination_path: str | Path,
    *,
    replacement_date: str,
    precondition_identity: dict[str, Any],
) -> dict[str, Any]:
    source = Path(source_path).resolve(strict=True)
    destination = Path(destination_path).resolve(strict=False)
    if source == destination:
        raise ValueError("DOCX copy destination must differ from source")
    if destination.exists():
        raise FileExistsError("destination already exists; refusing overwrite")
    if not destination.parent.is_dir():
        raise ValueError("destination parent is unavailable")

    current = observe_file_identity(source, max_hash_bytes=MAX_FILE_BYTES)
    if compare_file_identities(precondition_identity, current).get("exact") is not True:
        raise RuntimeError("stale_source_evidence: exact DOCX identity changed before mutation")
    inspection = inspect_docx(source)
    if inspection.get("ready") is not True:
        raise RuntimeError(f"{inspection.get('blocker')}: {inspection.get('detail')}")
    occurrences = list(inspection.get("payment_date_occurrences") or ())
    if len(occurrences) != 1:
        raise ValueError("DOCX mutation requires exactly one payment-date occurrence")
    target = occurrences[0]
    old_date = str(target["date"])
    if old_date == replacement_date:
        raise ValueError("replacement date already equals the current payment date")

    document = Document(source)
    before_records = _records(document)
    paragraph = _find_paragraph(document, str(target["location"]))
    before_target_text = paragraph.text
    if hashlib.sha256(before_target_text.encode("utf-8")).hexdigest() != target["paragraph_sha256"]:
        raise RuntimeError("stale_source_evidence: bound paragraph changed before mutation")
    replace_visible_span_across_runs(
        paragraph,
        int(target["date_start"]),
        int(target["date_end"]),
        replacement_date,
    )
    expected_target_text = (
        before_target_text[: int(target["date_start"])]
        + replacement_date
        + before_target_text[int(target["date_end"]) :]
    )

    fd, raw_temp = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    temp_path = Path(raw_temp)
    try:
        document.save(temp_path)
        temp_document = Document(temp_path)
        after_records = _records(temp_document)
        if len(after_records) != len(before_records):
            raise RuntimeError("DOCX verification failed: paragraph topology changed")
        changed = 0
        for before, after in zip(before_records, after_records):
            if before["location"] != after["location"]:
                raise RuntimeError("DOCX verification failed: paragraph location order changed")
            if before["run_format"] != after["run_format"]:
                raise RuntimeError("DOCX verification failed: run formatting changed")
            expected_text = expected_target_text if before["location"] == target["location"] else before["text"]
            if after["text"] != expected_text:
                raise RuntimeError("DOCX verification failed: unrelated or target paragraph text changed unexpectedly")
            changed += int(before["text"] != after["text"])
        if changed != 1:
            raise RuntimeError("DOCX verification failed: expected exactly one paragraph text change")
        temp_occurrences = _target_occurrences(after_records)
        if len(temp_occurrences) != 1 or temp_occurrences[0]["date"] != replacement_date:
            raise RuntimeError("DOCX verification failed: replacement date was not uniquely re-parsed")

        source_after_temp = observe_file_identity(source, max_hash_bytes=MAX_FILE_BYTES)
        if compare_file_identities(current, source_after_temp).get("exact") is not True:
            raise RuntimeError("DOCX source changed while destination was being prepared")
        if destination.exists():
            raise FileExistsError("destination appeared during mutation; refusing overwrite")
        _publish_no_overwrite(temp_path, destination)

        final_inspection = inspect_docx(destination)
        destination_identity = final_inspection.get("identity") or {}
        source_after = observe_file_identity(source, max_hash_bytes=MAX_FILE_BYTES)
        if compare_file_identities(current, source_after).get("exact") is not True:
            raise RuntimeError("DOCX source changed before final verification")
        if final_inspection.get("ready") is not True:
            raise RuntimeError("DOCX final reopen/inspection failed")
        final_occurrences = final_inspection.get("payment_date_occurrences") or []
        if len(final_occurrences) != 1 or final_occurrences[0].get("date") != replacement_date:
            raise RuntimeError("DOCX final verification did not find exactly the expected payment date")
        if final_inspection.get("structure_fingerprint") != _structure_fingerprint(after_records):
            raise RuntimeError("DOCX final structure fingerprint changed after publication")
        return {
            "source_identity_before": current,
            "source_identity_after": source_after,
            "destination_identity": destination_identity,
            "source_unchanged": True,
            "destination_reopened": True,
            "old_date": old_date,
            "new_date": replacement_date,
            "target_location": target["location"],
            "target_count_before": 1,
            "target_count_after": 1,
            "format_preserved": True,
            "surrounding_structure_preserved": True,
            "expected_structure_fingerprint": final_inspection["structure_fingerprint"],
        }
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise
