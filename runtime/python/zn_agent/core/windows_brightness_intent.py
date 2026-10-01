from __future__ import annotations

"""Deterministic natural-language intents for Windows screen brightness."""

import math
import re
from dataclasses import dataclass
from typing import Any

from .execution_mode import event_allows_effects

_SET_PATTERNS = (
    re.compile(
        r"^(?:请|帮我|麻烦)?\s*(?:把)?\s*(?:屏幕|系统)?\s*亮度\s*"
        r"(?:调到|调成|设为|设置为|设成|改成|提高到|降低到)\s*"
        r"(?P<level>\d+(?:\.\d+)?)\s*[%％]?\s*[。.!！]?$",
        re.I,
    ),
    re.compile(
        r"^(?:please\s+)?(?:set|change)\s+(?:the\s+)?(?:screen\s+)?brightness"
        r"\s+(?:to\s+)?(?P<level>\d+(?:\.\d+)?)\s*%?\s*[.!]?\s*$",
        re.I,
    ),
)

_READ_PATTERNS = (
    re.compile(
        r"^(?:请|帮我)?\s*(?:查一下|看看|告诉我)?\s*(?:现在|当前)?\s*"
        r"(?:屏幕|系统)?\s*亮度(?:是)?\s*(?:多少|几)(?:[%％])?\s*[？?。.!！]?$",
        re.I,
    ),
    re.compile(
        r"^(?:what(?:'s| is)|tell me)\s+(?:the\s+)?(?:current\s+)?"
        r"(?:screen\s+)?brightness(?:\s+level)?\s*[?]?\s*$",
        re.I,
    ),
)


@dataclass(frozen=True, slots=True)
class WindowsBrightnessSetGoal:
    level_percent: float


@dataclass(frozen=True, slots=True)
class WindowsBrightnessReadGoal:
    pass


def windows_brightness_set_goal(event: Any) -> WindowsBrightnessSetGoal | None:
    if not event_allows_effects(event) or not _eligible_event(event):
        return None
    task = _task(event)
    if not task:
        return None
    for pattern in _SET_PATTERNS:
        match = pattern.match(task)
        if match is None:
            continue
        level = _finite_number(match.group("level"))
        return WindowsBrightnessSetGoal(level) if level is not None else None
    return None


def windows_brightness_read_goal(event: Any) -> WindowsBrightnessReadGoal | None:
    if not _eligible_event(event):
        return None
    task = _task(event)
    if not task:
        return None
    return (
        WindowsBrightnessReadGoal()
        if any(pattern.match(task) for pattern in _READ_PATTERNS)
        else None
    )


def _eligible_event(event: Any) -> bool:
    payload = getattr(event, "payload", {}) or {}
    return bool(
        str(getattr(event, "kind", "") or "").strip().lower() == "desktop_user_event"
        and isinstance(payload, dict)
        and not payload.get("body_action")
        and not payload.get("native_action")
    )


def _task(event: Any) -> str:
    task = " ".join(str(getattr(event, "task", "") or "").strip().split())
    return task if 0 < len(task) <= 180 else ""


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
