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
    r"(?:(?:当前(?:打开的)?|已打开的)(?:软件|程序)(?:对应的|里的|里|的)?|当前程序对应的)?\s*"
    r"(?P<name>[A-Za-z0-9_\-\u4e00-\u9fff]{0,32}?)(?P<role>输入框|文本框|搜索框|字段)"
)
_NAMED_DESTINATION_PATTERNS = (
    re.compile(
        r"(?:找到|使用|选择)?\s*(?P<role>输入框|文本框|字段)\s*[\"“'‘]"
        r"(?P<name>[^\"”'’‘，,。；;\r\n]{1,160})[\"”'’]"
    ),
    re.compile(
        r"[\"“'‘](?P<name>[^\"”'’‘，,。；;\r\n]{1,160})[\"”'’]\s*"
        r"(?P<role>输入框|文本框|字段)"
    ),
)
_SUBMIT_RE = re.compile(
    r"^(?:点|点击|按下|选择)?\s*(?:按钮)?\s*[\"“'‘]?"
    r"(?P<name>[A-Za-z0-9_\-\u4e00-\u9fff]{1,32}?)[\"”'’]?"
    r"(?=后|并|，|,|。|；|;|$)"
)
_VALUE_BEFORE_DESTINATION_RE = re.compile(
    r"把\s*(?P<name>[^，,。；;\r\n]{1,64}?)\s*(?:填|输入|写|放)(?:到|进|入)?"
)
_SOURCE_HINT_RE = re.compile(
    r"名字(?:里)?(?:像|包含|带有|带)\s*[\"“'‘]?(?P<hint>[^\"”'’‘，,。；;\r\n]{1,64}?)[\"”'’]?\s*"
    r"的(?:那个|那份|那个文件|文件)?\s*\.?\s*txt(?=[，,。；;\s]|$)",
    re.I,
)
_YESTERDAY_HINT_RE = re.compile(
    r"昨天(?:那份|那个|的)?(?P<hint>[A-Za-z0-9_\-\u4e00-\u9fff]{1,32}?)(?:资料|文件|txt)"
)
_FINAL_TITLE_RE = re.compile(
    r"(?:窗口|软件|界面)(?:标题)?\s*(?:会)?\s*(?:变成|变为|显示为|显示成|显示)\s*[\"“'‘]?"
    r"(?P<title>[^\"”'’‘，,。；;\r\n]{1,160}?)[\"”'’]?"
    r"(?=后|并|，|,|。|；|;|确认|$)"
)
_FILL_CUE_RE = re.compile(r"(?:填|输入|写|放)(?:到|进|入)?")


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

    source_requirement = _natural_source_requirement(task, payload)
    if source_requirement is None:
        return None
    destination = _natural_destination(task)
    if destination is None:
        return None

    value_name = str(source_requirement.get("value_semantic_name") or "").strip()
    raw_target_name = _clean_semantic(destination["name"])
    target_name = _input_semantic_name(
        raw_target_name,
        destination["role"],
        value_name=value_name,
    )
    target_binding = "exact_name" if target_name else "focused_safe_edit"

    fill_matches = list(_FILL_CUE_RE.finditer(task))
    tail_start = max(
        int(destination["end"]),
        max((match.end() for match in fill_matches), default=int(destination["end"])),
    )
    submit_name = _submit_name(task[tail_start:])
    final_title = _final_title(task)
    if final_title and not submit_name:
        return None

    if submit_name:
        expected_final_state = (
            {"kind": "foreground_title_equals", "title": final_title}
            if final_title
            else {"kind": "foreground_title_changed"}
        )
    else:
        expected_final_state = {"kind": "text_matches"}

    return {
        "kind": "desktop_value_task",
        "source_requirement": source_requirement,
        "destination_app_scope": {"kind": "current_foreground_non_browser"},
        "target_input_binding": target_binding,
        "target_input_semantic_name": target_name,
        "submit_control_semantic_name": submit_name,
        "expected_final_state": expected_final_state,
    }


