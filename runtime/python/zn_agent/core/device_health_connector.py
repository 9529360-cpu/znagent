from __future__ import annotations

"""Device & health data connector (R11): local export files, read-only.

Scope is the LOCAL data plane only: the connector parses health data
files the user (or their paired devices) exported to this machine —
Apple Health ``export.xml`` is the reference format — and exposes
aggregation / listing / record queries as read-only ZN tools on the
EXISTING Fabric/Body capability path (the R1/R5 shape; no M-8 OpenAPI
adapter, because this is local file parsing, not REST).

PRIVACY BOUNDARY (hard): this module is local-read-only. It imports no
network stack at all (no ``socket``, no ``urllib``, no ``http.client``,
no ``requests``, no ``ssl``) — the only I/O is reading the export file
the caller names. The DOCTYPE internal subset of an Apple Health export
is stripped before XML parsing (anti-XXE), entity declarations never
reach the parser. The test suite asserts both statically and with a
socket-blocked end-to-end run; ``skills/device-health/skill.md`` states
the same boundary in user-facing words. Real-time device channels
(bluetooth / live sync) are explicitly out of scope for this item and
stay open for later work once a deployment shape is settled.

Three tools, all read-only, never gated by approval cards:

* ``device_health.summarize`` — per-day totals (steps, distance,
  active energy, exercise minutes, heart rate) over a bounded window.
* ``device_health.list_metrics`` — which metric types the export
  contains, with counts, units and date ranges.
* ``device_health.query_records`` — filtered raw records
  (limit-capped), for the "show me the details" questions.

Every failure is explicit: missing file, oversized file, malformed
XML, unknown dates, out-of-range arguments raise ``HealthDataError``
with the concrete reason. Numbers are never invented — an empty window
is reported as an empty answer, not as zeroes.
"""

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from .action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
)
from .body import BodyAction, BodyActionResult, NativeBody
from .models import utc_now

__all__ = [
    "SUMMARIZE_ACTION_ID",
    "LIST_METRICS_ACTION_ID",
    "QUERY_RECORDS_ACTION_ID",
    "ActivitySummary",
    "DailyHealthSummary",
    "DeviceHealthAttachment",
    "HealthDataError",
    "HealthExport",
    "HealthRecord",
    "MetricInfo",
    "attach_device_health_tools",
    "list_metric_types",
    "parse_health_export",
    "query_health_records",
    "read_health_export_file",
    "summarize_health",
]

PROVIDER_ID = "zn.device_health"

SUMMARIZE_ACTION_ID = "device_health.summarize"
LIST_METRICS_ACTION_ID = "device_health.list_metrics"
QUERY_RECORDS_ACTION_ID = "device_health.query_records"

_SOURCE_LABEL = "ZN device & health connector (local export files)"

#: Hard safety bounds. Exports larger than this are refused explicitly
#: instead of being chewed silently.
MAX_EXPORT_BYTES = 50 * 1024 * 1024
MAX_RECORDS = 500_000
MAX_SUMMARIZE_DAYS = 90
MAX_QUERY_LIMIT = 1000


class HealthDataError(Exception):
    """Explicit health-data failure: never invent numbers, never hide a reason."""


@dataclass(slots=True)
class HealthRecord:
    """One parsed ``<Record>`` from a health export.

    ``value`` is ``None`` for non-numeric records (e.g. sleep-analysis
    categories, whose value is an enum name); ``value_raw`` always
    carries the original string.
    """

    metric: str
    value: float | None
    value_raw: str
    unit: str
    start: datetime
    end: datetime
    source: str
    device: str = ""


@dataclass(slots=True)
class ActivitySummary:
    """One parsed ``<ActivitySummary>`` (watch-reported daily totals)."""

    day: date
    steps: float | None = None
    distance: float | None = None
    distance_unit: str = ""
    active_energy: float | None = None
    active_energy_unit: str = ""
    exercise_min: float | None = None
    stand_hours: float | None = None


