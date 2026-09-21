from __future__ import annotations

"""Deterministic bounded PPTX inspection and outline generation.

The model is intentionally absent from this module. It accepts only a typed,
bounded presentation outline, writes a new PPTX without overwriting existing
files, reopens the package, and verifies the generated visible structure before
reporting success.
"""

import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from pptx import Presentation

from .file_identity import observe_file_identity

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_PACKAGE_PARTS = 4096
MAX_SLIDES = 40
MAX_TITLE_CHARS = 240
MAX_SUBTITLE_CHARS = 600
MAX_BULLETS_PER_SLIDE = 24
MAX_BULLET_CHARS = 800
MAX_VISIBLE_CHARS = 64 * 1024

_UNSUPPORTED_PART_PREFIXES = (
    "ppt/activeX/",
    "ppt/embeddings/",
    "ppt/externalLinks/",
)
_UNSUPPORTED_PARTS = {"ppt/vbaProject.bin"}


def _block(identity: dict[str, Any], code: str, detail: str) -> dict[str, Any]:
    return {
        "ready": False,
        "blocker": code,
        "detail": str(detail)[:1000],
        "identity": identity,
    }


def _preflight(path: Path, identity: dict[str, Any]) -> tuple[bool, str | None]:
    if path.suffix.casefold() != ".pptx":
        return False, "only standard .pptx is supported"
    if (
        identity.get("exists") is not True
        or identity.get("type") != "file"
        or identity.get("stable") is not True
        or identity.get("digest_complete") is not True
    ):
        return False, "PPTX must be one stable regular file within the bounded size limit"
    try:
        with zipfile.ZipFile(path) as package:
            parts = package.infolist()
            names = {item.filename for item in parts}
            if len(parts) > MAX_PACKAGE_PARTS:
                return False, "PPTX package contains too many parts"
            expanded = sum(max(0, int(item.file_size)) for item in parts)
            if expanded > MAX_EXPANDED_BYTES:
                return False, "PPTX expanded package exceeds the bounded inspection limit"
            if "[Content_Types].xml" not in names or "ppt/presentation.xml" not in names:
                return False, "PPTX package is missing required presentation parts"
            for item in parts:
                name = item.filename.replace("\\", "/")
                if name.startswith("/") or name.startswith("../") or "/../" in name:
                    return False, "PPTX package contains an unsafe part path"
                if item.flag_bits & 0x1:
                    return False, "encrypted PPTX package parts are unsupported"
                if name in _UNSUPPORTED_PARTS or name.startswith(_UNSUPPORTED_PART_PREFIXES):
                    return False, f"unsupported PPTX package part: {name}"
    except (OSError, zipfile.BadZipFile) as exc:
        return False, f"invalid PPTX package: {type(exc).__name__}"
    return True, None


def _shape_texts(shape: Any) -> list[str]:
    texts: list[str] = []
    if bool(getattr(shape, "has_text_frame", False)):
        for paragraph in shape.text_frame.paragraphs:
            text = str(paragraph.text or "").strip()
            if text:
                texts.append(text)
    if bool(getattr(shape, "has_table", False)):
        for row in shape.table.rows:
            for cell in row.cells:
                text = str(cell.text or "").strip()
                if text:
                    texts.append(text)
    children = getattr(shape, "shapes", None)
    if children is not None:
        for child in children:
            texts.extend(_shape_texts(child))
    return texts


