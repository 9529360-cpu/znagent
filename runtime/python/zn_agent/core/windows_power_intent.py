from __future__ import annotations

"""Deterministic read-only natural-language views over Windows power context."""

import re
from dataclasses import dataclass
from typing import Any

_BATTERY_LEVEL_PATTERNS = (
    re.compile(
        r"^(?:请|帮我)?\s*(?:查一下|看看|告诉我)?\s*(?:现在|当前)?\s*"
        r"(?:电脑|笔记本)?\s*(?:电池)?电量(?:还剩|是)?\s*(?:多少|几)(?:[%％])?\s*[？?。.!！]?$",
        re.I,
    ),
    re.compile(
        r"^(?:how much battery(?: is)? left|what(?:'s| is) (?:the )?(?:current )?battery"
        r"(?: percentage| level)?)\s*[?]?\s*$",
        re.I,
    ),
)

_POWER_SOURCE_PATTERNS = (
    re.compile(
        r"^(?:请|帮我)?\s*(?:看看|告诉我)?\s*(?:电脑|笔记本)?\s*"
        r"(?:现在|当前)?\s*(?:插电了吗|接电源了吗|在用电池还是电源|电源接着吗)\s*[？?。.!！]?$",
        re.I,
    ),
    re.compile(
        r"^(?:is (?:the )?(?:computer|laptop) plugged in|"
        r"what(?:'s| is) (?:the )?(?:current )?power source)\s*[?]?\s*$",
        re.I,
    ),
)

_CHARGING_PATTERNS = (
    re.compile(
        r"^(?:请|帮我)?\s*(?:看看|告诉我)?\s*(?:现在|当前)?\s*"
        r"(?:电池|电脑|笔记本)?\s*(?:在充电吗|正在充电吗|充电了吗)\s*[？?。.!！]?$",
        re.I,
    ),
    re.compile(
        r"^(?:is (?:the )?(?:battery|computer|laptop) charging|"
        r"is (?:the )?battery being charged)\s*[?]?\s*$",
        re.I,
    ),
)

_BATTERY_SAVER_PATTERNS = (
    re.compile(
        r"^(?:请|帮我)?\s*(?:看看|告诉我)?\s*(?:现在|当前)?\s*"
        r"(?:省电模式|节电模式)(?:是)?\s*(?:开着吗|开启了吗|打开了吗|什么状态)\s*[？?。.!！]?$",
        re.I,
    ),
    re.compile(
        r"^(?:is (?:battery saver|power saver) (?:on|enabled)|"
        r"what(?:'s| is) (?:the )?(?:battery saver|power saver) status)\s*[?]?\s*$",
        re.I,
    ),
)


@dataclass(frozen=True, slots=True)
class WindowsBatteryLevelReadGoal:
    pass


@dataclass(frozen=True, slots=True)
class WindowsPowerSourceReadGoal:
    pass


@dataclass(frozen=True, slots=True)
class WindowsBatteryChargingReadGoal:
    pass


@dataclass(frozen=True, slots=True)
class WindowsBatterySaverReadGoal:
    pass


def windows_battery_level_read_goal(event: Any) -> WindowsBatteryLevelReadGoal | None:
    return WindowsBatteryLevelReadGoal() if _matches(event, _BATTERY_LEVEL_PATTERNS) else None


def windows_power_source_read_goal(event: Any) -> WindowsPowerSourceReadGoal | None:
    return WindowsPowerSourceReadGoal() if _matches(event, _POWER_SOURCE_PATTERNS) else None


def windows_battery_charging_read_goal(event: Any) -> WindowsBatteryChargingReadGoal | None:
    return WindowsBatteryChargingReadGoal() if _matches(event, _CHARGING_PATTERNS) else None


def windows_battery_saver_read_goal(event: Any) -> WindowsBatterySaverReadGoal | None:
    return WindowsBatterySaverReadGoal() if _matches(event, _BATTERY_SAVER_PATTERNS) else None


def _matches(event: Any, patterns: tuple[re.Pattern[str], ...]) -> bool:
    if not _eligible_event(event):
        return False
    task = _task(event)
    return bool(task and any(pattern.match(task) for pattern in patterns))


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
