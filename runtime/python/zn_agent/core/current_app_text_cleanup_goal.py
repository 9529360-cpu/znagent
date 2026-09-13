from __future__ import annotations

"""Typed desired state and deterministic text transform for E2E-13.

This module contains no desktop authority.  A model, when used, may propose only
these semantic fields.  HWND/PID/RuntimeId/current application text, the
transformed text, Body actions and completion truth are deliberately absent.
"""

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping

CURRENT_APP_TEXT_CLEANUP_GOAL_KIND = "foreground_desktop_text_cleanup"
CURRENT_APP_TEXT_CLEANUP_GOAL_KEY = "current_app_text_cleanup_goal"
TRIM_DROP_BLANK_DEDUPE_STABLE = "trim_drop_blank_dedupe_stable"
MAX_CURRENT_APP_TEXT_CHARS = 4096

_FIELD_FROM_THIS_DOCUMENT = re.compile(
    r"(?:这份|这个|当前的?)(?P<name>[\u4e00-\u9fffA-Za-z0-9 _-]{1,32}?)(?:整理|处理|清理)"
)
_TRIM_CUES = ("首尾空格", "前后空格", "两端空格", "trim")
_BLANK_CUES = ("空行", "blank line")
_DUPLICATE_CUES = ("重复", "duplicate", "dedupe")
_ORDER_CUES = ("原来的顺序", "原顺序", "顺序不变", "保留顺序", "preserve order")
_SAVE_CUES = ("保存", "save")
_CURRENT_APP_CUES = (
    "现在这个软件",
    "当前这个软件",
    "这个软件",
    "当前软件",
    "当前应用",
    "现在开的软件",
    "already-open app",
    "current app",
)


@dataclass(frozen=True, slots=True)
class CurrentAppTextCleanupGoal:
    kind: str
    field_name: str
    save_button_name: str
    transform: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TextCleanupResult:
    """One transient deterministic transform result.

    ``result_text`` is intentionally the only raw-content member.  Callers must
    keep the instance on the current stack and persist ``audit`` only.
    """

    result_text: str
    source_chars: int
    source_sha256: str
    source_line_count: int
    result_chars: int
    result_sha256: str
    result_line_count: int
    removed_blank_line_count: int
    removed_duplicate_line_count: int

    @property
    def audit(self) -> dict[str, Any]:
        return {
            "source_chars": self.source_chars,
            "source_sha256": self.source_sha256,
            "source_line_count": self.source_line_count,
            "result_chars": self.result_chars,
            "result_sha256": self.result_sha256,
            "result_line_count": self.result_line_count,
            "removed_blank_line_count": self.removed_blank_line_count,
            "removed_duplicate_line_count": self.removed_duplicate_line_count,
            "transform": TRIM_DROP_BLANK_DEDUPE_STABLE,
        }


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def deterministic_text_cleanup(
    value: str,
    *,
    max_chars: int = MAX_CURRENT_APP_TEXT_CHARS,
) -> TextCleanupResult:
    if not isinstance(value, str):
        raise ValueError("current-app text content must be a string")
    if len(value) > int(max_chars):
        raise ValueError(f"current-app text exceeds the {int(max_chars)} character bound")

    lines = value.splitlines()
    retained: list[str] = []
    seen: set[str] = set()
    removed_blank = 0
    removed_duplicate = 0
    for source_line in lines:
        line = source_line.strip()
        if not line:
            removed_blank += 1
            continue
        if line in seen:
            removed_duplicate += 1
            continue
        seen.add(line)
        retained.append(line)

    result = "\r\n".join(retained)
    if not result:
        raise ValueError("deterministic cleanup would produce an empty result")
    if len(result) > int(max_chars):
        raise ValueError(f"deterministic cleanup result exceeds the {int(max_chars)} character bound")

    return TextCleanupResult(
        result_text=result,
        source_chars=len(value),
        source_sha256=text_sha256(value),
        source_line_count=len(lines),
        result_chars=len(result),
        result_sha256=text_sha256(result),
        result_line_count=len(retained),
        removed_blank_line_count=removed_blank,
        removed_duplicate_line_count=removed_duplicate,
    )