def _fingerprint(slides: list[dict[str, Any]]) -> str:
    payload = json.dumps(slides, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def inspect_pptx(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve(strict=False)
    identity = observe_file_identity(source, max_hash_bytes=MAX_FILE_BYTES)
    ok, detail = _preflight(source, identity)
    if not ok:
        return _block(identity, "unsupported_presentation_structure", detail or "unsupported PPTX")
    try:
        presentation = Presentation(source)
    except Exception as exc:
        return _block(identity, "pptx_open_failed", type(exc).__name__)
    if len(presentation.slides) > MAX_SLIDES:
        return _block(identity, "presentation_too_large", f"PPTX has more than {MAX_SLIDES} slides")

    slides: list[dict[str, Any]] = []
    visible_chars = 0
    for index, slide in enumerate(presentation.slides, start=1):
        texts: list[str] = []
        for shape in slide.shapes:
            texts.extend(_shape_texts(shape))
        visible_chars += sum(len(text) for text in texts)
        if visible_chars > MAX_VISIBLE_CHARS:
            return _block(
                identity,
                "presentation_text_too_large",
                f"PPTX visible text exceeds {MAX_VISIBLE_CHARS} characters",
            )
        title_shape = slide.shapes.title
        title = str(title_shape.text or "").strip() if title_shape is not None else ""
        slides.append(
            {
                "slide_index": index,
                "title": title,
                "texts": texts,
            }
        )

    return {
        "ready": True,
        "identity": identity,
        "slide_count": len(slides),
        "visible_text_chars": visible_chars,
        "slides": slides,
        "structure_fingerprint": _fingerprint(slides),
    }


def _bounded_text(value: Any, *, field_name: str, limit: int, required: bool) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    text = value.strip()
    if required and not text:
        raise ValueError(f"{field_name} must not be empty")
    if len(text) > limit:
        raise ValueError(f"{field_name} exceeds {limit} characters")
    return text


def _normalize_outline(
    *,
    title: str,
    subtitle: str,
    slides: Sequence[Mapping[str, Any]],
) -> tuple[str, str, list[dict[str, Any]]]:
    normalized_title = _bounded_text(
        title, field_name="presentation title", limit=MAX_TITLE_CHARS, required=True
    )
    normalized_subtitle = _bounded_text(
        subtitle, field_name="presentation subtitle", limit=MAX_SUBTITLE_CHARS, required=False
    )
    if isinstance(slides, (str, bytes, Mapping)) or not isinstance(slides, Sequence):
        raise ValueError("slides must be an ordered sequence of objects")
    if len(slides) > MAX_SLIDES - 1:
        raise ValueError(f"presentation supports at most {MAX_SLIDES - 1} content slides")

    normalized_slides: list[dict[str, Any]] = []
    total_chars = len(normalized_title) + len(normalized_subtitle)
    for index, raw in enumerate(slides, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError(f"slide {index} must be an object")
        unexpected = set(raw) - {"title", "bullets"}
        if unexpected:
            raise ValueError(f"slide {index} contains unsupported fields: {sorted(unexpected)}")
        slide_title = _bounded_text(
            raw.get("title"), field_name=f"slide {index} title", limit=MAX_TITLE_CHARS, required=True
        )
        bullets_raw = raw.get("bullets", ())
        if isinstance(bullets_raw, (str, bytes, Mapping)) or not isinstance(
            bullets_raw, Sequence
        ):
            raise ValueError(f"slide {index} bullets must be an ordered sequence of strings")
        if len(bullets_raw) > MAX_BULLETS_PER_SLIDE:
            raise ValueError(
                f"slide {index} supports at most {MAX_BULLETS_PER_SLIDE} bullets"
            )
        bullets = [
            _bounded_text(
                item,
                field_name=f"slide {index} bullet {bullet_index}",
                limit=MAX_BULLET_CHARS,
                required=True,
            )
            for bullet_index, item in enumerate(bullets_raw, start=1)
        ]
        total_chars += len(slide_title) + sum(len(item) for item in bullets)
        if total_chars > MAX_VISIBLE_CHARS:
            raise ValueError(
                f"presentation outline exceeds {MAX_VISIBLE_CHARS} visible characters"
            )
        normalized_slides.append({"title": slide_title, "bullets": bullets})
    return normalized_title, normalized_subtitle, normalized_slides


def _publish_no_overwrite(temp_path: Path, destination: Path) -> None:
    try:
        os.link(temp_path, destination)
    except FileExistsError:
        raise FileExistsError("output_collision: destination already exists; refusing overwrite")
    temp_path.unlink()


def _expected_generated_texts(
    title: str,
    subtitle: str,
    slides: Sequence[Mapping[str, Any]],
) -> list[list[str]]:
    expected = [[text for text in (title, subtitle) if text]]
    for slide in slides:
        expected.append([str(slide["title"]), *[str(item) for item in slide["bullets"]]])
    return expected


def create_pptx_from_outline(
    destination_path: str | Path,
    *,
    title: str,
    subtitle: str = "",
    slides: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    destination = Path(destination_path).resolve(strict=False)
    if destination.suffix.casefold() != ".pptx":
        raise ValueError("PPTX destination must use the .pptx extension")
    if not destination.parent.exists() or not destination.parent.is_dir():
        raise FileNotFoundError("PPTX destination parent directory does not exist")
    if destination.exists():
        raise FileExistsError("output_collision: destination already exists; refusing overwrite")

    normalized_title, normalized_subtitle, normalized_slides = _normalize_outline(
        title=title,
        subtitle=subtitle,
        slides=slides,
    )
    expected_texts = _expected_generated_texts(
        normalized_title,
        normalized_subtitle,
        normalized_slides,
    )

    presentation = Presentation()
    title_slide = presentation.slides.add_slide(presentation.slide_layouts[0])
    if title_slide.shapes.title is None:
        raise RuntimeError("default PPTX title layout has no title placeholder")
    title_slide.shapes.title.text = normalized_title
    if normalized_subtitle:
        if len(title_slide.placeholders) < 2:
            raise RuntimeError("default PPTX title layout has no subtitle placeholder")
        title_slide.placeholders[1].text = normalized_subtitle

    for spec in normalized_slides:
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        if slide.shapes.title is None or len(slide.placeholders) < 2:
            raise RuntimeError("default PPTX content layout lacks required placeholders")
        slide.shapes.title.text = str(spec["title"])
        text_frame = slide.placeholders[1].text_frame
        text_frame.clear()
        bullets = list(spec["bullets"])
        if bullets:
            text_frame.paragraphs[0].text = bullets[0]
            for bullet in bullets[1:]:
                paragraph = text_frame.add_paragraph()
                paragraph.text = bullet

    fd, raw_temp = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".pptx",
        dir=destination.parent,
    )
    os.close(fd)
    temp_path = Path(raw_temp)
    try:
        presentation.save(temp_path)
        temp_inspection = inspect_pptx(temp_path)
        if temp_inspection.get("ready") is not True:
            raise RuntimeError(
                f"PPTX generated package failed reopen: {temp_inspection.get('detail')}"
            )
        observed_texts = [list(item.get("texts") or ()) for item in temp_inspection["slides"]]
        if observed_texts != expected_texts:
            raise RuntimeError("PPTX generated visible text differs from the admitted outline")
        if int(temp_inspection["slide_count"]) != len(expected_texts):
            raise RuntimeError("PPTX generated slide count differs from the admitted outline")
        if destination.exists():
            raise FileExistsError("output_collision: destination appeared during PPTX generation")
        _publish_no_overwrite(temp_path, destination)

        final_inspection = inspect_pptx(destination)
        if final_inspection.get("ready") is not True:
            raise RuntimeError("PPTX final fresh reopen/inspection failed")
        final_texts = [list(item.get("texts") or ()) for item in final_inspection["slides"]]
        if final_texts != expected_texts:
            raise RuntimeError("PPTX final visible text differs from the admitted outline")
        if final_inspection.get("structure_fingerprint") != temp_inspection.get(
            "structure_fingerprint"
        ):
            raise RuntimeError("PPTX final structure fingerprint differs from verified temp output")
        return {
            "verified": True,
            "destination": str(destination),
            "identity": final_inspection["identity"],
            "slide_count": final_inspection["slide_count"],
            "visible_text_chars": final_inspection["visible_text_chars"],
            "structure_fingerprint": final_inspection["structure_fingerprint"],
        }
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise
