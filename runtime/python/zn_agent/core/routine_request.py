from __future__ import annotations

"""Parse one user sentence into a routine-creation draft.

Pure function, no I/O: the workbench sends one sentence ("每个工作日 9 点
汇总昨天的进展") and gets back a draft carrying the six confirmations a
routine needs before it may run:

1. owner (负责人)
2. schedule + timezone (时间表与时区)
3. input source (输入来源)
4. expected result (预期结果)
5. approval boundary (审批边界)
6. missing-data policy (数据源缺失时怎么办)

Conservative by design: a schedule clause is only recognized when an
explicit schedule pattern matches. Everything else stays in the task text,
and unparsed schedule / empty task are reported in ``missing`` so the
confirmation UI asks the user instead of silently inventing a schedule.
"""

import re
from dataclasses import asdict, dataclass, field

from .routine_schedule import (
    MIN_ROUTINE_INTERVAL_SECONDS,
    RoutineSchedule,
    local_timezone_name,
    parse_cron,
)

MISSING_DATA_POLICIES: tuple[str, ...] = ("skip", "notify", "use_last_known")

DEFAULT_OWNER = "ZN"
DEFAULT_INPUT_SOURCE = "ZN 记忆与当前工作现场"
DEFAULT_APPROVAL_BOUNDARY = (
    "只读汇总，不发送、不发布、不删除、不购买；超出范围需审批"
)
DEFAULT_MISSING_DATA_POLICY = "skip"
DEFAULT_AUTO_PAUSE_AFTER_DAYS = 14

#: Chinese weekday characters -> cron day-of-week (0 = Sunday).
_ZH_WEEKDAYS: dict[str, int] = {
    "日": 0,
    "天": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
}

#: English weekday names -> cron day-of-week.
_EN_WEEKDAYS: dict[str, int] = {
    "sunday": 0,
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
}

#: Time-of-day words that shift a bare hour into the afternoon/evening.
_AFTERNOON_MARKERS = ("下午", "晚上", "傍晚", "夜里", "pm", "p.m.")
_NOON_MARKERS = ("中午", "正午")


@dataclass(slots=True)
class RoutineDraft:
    """One routine-creation draft: six confirmations + task + schedule."""

    text: str
    task: str
    owner: str = DEFAULT_OWNER
    schedule_kind: str = ""
    interval_seconds: int | None = None
    cron_expression: str | None = None
    timezone: str = ""
    input_source: str = DEFAULT_INPUT_SOURCE
    expected_result: str = ""
    approval_boundary: str = DEFAULT_APPROVAL_BOUNDARY
    missing_data_policy: str = DEFAULT_MISSING_DATA_POLICY
    auto_pause_after_days: int = DEFAULT_AUTO_PAUSE_AFTER_DAYS
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def schedule(self) -> RoutineSchedule:
        """Validated schedule for this draft; raises when the draft lacks one."""
        if self.schedule_kind not in {"interval", "cron"}:
            raise ValueError("routine draft has no parsed schedule")
        return RoutineSchedule(
            kind=self.schedule_kind,
            interval_seconds=self.interval_seconds,
            cron_expression=self.cron_expression,
            timezone=self.timezone or "UTC",
        )


def _shift_hour(hour: int, text_before: str, text_after: str) -> int:
    """Apply 上午/下午/晚上 markers to a bare hour (12-hour clock)."""
    context = f"{text_before} {text_after}"
    if any(marker in context for marker in _AFTERNOON_MARKERS) and hour < 12:
        return hour + 12
    if any(marker in context for marker in _NOON_MARKERS) and hour == 11:
        return 12
    return hour


