from __future__ import annotations

"""Deterministic schedule specs for ZN routines.

Two schedule kinds, both timezone-aware:

- ``interval``: every N seconds (N >= 60, same lower bound as the existing
  recurring Will triggers).
- ``cron``: a 5-field cron expression (minute hour day-of-month month
  day-of-week) evaluated in the routine's timezone. Day-of-month and
  day-of-week follow Vixie cron semantics: when both are restricted, an
  occurrence matches when *either* field matches.

No LLM, no I/O: parsing and next-occurrence math are pure functions so the
confirmation draft, the trigger layer, and the tests all agree on when a
routine will fire next.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MIN_ROUTINE_INTERVAL_SECONDS = 60
MAX_ROUTINE_INTERVAL_SECONDS = 366 * 24 * 60 * 60
_CRON_FIELD_RANGES: tuple[tuple[int, int], ...] = (
    (0, 59),  # minute
    (0, 23),  # hour
    (1, 31),  # day of month
    (1, 12),  # month
    (0, 7),  # day of week (0 and 7 both mean Sunday)
)
_MONTH_NAMES = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_DOW_NAMES = {
    "sun": 0,
    "mon": 1,
    "tue": 2,
    "wed": 3,
    "thu": 4,
    "fri": 5,
    "sat": 6,
}


#: IANA names that are exactly UTC. Only these get a fallback when no
#: timezone database is available (see resolve_timezone): any other name
#: must still raise, so a misspelled zone is never silently treated as UTC.
_UTC_ALIASES: frozenset[str] = frozenset({"UTC", "GMT", "Etc/UTC", "Etc/GMT"})


def resolve_timezone(name: str) -> tzinfo:
    """Return the tzinfo for a timezone name; raise ValueError when unknown.

    ZoneInfo is preferred so DST rules are exact. On hosts without a system
    timezone database and without the tzdata package (notably Windows), the
    UTC aliases fall back to datetime.timezone.utc so the scheduler keeps
    working instead of failing every schedule; any other name still raises.
    """
    text = str(name or "").strip()
    if not text:
        raise ValueError("routine timezone must not be empty")
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError):
        pass
    if text in _UTC_ALIASES:
        return timezone.utc
    raise ValueError(f"unknown routine timezone: {text}") from None


def local_timezone_name() -> str:
    """Best-effort IANA name of the host's local timezone; UTC as fallback."""
    try:
        key = datetime.now().astimezone().tzinfo.key  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        return "UTC"
    if isinstance(key, str) and key:
        try:
            ZoneInfo(key)
        except (ZoneInfoNotFoundError, ValueError):
            return "UTC"
        return key
    return "UTC"


@dataclass(frozen=True, slots=True)
class CronExpression:
    """A validated 5-field cron expression."""

    minute: frozenset[int]
    hour: frozenset[int]
    day_of_month: frozenset[int]
    month: frozenset[int]
    day_of_week: frozenset[int]
    raw: str

    @property
    def day_of_month_restricted(self) -> bool:
        return self.day_of_month != frozenset(range(1, 32))

    @property
    def day_of_week_restricted(self) -> bool:
        return self.day_of_week != frozenset(range(0, 8))

    def matches(self, moment: datetime) -> bool:
        """True when a wall-clock moment matches all restricted fields."""
        dow = (moment.weekday() + 1) % 7
        dom_match = moment.day in self.day_of_month
        dow_match = dow in self.day_of_week or (dow == 0 and 7 in self.day_of_week)
        if self.day_of_month_restricted and self.day_of_week_restricted:
            day_match = dom_match or dow_match
        elif self.day_of_month_restricted:
            day_match = dom_match
        elif self.day_of_week_restricted:
            day_match = dow_match
        else:
            day_match = True
        return (
            moment.minute in self.minute
            and moment.hour in self.hour
            and moment.month in self.month
            and day_match
        )


