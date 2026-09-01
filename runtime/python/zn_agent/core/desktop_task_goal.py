from __future__ import annotations

"""Typed desired state for carrying investigated values into the current desktop app.

This module owns no runtime, UI authority, selector, RuntimeId, process identity,
action permission or completion judgment. It only normalizes user-owned task data
that the Resident must subsequently ground against fresh filesystem/browser/UIA
reality.
"""

import re
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from .models import AgentEvent

_MAX_SEMANTIC_NAME = 160
_MAX_TASK_CHARS = 1600
_FORBIDDEN_AUTHORITY_FIELDS = frozenset(
    {
        "runtime_id",
        "process_id",
        "process_name",
        "selector",
        "automation_id",
        "coordinates",
        "x_fraction",
        "y_fraction",
        "completion_verified",
        "authorized",
    }
)
_DESTINATION_RE = re.compile(
    r"(?:填|输入|写|放)(?:到|进|入)?\s*"
    r"(?:(?:当前|已打开的)(?:软件|程序)(?:对应的|里的|里|的)?|当前程序对应的)?\s*"
    r"(?P<name>[A-Za-z0-9_\-\u4e00-\u9fff]{0,32}?)(?P<role>输入框|文本框|搜索框|字段)"
)
_SUBMIT_RE = re.compile(
    r"(?:点|点击|按下|选择)?\s*(?P<name>[A-Za-z0-9_\-\u4e00-\u9fff]{1,32}?)(?=后|并|，|,|。|；|;|$)"
)
_VALUE_BEFORE_DESTINATION_RE = re.compile(
    r"把\s*(?P<name>[A-Za-z0-9_\-\u4e00-\u9fff]{1,40}?)\s*(?:填|输入|写|放)(?:到|进|入)?"
)
_SOURCE_HINT_RE = re.compile(
    r"昨天(?:那份|那个|的)?(?P<hint>[A-Za-z0-9_\-\u4e00-\u9fff]{1,32}?)(?:资料|文件|txt)"
)


def desktop_task_request(event: "AgentEvent") -> dict[str, Any] | None:
    payload = event.payload or {}
    if (
        str(event.kind or "").strip().lower() != "desktop_user_event"
        or payload.get("body_action")
        or payload.get("native_action")
    ):
        return None
    task = " ".join(str(event.task or "").strip().split())
    if not task or len(task) > _MAX_TASK_CHARS:
        return None

    proposed = payload.get("resident_desktop_task")
    if isinstance(proposed, Mapping):
        return _validated_proposal(task, payload, proposed)

    workspace = str(payload.get("workspace_path") or "").strip()
    if not workspace or not any(token in task for token in ("文件", "资料", "txt")):
        return None
    destination = _DESTINATION_RE.search(task)
    if destination is None:
        return None
    value_name = _value_semantic_name(task)
    target_name = _input_semantic_name(
        destination.group("name"),
        destination.group("role"),
        value_name=value_name,
    )
    if not target_name:
        return None

    tail = task[destination.end() :]
    submit_name = _submit_name(tail)
    if not submit_name:
        return None

    hint_match = _SOURCE_HINT_RE.search(task)
    hint = _clean_semantic(hint_match.group("hint")) if hint_match else None
    modified_day = "yesterday" if "昨天" in task else None

    return {
        "kind": "desktop_value_submit",
        "source_requirement": {
            "kind": "workspace_file",
            "workspace_path": workspace,
            "name_hint": hint,
            "modified_day": modified_day,
            "value_semantic_name": value_name or "file_text",
        },
        "destination_app_scope": {"kind": "current_foreground_non_browser"},
        "target_input_semantic_name": target_name,
        "submit_control_semantic_name": submit_name,
        "expected_final_state": {"kind": "foreground_title_changed"},
    }


