from __future__ import annotations

"""Bounded state model for the native ZN Slides v1 product."""

import json
import re
from typing import Any, Mapping, Sequence

SPEC_VERSION = 1
PRESENTATION_LAYOUTS = (
    "title",
    "title-body",
    "title-bullets",
    "architecture",
    "image-right",
)
PRESENTATION_THEMES = ("dark-tech", "light-clean")
MAX_PRESENTATION_SLIDES = 20
MAX_TITLE_CHARS = 160
MAX_BODY_CHARS = 800
MAX_BULLETS = 8
MAX_BULLET_CHARS = 360
MAX_DIAGRAM_NODES = 6
MAX_DIAGRAM_EDGES = 8

_DECK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_SLIDE_ID_RE = re.compile(r"^slide-[1-9][0-9]?$")
_NODE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")


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


def _bullets(value: Any, *, index: int) -> list[str]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise ValueError(f"slide {index} bullets must be an ordered list")
    if len(value) > MAX_BULLETS:
        raise ValueError(f"slide {index} supports at most {MAX_BULLETS} bullets")
    return [
        _text(item, field=f"slide {index} bullet {offset + 1}", limit=MAX_BULLET_CHARS, required=True)
        for offset, item in enumerate(value)
    ]


def _diagram(value: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - {"nodes", "edges"}:
        raise ValueError(f"slide {index} architecture diagram must contain only nodes and edges")
    raw_nodes = value.get("nodes")
    raw_edges = value.get("edges")
    if isinstance(raw_nodes, (str, bytes, Mapping)) or not isinstance(raw_nodes, Sequence):
        raise ValueError(f"slide {index} diagram nodes must be an ordered list")
    if isinstance(raw_edges, (str, bytes, Mapping)) or not isinstance(raw_edges, Sequence):
        raise ValueError(f"slide {index} diagram edges must be an ordered list")
    if not 2 <= len(raw_nodes) <= MAX_DIAGRAM_NODES:
        raise ValueError(f"slide {index} architecture diagram needs 2..{MAX_DIAGRAM_NODES} nodes")
    if not 1 <= len(raw_edges) <= MAX_DIAGRAM_EDGES:
        raise ValueError(f"slide {index} architecture diagram needs 1..{MAX_DIAGRAM_EDGES} edges")

    nodes: list[dict[str, str]] = []
    ids: set[str] = set()
    for offset, raw in enumerate(raw_nodes):
        if not isinstance(raw, Mapping) or "id" not in raw or "label" not in raw:
            raise ValueError(f"slide {index} diagram node {offset + 1} must contain exactly id and label")
        node_id = _text(raw.get("id"), field="diagram node id", limit=32, required=True)
        if not _NODE_ID_RE.fullmatch(node_id) or node_id in ids:
            raise ValueError(f"slide {index} diagram node ids must be unique safe identifiers")
        ids.add(node_id)
        nodes.append({
            "id": node_id,
            "label": _text(raw.get("label"), field="diagram node label", limit=80, required=True),
        })

    edges: list[dict[str, str]] = []
    for offset, raw in enumerate(raw_edges):
        if not isinstance(raw, Mapping) or "from" not in raw or "to" not in raw:
            raise ValueError(f"slide {index} diagram edge {offset + 1} must contain exactly from and to")
        source = _text(raw.get("from"), field="diagram edge from", limit=32, required=True)
        target = _text(raw.get("to"), field="diagram edge to", limit=32, required=True)
        if source not in ids or target not in ids or source == target:
            raise ValueError(f"slide {index} diagram edge must connect two known distinct nodes")
        edges.append({"from": source, "to": target})
    return {"nodes": nodes, "edges": edges}


def normalize_presentation_slide(raw: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"slide {index} must be an object")
    allowed = {"id", "layout", "title", "body", "bullets", "image_artifact_id", "diagram"}
    if set(raw) - allowed:
        raise ValueError(f"slide {index} contains unsupported fields")
    expected_id = f"slide-{index}"
    slide_id = _text(raw.get("id"), field=f"slide {index} id", limit=16, required=True)
    if slide_id != expected_id or not _SLIDE_ID_RE.fullmatch(slide_id):
        raise ValueError(f"slide {index} must keep stable id {expected_id}")

    layout = _text(raw.get("layout"), field=f"slide {index} layout", limit=32, required=True)
    if layout not in PRESENTATION_LAYOUTS:
        raise ValueError(f"slide {index} uses unsupported layout: {layout}")
    title = _text(raw.get("title"), field=f"slide {index} title", limit=MAX_TITLE_CHARS, required=True)
    body = _text(raw.get("body", ""), field=f"slide {index} body", limit=MAX_BODY_CHARS)
    bullets = _bullets(raw.get("bullets", []), index=index)
    image_artifact_id = _text(
        raw.get("image_artifact_id", ""),
        field=f"slide {index} image artifact id",
        limit=128,
    )

    result: dict[str, Any] = {
        "id": slide_id,
        "layout": layout,
        "title": title,
        "body": body,
        "bullets": bullets,
        "image_artifact_id": image_artifact_id,
    }
    if layout == "title":
        if index != 1 or bullets or image_artifact_id or raw.get("diagram") is not None:
            raise ValueError("title layout is only valid for slide 1 and has no bullets/image/diagram")
    elif layout == "title-body":
        if not body or bullets or image_artifact_id or raw.get("diagram") is not None:
            raise ValueError(f"slide {index} title-body requires body only")
    elif layout == "title-bullets":
        if not bullets or image_artifact_id or raw.get("diagram") is not None:
            raise ValueError(f"slide {index} title-bullets requires bullets and no image/diagram")
    elif layout == "architecture":
        if body or bullets or image_artifact_id:
            raise ValueError(f"slide {index} architecture contains only title and diagram")
        result["diagram"] = _diagram(raw.get("diagram"), index=index)
    elif layout == "image-right":
        if not image_artifact_id or raw.get("diagram") is not None:
            raise ValueError(f"slide {index} image-right requires a current Work image artifact")
        if not body and not bullets:
            raise ValueError(f"slide {index} image-right requires body or bullets")
    return result


def normalize_presentation_spec(
    raw: Any,
    *,
    expected_slide_count: int | None = None,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("PresentationSpec must be one object")
    if set(raw) != {"version", "deck_id", "title", "theme", "slides"}:
        raise ValueError("PresentationSpec v1 must contain exactly version, deck_id, title, theme and slides")
    if int(raw.get("version") or 0) != SPEC_VERSION:
        raise ValueError(f"PresentationSpec version must be {SPEC_VERSION}")
    deck_id = _text(raw.get("deck_id"), field="deck_id", limit=64, required=True)
    if not _DECK_ID_RE.fullmatch(deck_id):
        raise ValueError("deck_id is not a safe stable identifier")
    title = _text(raw.get("title"), field="deck title", limit=MAX_TITLE_CHARS, required=True)
    theme = _text(raw.get("theme"), field="theme", limit=32, required=True)
    if theme not in PRESENTATION_THEMES:
        raise ValueError(f"unsupported presentation theme: {theme}")
    raw_slides = raw.get("slides")
    if isinstance(raw_slides, (str, bytes, Mapping)) or not isinstance(raw_slides, Sequence):
        raise ValueError("PresentationSpec slides must be an ordered list")
    if not 1 <= len(raw_slides) <= MAX_PRESENTATION_SLIDES:
        raise ValueError(f"PresentationSpec supports 1..{MAX_PRESENTATION_SLIDES} slides")
    if expected_slide_count is not None and len(raw_slides) != int(expected_slide_count):
        raise ValueError("PresentationSpec does not match the requested slide count")
    slides = [
        normalize_presentation_slide(item, index=index)
        for index, item in enumerate(raw_slides, start=1)
    ]
    if slides[0]["layout"] != "title":
        raise ValueError("slide 1 must use title layout")
    return {
        "version": SPEC_VERSION,
        "deck_id": deck_id,
        "title": title,
        "theme": theme,
        "slides": slides,
    }


def presentation_visible_texts(spec: Mapping[str, Any]) -> list[list[str]]:
    normalized = normalize_presentation_spec(spec)
    result: list[list[str]] = []
    for slide in normalized["slides"]:
        texts = [slide["title"]]
        if slide["layout"] == "architecture":
            texts.extend(node["label"] for node in slide["diagram"]["nodes"])
        else:
            if slide["body"]:
                texts.append(slide["body"])
            texts.extend(slide["bullets"])
        result.append(texts)
    return result


def presentation_spec_json(spec: Mapping[str, Any]) -> str:
    return json.dumps(
        normalize_presentation_spec(spec),
        ensure_ascii=False,
        separators=(",", ":"),
    )
