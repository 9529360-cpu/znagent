from __future__ import annotations

"""Typed desired state for a workspace-to-desktop user goal.

``DesktopTaskGoal`` is goal data, not an action sequence and not current-world
authority.  ``ResidentGoalRuntime`` still forms one movement at a time from fresh
file, foreground-window and UI Automation evidence.

The regular expressions in this module are only a deterministic fast path for
explicitly worded requests.  They are not the product language boundary: when
this fast path does not apply, the existing bounded goal-understanding layer may
propose the same typed goal and Resident still owns grounding, authority and
completion.
"""

import re
from dataclasses import dataclass
from typing import Any, Mapping


DESKTOP_TASK_GOAL_KIND = "workspace_to_foreground_desktop"

_QUOTED_INPUT = re.compile(
    r"(?:输入框|文本框|字段)\s*[\"“'‘](?P<name>[^\"”'’‘，,。；;\r\n]{1,160})[\"”'’]"
)
_NAMED_SEARCH = re.compile(
    r"(?P<name>账号|订单号?|订单搜索|[^，,。；;\r\n]{1,24}?)\s*(?:输入框|搜索框)"
)
_FILE_HINT = re.compile(
    r"名字(?:里)?(?:像|包含|带有|带)\s*[\"“'‘]?(?P<name>[^\"”'’‘，,。；;\r\n]{1,64}?)[\"”'’]?\s*"
    r"的(?:那个|那份|文件)?\s*\.?\s*txt",
    re.I,
)
_BUTTON = re.compile(
    r"(?:点击|点|按|提交(?:到)?)\s*(?:按钮)?\s*[\"“'‘]?(?P<name>[^\"”'’‘，,。；;后\r\n]{1,64})[\"”'’]?"
)
_FINAL_TITLE = re.compile(
    r"窗口(?:变成|显示为|标题为)\s*[\"“'‘]?(?P<title>[^\"”'’‘，,。；;\r\n]{1,160})[\"”'’]?"
)


@dataclass(frozen=True, slots=True)
class DesktopTaskGoal:
    workspace_path: str
    source_name_hint: str
    input_name: str
    button_name: str
    expected_title: str | None = None
    source_modified_yesterday: bool = False


def desktop_task_goal_payload(goal: DesktopTaskGoal) -> dict[str, Any]:
    """Persist only semantic desired-state data, never current-world authority."""

    return {
        "kind": DESKTOP_TASK_GOAL_KIND,
        "source_name_hint": goal.source_name_hint,
        "input_name": goal.input_name,
        "button_name": goal.button_name,
        "expected_title": goal.expected_title,
        "source_modified_yesterday": goal.source_modified_yesterday,
    }


def desktop_task_goal(event) -> DesktopTaskGoal | None:
    """Return an already-typed goal or one optional explicit-language fast path."""

    payload = event.payload or {}
    if (
        str(event.kind or "").lower() != "desktop_user_event"
        or not str(payload.get("workspace_path") or "").strip()
        or payload.get("body_action")
        or payload.get("native_action")
    ):
        return None

    structured = payload.get("desktop_task_goal")
    if isinstance(structured, Mapping):
        return _structured_desktop_task_goal(
            workspace_path=str(payload["workspace_path"]),
            structured=structured,
        )

    return explicit_desktop_task_goal_hint(event)


def explicit_desktop_task_goal_hint(event) -> DesktopTaskGoal | None:
    """Deterministic optimization for explicit wording, never the language gate."""

    payload = event.payload or {}
    if (
        str(event.kind or "").lower() != "desktop_user_event"
        or not str(payload.get("workspace_path") or "").strip()
        or payload.get("body_action")
        or payload.get("native_action")
    ):
        return None

    task = " ".join(str(event.task or "").strip().split())
    if not task or not any(word in task for word in ("填", "输入", "放到")):
        return None
    if not any(word in task for word in ("点击", "点查询", "提交", "打开结果")):
        return None

    quoted = _QUOTED_INPUT.search(task)
    named = _NAMED_SEARCH.search(task)
    input_name = _clean(
        quoted.group("name") if quoted else named.group("name") if named else ""
    )
    hint_match = _FILE_HINT.search(task)
    if hint_match:
        hint = _clean(hint_match.group("name"))
    elif "订单" in task:
        hint = "订单"
    elif "账号" in task:
        hint = "账号"
    else:
        hint = ""

    button_match = _BUTTON.search(task)
    if button_match:
        button_name = _clean(button_match.group("name"))
    elif "打开结果" in task:
        button_name = "打开结果"
    elif "查询" in task:
        button_name = "查询"
    elif "提交" in task:
        button_name = "提交"
    else:
        button_name = ""
    title_match = _FINAL_TITLE.search(task)
    expected_title = _clean(title_match.group("title")) if title_match else None
    if not (hint and input_name and button_name):
        return None
    return DesktopTaskGoal(
        workspace_path=str(payload["workspace_path"]),
        source_name_hint=hint,
        input_name=input_name,
        button_name=button_name,
        expected_title=expected_title,
        source_modified_yesterday="昨天" in task,
    )


def _structured_desktop_task_goal(
    *,
    workspace_path: str,
    structured: Mapping[str, Any],
) -> DesktopTaskGoal | None:
    kind = _clean(structured.get("kind"))
    if kind and kind != DESKTOP_TASK_GOAL_KIND:
        return None
    hint = _clean(structured.get("source_name_hint"))
    input_name = _clean(structured.get("input_name"))
    button_name = _clean(structured.get("button_name"))
    title = _clean(structured.get("expected_title")) or None
    modified_yesterday = structured.get("source_modified_yesterday", False)
    if not isinstance(modified_yesterday, bool):
        return None
    if (
        not hint
        or not input_name
        or not button_name
        or len(hint) > 64
        or len(input_name) > 160
        or len(button_name) > 160
        or (title is not None and len(title) > 160)
    ):
        return None
    return DesktopTaskGoal(
        workspace_path=workspace_path,
        source_name_hint=hint,
        input_name=input_name,
        button_name=button_name,
        expected_title=title,
        source_modified_yesterday=modified_yesterday,
    )


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())