def parse_cron(expression: str) -> CronExpression:
    """Parse and validate a 5-field cron expression."""
    text = str(expression or "").strip()
    fields = text.split()
    if len(fields) != 5:
        raise ValueError("cron expression must have exactly 5 fields")
    parsed: list[frozenset[int]] = []
    for index, field in enumerate(fields):
        low, high = _CRON_FIELD_RANGES[index]
        names = _MONTH_NAMES if index == 3 else _DOW_NAMES if index == 4 else {}
        parsed.append(_parse_cron_field(field, low, high, names))
    minute, hour, day_of_month, month, day_of_week = parsed
    # Normalize Sunday: keep both 0 and 7 in the stored set so matches() and
    # the day-of-week restriction check agree.
    return CronExpression(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month=month,
        day_of_week=day_of_week,
        raw=" ".join(fields),
    )


def _parse_cron_field(
    field: str,
    low: int,
    high: int,
    names: dict[str, int],
) -> frozenset[int]:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise ValueError("cron field must not contain an empty part")
        step = 1
        if "/" in part:
            base, step_text = part.split("/", 1)
            try:
                step = int(step_text)
            except ValueError as exc:
                raise ValueError(f"invalid cron step: {part}") from exc
            if step < 1:
                raise ValueError(f"cron step must be at least 1: {part}")
            part = base
        if part in {"*", ""}:
            start, end = low, high
        elif "-" in part:
            start_text, end_text = part.split("-", 1)
            start = _cron_value(start_text, low, high, names)
            end = _cron_value(end_text, low, high, names)
            if start > end:
                raise ValueError(f"cron range is reversed: {part}")
        else:
            start = end = _cron_value(part, low, high, names)
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError("cron field matched no values")
    if min(values) < low or max(values) > high:
        raise ValueError("cron field value out of range")
    return frozenset(values)


def _cron_value(text: str, low: int, high: int, names: dict[str, int]) -> int:
    lowered = text.strip().lower()
    if lowered in names:
        return names[lowered]
    try:
        value = int(lowered)
    except ValueError as exc:
        raise ValueError(f"invalid cron value: {text}") from exc
    if value < low or value > high:
        raise ValueError(f"cron value out of range: {text}")
    return value