def _parse_time(text: str) -> tuple[int, int] | None:
    """Parse a time-of-day from text: (hour, minute) or None."""
    # "9:30" / "9：30"
    match = re.search(r"(\d{1,2})\s*[:：]\s*(\d{1,2})", text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return (hour, minute)
        return None
    # "9 点半" -> 9:30
    match = re.search(r"(\d{1,2})\s*点\s*半", text)
    if match:
        hour = int(match.group(1))
        if 0 <= hour <= 23:
            return (_shift_hour(hour, text[: match.start()], text[match.end() :]), 30)
    # "9 点 30 分" / "9 点"
    match = re.search(r"(\d{1,2})\s*点(?:\s*(\d{1,2})\s*分)?", text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return (_shift_hour(hour, text[: match.start()], text[match.end() :]), minute)
    # "9am" / "9 pm" / "9 o'clock"
    match = re.search(r"(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.|o'clock)", text, flags=re.IGNORECASE)
    if match:
        hour = int(match.group(1))
        marker = match.group(2).lower()
        if 1 <= hour <= 12:
            if marker.startswith("p") and hour < 12:
                hour += 12
            elif marker.startswith("a") and hour == 12:
                hour = 0
            return (hour, 0)
    return None


def _parse_timezone(text: str) -> str | None:
    """Explicit timezone marker in the text, or None."""
    if "北京时间" in text or "中国时间" in text:
        return "Asia/Shanghai"
    match = re.search(r"(?:时区|timezone)\s*[:：]?\s*([A-Za-z_]+/[A-Za-z_+-]+)", text)
    if match:
        return match.group(1)
    match = re.search(r"\b(UTC|GMT)\b", text, flags=re.IGNORECASE)
    if match:
        return "UTC"
    return None


def _strip_timezone_clause(text: str) -> str:
    text = re.sub(r"(北京时间|中国时间)", "", text)
    text = re.sub(r"(?:时区|timezone)\s*[:：]?\s*[A-Za-z_]+/[A-Za-z_+-]+", "", text)
    text = re.sub(r"\b(?:UTC|GMT)\b", "", text, flags=re.IGNORECASE)
    return text


def _parse_schedule_clause(text: str) -> tuple[dict, str] | None:
    """Find a schedule clause; return (schedule fields, text without it)."""
    # --- interval: 每隔/每 N 分钟/小时/天/周; every N minutes/hours/days/weeks
    match = re.search(
        r"每隔?\s*(\d+)\s*(分钟|分|min|mins?|minutes?|小时|时|hour|hours?|天|日|day|days?|周|星期|week|weeks?)",
        text,
    )
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        seconds = {
            "分钟": 60,
            "分": 60,
            "小时": 3600,
            "时": 3600,
            "天": 86400,
            "日": 86400,
            "周": 604800,
            "星期": 604800,
        }
        if unit in seconds:
            total = amount * seconds[unit]
        elif unit.startswith("min"):
            total = amount * 60
        elif unit.startswith("hour"):
            total = amount * 3600
        elif unit.startswith("day"):
            total = amount * 86400
        else:
            total = amount * 604800
        if total < MIN_ROUTINE_INTERVAL_SECONDS:
            return None
        return (
            {"schedule_kind": "interval", "interval_seconds": total},
            (text[: match.start()] + " " + text[match.end() :]),
        )
    match = re.search(
        r"\bevery\s+(\d+)\s*(minutes?|hours?|days?|weeks?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        total = amount * {
            "minute": 60,
            "minutes": 60,
            "hour": 3600,
            "hours": 3600,
            "day": 86400,
            "days": 86400,
            "week": 604800,
            "weeks": 604800,
        }[unit]
        if total < MIN_ROUTINE_INTERVAL_SECONDS:
            return None
        return (
            {"schedule_kind": "interval", "interval_seconds": total},
            (text[: match.start()] + " " + text[match.end() :]),
        )
    if re.search(r"每小时", text):
        return (
            {"schedule_kind": "interval", "interval_seconds": 3600},
            re.sub(r"每小时", " ", text, count=1),
        )
    if re.search(r"\bhourly\b", text, flags=re.IGNORECASE):
        return (
            {"schedule_kind": "interval", "interval_seconds": 3600},
            re.sub(r"\bhourly\b", " ", text, count=1, flags=re.IGNORECASE),
        )

    # --- wall-clock: 每个工作日 / 每天 / 每周X / 每月N号 / every ... at ...
    time = _parse_time(text)
    if re.search(r"每个工作日", text):
        hour, minute = time or (9, 0)
        return (
            {
                "schedule_kind": "cron",
                "cron_expression": f"{minute} {hour} * * 1-5",
            },
            re.sub(r"每个工作日", " ", text, count=1),
        )
    if re.search(r"\bevery\s+weekdays?\b", text, flags=re.IGNORECASE):
        hour, minute = time or (9, 0)
        return (
            {
                "schedule_kind": "cron",
                "cron_expression": f"{minute} {hour} * * 1-5",
            },
            re.sub(r"\bevery\s+weekdays?\b", " ", text, count=1, flags=re.IGNORECASE),
        )
    match = re.search(r"每周([一二三四五六日天、,，和\s]+)", text)
    if match:
        days = sorted({_ZH_WEEKDAYS[char] for char in match.group(1) if char in _ZH_WEEKDAYS})
        if days:
            hour, minute = time or (9, 0)
            return (
                {
                    "schedule_kind": "cron",
                    "cron_expression": f"{minute} {hour} * * {','.join(str(d) for d in days)}",
                },
                (text[: match.start()] + " " + text[match.end() :]),
            )
    match = re.search(
        r"\bevery\s+(sunday|monday|tuesday|wednesday|thursday|friday|saturday)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        dow = _EN_WEEKDAYS[match.group(1).lower()]
        hour, minute = time or (9, 0)
        return (
            {
                "schedule_kind": "cron",
                "cron_expression": f"{minute} {hour} * * {dow}",
            },
            (text[: match.start()] + " " + text[match.end() :]),
        )
    match = re.search(r"每月\s*(\d{1,2})\s*[号日]", text)
    if match:
        dom = int(match.group(1))
        if 1 <= dom <= 31:
            hour, minute = time or (9, 0)
            return (
                {
                    "schedule_kind": "cron",
                    "cron_expression": f"{minute} {hour} {dom} * *",
                },
                (text[: match.start()] + " " + text[match.end() :]),
            )
    match = re.search(
        r"\bon\s+the\s+(\d{1,2})(?:st|nd|rd|th)?\s+of\s+every\s+month\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        dom = int(match.group(1))
        if 1 <= dom <= 31:
            hour, minute = time or (9, 0)
            return (
                {
                    "schedule_kind": "cron",
                    "cron_expression": f"{minute} {hour} {dom} * *",
                },
                (text[: match.start()] + " " + text[match.end() :]),
            )
    if re.search(r"每天", text) or re.search(r"\bevery\s+day\b", text, flags=re.IGNORECASE) or re.search(
        r"\bdaily\b", text, flags=re.IGNORECASE
    ):
        hour, minute = time or (9, 0)
        cleaned = re.sub(r"每天", " ", text, count=1)
        cleaned = re.sub(r"\bevery\s+day\b", " ", cleaned, count=1, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bdaily\b", " ", cleaned, count=1, flags=re.IGNORECASE)
        return (
            {"schedule_kind": "cron", "cron_expression": f"{minute} {hour} * * *"},
            cleaned,
        )
    return None


def _clean_task(text: str) -> str:
    """Task text left after removing schedule/timezone/creation phrasing."""
    text = _strip_timezone_clause(text)
    # Remove the "at <time>" clause before the bare time removal below,
    # otherwise "at 9am" loses "9am" first and strands the "at".
    text = re.sub(r"\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?\b", " ", text, flags=re.IGNORECASE)
    # Remove the time-of-day clause that belonged to the schedule.
    text = re.sub(r"(\d{1,2})\s*[:：]\s*(\d{1,2})", " ", text)
    text = re.sub(r"(\d{1,2})\s*点\s*半", " ", text)
    text = re.sub(r"(\d{1,2})\s*点(?:\s*(\d{1,2})\s*分)?", " ", text)
    text = re.sub(r"(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.|o'clock)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"(上午|早上|中午|下午|晚上|傍晚|夜里)", " ", text)
    # Creation phrasing.
    text = re.sub(
        r"^(?:帮我|请|麻烦|记得|要|帮|给|为我|create|set\s+up|set|add|schedule|make)\s*",
        "",
        text,
    )
    text = re.sub(
        r"^(?:创建一个|建一个|设置一个|新增一个|弄一个)?\s*(?:定时任务|例行任务|routine|scheduled\stask)\s*[，,；;：:、]?\s*",
        "",
        text,
    )
    text = re.sub(r"(?:吧|一下|一下吧|嘛|啊|哦|呢|please|pls)[。！!？?、，,；;]*$", "", text)
    text = re.sub(r"\s+", " ", text).strip("，。,；;：:、 \t")
    if len(text) > 200:
        return ""
    return text


def parse_routine_request(text: str) -> RoutineDraft | None:
    """Parse one sentence into a routine draft; None for empty input.

    The draft always carries all six confirmations (parsed values or
    defaults). ``missing`` names what the confirmation UI must still ask for:
    a schedule when no schedule pattern matched, and a task when nothing
    actionable remains.
    """
    raw = str(text or "").strip()
    if not raw:
        return None
    timezone = _parse_timezone(raw) or local_timezone_name()
    schedule_fields: dict = {}
    remainder = raw
    parsed = _parse_schedule_clause(raw)
    if parsed is not None:
        schedule_fields, remainder = parsed
    task = _clean_task(remainder)
    missing: list[str] = []
    if not schedule_fields:
        missing.append("schedule")
    if not task:
        missing.append("task")
    draft = RoutineDraft(
        text=raw,
        task=task,
        schedule_kind=str(schedule_fields.get("schedule_kind") or ""),
        interval_seconds=schedule_fields.get("interval_seconds"),
        cron_expression=schedule_fields.get("cron_expression"),
        timezone=timezone,
        expected_result=f"完成：{task}" if task else "",
        missing=missing,
    )
    # Validate what was parsed; an invalid cron never survives into a draft.
    if draft.schedule_kind:
        try:
            draft.schedule()
        except ValueError:
            draft.schedule_kind = ""
            draft.interval_seconds = None
            draft.cron_expression = None
            if "schedule" not in draft.missing:
                draft.missing.append("schedule")
    return draft


def validate_routine_draft(raw: dict) -> RoutineDraft:
    """Validate a (possibly user-edited) draft dict into a RoutineDraft.

    Raises ValueError with a plain-language reason when any of the six
    confirmations is missing or invalid. The confirmation UI must not let
    an unconfirmed draft create a routine.
    """
    if not isinstance(raw, dict):
        raise ValueError("routine draft must be an object")
    task = str(raw.get("task") or "").strip()
    if not task:
        raise ValueError("routine task must not be empty")
    if len(task) > 200:
        raise ValueError("routine task must be at most 200 characters")
    owner = str(raw.get("owner") or "").strip()
    if not owner:
        raise ValueError("routine owner must not be empty")
    input_source = str(raw.get("input_source") or "").strip()
    if not input_source:
        raise ValueError("routine input source must not be empty")
    expected_result = str(raw.get("expected_result") or "").strip()
    if not expected_result:
        raise ValueError("routine expected result must not be empty")
    approval_boundary = str(raw.get("approval_boundary") or "").strip()
    # An empty boundary is allowed and means "unrestricted": occurrences
    # of the routine execute without an approval card. A non-empty
    # boundary is enforced by the routine layer (see routine.py): the
    # occurrence is held for approval before it may execute. The
    # one-sentence parser keeps the safe non-empty default, so a routine
    # is only unrestricted when the user explicitly clears its boundary.
    if len(approval_boundary) > 1000:
        raise ValueError("routine approval boundary must be at most 1000 characters")
    missing_data_policy = str(raw.get("missing_data_policy") or "").strip()
    if missing_data_policy not in MISSING_DATA_POLICIES:
        raise ValueError(
            "missing-data policy must be one of: " + ", ".join(MISSING_DATA_POLICIES)
        )
    try:
        auto_pause = int(raw.get("auto_pause_after_days", DEFAULT_AUTO_PAUSE_AFTER_DAYS))
    except (TypeError, ValueError) as exc:
        raise ValueError("auto_pause_after_days must be an integer") from exc
    if auto_pause < 0 or auto_pause > 365:
        raise ValueError("auto_pause_after_days must be between 0 and 365")
    draft = RoutineDraft(
        text=str(raw.get("text") or task),
        task=task,
        owner=owner,
        schedule_kind=str(raw.get("schedule_kind") or ""),
        interval_seconds=raw.get("interval_seconds"),
        cron_expression=raw.get("cron_expression"),
        timezone=str(raw.get("timezone") or "UTC"),
        input_source=input_source,
        expected_result=expected_result,
        approval_boundary=approval_boundary,
        missing_data_policy=missing_data_policy,
        auto_pause_after_days=auto_pause,
        missing=[],
    )
    draft.schedule()  # raises when the schedule is missing or invalid
    return draft


__all__ = [
    "DEFAULT_APPROVAL_BOUNDARY",
    "DEFAULT_AUTO_PAUSE_AFTER_DAYS",
    "DEFAULT_INPUT_SOURCE",
    "DEFAULT_MISSING_DATA_POLICY",
    "DEFAULT_OWNER",
    "MISSING_DATA_POLICIES",
    "RoutineDraft",
    "parse_cron",
    "parse_routine_request",
    "validate_routine_draft",
]