@dataclass(slots=True)
class HealthExport:
    """A parsed export file: records, summaries, and the skip count."""

    records: list[HealthRecord]
    summaries: list[ActivitySummary]
    skipped_records: int = 0
    path: str = ""


@dataclass(slots=True)
class DailyHealthSummary:
    """Per-day aggregates computed from quantity records only."""

    day: date
    steps: float = 0.0
    distance_km: float = 0.0
    active_energy_kcal: float = 0.0
    exercise_min: float = 0.0
    heart_rate_avg: float | None = None
    heart_rate_min: float | None = None
    heart_rate_max: float | None = None
    resting_heart_rate_avg: float | None = None
    sources: tuple[str, ...] = ()
    record_count: int = 0
    #: Watch-reported totals for the same day, for cross-checking.
    watch: ActivitySummary | None = None


@dataclass(slots=True)
class MetricInfo:
    """One metric type present in the export."""

    apple_type: str
    metric: str
    unit: str
    count: int
    first_start: datetime | None = None
    last_end: datetime | None = None


# ---------------------------------------------------------------------------
# Apple Health export parsing
# ---------------------------------------------------------------------------

#: Apple HealthKit quantity/category types we give canonical names to.
#: Anything else is still parsed — it just keeps its Apple type string
#: as the metric name, so no data is silently dropped.
_METRIC_MAP: dict[str, tuple[str, str]] = {
    "HKQuantityTypeIdentifierStepCount": ("steps", "count"),
    "HKQuantityTypeIdentifierDistanceWalkingRunning": ("distance", "km"),
    "HKQuantityTypeIdentifierActiveEnergyBurned": ("active_energy", "kcal"),
    "HKQuantityTypeIdentifierAppleExerciseTime": ("exercise", "min"),
    "HKQuantityTypeIdentifierHeartRate": ("heart_rate", "count/min"),
    "HKQuantityTypeIdentifierRestingHeartRate": ("resting_heart_rate", "count/min"),
    "HKQuantityTypeIdentifierBodyMass": ("body_mass", "kg"),
    "HKQuantityTypeIdentifierBodyFatPercentage": ("body_fat", "%"),
    "HKCategoryTypeIdentifierSleepAnalysis": ("sleep", ""),
}

#: Unit conversions applied when aggregating distance / energy / exercise.
_DISTANCE_TO_KM: dict[str, float] = {
    "km": 1.0,
    "m": 0.001,
    "mi": 1.60934,
    "ft": 0.0003048,
}
_ENERGY_TO_KCAL: dict[str, float] = {
    "kcal": 1.0,
    "cal": 0.001,
    "kj": 0.239006,
    "j": 0.000239006,
}
_EXERCISE_TO_MIN: dict[str, float] = {
    "min": 1.0,
    "s": 1.0 / 60.0,
    "hr": 60.0,
    "h": 60.0,
}

#: The DOCTYPE (with its internal entity subset) of a real Apple Health
#: export is stripped before parsing: stdlib ElementTree never resolves
#: external entities, and dropping the doctype keeps malformed-entity
#: payloads from ever reaching the parser.
_DOCTYPE_RE = re.compile(r"<!DOCTYPE[^>\[]*(?:\[[^\]]*\][^>]*)?>", re.DOTALL)


def _strip_doctype(text: str) -> str:
    return _DOCTYPE_RE.sub("", text)


def _parse_health_datetime(value: str) -> datetime:
    """Parse Apple Health's ``"2026-10-19 08:00:00 -0400"`` datetimes."""
    raw = value.strip()
    for pattern in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, pattern)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HealthDataError(f"unparseable health date {value!r}") from exc


