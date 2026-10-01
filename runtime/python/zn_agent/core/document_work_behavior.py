from __future__ import annotations

"""Native Document Work behavior for one ZN Resident and the existing Work ledger."""

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .document_spec import (
    document_spec_json,
    normalize_document_section,
    normalize_document_spec,
)
from .execution_mode import event_allows_effects
from .models import ExecutionPath, ResidentRunResult, utc_now
from .office_document import create_docx_from_spec
from .work import WorkArtifact

_STATE_KEY = "document_work_v1"
_INSTALL_MARKER = "_zn_document_work_v1_installed"
_KIND = "document"
_CREATE_MARKERS = (
    "\u5e2e\u6211\u5199",
    "\u5199\u4e00\u4efd",
    "\u8d77\u8349",
    "\u751f\u6210",
    "\u521b\u5efa",
    "write",
    "draft",
    "create",
)
_DOCUMENT_MARKERS = (
    "\u6587\u6863",
    "\u62a5\u544a",
    "\u6587\u7ae0",
    "\u65b9\u6848",
    "\u7a3f",
    "document",
    "report",
    "article",
)
_EXPORT_MARKERS = (
    "\u5bfc\u51fa",
    "\u4fdd\u5b58\u4e3a",
    "export",
)
_SIMPLIFY_MARKERS = (
    "\u7cbe\u7b80",
    "\u7b80\u5316",
    "simplify",
    "shorten",
    "concise",
)
_THREE_POINT_MARKERS = (
    "\u4e09\u70b9",
    "3\u70b9",
    "3 \u70b9",
    "three points",
)
_CHINESE_NUMERALS = {
    "\u4e00": 1,
    "\u4e8c": 2,
    "\u4e09": 3,
    "\u56db": 4,
    "\u4e94": 5,
    "\u516d": 6,
    "\u4e03": 7,
    "\u516b": 8,
    "\u4e5d": 9,
    "\u5341": 10,
}


def _thread_id(event: Any) -> str:
    return str((getattr(event, "payload", {}) or {}).get("work_thread_id") or "").strip()


def _document_artifact_id(thread_id: str) -> str:
    digest = hashlib.sha256(f"{thread_id}\0document".encode("utf-8")).hexdigest()[:20]
    return f"artifact-document-{digest}"


def _file_artifact_id(thread_id: str, path: Path) -> str:
    digest = hashlib.sha256(f"{thread_id}\0docx\0{path}".encode("utf-8")).hexdigest()[:20]
    return f"artifact-{digest}"


def _document_artifact(resident: Any, thread_id: str) -> WorkArtifact | None:
    if not thread_id:
        return None
    for artifact in resident.work_ledger.list_artifacts(thread_id, limit=96):
        if artifact.kind == _KIND:
            return artifact
    return None


def _document_spec(artifact: WorkArtifact | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    try:
        return normalize_document_spec(json.loads(artifact.content))
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


def _section_index(task: str, spec: Mapping[str, Any] | None) -> int | None:
    digit = re.search(r"\u7b2c\s*(\d{1,2})\s*(?:\u8282|\u7ae0|\u90e8\u5206|\u7ae0\u8282)", task)
    if digit:
        return int(digit.group(1))
    chinese = re.search(
        r"\u7b2c\s*([\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]{1,3})\s*(?:\u8282|\u7ae0|\u90e8\u5206|\u7ae0\u8282)",
        task,
    )
    if chinese:
        return _chinese_number(chinese.group(1))
    english = re.search(r"\bsection\s+(\d{1,2})\b", task, flags=re.IGNORECASE)
    if english:
        return int(english.group(1))
    if spec is None:
        return None
    lowered = task.casefold()
    matches = [
        index
        for index, section in enumerate(spec["sections"], start=1)
        if str(section["heading"]).casefold() in lowered
    ]
    return matches[0] if len(matches) == 1 else None


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
    current_artifact = _document_artifact(resident, thread_id)
    current_spec = _document_spec(current_artifact)

    if current_artifact is not None and any(marker.casefold() in lowered for marker in _EXPORT_MARKERS):
        if any(token in lowered for token in ("docx", "word", "\u6587\u6863")) or "\u5bfc\u51fa" in task:
            return {"kind": "export"}

    target = _section_index(task, current_spec)
    if current_artifact is not None and current_spec is not None and target is not None:
        return {"kind": "edit", "section_index": target}

    if ".docx" in lowered:
        return None
    has_create = any(marker.casefold() in lowered for marker in _CREATE_MARKERS)
    has_document = any(marker.casefold() in lowered for marker in _DOCUMENT_MARKERS)
    if has_create and has_document and current_artifact is None:
        return {"kind": "create"}
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


def _create_spec(
    resident: Any,
    event: Any,
    *,
    thread_id: str,
) -> tuple[dict[str, Any], int]:
    task = str(getattr(event, "task", "") or "")
    document_id = "doc-" + hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:12]
    question = (
        "Create one DocumentSpec v1 for the user's requested native ZN document. "
        "Return one JSON object only, no markdown. Top-level fields must be exactly "
        "version, document_id, title, subtitle, sections. version=1 and "
        f"document_id={json.dumps(document_id)}. subtitle may be an empty string. "
        "sections must contain 1..12 ordered section objects. Every section must contain "
        "exactly id, heading, paragraphs, bullets. ids must be section-1, section-2, ... "
        "in order. Use 0..4 concise paragraphs and 0..8 bullets per section, but every "
        "section needs at least one paragraph or bullet. If the user explicitly names "
        "the desired sections, include those named sections in that order and do not add "
        "unrequested sections. Do not invent metrics, customers, dates, financial claims, "
        "market share or external facts. Known ZN facts you may use: ZN is one long-lived "
        "Resident that owns durable Work and combines Body, Senses, CognitiveResources, "
        "Browser, Desktop, Files, Research and fresh verification to complete real tasks. "
        f"User request: {task}"
    )
    raw, invocations = _model_result(
        resident,
        event,
        question,
        purpose="document_spec_create",
    )
    raw = dict(raw)
    raw["version"] = 1
    raw["document_id"] = document_id
    if raw.get("subtitle") is None:
        raw["subtitle"] = ""
    sections = raw.get("sections")
    if isinstance(sections, list):
        normalized_sections = []
        for index, section in enumerate(sections, start=1):
            if not isinstance(section, Mapping):
                normalized_sections.append(section)
                continue
            item = dict(section)
            item["id"] = f"section-{index}"
            if item.get("paragraphs") is None:
                item["paragraphs"] = []
            if item.get("bullets") is None:
                item["bullets"] = []
            normalized_sections.append(item)
        raw["sections"] = normalized_sections
    try:
        normalized = normalize_document_spec(raw)
    except Exception as exc:
        setattr(exc, "model_invocations", invocations)
        raise
    if normalized["document_id"] != document_id:
        raise ValueError("cognition changed the stable Work document_id")
    return normalized, invocations