def current_app_text_cleanup_goal(event) -> CurrentAppTextCleanupGoal | None:
    payload = getattr(event, "payload", {}) or {}
    raw = payload.get(CURRENT_APP_TEXT_CLEANUP_GOAL_KEY)
    if raw is not None:
        return validate_current_app_text_cleanup_goal(
            str(getattr(event, "task", "") or ""),
            raw,
        )
    return explicit_current_app_text_cleanup_goal_hint(event)


def explicit_current_app_text_cleanup_goal_hint(event) -> CurrentAppTextCleanupGoal | None:
    if str(getattr(event, "kind", "") or "").strip().lower() != "desktop_user_event":
        return None
    payload = getattr(event, "payload", {}) or {}
    if payload.get("body_action") or payload.get("native_action"):
        return None
    task = " ".join(str(getattr(event, "task", "") or "").split())
    if not _has_cleanup_semantics(task) or not _contains_any(task, _CURRENT_APP_CUES):
        return None

    field_name = "工作记录" if "工作记录" in task else ""
    if not field_name:
        match = _FIELD_FROM_THIS_DOCUMENT.search(task)
        if match is not None:
            field_name = " ".join(match.group("name").strip().split())
    if not field_name or field_name not in task:
        return None
    save_name = "保存" if "保存" in task else "save" if "save" in task.casefold() else ""
    if not save_name:
        return None
    return CurrentAppTextCleanupGoal(
        kind=CURRENT_APP_TEXT_CLEANUP_GOAL_KIND,
        field_name=field_name,
        save_button_name=save_name,
        transform=TRIM_DROP_BLANK_DEDUPE_STABLE,
    )


def validate_current_app_text_cleanup_goal(
    task: str,
    raw: Mapping[str, Any] | Any,
) -> CurrentAppTextCleanupGoal | None:
    """Accept only semantic desired state grounded in the user's own request."""

    if not isinstance(raw, Mapping):
        return None
    allowed = {"kind", "field_name", "save_button_name", "transform"}
    if set(raw) != allowed:
        return None
    normalized_task = " ".join(str(task or "").split())
    if not _has_cleanup_semantics(normalized_task):
        return None
    kind = str(raw.get("kind") or "").strip()
    field_name = " ".join(str(raw.get("field_name") or "").strip().split())
    save_name = " ".join(str(raw.get("save_button_name") or "").strip().split())
    transform = str(raw.get("transform") or "").strip()
    if kind != CURRENT_APP_TEXT_CLEANUP_GOAL_KIND or transform != TRIM_DROP_BLANK_DEDUPE_STABLE:
        return None
    if not _safe_semantic_name(field_name) or not _safe_semantic_name(save_name):
        return None
    if field_name not in normalized_task:
        return None
    if save_name.casefold() not in normalized_task.casefold():
        return None
    return CurrentAppTextCleanupGoal(
        kind=kind,
        field_name=field_name,
        save_button_name=save_name,
        transform=transform,
    )


def _has_cleanup_semantics(task: str) -> bool:
    lowered = str(task or "").casefold()
    return bool(
        _contains_any(lowered, _TRIM_CUES)
        and _contains_any(lowered, _BLANK_CUES)
        and _contains_any(lowered, _DUPLICATE_CUES)
        and _contains_any(lowered, _ORDER_CUES)
        and _contains_any(lowered, _SAVE_CUES)
    )


def _contains_any(text: str, cues: tuple[str, ...]) -> bool:
    lowered = str(text or "").casefold()
    return any(str(cue).casefold() in lowered for cue in cues)


def _safe_semantic_name(value: str) -> bool:
    return bool(
        value
        and len(value) <= 80
        and not any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    )