def _parse_float_or_none(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _canonical_metric(apple_type: str) -> tuple[str, str]:
    return _METRIC_MAP.get(apple_type, (apple_type, ""))


def _build_record(element: ET.Element) -> HealthRecord:
    get = element.get
    apple_type = (get("type") or "").strip()
    value_raw = (get("value") or "").strip()
    unit = (get("unit") or "").strip()
    if not apple_type or not value_raw:
        raise HealthDataError("Record is missing 'type' or 'value'")
    start_raw, end_raw = get("startDate"), get("endDate")
    if not start_raw or not end_raw:
        raise HealthDataError("Record is missing 'startDate' or 'endDate'")
    metric, _default_unit = _canonical_metric(apple_type)
    return HealthRecord(
        metric=metric,
        value=_parse_float_or_none(value_raw),
        value_raw=value_raw,
        unit=unit,
        start=_parse_health_datetime(start_raw),
        end=_parse_health_datetime(end_raw),
        source=(get("sourceName") or "").strip(),
        device=(get("device") or "").strip(),
    )


def _build_summary(element: ET.Element) -> ActivitySummary:
    get = element.get
    day_raw = (get("dateComponents") or "").strip()
    try:
        day = date.fromisoformat(day_raw)
    except ValueError as exc:
        raise HealthDataError(
            f"unparseable ActivitySummary date {day_raw!r}"
        ) from exc
    return ActivitySummary(
        day=day,
        steps=_parse_float_or_none(get("stepCount") or ""),
        distance=_parse_float_or_none(get("distance") or ""),
        distance_unit=(get("distanceUnit") or "").strip(),
        active_energy=_parse_float_or_none(get("activeEnergyBurned") or ""),
        active_energy_unit=(get("activeEnergyBurnedUnit") or "").strip(),
        exercise_min=_parse_float_or_none(get("appleExerciseTime") or ""),
        stand_hours=_parse_float_or_none(get("appleStandHours") or ""),
    )


def parse_health_export(
    text: str, *, max_records: int = MAX_RECORDS
) -> HealthExport:
    """Parse one Apple Health ``export.xml`` document.

    Returns the records and activity summaries plus the number of
    skipped (unparseable-but-harmless) records. Anything structurally
    wrong — no ``<HealthData>`` root, malformed XML, missing required
    attributes — raises :class:`HealthDataError` explicitly.
    """
    if max_records < 1:
        raise HealthDataError("'max_records' must be at least 1")
    cleaned = _strip_doctype(text)
    try:
        root = ET.fromstring(cleaned)
    except ET.ParseError as exc:
        raise HealthDataError(f"malformed health export XML: {exc}") from exc
    if root.tag != "HealthData":
        raise HealthDataError(
            f"not a health export: root element is {root.tag!r}, "
            "expected 'HealthData'"
        )
    records: list[HealthRecord] = []
    summaries: list[ActivitySummary] = []
    skipped = 0
    for element in root.iter():
        tag = element.tag
        if tag == "Record":
            if len(records) >= max_records:
                raise HealthDataError(
                    f"export holds more than {max_records} records: "
                    "refusing to chew it silently"
                )
            try:
                records.append(_build_record(element))
            except HealthDataError:
                skipped += 1
        elif tag == "ActivitySummary":
            try:
                summaries.append(_build_summary(element))
            except HealthDataError:
                skipped += 1
    records.sort(key=lambda record: record.start)
    summaries.sort(key=lambda summary: summary.day)
    return HealthExport(
        records=records, summaries=summaries, skipped_records=skipped
    )


def read_health_export_file(
    path: str | Path, *, max_bytes: int = MAX_EXPORT_BYTES
) -> HealthExport:
    """Read and parse a health export file from the local disk.

    Local read only — this function opens the named path and nothing
    else; no network is involved at any point.
    """
    resolved = Path(str(path)).expanduser()
    if not resolved.exists():
        raise HealthDataError(f"health export file not found: {resolved}")
    if not resolved.is_file():
        raise HealthDataError(
            f"health export path is not a file: {resolved}"
        )
    try:
        size = resolved.stat().st_size
    except OSError as exc:
        raise HealthDataError(
            f"cannot stat health export file {resolved}: {exc}"
        ) from exc
    if size > max_bytes:
        raise HealthDataError(
            f"health export file {resolved} is {size} bytes, over the "
            f"{max_bytes}-byte bound: refusing to load it whole"
        )
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise HealthDataError(
            f"cannot read health export file {resolved}: {exc}"
        ) from exc
    export = parse_health_export(text)
    export.path = str(resolved)
    return export

# ---------------------------------------------------------------------------
# Aggregation: daily summaries
# ---------------------------------------------------------------------------


def _to_km(value: float, unit: str) -> float:
    factor = _DISTANCE_TO_KM.get(unit.strip().lower())
    if factor is None:
        return 0.0
    return value * factor


def _to_kcal(value: float, unit: str) -> float:
    factor = _ENERGY_TO_KCAL.get(unit.strip().lower())
    if factor is None:
        return 0.0
    return value * factor


def _to_min(value: float, unit: str) -> float:
    factor = _EXERCISE_TO_MIN.get(unit.strip().lower())
    if factor is None:
        return 0.0
    return value * factor


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def summarize_health(
    records: list[HealthRecord],
    summaries: list[ActivitySummary],
    *,
    days: int,
    end: date | datetime,
) -> list[DailyHealthSummary]:
    """Aggregate quantity records into per-day totals.

    ``days`` is bounded to 1..90; ``end`` is the last included day.
    Only the canonical quantity metrics (steps, distance, active energy,
    exercise, heart rate) are aggregated — everything else stays
    queryable through :func:`query_health_records`. A day with no
    records is returned with zeroed totals (and ``heart_rate_avg=None``),
    never omitted, so an empty window is an honest empty answer.
    Watch ``ActivitySummary`` entries are attached per day as
    device-reported totals for cross-checking.
    """
    if not 1 <= days <= MAX_SUMMARIZE_DAYS:
        raise HealthDataError(
            f"'days' must be within 1..{MAX_SUMMARIZE_DAYS}, got {days}"
        )
    end_day = end.date() if isinstance(end, datetime) else end
    first_day = end_day - timedelta(days=days - 1)

    buckets: dict[date, DailyHealthSummary] = {}
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        buckets[day] = DailyHealthSummary(day=day)
    heart_rates: dict[date, list[float]] = {}
    resting_rates: dict[date, list[float]] = {}
    sources: dict[date, set[str]] = {day: set() for day in buckets}

    for record in records:
        day = record.start.date()
        bucket = buckets.get(day)
        if bucket is None:
            continue
        if record.value is None:
            continue
        bucket.record_count += 1
        if record.source:
            sources[day].add(record.source)
        if record.metric == "steps":
            bucket.steps += record.value
        elif record.metric == "distance":
            bucket.distance_km += _to_km(record.value, record.unit)
        elif record.metric == "active_energy":
            bucket.active_energy_kcal += _to_kcal(record.value, record.unit)
        elif record.metric == "exercise":
            bucket.exercise_min += _to_min(record.value, record.unit)
        elif record.metric == "heart_rate":
            heart_rates.setdefault(day, []).append(record.value)
        elif record.metric == "resting_heart_rate":
            resting_rates.setdefault(day, []).append(record.value)

    summary_by_day = {summary.day: summary for summary in summaries}
    result: list[DailyHealthSummary] = []
    for day in sorted(buckets):
        bucket = buckets[day]
        rates = heart_rates.get(day, [])
        resting = resting_rates.get(day, [])
        bucket.heart_rate_avg = _avg(rates)
        bucket.heart_rate_min = min(rates) if rates else None
        bucket.heart_rate_max = max(rates) if rates else None
        bucket.resting_heart_rate_avg = _avg(resting)
        bucket.sources = tuple(sorted(sources[day]))
        bucket.watch = summary_by_day.get(day)
        result.append(bucket)
    return result


def _daily_summary_to_dict(day_summary: DailyHealthSummary) -> dict[str, Any]:
    data: dict[str, Any] = {
        "day": day_summary.day.isoformat(),
        "steps": round(day_summary.steps, 1),
        "distance_km": round(day_summary.distance_km, 2),
        "active_energy_kcal": round(day_summary.active_energy_kcal, 1),
        "exercise_min": round(day_summary.exercise_min, 1),
        "heart_rate_avg": day_summary.heart_rate_avg,
        "heart_rate_min": day_summary.heart_rate_min,
        "heart_rate_max": day_summary.heart_rate_max,
        "resting_heart_rate_avg": day_summary.resting_heart_rate_avg,
        "sources": list(day_summary.sources),
        "record_count": day_summary.record_count,
    }
    watch = day_summary.watch
    if watch is not None:
        data["watch_activity_summary"] = _summary_to_dict(watch)
    return data


def _summary_to_dict(summary: ActivitySummary) -> dict[str, Any]:
    return {
        "day": summary.day.isoformat(),
        "steps": summary.steps,
        "distance": summary.distance,
        "distance_unit": summary.distance_unit,
        "active_energy": summary.active_energy,
        "active_energy_unit": summary.active_energy_unit,
        "exercise_min": summary.exercise_min,
        "stand_hours": summary.stand_hours,
    }


# ---------------------------------------------------------------------------
# Metric inventory + record queries
# ---------------------------------------------------------------------------


def list_metric_types(
    records: list[HealthRecord], summaries: list[ActivitySummary]
) -> list[MetricInfo]:
    """Inventory of metric types present in the export.

    Unknown Apple types keep their full Apple type string as the metric
    name — data is never dropped because we have no canonical name.
    """
    by_type: dict[str, list[HealthRecord]] = {}
    for record in records:
        by_type.setdefault(record.metric, []).append(record)
    infos: list[MetricInfo] = []
    for metric, items in sorted(by_type.items()):
        first = min(items, key=lambda item: item.start)
        last = max(items, key=lambda item: item.end)
        units = {item.unit for item in items if item.unit}
        infos.append(
            MetricInfo(
                apple_type=metric,
                metric=metric,
                unit=", ".join(sorted(units)) or "(unitless)",
                count=len(items),
                first_start=first.start,
                last_end=last.end,
            )
        )
    if summaries:
        days = sorted(summary.day for summary in summaries)
        infos.append(
            MetricInfo(
                apple_type="ActivitySummary",
                metric="activity_summary",
                unit="(device-reported)",
                count=len(summaries),
                first_start=datetime.combine(days[0], datetime.min.time()),
                last_end=datetime.combine(days[-1], datetime.max.time()),
            )
        )
    return infos


def _record_to_dict(record: HealthRecord) -> dict[str, Any]:
    return {
        "metric": record.metric,
        "value": record.value,
        "value_raw": record.value_raw,
        "unit": record.unit,
        "start": record.start.isoformat(),
        "end": record.end.isoformat(),
        "source": record.source,
        "device": record.device,
    }


def _coerce_filter_date(
    value: str | date | datetime | None, name: str
) -> date | None:
    """Coerce a date filter to a plain date, explicitly or not at all."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise HealthDataError(
            f"'{name}' must be an ISO date (YYYY-MM-DD), got {raw!r}"
        ) from exc


def query_health_records(
    records: list[HealthRecord],
    summaries: list[ActivitySummary],
    *,
    metric: str | None = None,
    start: str | date | datetime | None = None,
    end: str | date | datetime | None = None,
    source: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Filtered raw records (plus activity summaries on request).

    ``metric`` may be a canonical name (``steps``) or a full Apple type
    string; ``"activity_summary"`` selects the watch summaries instead
    of records. ``limit`` is capped to 1..1000 and results are oldest
    first. An over-limit query returns the first ``limit`` rows and
    reports the truncation honestly in ``data.truncated`` of the tool
    output (the tool wrapper sets it).
    """
    if not 1 <= limit <= MAX_QUERY_LIMIT:
        raise HealthDataError(
            f"'limit' must be within 1..{MAX_QUERY_LIMIT}, got {limit}"
        )
    start_day = _coerce_filter_date(start, "start")
    end_day = _coerce_filter_date(end, "end")
    if metric == "activity_summary":
        rows = [
            {**_summary_to_dict(summary), "metric": "activity_summary"}
            for summary in summaries
            if (start_day is None or summary.day >= start_day)
            and (end_day is None or summary.day <= end_day)
        ]
        return rows[:limit]
    wanted = metric.strip() if metric else None
    rows: list[dict[str, Any]] = []
    for record in records:
        if wanted and record.metric != wanted:
            continue
        day = record.start.date()
        if start_day is not None and day < start_day:
            continue
        if end_day is not None and day > end_day:
            continue
        if source and record.source != source:
            continue
        rows.append(_record_to_dict(record))
        if len(rows) >= limit:
            break
    return rows

# ---------------------------------------------------------------------------
# Fabric / Body attachment (R1/R5 shape, read-only)
# ---------------------------------------------------------------------------


def _body_kind(action_id: str) -> str:
    digest = hashlib.sha256(action_id.encode("utf-8")).hexdigest()[:24]
    # Reuses the admitted zn_rest_read_* namespace (same as the R5
    # calendar connector): no new body.py namespace is needed.
    return f"zn_rest_read_{digest}"


def _metric_to_dict(info: MetricInfo) -> dict[str, Any]:
    return {
        "apple_type": info.apple_type,
        "metric": info.metric,
        "unit": info.unit,
        "count": info.count,
        "first_start": (
            info.first_start.isoformat() if info.first_start else None
        ),
        "last_end": info.last_end.isoformat() if info.last_end else None,
    }


class DeviceHealthAttachment:
    """Handle returned by :func:`attach_device_health_tools`; call detach()."""

    def __init__(
        self,
        fabric: ActionFabricRegistry,
        body: NativeBody,
        kinds: list[str],
        action_ids: list[str],
    ) -> None:
        self._fabric = fabric
        self._body = body
        self._kinds = kinds
        self._action_ids = action_ids
        self._detached = False

    @property
    def action_ids(self) -> tuple[str, ...]:
        return tuple(self._action_ids)

    def detach(self) -> None:
        if self._detached:
            return
        self._detached = True
        for action_id in self._action_ids:
            self._fabric.unregister(action_id)
        for kind in self._kinds:
            self._body.unregister_external_read_handler(kind)


def _require_path(args: Mapping[str, Any], default: str | None) -> Path:
    raw = args.get("path") or default
    if not raw:
        raise HealthDataError(
            "no health export file configured: pass 'path' or attach "
            "with health_path"
        )
    return Path(str(raw)).expanduser()


def _parse_tool_date(value: Any, name: str) -> date | None:
    if value is None or str(value).strip() == "":
        return None
    raw = str(value).strip()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise HealthDataError(
            f"'{name}' must be an ISO date (YYYY-MM-DD), got {raw!r}"
        ) from exc


def _health_probe(default_path: str | None):
    def probe(item) -> ActionAvailability:
        if default_path:
            return ActionAvailability(
                item.action_id,
                "available",
                reason="health export file configured",
                evidence={"path": default_path},
            )
        return ActionAvailability(
            item.action_id,
            "available",
            reason="health action usable with an explicit 'path' argument",
        )

    return probe


def attach_device_health_tools(
    fabric: ActionFabricRegistry,
    body: NativeBody,
    *,
    health_path: str | None = None,
) -> DeviceHealthAttachment:
    """Attach the device-health toolset to the Fabric/Body, R1/R5 shape.

    ``health_path`` is the default local health export file (e.g. an
    Apple Health ``export.xml``); every tool also accepts an explicit
    ``path`` argument. All three tools are read-only: they open the
    file, parse it, and answer — no writes, no approvals, no network.
    """
    prepared: list[tuple[ActionDescriptor, Any]] = []

    # -- summarize ------------------------------------------------------
    def call_summarize(action: BodyAction, started: str) -> BodyActionResult:
        path = _require_path(action.args, health_path)
        try:
            days = int(action.args.get("days", 7))
        except (TypeError, ValueError):
            raise HealthDataError(
                f"'days' must be an integer, got {action.args.get('days')!r}"
            ) from None
        end = _parse_tool_date(action.args.get("end"), "end")
        export = read_health_export_file(path)
        window_end = end or date.today()
        days_summary = summarize_health(
            export.records, export.summaries, days=days, end=window_end
        )
        output = json.dumps(
            [_daily_summary_to_dict(item) for item in days_summary],
            ensure_ascii=False,
            indent=2,
        )
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=output,
            data={
                "provider_id": PROVIDER_ID,
                "tool": "summarize",
                "path": str(path),
                "days": days,
                "end": window_end.isoformat(),
                "day_count": len(days_summary),
                "skipped_records": export.skipped_records,
                "summaries": [
                    _daily_summary_to_dict(item) for item in days_summary
                ],
                "untrusted_external_evidence": False,
            },
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    prepared.append(
        (
            ActionDescriptor(
                action_id=SUMMARIZE_ACTION_ID,
                provider=PROVIDER_ID,
                description=(
                    "Daily health totals (steps, distance, active energy, "
                    "exercise, heart rate) from a local health export file "
                    "such as Apple Health export.xml. Read-only: never "
                    "modifies the file, never touches the network."
                ),
                body_action_kind=_body_kind(SUMMARIZE_ACTION_ID),
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": (
                                "Health export file path; defaults to the "
                                "attached one"
                            ),
                        },
                        "days": {
                            "type": "integer",
                            "description": "Look-back window in days (1..90)",
                        },
                        "end": {
                            "type": "string",
                            "description": (
                                "Last included day, YYYY-MM-DD; defaults "
                                "to today"
                            ),
                        },
                    },
                    "additionalProperties": False,
                },
                effect_class="read_only",
                required_authority=(),
                sensitivity="personal_health",
                preconditions=("a local health export file to read",),
                verification=("numbers come from the named file",),
                replay_semantics="read_only",
                tags=("device_health", "read_only"),
            ),
            call_summarize,
        )
    )

    # -- list_metrics ---------------------------------------------------
    def call_list_metrics(
        action: BodyAction, started: str
    ) -> BodyActionResult:
        path = _require_path(action.args, health_path)
        export = read_health_export_file(path)
        infos = list_metric_types(export.records, export.summaries)
        output = json.dumps(
            [_metric_to_dict(info) for info in infos],
            ensure_ascii=False,
            indent=2,
        )
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=output,
            data={
                "provider_id": PROVIDER_ID,
                "tool": "list_metrics",
                "path": str(path),
                "metric_count": len(infos),
                "metrics": [_metric_to_dict(info) for info in infos],
                "skipped_records": export.skipped_records,
                "untrusted_external_evidence": False,
            },
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    prepared.append(
        (
            ActionDescriptor(
                action_id=LIST_METRICS_ACTION_ID,
                provider=PROVIDER_ID,
                description=(
                    "Inventory of metric types in a local health export "
                    "file (counts, units, date ranges). Read-only: never "
                    "modifies the file, never touches the network."
                ),
                body_action_kind=_body_kind(LIST_METRICS_ACTION_ID),
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": (
                                "Health export file path; defaults to the "
                                "attached one"
                            ),
                        },
                    },
                    "additionalProperties": False,
                },
                effect_class="read_only",
                required_authority=(),
                sensitivity="personal_health",
                preconditions=("a local health export file to read",),
                verification=("the inventory comes from the named file",),
                replay_semantics="read_only",
                tags=("device_health", "read_only"),
            ),
            call_list_metrics,
        )
    )

    # -- query_records --------------------------------------------------
    def call_query_records(
        action: BodyAction, started: str
    ) -> BodyActionResult:
        path = _require_path(action.args, health_path)
        try:
            limit = int(action.args.get("limit", 200))
        except (TypeError, ValueError):
            raise HealthDataError(
                "'limit' must be an integer, "
                f"got {action.args.get('limit')!r}"
            ) from None
        start = _parse_tool_date(action.args.get("start"), "start")
        end = _parse_tool_date(action.args.get("end"), "end")
        metric_raw = action.args.get("metric")
        metric = str(metric_raw).strip() if metric_raw else None
        source_raw = action.args.get("source")
        source = str(source_raw).strip() if source_raw else None
        export = read_health_export_file(path)
        rows = query_health_records(
            export.records,
            export.summaries,
            metric=metric,
            start=start,
            end=end,
            source=source,
            limit=limit,
        )
        output = json.dumps(rows, ensure_ascii=False, indent=2)
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=output,
            data={
                "provider_id": PROVIDER_ID,
                "tool": "query_records",
                "path": str(path),
                "row_count": len(rows),
                "limit": limit,
                "truncated": len(rows) >= limit,
                "records": rows,
                "untrusted_external_evidence": False,
            },
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    prepared.append(
        (
            ActionDescriptor(
                action_id=QUERY_RECORDS_ACTION_ID,
                provider=PROVIDER_ID,
                description=(
                    "Filtered raw records from a local health export file "
                    "(by metric, date range, source; limit-capped). "
                    "Read-only: never modifies the file, never touches "
                    "the network."
                ),
                body_action_kind=_body_kind(QUERY_RECORDS_ACTION_ID),
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": (
                                "Health export file path; defaults to the "
                                "attached one"
                            ),
                        },
                        "metric": {
                            "type": "string",
                            "description": (
                                "Canonical metric (steps, heart_rate, ...) "
                                "or full Apple type; 'activity_summary' "
                                "selects watch summaries"
                            ),
                        },
                        "start": {
                            "type": "string",
                            "description": "First day, YYYY-MM-DD",
                        },
                        "end": {
                            "type": "string",
                            "description": "Last day, YYYY-MM-DD",
                        },
                        "source": {
                            "type": "string",
                            "description": "Record sourceName filter",
                        },
                        "limit": {
                            "type": "integer",
                            "description": (
                                "Max rows returned (1..1000, default 200)"
                            ),
                        },
                    },
                    "additionalProperties": False,
                },
                effect_class="read_only",
                required_authority=(),
                sensitivity="personal_health",
                preconditions=("a local health export file to read",),
                verification=("rows come from the named file",),
                replay_semantics="read_only",
                tags=("device_health", "read_only"),
            ),
            call_query_records,
        )
    )

    # -- register, with rollback on failure (calendar/R5 shape) ------------
    probes = {
        SUMMARIZE_ACTION_ID: _health_probe(health_path),
        LIST_METRICS_ACTION_ID: _health_probe(health_path),
        QUERY_RECORDS_ACTION_ID: _health_probe(health_path),
    }
    attached_kinds: list[str] = []
    registered: list[ActionDescriptor] = []
    action_ids: list[str] = []
    try:
        for descriptor, _handler in prepared:
            if fabric.descriptor(descriptor.action_id) is not None:
                raise ValueError(
                    "Action Fabric already owns action "
                    f"{descriptor.action_id}"
                )
            assert descriptor.body_action_kind is not None
            if descriptor.body_action_kind in body._external_read_handlers:
                raise ValueError("Body extension identifier collision")

        for descriptor, handler in prepared:
            kind = descriptor.body_action_kind
            assert kind is not None
            body.register_external_read_handler(kind, handler)
            attached_kinds.append(kind)
            fabric.register(
                descriptor, availability_probe=probes[descriptor.action_id]
            )
            registered.append(descriptor)
            action_ids.append(descriptor.action_id)
    except Exception:
        for descriptor in registered:
            fabric.unregister(descriptor.action_id)
        for kind in attached_kinds:
            body.unregister_external_read_handler(kind)
        raise
    return DeviceHealthAttachment(fabric, body, attached_kinds, action_ids)