def _section_visible_chars(section: Mapping[str, Any]) -> int:
    return (
        len(str(section.get("heading") or ""))
        + sum(len(str(value)) for value in section.get("paragraphs") or ())
        + sum(len(str(value)) for value in section.get("bullets") or ())
    )


def _edit_spec(
    resident: Any,
    event: Any,
    *,
    current: Mapping[str, Any],
    section_index: int,
) -> tuple[dict[str, Any], int]:
    sections = list(current["sections"])
    if not 1 <= section_index <= len(sections):
        raise ValueError(f"requested section {section_index} is outside the current document")
    target = dict(sections[section_index - 1])
    task = str(getattr(event, "task", "") or "")
    lowered = task.casefold()
    wants_simplify = any(marker.casefold() in lowered for marker in _SIMPLIFY_MARKERS)
    wants_three = any(marker.casefold() in lowered for marker in _THREE_POINT_MARKERS)
    extra_rule = ""
    if wants_three:
        extra_rule += " Return exactly three bullets. "
    if wants_simplify:
        extra_rule += " Make the section materially shorter while preserving its core meaning. "
    question = (
        "Modify exactly one section from an existing DocumentSpec v1. Return one JSON "
        "section object only, no markdown. It must contain exactly id, heading, paragraphs, "
        "bullets. Keep id and heading exactly unchanged. Do not modify or discuss other "
        f"sections. {extra_rule} Do not invent metrics, customers, dates, financial claims "
        "or external facts. "
        f"Document title: {json.dumps(current['title'], ensure_ascii=False)}. "
        f"Current target section: {json.dumps(target, ensure_ascii=False)}. "
        f"User request: {task}"
    )
    raw, invocations = _model_result(
        resident,
        event,
        question,
        purpose="document_spec_edit_section",
    )
    raw = dict(raw)
    raw["id"] = target["id"]
    raw["heading"] = target["heading"]
    if raw.get("paragraphs") is None:
        raw["paragraphs"] = []
    if raw.get("bullets") is None:
        raw["bullets"] = []
    try:
        replacement = normalize_document_section(raw, index=section_index)
    except Exception as exc:
        setattr(exc, "model_invocations", invocations)
        raise
    if wants_three and len(replacement["bullets"]) != 3:
        raise ValueError("three-point edit did not produce exactly three bullets")
    if wants_simplify and _section_visible_chars(replacement) >= _section_visible_chars(target):
        raise ValueError("simplify edit did not make the target section shorter")
    updated = dict(current)
    updated["sections"] = [dict(section) for section in sections]
    updated["sections"][section_index - 1] = replacement
    return normalize_document_spec(updated), invocations