def _validated_proposal(
    task: str,
    payload: Mapping[str, Any],
    proposed: Mapping[str, Any],
) -> dict[str, Any] | None:
    if any(key in proposed for key in _FORBIDDEN_AUTHORITY_FIELDS):
        return None
    if str(proposed.get("kind") or "").strip() != "desktop_value_submit":
        return None
    source = proposed.get("source_requirement")
    app_scope = proposed.get("destination_app_scope")
    final = proposed.get("expected_final_state")
    if not isinstance(source, Mapping) or not isinstance(app_scope, Mapping) or not isinstance(final, Mapping):
        return None
    if any(key in source for key in _FORBIDDEN_AUTHORITY_FIELDS):
        return None
    if any(key in app_scope for key in _FORBIDDEN_AUTHORITY_FIELDS):
        return None
    if any(key in final for key in _FORBIDDEN_AUTHORITY_FIELDS):
        return None

    source_kind = str(source.get("kind") or "").strip()
    if source_kind not in {"workspace_file", "managed_browser_research"}:
        return None
    if str(app_scope.get("kind") or "").strip() != "current_foreground_non_browser":
        return None
    if str(final.get("kind") or "").strip() != "foreground_title_changed":
        return None

    target_name = _clean_semantic(proposed.get("target_input_semantic_name"))
    submit_name = _clean_semantic(proposed.get("submit_control_semantic_name"))
    if not target_name or not submit_name:
        return None
    # Parser/model output may normalize a visible role (for example 订单编号 ->
    # 订单搜索) but may not invent unrelated task concepts.
    if not _semantic_grounded_in_task(task, target_name) or not _traceable_semantic(task, submit_name):
        return None

    if source_kind == "workspace_file":
        workspace = str(payload.get("workspace_path") or "").strip()
        if not workspace or str(source.get("workspace_path") or "").strip() != workspace:
            return None
        hint = _clean_semantic(source.get("name_hint")) or None
        if hint and not _traceable_semantic(task, hint):
            return None
        modified_day = str(source.get("modified_day") or "").strip().lower() or None
        if modified_day not in {None, "yesterday"}:
            return None
        if modified_day == "yesterday" and "昨天" not in task:
            return None
        value_name = _clean_semantic(source.get("value_semantic_name")) or "file_text"
        if value_name != "file_text" and not _semantic_grounded_in_task(task, value_name):
            return None
        normalized_source = {
            "kind": "workspace_file",
            "workspace_path": workspace,
            "name_hint": hint,
            "modified_day": modified_day,
            "value_semantic_name": value_name,
        }
    else:
        result_name = _clean_semantic(source.get("value_semantic_name"))
        if not result_name or not _semantic_grounded_in_task(task, result_name):
            return None
        normalized_source = {
            "kind": "managed_browser_research",
            "value_semantic_name": result_name,
            "require_two_sources": True,
        }

    return {
        "kind": "desktop_value_submit",
        "source_requirement": normalized_source,
        "destination_app_scope": {"kind": "current_foreground_non_browser"},
        "target_input_semantic_name": target_name,
        "submit_control_semantic_name": submit_name,
        "expected_final_state": {"kind": "foreground_title_changed"},
    }


def _value_semantic_name(task: str) -> str:
    match = _VALUE_BEFORE_DESTINATION_RE.search(task)
    value = _clean_semantic(match.group("name")) if match else ""
    for prefix in (
        "文件里的",
        "文件中的",
        "文件里",
        "资料里的",
        "资料中的",
        "资料里",
    ):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    return _clean_semantic(value)


def _input_semantic_name(raw: str, role: str, *, value_name: str) -> str:
    value = _clean_semantic(raw)
    if not value:
        value = _base_value_semantic(value_name)
    if role == "搜索框" and value and not value.endswith("搜索"):
        value += "搜索"
    return value[:_MAX_SEMANTIC_NAME]


def _base_value_semantic(value: str) -> str:
    text = _clean_semantic(value)
    for suffix in ("编号", "号码", "号", "代码", "code", "Code", "CODE"):
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def _submit_name(tail: str) -> str | None:
    text = str(tail or "").strip(" ，,；;")
    if not text:
        return None
    for marker in ("然后", "再", "随后", "并且"):
        if text.startswith(marker):
            text = text[len(marker) :].strip()
            break
    text = re.sub(r"^(?:点|点击|按下|选择)\s*", "", text)
    if text.startswith("提交"):
        return "提交"
    if text.startswith("打开结果"):
        return "打开结果"
    match = _SUBMIT_RE.search(text)
    return _clean_semantic(match.group("name")) if match else None


def _clean_semantic(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    return text.strip("的把将到进里中“”‘’\"'，,。；;：:")[:_MAX_SEMANTIC_NAME]


def _traceable_semantic(task: str, value: str) -> bool:
    needle = "".join(str(value or "").split()).casefold()
    haystack = "".join(str(task or "").split()).casefold()
    return bool(needle and needle in haystack)


def _semantic_grounded_in_task(task: str, value: str) -> bool:
    if _traceable_semantic(task, value):
        return True
    normalized = _clean_semantic(value)
    if normalized.endswith("搜索"):
        normalized = normalized[: -len("搜索")]
    base = _base_value_semantic(normalized)
    return bool(base and _traceable_semantic(task, base))