def _natural_source_requirement(
    task: str,
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    workspace = str(payload.get("workspace_path") or "").strip()
    if workspace and any(token in task for token in ("文件", "资料", "txt")):
        hint_match = _SOURCE_HINT_RE.search(task) or _YESTERDAY_HINT_RE.search(task)
        hint = _clean_semantic(hint_match.group("hint")) if hint_match else None
        return {
            "kind": "workspace_file",
            "workspace_path": workspace,
            "name_hint": hint,
            "modified_day": "yesterday" if "昨天" in task else None,
            "value_semantic_name": _value_semantic_name(task) or "file_text",
        }

    lowered = task.lower()
    current_page = any(
        cue in lowered
        for cue in ("current browser page", "current page", "authorized page")
    ) or any(
        cue in task
        for cue in ("当前浏览器页面", "当前页面", "已授权的当前浏览器", "已授权页面")
    )
    references = "reference" in lowered or "参考" in task
    agreement = any(cue in lowered for cue in ("agree", "same", "consistent")) or any(
        cue in task for cue in ("一致", "相同", "共同")
    )
    release_code = bool(
        "release code" in lowered
        or ("release" in lowered and "code" in lowered)
        or "发布代码" in task
        or "发行代码" in task
    )
    if current_page and references and agreement and release_code:
        return {
            "kind": "managed_browser_research",
            "value_semantic_name": "release code",
            "require_two_sources": True,
        }
    return None


def _natural_destination(task: str) -> dict[str, Any] | None:
    direct = _DESTINATION_RE.search(task)
    if direct is not None:
        return {
            "name": direct.group("name"),
            "role": direct.group("role"),
            "start": direct.start(),
            "end": direct.end(),
        }
    if not _FILL_CUE_RE.search(task):
        return None
    matches: list[dict[str, Any]] = []
    for pattern in _NAMED_DESTINATION_PATTERNS:
        for match in pattern.finditer(task):
            item = {
                "name": match.group("name"),
                "role": match.group("role"),
                "start": match.start(),
                "end": match.end(),
            }
            if item not in matches:
                matches.append(item)
    if len(matches) != 1:
        return None
    return matches[0]


def _validated_proposal(
    task: str,
    payload: Mapping[str, Any],
    proposed: Mapping[str, Any],
) -> dict[str, Any] | None:
    if any(key in proposed for key in _FORBIDDEN_AUTHORITY_FIELDS):
        return None
    if str(proposed.get("kind") or "").strip() not in {
        "desktop_value_task",
        "desktop_value_submit",
    }:
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

    binding = str(proposed.get("target_input_binding") or "exact_name").strip()
    if binding not in {"exact_name", "focused_safe_edit"}:
        return None
    target_name = _clean_semantic(proposed.get("target_input_semantic_name")) or None
    if binding == "exact_name":
        if not target_name or not _semantic_grounded_in_task(task, target_name):
            return None
    elif target_name is not None:
        return None

    submit_name = _clean_semantic(proposed.get("submit_control_semantic_name")) or None
    if submit_name and not _traceable_semantic(task, submit_name):
        return None

    final_kind = str(final.get("kind") or "").strip()
    if submit_name:
        if final_kind not in {"foreground_title_changed", "foreground_title_equals"}:
            return None
    elif final_kind != "text_matches":
        return None
    final_title = None
    if final_kind == "foreground_title_equals":
        final_title = _clean_semantic(final.get("title"))
        if not final_title or not _traceable_semantic(task, final_title):
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

    normalized_final = {"kind": final_kind}
    if final_title:
        normalized_final["title"] = final_title
    return {
        "kind": "desktop_value_task",
        "source_requirement": normalized_source,
        "destination_app_scope": {"kind": "current_foreground_non_browser"},
        "target_input_binding": binding,
        "target_input_semantic_name": target_name,
        "submit_control_semantic_name": submit_name,
        "expected_final_state": normalized_final,
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
        "里面的",
        "查到的",
        "确认的",
    ):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    return _clean_semantic(value)


def _input_semantic_name(raw: str, role: str, *, value_name: str) -> str | None:
    value = _clean_semantic(raw)
    if not value and role == "搜索框":
        value = _base_value_semantic(value_name)
    if not value:
        return None
    if role == "搜索框" and not value.endswith("搜索"):
        value += "搜索"
    return value[:_MAX_SEMANTIC_NAME]


def _base_value_semantic(value: str) -> str:
    text = _clean_semantic(value)
    for suffix in ("编号", "号码", "号", "代码", "code", "Code", "CODE"):
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def _submit_name(tail: str) -> str | None:
    text = str(tail or "").lstrip("里中内去 ，,；;")
    if not text:
        return None
    for marker in ("然后", "再", "随后", "并且"):
        if text.startswith(marker):
            text = text[len(marker) :].strip()
            break
    text = text.lstrip(" ，,；;")
    normalized = re.sub(r"^(?:点|点击|按下|选择)\s*(?:按钮)?\s*", "", text)
    if normalized.startswith("提交"):
        return "提交"
    if normalized.startswith("打开结果"):
        return "打开结果"
    match = _SUBMIT_RE.search(text)
    return _clean_semantic(match.group("name")) if match else None


def _final_title(task: str) -> str | None:
    match = _FINAL_TITLE_RE.search(task)
    return _clean_semantic(match.group("title")) if match else None


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