def _save_document(
    resident: Any,
    event: Any,
    *,
    thread_id: str,
    spec: Mapping[str, Any],
    previous: WorkArtifact | None,
    last_export: Mapping[str, Any] | None = None,
    selected_section_id: str | None = None,
) -> WorkArtifact:
    normalized = normalize_document_spec(spec)
    previous_meta = dict(previous.metadata) if previous is not None else {}
    revision = int(previous_meta.get("revision") or 0) + (0 if last_export is not None else 1)
    metadata: dict[str, Any] = {
        "document_spec_version": 1,
        "document_id": normalized["document_id"],
        "section_count": len(normalized["sections"]),
        "revision": max(1, revision),
        "latest_event_id": event.event_id,
        "status": "ready",
    }
    if previous_meta.get("last_export"):
        metadata["last_export"] = previous_meta["last_export"]
    if last_export is not None:
        metadata["last_export"] = dict(last_export)
    preferred = str(
        selected_section_id or previous_meta.get("selected_section_id") or ""
    ).strip()
    if preferred and any(section["id"] == preferred for section in normalized["sections"]):
        metadata["selected_section_id"] = preferred
    artifact = WorkArtifact(
        artifact_id=_document_artifact_id(thread_id),
        thread_id=thread_id,
        event_id=event.event_id,
        kind=_KIND,
        name=str(normalized["title"]),
        content=document_spec_json(normalized),
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
        "DOCX export requires the attached Work workspace or an existing Downloads folder"
    )


def _filename(title: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', title).strip(' .')
    value = re.sub(r"\s+", " ", value)[:80].rstrip(" .")
    return (value or "ZN Document") + ".docx"


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
        "create_docx_from_spec",
        event_id=event.event_id,
        destination_path=str(destination),
        spec=dict(spec),
    )
    if not result.success:
        raise RuntimeError(str(result.error or result.output or "DOCX export failed"))
    verification = dict(result.data)
    if verification.get("verified") is not True:
        raise RuntimeError("DOCX export did not pass fresh reopen verification")
    file_artifact = WorkArtifact(
        artifact_id=_file_artifact_id(thread_id, destination),
        thread_id=thread_id,
        event_id=event.event_id,
        kind="file",
        name=destination.name,
        path=str(destination),
        content="Verified DOCX export from current DocumentSpec v1",
        metadata={
            "mode": "document_export",
            "document_id": spec["document_id"],
            "verified": True,
            "paragraph_count": verification.get("paragraph_count"),
            "identity": verification.get("identity"),
            "structure_fingerprint": verification.get("structure_fingerprint"),
        },
        created_at=utc_now(),
    )
    resident.work_ledger._save_artifact(file_artifact)
    _save_document(
        resident,
        event,
        thread_id=thread_id,
        spec=spec,
        previous=artifact,
        last_export={
            "path": str(destination),
            "verified": True,
            "paragraph_count": verification.get("paragraph_count"),
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
        reason="document_work_failed_closed",
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
        reason="native Document Work completed through the existing Resident, Work and Body",
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
        return _fail(resident, event, state, "Document requires one current durable Root Work")
    state.data[_STATE_KEY] = {
        "operation": dict(operation),
        "thread_id": thread_id,
        "root_work_item_id": root.work_item_id,
        "plan_version": root.plan_version,
    }
    state.stage = "document_work"
    state.next_action = "update the current DocumentSpec and native Document Work artifact"
    state.blocked_by = None
    resident.store.save_working_state(state)
    return None


def _execute(resident: Any, event: Any, state: Any):
    meta = dict(state.data.get(_STATE_KEY) or {})
    operation = dict(meta.get("operation") or {})
    thread_id = str(meta.get("thread_id") or "")
    kind = str(operation.get("kind") or "")
    current_artifact = _document_artifact(resident, thread_id)
    current_spec = _document_spec(current_artifact)
    invocations = 0
    try:
        if kind == "create":
            spec, invocations = _create_spec(
                resident,
                event,
                thread_id=thread_id,
            )
            artifact = _save_document(
                resident,
                event,
                thread_id=thread_id,
                spec=spec,
                previous=current_artifact,
                selected_section_id="section-1",
            )
            return _finish(
                resident,
                event,
                state,
                f"Document workspace is ready with {len(spec['sections'])} sections: {artifact.name}.",
                model_invocations=invocations,
            )
        if kind == "edit":
            if current_artifact is None or current_spec is None:
                raise RuntimeError("current DocumentSpec is missing or invalid")
            section_index = int(operation.get("section_index") or 0)
            spec, invocations = _edit_spec(
                resident,
                event,
                current=current_spec,
                section_index=section_index,
            )
            _save_document(
                resident,
                event,
                thread_id=thread_id,
                spec=spec,
                previous=current_artifact,
                selected_section_id=f"section-{section_index}",
            )
            return _finish(
                resident,
                event,
                state,
                f"Section {section_index} updated in the current Document workspace.",
                model_invocations=invocations,
            )
        if kind == "export":
            if current_artifact is None or current_spec is None:
                raise RuntimeError("current DocumentSpec is missing or invalid")
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
                f"Verified DOCX exported and freshly reopened: {destination}",
                model_invocations=0,
            )
        raise RuntimeError("unsupported Document operation")
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


def install_document_work_behavior(resident: Any) -> None:
    if getattr(resident, _INSTALL_MARKER, False):
        return
    body = resident.body
    original_dispatch = body._dispatch

    def dispatch(action: Any, started: Any):
        if str(action.kind or "").lower() == "create_docx_from_spec":
            data = create_docx_from_spec(
                action.args.get("destination_path"),
                spec=dict(action.args.get("spec") or {}),
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
        if stage == "document_work":
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
