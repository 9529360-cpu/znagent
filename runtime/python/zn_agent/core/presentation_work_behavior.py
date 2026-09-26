from __future__ import annotations

"""Native Slides Work behavior for one ZN Resident and the existing Work ledger."""

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .execution_mode import event_allows_effects
from .models import ExecutionPath, ResidentRunResult, utc_now
from .presentation_document import create_pptx_from_spec
from .presentation_spec import (
    PRESENTATION_LAYOUTS,
    normalize_presentation_slide,
    normalize_presentation_spec,
    presentation_spec_json,
)
from .work import WorkArtifact

_STATE_KEY = "presentation_work_v1"
_INSTALL_MARKER = "_zn_presentation_work_v1_installed"
_KIND = "presentation"
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_PPT_MARKERS = ("ppt", "pptx", "\u5e7b\u706f\u7247", "\u6f14\u793a\u6587\u7a3f")
_CREATE_MARKERS = (
    "\u5e2e\u6211\u505a",
    "\u505a\u4e00\u4efd",
    "\u751f\u6210",
    "\u521b\u5efa",
    "create",
    "make",
    "build",
)
_EXPORT_MARKERS = ("\u5bfc\u51fa", "\u4fdd\u5b58\u4e3a", "export")
_ARCHITECTURE_MARKERS = ("\u67b6\u6784\u56fe", "architecture diagram")
_SIMPLIFY_MARKERS = ("\u7cbe\u7b80", "\u7b80\u5316", "simplify", "shorten", "concise")
_CHINESE_NUMERALS = {
    "\u4e00": 1, "\u4e8c": 2, "\u4e09": 3, "\u56db": 4, "\u4e94": 5,
    "\u516d": 6, "\u4e03": 7, "\u516b": 8, "\u4e5d": 9, "\u5341": 10,
}


def _thread_id(event: Any) -> str:
    return str((getattr(event, "payload", {}) or {}).get("work_thread_id") or "").strip()


def _deck_artifact_id(thread_id: str) -> str:
    digest = hashlib.sha256(f"{thread_id}\0slides".encode("utf-8")).hexdigest()[:20]
    return f"artifact-presentation-{digest}"


def _file_artifact_id(thread_id: str, path: Path) -> str:
    digest = hashlib.sha256(f"{thread_id}\0pptx\0{path}".encode("utf-8")).hexdigest()[:20]
    return f"artifact-{digest}"


def _presentation_artifact(resident: Any, thread_id: str) -> WorkArtifact | None:
    if not thread_id:
        return None
    for artifact in resident.work_ledger.list_artifacts(thread_id, limit=96):
        if artifact.kind == _KIND:
            return artifact
    return None