def next_cron_occurrence(
    expr: CronExpression,
    after: datetime,
    tz: tzinfo,
) -> datetime:
    """First cron occurrence strictly after ``after``, in the schedule timezone."""
    if after.tzinfo is None:
        raise ValueError("next_cron_occurrence requires a timezone-aware datetime")
    # Start at the next whole minute in wall-clock time.
    candidate = (
        after.astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
    )
    for _ in range(366 * 4 * 24 * 60):
        if expr.matches(candidate):
            return candidate
        # Field-walking: jump past the mismatching field instead of stepping
        # minute by minute, so a Feb-29 schedule does not loop for years.
        if candidate.month not in expr.month:
            candidate = candidate.replace(
                day=1, hour=0, minute=0
            ) + _months_to_next(candidate, expr)
            continue
        dow = (candidate.weekday() + 1) % 7
        dom_match = candidate.day in expr.day_of_month
        dow_match = dow in expr.day_of_week or (dow == 0 and 7 in expr.day_of_week)
        if expr.day_of_month_restricted and expr.day_of_week_restricted:
            day_ok = dom_match or dow_match
        elif expr.day_of_month_restricted:
            day_ok = dom_match
        elif expr.day_of_week_restricted:
            day_ok = dow_match
        else:
            day_ok = True
        if not day_ok:
            candidate = (candidate + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if candidate.hour not in expr.hour:
            candidate = (candidate + timedelta(hours=1)).replace(minute=0)
            continue
        if candidate.minute not in expr.minute:
            candidate = candidate + timedelta(minutes=1)
            continue
        return candidate
    raise ValueError("no cron occurrence found within the search horizon")


def _months_to_next(candidate: datetime, expr: CronExpression) -> timedelta:
    """Timedelta to the 1st of the next month whose month field matches."""
    year, month = candidate.year, candidate.month
    for _ in range(13):
        month += 1
        if month > 12:
            month = 1
            year += 1
        if month in expr.month:
            break
    target = candidate.replace(year=year, month=month, day=1, hour=0, minute=0)
    return target - candidate.replace(day=1, hour=0, minute=0)


def count_cron_occurrences(
    expr: CronExpression,
    start_exclusive: datetime,
    end_inclusive: datetime,
    tz: tzinfo,
    *,
    cap: int = 10_000,
) -> int:
    """Occurrences in (start, end]; capped so a long-unrun routine stays cheap.

    When the cap is hit the returned count is a lower bound; the caller still
    advances past ``end`` so no backlog burst is created.
    """
    if end_inclusive <= start_exclusive:
        return 0
    count = 0
    cursor = start_exclusive
    while count < cap:
        nxt = next_cron_occurrence(expr, cursor, tz)
        if nxt > end_inclusive:
            return count
        count += 1
        cursor = nxt
    return count


@dataclass(frozen=True, slots=True)
class RoutineSchedule:
    """A validated routine schedule: fixed interval or cron, plus timezone."""

    kind: str  # "interval" | "cron"
    interval_seconds: int | None = None
    cron_expression: str | None = None
    timezone: str = "UTC"

    def __post_init__(self) -> None:
        if self.kind not in {"interval", "cron"}:
            raise ValueError("routine schedule kind must be interval or cron")
        resolve_timezone(self.timezone)
        if self.kind == "interval":
            if self.interval_seconds is None:
                raise ValueError("interval schedule requires interval_seconds")
            try:
                interval = int(self.interval_seconds)
            except (TypeError, ValueError) as exc:
                raise ValueError("interval_seconds must be an integer") from exc
            if interval < MIN_ROUTINE_INTERVAL_SECONDS:
                raise ValueError(
                    "routine interval must be at least "
                    f"{MIN_ROUTINE_INTERVAL_SECONDS} seconds"
                )
            if interval > MAX_ROUTINE_INTERVAL_SECONDS:
                raise ValueError(
                    "routine interval must be at most "
                    f"{MAX_ROUTINE_INTERVAL_SECONDS} seconds"
                )
            object.__setattr__(self, "interval_seconds", interval)
        else:
            if not str(self.cron_expression or "").strip():
                raise ValueError("cron schedule requires cron_expression")
            object.__setattr__(
                self, "cron_expression", parse_cron(self.cron_expression).raw
            )

    def parsed_cron(self) -> CronExpression:
        if self.kind != "cron":
            raise ValueError("not a cron schedule")
        return parse_cron(str(self.cron_expression))

    def next_due_after(self, after: datetime) -> datetime:
        """Next due instant strictly after ``after`` (timezone-aware)."""
        if after.tzinfo is None:
            raise ValueError("next_due_after requires a timezone-aware datetime")
        tz = resolve_timezone(self.timezone)
        if self.kind == "interval":
            return after.astimezone(timezone.utc) + timedelta(
                seconds=int(self.interval_seconds or 0)
            )
        return next_cron_occurrence(self.parsed_cron(), after, tz)

    def describe(self) -> str:
        if self.kind == "interval":
            seconds = int(self.interval_seconds or 0)
            if seconds % 86400 == 0:
                return f"every {seconds // 86400} day(s)"
            if seconds % 3600 == 0:
                return f"every {seconds // 3600} hour(s)"
            if seconds % 60 == 0:
                return f"every {seconds // 60} minute(s)"
            return f"every {seconds} second(s)"
        return f"cron {self.cron_expression} ({self.timezone})"


__all__ = [
    "CronExpression",
    "RoutineSchedule",
    "count_cron_occurrences",
    "local_timezone_name",
    "next_cron_occurrence",
    "parse_cron",
    "resolve_timezone",
]