def _presentation_spec(artifact: WorkArtifact | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    try:
        return normalize_presentation_spec(json.loads(artifact.content))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _chinese_number(token: str) -> int | None:
    token = token.strip()
    if token in _CHINESE_NUMERALS:
        return _CHINESE_NUMERALS[token]
    if token.startswith("\u5341") and len(token) == 2 and token[1] in _CHINESE_NUMERALS:
        return 10 + _CHINESE_NUMERALS[token[1]]
    if len(token) == 2 and token[0] in _CHINESE_NUMERALS and token[1] == "\u5341":
        return _CHINESE_NUMERALS[token[0]] * 10
    return None


def _slide_count(task: str) -> int | None:
    page_chars = "\u9875\u9801\u5f20"
    patterns = (
        r"(?<!\d)(\d{1,2})\s*[" + page_chars + "]",
        r"(?<!\d)(\d{1,2})\s*slides?",
    )
    for pattern in patterns:
        match = re.search(pattern, task, flags=re.IGNORECASE)
        if match:
            value = int(match.group(1))
            return value if 1 <= value <= 20 else None
    return None


def _slide_index(task: str) -> int | None:
    page_chars = "\u9875\u9801\u5f20"
    prefix = "\u7b2c"
    digit = re.search(prefix + r"\s*(\d{1,2})\s*[" + page_chars + "]", task)
    if digit:
        return int(digit.group(1))
    chinese_digits = "\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341"
    chinese = re.search(
        prefix + r"\s*([" + chinese_digits + r"]{1,3})\s*[" + page_chars + "]",
        task,
    )
    if chinese:
        return _chinese_number(chinese.group(1))
    english = re.search(r"slide\s+(\d{1,2})", task, flags=re.IGNORECASE)
    return int(english.group(1)) if english else None


def _strip_json_response(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    fence = chr(96) * 3
    if raw.startswith(fence) and raw.endswith(fence):
        lines = raw.splitlines()
        if len(lines) >= 3:
            raw = "\n".join(lines[1:-1]).strip()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("cognition must return exactly one JSON object")
    return value


def _operation(resident: Any, event: Any) -> dict[str, Any] | None:
    if not event_allows_effects(event):
        return None
    if str(getattr(event, "kind", "") or "").strip().lower() != "desktop_user_event":
        return None
    payload = getattr(event, "payload", {}) or {}
    if payload.get("body_action") or payload.get("native_action"):
        return None
    task = " ".join(str(getattr(event, "task", "") or "").split())
    if not task:
        return None
    lowered = task.casefold()
    thread_id = _thread_id(event)
    current = _presentation_artifact(resident, thread_id)
    if current is not None and any(marker.casefold() in lowered for marker in _EXPORT_MARKERS):
        return {"kind": "export"}
    index = _slide_index(task)
    if current is not None and index is not None:
        return {"kind": "edit", "slide_index": index}
    has_ppt = any(marker.casefold() in lowered for marker in _PPT_MARKERS)
    has_create = any(marker.casefold() in lowered for marker in _CREATE_MARKERS)
    if has_ppt and (has_create or current is None):
        return {"kind": "create", "slide_count": _slide_count(task) or 6}
    return None


def _model_result(
    resident: Any,
    event: Any,
    question: str,
    *,
    purpose: str,
) -> tuple[dict[str, Any], int]:
    decision = resident.budget.decide(event, memory_hit=False, local_capability_available=False)
    if not decision.use_model or decision.max_model_calls <= 0:
        raise RuntimeError(f"cognitive budget rejected {purpose}: {decision.reason}")
    result = resident.kernel.run_goal(
        question,
        required_capabilities=("language_understanding",),
        priority=event.priority,
        metadata={"resident_event_id": event.event_id, "purpose": purpose},
        max_attempts_override=1,
        goal_id=f"{event.event_id}:{purpose}",
    )
    invocations = int(resident._model_invocations(result))
    if not (result.worker_result.success and result.assessment.success):
        raise RuntimeError(f"bounded cognition failed for {purpose}")
    return _strip_json_response(result.worker_result.response), invocations


def _image_artifact_ids(resident: Any, thread_id: str) -> list[str]:
    result: list[str] = []
    for artifact in resident.work_ledger.list_artifacts(thread_id, limit=96):
        path = Path(artifact.path) if artifact.path else None
        if path is not None and path.suffix.casefold() in _IMAGE_SUFFIXES and path.is_file():
            result.append(artifact.artifact_id)
    return result[:12]


def _create_spec(
    resident: Any,
    event: Any,
    *,
    slide_count: int,
    thread_id: str,
) -> tuple[dict[str, Any], int]:
    if not 3 <= slide_count <= 20:
        raise ValueError("Slides creation supports 3..20 total slides")
    task = str(getattr(event, "task", "") or "")
    lowered = task.casefold()
    theme = (
        "dark-tech"
        if any(token in lowered for token in ("\u6df1\u8272", "\u79d1\u6280", "dark", "tech"))
        else "light-clean"
    )
    deck_id = "deck-" + hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:12]
    image_ids = _image_artifact_ids(resident, thread_id)
    requested_architecture = any(marker.casefold() in lowered for marker in _ARCHITECTURE_MARKERS)
    requested_image = any(token in lowered for token in ("image", "photo", "picture", "\u56fe\u7247", "\u7167\u7247"))
    allowed_layouts = ["title", "title-body", "title-bullets"]
    if requested_architecture:
        allowed_layouts.append("architecture")
    if requested_image and image_ids:
        allowed_layouts.append("image-right")
    required_ids = [f"slide-{index}" for index in range(1, slide_count + 1)]
    question = (
        "Create one PresentationSpec v1 for the user's requested deck. Return one JSON object only, no markdown. "
        f"Top-level fields must be exactly version, deck_id, title, theme, slides. version=1, "
        f"deck_id={json.dumps(deck_id)}, theme={json.dumps(theme)}. "
        f"The slides array MUST contain exactly {slide_count} objects in this exact order with no omissions: "
        f"{json.dumps(required_ids)}. Count the array before answering; do not stop early. "
        "Every slide object must contain exactly id, layout, title, body, bullets, image_artifact_id, "
        "plus diagram only when layout=architecture. "
        "Unused body/image_artifact_id must be the empty string and unused bullets must be []; never return null. "
        f"Allowed layouts for THIS request are only {json.dumps(allowed_layouts)}. "
        "Slide 1 must use title. Do not use architecture unless the user explicitly requested an architecture diagram. "
        "For architecture, body must be empty, bullets must be [], image_artifact_id must be empty, and diagram must be "
        "{nodes:[{id,label}],edges:[{from,to}]} with 2..6 nodes. "
        "Do not use image-right unless the user explicitly requested an image and image_artifact_id is one of: "
        f"{json.dumps(image_ids)}. "
        "Use concise presentation copy. Do not invent metrics, customers, dates, financial claims, market share or "
        "external facts. Known ZN product facts you may use: ZN is a general-purpose personal assistant centered on "
        "one Resident and one Work; its existing product architecture includes Body, Senses, CognitiveResources, "
        "Desktop, Browser, File, Research and bounded verification. "
        f"User request: {task}"
    )
    raw, invocations = _model_result(
        resident, event, question, purpose="presentation_spec_create"
    )
    raw = dict(raw)
    raw["version"] = 1
    raw["deck_id"] = deck_id
    raw["theme"] = theme
    slides_raw = raw.get("slides")
    if isinstance(slides_raw, list):
        normalized_slides = []
        for index, slide in enumerate(slides_raw, start=1):
            if not isinstance(slide, Mapping):
                normalized_slides.append(slide)
                continue
            item = dict(slide)
            item["id"] = f"slide-{index}"
            layout = str(item.get("layout") or "")
            if layout == "title":
                if item.get("body") is None:
                    item["body"] = ""
                item["bullets"] = []
                item["image_artifact_id"] = ""
                item.pop("diagram", None)
            elif layout == "title-body":
                if item.get("body") is None:
                    item["body"] = ""
                item["bullets"] = []
                item["image_artifact_id"] = ""
                item.pop("diagram", None)
            elif layout == "title-bullets":
                item["body"] = ""
                if item.get("bullets") is None:
                    item["bullets"] = []
                item["image_artifact_id"] = ""
                item.pop("diagram", None)
            elif layout == "architecture":
                item["body"] = ""
                item["bullets"] = []
                item["image_artifact_id"] = ""
            elif layout == "image-right":
                if item.get("body") is None:
                    item["body"] = ""
                if item.get("bullets") is None:
                    item["bullets"] = []
                if item.get("image_artifact_id") is None:
                    item["image_artifact_id"] = ""
                item.pop("diagram", None)
            normalized_slides.append(item)
        raw["slides"] = normalized_slides
    try:
        normalized = normalize_presentation_spec(raw, expected_slide_count=slide_count)
        allowed_images = set(image_ids)
        for slide in normalized["slides"]:
            image_artifact_id = str(slide.get("image_artifact_id") or "")
            if image_artifact_id and image_artifact_id not in allowed_images:
                raise ValueError("cognition referenced an image outside the current Work")
    except Exception as exc:
        setattr(exc, "model_invocations", invocations)
        raise
    return normalized, invocations


def _edit_spec(
    resident: Any,
    event: Any,
    *,
    current: Mapping[str, Any],
    slide_index: int,
) -> tuple[dict[str, Any], int]:
    slides = list(current["slides"])
    if not 1 <= slide_index <= len(slides):
        raise ValueError(f"requested slide {slide_index} is outside the current deck")
    target = dict(slides[slide_index - 1])
    task = str(getattr(event, "task", "") or "")
    lowered = task.casefold()
    wants_architecture = any(marker.casefold() in lowered for marker in _ARCHITECTURE_MARKERS)
    wants_simplify = any(marker.casefold() in lowered for marker in _SIMPLIFY_MARKERS)
    layout_rule = (
        "The returned layout must be architecture with a 2..6 node bounded diagram."
        if wants_architecture
        else f"Keep layout exactly {json.dumps(target['layout'])}; the user did not request a layout change."
    )
    simplify_rule = (
        "Make the copy materially shorter while preserving its core meaning."
        if wants_simplify
        else ""
    )
    question = (
        "Modify exactly one slide from an existing PresentationSpec v1. Return one JSON slide object only, "
        "no markdown. It must contain id, layout, title, body, bullets, image_artifact_id, plus diagram only "
        "for architecture. "
        f"Keep id exactly {json.dumps(target['id'])}. {layout_rule} {simplify_rule} "
        "Do not modify or discuss other slides. Do not invent metrics, customers, dates, financial claims "
        "or external facts. "
        f"Deck title: {json.dumps(current['title'], ensure_ascii=False)}. "
        f"Current target slide: {json.dumps(target, ensure_ascii=False)}. User request: {task}"
    )
    raw, invocations = _model_result(
        resident, event, question, purpose="presentation_spec_edit_slide"
    )
    raw = dict(raw)
    raw["id"] = target["id"]
    layout = str(raw.get("layout") or "")
    if layout == "title":
        if raw.get("body") is None:
            raw["body"] = ""
        raw["bullets"] = []
        raw["image_artifact_id"] = ""
        raw.pop("diagram", None)
    elif layout == "title-body":
        if raw.get("body") is None:
            raw["body"] = ""
        raw["bullets"] = []
        raw["image_artifact_id"] = ""
        raw.pop("diagram", None)
    elif layout == "title-bullets":
        raw["body"] = ""
        if raw.get("bullets") is None:
            raw["bullets"] = []
        raw["image_artifact_id"] = ""
        raw.pop("diagram", None)
    elif layout == "architecture":
        raw["body"] = ""
        raw["bullets"] = []
        raw["image_artifact_id"] = ""
    elif layout == "image-right":
        if raw.get("body") is None:
            raw["body"] = ""
        if raw.get("bullets") is None:
            raw["bullets"] = []
        if raw.get("image_artifact_id") is None:
            raw["image_artifact_id"] = ""
        raw.pop("diagram", None)
    try:
        replacement = normalize_presentation_slide(raw, index=slide_index)
    except Exception as exc:
        setattr(exc, "model_invocations", invocations)
        raise
    if replacement["id"] != target["id"]:
        raise ValueError("cognition changed the stable slide id")
    if wants_architecture and replacement["layout"] != "architecture":
        raise ValueError("architecture edit did not produce architecture layout")
    if not wants_architecture and replacement["layout"] != target["layout"]:
        raise ValueError("slide edit changed layout without explicit user request")
    updated = dict(current)
    updated["slides"] = [dict(item) for item in slides]
    updated["slides"][slide_index - 1] = replacement
    return normalize_presentation_spec(updated), invocations


def _save_deck(
    resident: Any,
    event: Any,
    *,
    thread_id: str,
    spec: Mapping[str, Any],
    previous: WorkArtifact | None,
    last_export: Mapping[str, Any] | None = None,
    selected_slide_id: str | None = None,
) -> WorkArtifact:
    normalized = normalize_presentation_spec(spec)
    previous_meta = dict(previous.metadata) if previous is not None else {}
    revision = int(previous_meta.get("revision") or 0) + (0 if last_export is not None else 1)
    metadata = {
        "presentation_spec_version": 1,
        "deck_id": normalized["deck_id"],
        "theme": normalized["theme"],
        "slide_count": len(normalized["slides"]),
        "revision": max(1, revision),
        "latest_event_id": event.event_id,
        "status": "ready",
    }
    if previous_meta.get("last_export"):
        metadata["last_export"] = previous_meta["last_export"]
    if last_export is not None:
        metadata["last_export"] = dict(last_export)
    preferred_slide_id = str(
        selected_slide_id or previous_meta.get("selected_slide_id") or ""
    ).strip()
    if preferred_slide_id and any(
        slide["id"] == preferred_slide_id for slide in normalized["slides"]
    ):
        metadata["selected_slide_id"] = preferred_slide_id
    artifact = WorkArtifact(
        artifact_id=_deck_artifact_id(thread_id),
        thread_id=thread_id,
        event_id=event.event_id,
        kind=_KIND,
        name=str(normalized["title"]),
        content=presentation_spec_json(normalized),
        metadata=metadata,
        created_at=utc_now(),
    )
    resident.work_ledger._save_artifact(artifact)
    return artifact


def _export_directory(event: Any) -> Path:
    payload = getattr(event, "payload", {}) or {}
    workspace = str(payload.get("workspace_path") or "").strip()
    if workspace:
        path = Path(workspace).resolve(strict=True)
        if path.is_dir():
            return path
    downloads = Path.home() / "Downloads"
    if downloads.is_dir():
        return downloads.resolve(strict=True)
    raise RuntimeError(
        "PPTX export requires the attached Work workspace or an existing Downloads folder"
    )


def _filename(title: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", title).strip(" .")
    value = re.sub(r"\s+", " ", value)[:80].rstrip(" .")
    return (value or "ZN Slides") + ".pptx"


def _image_paths(
    resident: Any,
    thread_id: str,
    spec: Mapping[str, Any],
) -> dict[str, str]:
    required = {
        str(slide.get("image_artifact_id") or "")
        for slide in spec["slides"]
        if str(slide.get("image_artifact_id") or "")
    }
    if not required:
        return {}
    artifacts = {
        item.artifact_id: item
        for item in resident.work_ledger.list_artifacts(thread_id, limit=96)
    }
    result: dict[str, str] = {}
    for artifact_id in required:
        artifact = artifacts.get(artifact_id)
        if artifact is None or not artifact.path:
            raise ValueError(f"image artifact is not present in current Work: {artifact_id}")
        path = Path(artifact.path).resolve(strict=True)
        if path.suffix.casefold() not in _IMAGE_SUFFIXES or not path.is_file():
            raise ValueError(f"image artifact is not a supported real image: {artifact_id}")
        result[artifact_id] = str(path)
    return result


def _export(
    resident: Any,
    event: Any,
    *,
    thread_id: str,
    artifact: WorkArtifact,
    spec: Mapping[str, Any],
) -> tuple[str, WorkArtifact]:
    destination = _export_directory(event) / _filename(str(spec["title"]))
    result = resident.body.act(
        "create_pptx_from_spec",
        event_id=event.event_id,
        destination_path=str(destination),
        spec=dict(spec),
        image_paths=_image_paths(resident, thread_id, spec),
    )
    if not result.success:
        raise RuntimeError(str(result.error or result.output or "PPTX export failed"))
    verification = dict(result.data)
    if (
        verification.get("verified") is not True
        or int(verification.get("slide_count") or 0) != len(spec["slides"])
    ):
        raise RuntimeError("PPTX export did not pass fresh reopen verification")
    file_artifact = WorkArtifact(
        artifact_id=_file_artifact_id(thread_id, destination),
        thread_id=thread_id,
        event_id=event.event_id,
        kind="file",
        name=destination.name,
        path=str(destination),
        content="Verified PPTX export from current PresentationSpec v1",
        metadata={
            "mode": "presentation_export",
            "deck_id": spec["deck_id"],
            "verified": True,
            "slide_count": verification["slide_count"],
            "identity": verification.get("identity"),
            "structure_fingerprint": verification.get("structure_fingerprint"),
        },
        created_at=utc_now(),
    )
    resident.work_ledger._save_artifact(file_artifact)
    _save_deck(
        resident,
        event,
        thread_id=thread_id,
        spec=spec,
        previous=artifact,
        last_export={
            "path": str(destination),
            "verified": True,
            "slide_count": verification["slide_count"],
            "structure_fingerprint": verification.get("structure_fingerprint"),
            "exported_at": utc_now(),
        },
    )
    return str(destination), file_artifact


def _fail(
    resident: Any,
    event: Any,
    state: Any,
    reason: str,
    *,
    model_invocations: int = 0,
):
    state.stage = "failed"
    state.next_action = None
    state.blocked_by = str(reason)[:1000]
    resident.store.save_working_state(state)
    return ResidentRunResult(
        event=event,
        execution_path=ExecutionPath.INVESTIGATION,
        success=False,
        response=str(reason)[:8000],
        model_invocations=model_invocations,
        reason="presentation_work_failed_closed",
    )


def _finish(
    resident: Any,
    event: Any,
    state: Any,
    response: str,
    *,
    model_invocations: int,
):
    state.stage = "complete"
    state.next_action = None
    state.blocked_by = None
    resident.store.save_working_state(state)
    return ResidentRunResult(
        event=event,
        execution_path=ExecutionPath.INVESTIGATION,
        success=True,
        response=response[:8000],
        model_invocations=model_invocations,
        reason="native Slides Work completed through the existing Resident, Work and Body",
    )


def _begin(
    resident: Any,
    event: Any,
    state: Any,
    operation: Mapping[str, Any],
):
    root = resident.work_ledger.work_item_for_event(event.event_id)
    thread_id = _thread_id(event)
    if (
        root is None
        or root.parent_work_item_id is not None
        or not thread_id
        or root.work_thread_id != thread_id
    ):
        return _fail(resident, event, state, "Slides requires one current durable Root Work")
    state.data[_STATE_KEY] = {
        "operation": dict(operation),
        "thread_id": thread_id,
        "root_work_item_id": root.work_item_id,
        "plan_version": root.plan_version,
    }
    state.stage = "presentation_work"
    state.next_action = "update the current PresentationSpec and Slides Work artifact"
    state.blocked_by = None
    resident.store.save_working_state(state)
    return None


def _execute(resident: Any, event: Any, state: Any):
    meta = dict(state.data.get(_STATE_KEY) or {})
    operation = dict(meta.get("operation") or {})
    thread_id = str(meta.get("thread_id") or "")
    kind = str(operation.get("kind") or "")
    current_artifact = _presentation_artifact(resident, thread_id)
    current_spec = _presentation_spec(current_artifact)
    invocations = 0
    try:
        if kind == "create":
            spec, invocations = _create_spec(
                resident,
                event,
                slide_count=int(operation.get("slide_count") or 6),
                thread_id=thread_id,
            )
            artifact = _save_deck(
                resident,
                event,
                thread_id=thread_id,
                spec=spec,
                previous=current_artifact,
                selected_slide_id="slide-1",
            )
            return _finish(
                resident,
                event,
                state,
                f"Slides workspace is ready with {len(spec['slides'])} slides: {artifact.name}.",
                model_invocations=invocations,
            )
        if kind == "edit":
            if current_artifact is None or current_spec is None:
                raise RuntimeError("current PresentationSpec is missing or invalid")
            slide_index = int(operation.get("slide_index") or 0)
            spec, invocations = _edit_spec(
                resident,
                event,
                current=current_spec,
                slide_index=slide_index,
            )
            _save_deck(
                resident,
                event,
                thread_id=thread_id,
                spec=spec,
                previous=current_artifact,
                selected_slide_id=f"slide-{slide_index}",
            )
            return _finish(
                resident,
                event,
                state,
                f"Slide {slide_index} updated in the current Slides workspace.",
                model_invocations=invocations,
            )
        if kind == "export":
            if current_artifact is None or current_spec is None:
                raise RuntimeError("current PresentationSpec is missing or invalid")
            destination, _ = _export(
                resident,
                event,
                thread_id=thread_id,
                artifact=current_artifact,
                spec=current_spec,
            )
            return _finish(
                resident,
                event,
                state,
                f"Verified PPTX exported and freshly reopened: {destination}",
                model_invocations=0,
            )
        raise RuntimeError("unsupported Slides operation")
    except Exception as exc:
        observed_invocations = max(
            invocations,
            int(getattr(exc, "model_invocations", 0) or 0),
        )
        return _fail(
            resident,
            event,
            state,
            f"{type(exc).__name__}: {exc}",
            model_invocations=observed_invocations,
        )


def install_presentation_work_behavior(resident: Any) -> None:
    if getattr(resident, _INSTALL_MARKER, False):
        return
    body = resident.body
    original_dispatch = body._dispatch

    def dispatch(action: Any, started: Any):
        if str(action.kind or "").lower() == "create_pptx_from_spec":
            data = create_pptx_from_spec(
                action.args.get("destination_path"),
                spec=dict(action.args.get("spec") or {}),
                image_paths=dict(action.args.get("image_paths") or {}),
            )
            return body._ok(
                action,
                started,
                output=str(action.args.get("destination_path") or ""),
                data=data,
            )
        return original_dispatch(action, started)

    original_advance = resident._advance_event_step

    def advance(
        event: Any,
        state: Any,
        *,
        readiness: Any,
        learning_evidence: Any,
        thought: Any = None,
    ):
        stage = str(state.stage or "")
        if stage == "orient":
            operation = _operation(resident, event)
            if operation is not None:
                return _begin(resident, event, state, operation)
        if stage == "presentation_work":
            return _execute(resident, event, state)
        return original_advance(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    body._dispatch = dispatch
    resident._advance_event_step = advance
    setattr(resident, _INSTALL_MARKER, True)
