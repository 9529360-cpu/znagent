from __future__ import annotations

"""Calendar connector (R5): local ICS reading plus CalDAV reading/writing.

Two event sources become ZN tools on the EXISTING Fabric/Body capability
path, in the same shape as the R1/R2 connectors — never a parallel
mechanism:

* ICS files: read-only ``calendar.ics.list_events`` parses a local
  ``.ics`` file and lists upcoming events; ``calendar.ics.create_event``
  appends one ``VEVENT`` to the file.
* CalDAV: read-only ``calendar.caldav.list_events`` runs a
  ``calendar-query`` REPORT with a time range; ``calendar.caldav.create_event``
  PUTs one new ``.ics`` resource. The CalDAV transport is a tiny WebDAV
  HTTP client (the M-8 OpenAPI adapter's REST client cannot speak
  PROPFIND/REPORT/PUT with XML bodies); the action registration,
  approval gating, replay guard, and Body dispatch all follow the
  existing conventions.

Write actions carry an ``approval:production_change`` tag, so the
ActionExecutionRuntime opens an approval card before dispatch: a denied
or undecided write never reaches the file or the server. Credentials for
CalDAV are passed in by the host at attach time and never stored in the
repository; with no CalDAV configuration the CalDAV actions report
themselves unavailable instead of pretending to work.
"""

import base64
import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .action_execution import (
    ActionExecutionRuntime,
    ActionObservation,
    ActionRequest,
    ActionVerification,
)
from .action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
)
from .approval_cards import APPROVAL_KINDS
from .body import BodyAction, BodyActionResult, NativeBody
from .mcp_capability_adapter import mcp_write_replay_identity
from .models import utc_now

__all__ = [
    "APPROVAL_KIND",
    "CALDAV_CREATE_EVENT_ACTION_ID",
    "CALDAV_LIST_EVENTS_ACTION_ID",
    "ICS_CREATE_EVENT_ACTION_ID",
    "ICS_LIST_EVENTS_ACTION_ID",
    "CalDavConfig",
    "CalDavHttpClient",
    "CalDavHttpResponse",
    "CalendarAttachment",
    "CalendarError",
    "CalendarEvent",
    "UrllibCalDavHttpClient",
    "attach_calendar_tools",
    "caldav_create_event",
    "caldav_list_events",
    "list_upcoming_events",
    "parse_ics",
    "read_ics_file",
    "register_calendar_runtime",
    "render_ics",
    "render_ics_event",
]

PROVIDER_ID = "zn.calendar"
APPROVAL_KIND = "production_change"
assert APPROVAL_KIND in APPROVAL_KINDS

ICS_LIST_EVENTS_ACTION_ID = "calendar.ics.list_events"
ICS_CREATE_EVENT_ACTION_ID = "calendar.ics.create_event"
CALDAV_LIST_EVENTS_ACTION_ID = "calendar.caldav.list_events"
CALDAV_CREATE_EVENT_ACTION_ID = "calendar.caldav.create_event"

_SOURCE_LABEL = "ZN calendar connector (ICS / CalDAV)"


class CalendarError(Exception):
    """Explicit calendar failure: never invent events, never hide a reason."""


@dataclass(slots=True)
class CalendarEvent:
    """One parsed calendar event, datetimes normalized to UTC when aware."""

    uid: str
    summary: str
    start: datetime
    end: datetime | None = None
    all_day: bool = False
    description: str = ""
    location: str = ""
    source: str = ""


# ---------------------------------------------------------------------------
# ICS parsing
# ---------------------------------------------------------------------------

_ICS_DATETIME_RE = re.compile(
    r"^(?P<date>\d{8})(?:T(?P<time>\d{6})(?P<zone>Z|[+-]\d{4})?)?$"
)
_ICS_LINE_RE = re.compile(r"^(?P<name>[A-Za-z0-9-]+)(?P<params>(?:;[^:]*)*):(?P<value>.*)$")


def _unescape_ics_text(value: str) -> str:
    return (
        value.replace("\\N", "\n")
        .replace("\\n", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def _escape_ics_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _unfold_ics(text: str) -> list[str]:
    """Unfold RFC 5545 line folding: a line starting with space/tab continues."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _parse_ics_datetime(value: str, params: Mapping[str, str]) -> tuple[datetime, bool]:
    value = value.strip()
    match = _ICS_DATETIME_RE.match(value)
    if not match:
        raise CalendarError(f"unparseable ICS datetime: {value!r}")
    year = int(value[0:4])
    month = int(value[4:6])
    day = int(value[6:8])
    time_part = match.group("time")
    if time_part is None:
        return datetime(year, month, day, tzinfo=timezone.utc), True
    hour, minute, second = (
        int(time_part[0:2]),
        int(time_part[2:4]),
        int(time_part[4:6]),
    )
    zone = match.group("zone")
    if zone == "Z":
        return (
            datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc),
            False,
        )
    if zone is not None:
        sign = 1 if zone[0] == "+" else -1
        offset = timedelta(
            hours=sign * int(zone[1:3]), minutes=sign * int(zone[3:5])
        )
        return (
            datetime(
                year, month, day, hour, minute, second,
                tzinfo=timezone(offset),
            ),
            False,
        )
    tzid = params.get("TZID")
    if tzid:
        try:
            tz = ZoneInfo(tzid)
        except ZoneInfoNotFoundError:
            raise CalendarError(
                f"unknown ICS timezone TZID={tzid!r}; cannot place the event"
            ) from None
        return datetime(year, month, day, hour, minute, second, tzinfo=tz), False
    # Naive local time: treat as UTC and say so via all_day=False; the
    # caller sees an aware datetime, so comparisons stay well-defined.
    return (
        datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc),
        False,
    )


def _split_ics_property(line: str) -> tuple[str, dict[str, str], str]:
    match = _ICS_LINE_RE.match(line)
    if not match:
        raise CalendarError(f"malformed ICS line: {line!r}")
    params: dict[str, str] = {}
    for chunk in match.group("params").lstrip(";").split(";"):
        if not chunk:
            continue
        name, _, pvalue = chunk.partition("=")
        params[name.strip().upper()] = pvalue.strip()
    return match.group("name").upper(), params, match.group("value")


def parse_ics(text: str) -> list[CalendarEvent]:
    """Parse ICS text into events. Malformed input raises CalendarError."""
    if "BEGIN:VCALENDAR" not in text.replace(" ", ""):
        raise CalendarError("not an ICS calendar: missing BEGIN:VCALENDAR")
    events: list[CalendarEvent] = []
    current: dict[str, tuple[dict[str, str], str]] | None = None
    in_event = False
    for line in _unfold_ics(text):
        stripped = line.strip()
        if stripped == "BEGIN:VEVENT":
            in_event = True
            current = {}
            continue
        if stripped == "END:VEVENT":
            if in_event and current is not None:
                events.append(_build_event(current))
            in_event = False
            current = None
            continue
        if in_event and current is not None and stripped and ":" in line:
            name, params, value = _split_ics_property(line)
            current[name] = (params, value)
    return events


def _build_event(props: dict[str, tuple[dict[str, str], str]]) -> CalendarEvent:
    def prop(name: str) -> tuple[dict[str, str], str] | None:
        return props.get(name)

    uid = ""
    summary = ""
    description = ""
    location = ""
    start: datetime | None = None
    end: datetime | None = None
    all_day = False
    for name, (params, value) in props.items():
        if name == "UID":
            uid = value.strip()
        elif name == "SUMMARY":
            summary = _unescape_ics_text(value)
        elif name == "DESCRIPTION":
            description = _unescape_ics_text(value)
        elif name == "LOCATION":
            location = _unescape_ics_text(value)
        elif name == "DTSTART":
            start, all_day = _parse_ics_datetime(value, params)
        elif name == "DTEND":
            end, _ = _parse_ics_datetime(value, params)
    if not uid:
        raise CalendarError("VEVENT without UID: cannot identify the event")
    if start is None:
        raise CalendarError(f"VEVENT {uid!r} without DTSTART")
    if end is not None and end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return CalendarEvent(
        uid=uid,
        summary=summary,
        start=start,
        end=end,
        all_day=all_day,
        description=description,
        location=location,
    )


def read_ics_file(path: str | Path) -> list[CalendarEvent]:
    """Read and parse one ICS file. Absent/unreadable files are explicit."""
    resolved = Path(path).expanduser()
    try:
        text = resolved.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise CalendarError(f"ICS file not found: {resolved}") from None
    except OSError as exc:
        raise CalendarError(
            f"cannot read ICS file {resolved}: {exc}"
        ) from exc
    return parse_ics(text)


def list_upcoming_events(
    events: list[CalendarEvent],
    *,
    days: int = 7,
    now: datetime | None = None,
) -> list[CalendarEvent]:
    """Events starting within [now, now + days], soonest first."""
    if days < 1 or days > 366:
        raise CalendarError(f"days must be 1..366, got {days!r}")
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    horizon = moment + timedelta(days=days)

    def start_of(event: CalendarEvent) -> datetime:
        start = event.start
        return start if start.tzinfo is not None else start.replace(
            tzinfo=timezone.utc
        )

    upcoming = [
        event
        for event in events
        if moment <= start_of(event) <= horizon
    ]
    upcoming.sort(key=start_of)
    return upcoming


def render_ics_event(event: CalendarEvent) -> str:
    """Render one event as a VEVENT block (UTC or date-only)."""

    def stamp(value: datetime | None, *, all_day: bool) -> str:
        if value is None:
            return ""
        if all_day:
            return value.date().strftime("%Y%m%d")
        moment = value
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VEVENT",
        f"UID:{event.uid}",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART:{stamp(event.start, all_day=event.all_day)}",
    ]
    if event.end is not None:
        lines.append(f"DTEND:{stamp(event.end, all_day=event.all_day)}")
    lines.append(f"SUMMARY:{_escape_ics_text(event.summary)}")
    if event.description:
        lines.append(f"DESCRIPTION:{_escape_ics_text(event.description)}")
    if event.location:
        lines.append(f"LOCATION:{_escape_ics_text(event.location)}")
    lines.append("END:VEVENT")
    return "\r\n".join(lines)


def render_ics(events: list[CalendarEvent]) -> str:
    """Render a full VCALENDAR document."""
    body = "\r\n".join(render_ics_event(event) for event in events)
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//ZN//calendar-connector//EN\r\n"
        f"{body}\r\n"
        "END:VCALENDAR\r\n"
    )


def _parse_iso_datetime(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise CalendarError("event start/end must not be empty")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise CalendarError(
            f"unparseable datetime {text!r}: use ISO 8601, "
            "e.g. 2026-10-25T10:00:00+08:00 or a plain date for all-day"
        ) from None
    if parsed.tzinfo is None:
        # Plain date or naive datetime: treat as an all-day date.
        if len(text) == 10:
            return datetime.combine(
                parsed.date(), time.min, tzinfo=timezone.utc
            )
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _atomic_write_text(path: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        # Best-effort cleanup of the temp file; its removal failing must not
        # mask the original error being raised.
        with suppress(OSError):
            os.unlink(tmp_name)
        raise


# ---------------------------------------------------------------------------
# CalDAV transport (WebDAV: PROPFIND / REPORT / PUT with XML bodies)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CalDavHttpResponse:
    status_code: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class CalDavHttpClient(Protocol):
    """Synchronous WebDAV transport, injectable for tests."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        data: bytes | None,
        timeout_seconds: float,
    ) -> CalDavHttpResponse: ...


class UrllibCalDavHttpClient:
    """Stdlib urllib WebDAV transport: no new dependency, bounded reads."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        data: bytes | None,
        timeout_seconds: float,
    ) -> CalDavHttpResponse:
        request = urllib.request.Request(
            url,
            data=data,
            headers=dict(headers),
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(
                request, timeout=timeout_seconds
            ) as response:
                return CalDavHttpResponse(
                    status_code=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(8 * 1024 * 1024),
                )
        except urllib.error.HTTPError as exc:
            return CalDavHttpResponse(
                status_code=exc.code,
                headers=dict(exc.headers.items()) if exc.headers else {},
                body=exc.read(1 * 1024 * 1024),
            )


@dataclass(slots=True)
class CalDavConfig:
    """CalDAV connection details, supplied by the host at attach time.

    Never committed to the repository; with no instance configured the
    CalDAV actions report themselves unavailable.
    """

    server_url: str
    calendar_path: str
    username: str = ""
    password: str = ""

    @property
    def calendar_url(self) -> str:
        base = self.server_url.rstrip("/")
        path = self.calendar_path
        if not path.startswith("/"):
            path = "/" + path
        if not path.endswith("/"):
            path += "/"
        return base + path


_DAV_NS = "DAV:"
_CAL_NS = "urn:ietf:params:xml:ns:caldav"
_NS = {"d": _DAV_NS, "c": _CAL_NS}


def _caldav_auth_headers(config: CalDavConfig) -> dict[str, str]:
    headers = {
        "Content-Type": 'application/xml; charset="utf-8"',
        "Depth": "1",
    }
    if config.username:
        token = base64.b64encode(
            f"{config.username}:{config.password}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    return headers


def _calendar_query_xml(start: datetime, end: datetime) -> bytes:
    def stamp(moment: datetime) -> str:
        aware = moment if moment.tzinfo else moment.replace(
            tzinfo=timezone.utc
        )
        return aware.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    return (
        '<?xml version="1.0" encoding="utf-8" ?>'
        '<c:calendar-query xmlns:d="DAV:" '
        'xmlns:c="urn:ietf:params:xml:ns:caldav">'
        "<d:prop><d:getetag /><c:calendar-data /></d:prop>"
        "<c:filter><c:comp-filter name=\"VCALENDAR\">"
        "<c:comp-filter name=\"VEVENT\">"
        f'<c:time-range start="{stamp(start)}" end="{stamp(end)}" />'
        "</c:comp-filter></c:comp-filter></c:filter>"
        "</c:calendar-query>"
    ).encode("utf-8")


def _extract_calendar_data(xml_text: str) -> list[str]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise CalendarError(
            f"CalDAV server returned unparseable XML: {exc}"
        ) from exc
    payloads: list[str] = []
    for response in root.findall("d:response", _NS):
        status = response.find("d:status", _NS)
        if status is not None and "200" not in (status.text or ""):
            propstat = response.find("d:propstat", _NS)
            if propstat is None:
                continue
        prop = response.find("d:propstat/d:prop", _NS)
        if prop is None:
            prop = response.find("d:prop", _NS)
        if prop is None:
            continue
        data = prop.find("c:calendar-data", _NS)
        if data is not None and data.text:
            payloads.append(data.text)
    return payloads


def caldav_list_events(
    client: CalDavHttpClient,
    config: CalDavConfig,
    *,
    days: int = 7,
    now: datetime | None = None,
    timeout_seconds: float = 20.0,
) -> list[CalendarEvent]:
    """Query one CalDAV calendar for events in the next ``days`` days."""
    if not config.server_url or not config.calendar_path:
        raise CalendarError(
            "CalDAV is not configured: server_url and calendar_path "
            "are required"
        )
    if days < 1 or days > 366:
        raise CalendarError(f"days must be 1..366, got {days!r}")
    moment = now or datetime.now(timezone.utc)
    horizon = moment + timedelta(days=days)
    xml = _calendar_query_xml(moment, horizon)
    try:
        response = client.request(
            "REPORT",
            config.calendar_url,
            headers=_caldav_auth_headers(config),
            data=xml,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        raise CalendarError(
            f"CalDAV REPORT failed: {type(exc).__name__}: {exc}"
        ) from exc
    if response.status_code == 401:
        raise CalendarError(
            "CalDAV REPORT rejected: 401 unauthorized "
            "(check username/password)"
        )
    if response.status_code not in (200, 207):
        raise CalendarError(
            f"CalDAV REPORT failed with HTTP {response.status_code}"
        )
    events: list[CalendarEvent] = []
    for payload in _extract_calendar_data(response.text):
        for event in parse_ics(payload):
            event.source = config.calendar_url
            events.append(event)
    return list_upcoming_events(events, days=days, now=moment)


def caldav_create_event(
    client: CalDavHttpClient,
    config: CalDavConfig,
    event: CalendarEvent,
    *,
    timeout_seconds: float = 20.0,
) -> str:
    """PUT one new event resource. Returns the resource URL."""
    if not config.server_url or not config.calendar_path:
        raise CalendarError(
            "CalDAV is not configured: server_url and calendar_path "
            "are required"
        )
    resource_url = config.calendar_url + urllib.parse.quote(
        f"{event.uid}.ics", safe=""
    )
    body = render_ics([event]).encode("utf-8")
    headers = _caldav_auth_headers(config)
    headers["Content-Type"] = "text/calendar; charset=utf-8"
    try:
        response = client.request(
            "PUT",
            resource_url,
            headers=headers,
            data=body,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        raise CalendarError(
            f"CalDAV PUT failed: {type(exc).__name__}: {exc}"
        ) from exc
    if response.status_code == 401:
        raise CalendarError(
            "CalDAV PUT rejected: 401 unauthorized "
            "(check username/password)"
        )
    if response.status_code not in (200, 201, 204):
        raise CalendarError(
            f"CalDAV PUT failed with HTTP {response.status_code}: "
            "the event may not have been stored; re-list before retrying"
        )
    return resource_url


# ---------------------------------------------------------------------------
# Fabric/Body attachment
# ---------------------------------------------------------------------------


def _body_kind(action_id: str, *, read: bool) -> str:
    digest = hashlib.sha256(action_id.encode("utf-8")).hexdigest()[:24]
    return f"zn_rest_read_{digest}" if read else f"zn_rest_write_{digest}"


def _event_to_dict(event: CalendarEvent) -> dict[str, Any]:
    return {
        "uid": event.uid,
        "summary": event.summary,
        "start": event.start.isoformat(),
        "end": event.end.isoformat() if event.end else None,
        "all_day": event.all_day,
        "description": event.description,
        "location": event.location,
        "source": event.source,
    }


def _events_output(events: list[CalendarEvent]) -> str:
    return json.dumps(
        [_event_to_dict(event) for event in events],
        ensure_ascii=False,
        indent=2,
    )


class CalendarAttachment:
    """Handle returned by :func:`attach_calendar_tools`; call detach()."""

    def __init__(
        self,
        fabric: ActionFabricRegistry,
        body: NativeBody,
        kinds: list[tuple[str, bool]],
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
        for kind, was_read in self._kinds:
            if was_read:
                self._body.unregister_external_read_handler(kind)
            else:
                self._body.unregister_external_write_handler(kind)


def _require_path(args: Mapping[str, Any], default: str | None) -> Path:
    raw = args.get("path") or default
    if not raw:
        raise CalendarError(
            "no ICS file configured: pass 'path' or attach with ics_path"
        )
    return Path(str(raw)).expanduser()


def _build_event_from_args(args: Mapping[str, Any]) -> CalendarEvent:
    summary = str(args.get("summary") or "").strip()
    if not summary:
        raise CalendarError("event 'summary' must not be empty")
    start = _parse_iso_datetime(str(args.get("start") or ""))
    end_raw = args.get("end")
    end = _parse_iso_datetime(str(end_raw)) if end_raw else None
    if end is not None and end < start:
        raise CalendarError("event 'end' must not be before 'start'")
    all_day = len(str(args.get("start") or "").strip()) == 10
    uid = str(args.get("uid") or "").strip() or uuid.uuid4().hex
    return CalendarEvent(
        uid=uid,
        summary=summary,
        start=start,
        end=end,
        all_day=all_day,
        description=str(args.get("description") or ""),
        location=str(args.get("location") or ""),
        source="ics",
    )


def _ics_probe(default_path: str | None):
    def probe(item) -> ActionAvailability:
        if default_path:
            return ActionAvailability(
                item.action_id,
                "available",
                reason="ICS calendar file configured",
                evidence={"path": default_path},
            )
        return ActionAvailability(
            item.action_id,
            "available",
            reason="ICS action usable with an explicit 'path' argument",
        )

    return probe


def _caldav_probe(config: CalDavConfig | None):
    def probe(item) -> ActionAvailability:
        if config is None or not config.server_url:
            return ActionAvailability(
                item.action_id,
                "unavailable",
                reason=(
                    "no CalDAV server configured: attach with a "
                    "CalDavConfig to enable these actions"
                ),
            )
        return ActionAvailability(
            item.action_id,
            "available",
            reason="CalDAV calendar configured",
            evidence={"calendar_url": config.calendar_url},
        )

    return probe


def attach_calendar_tools(
    fabric: ActionFabricRegistry,
    body: NativeBody,
    *,
    ics_path: str | None = None,
    caldav: CalDavConfig | None = None,
    http_client: CalDavHttpClient | None = None,
    timeout_seconds: float = 20.0,
) -> CalendarAttachment:
    """Attach the calendar toolset to the Fabric/Body, R1/R2 shape.

    ``ics_path`` is the default local ``.ics`` file; ``caldav`` enables
    the CalDAV actions (absent config leaves them registered but
    reporting unavailable). ``http_client`` defaults to the stdlib
    urllib transport; tests inject a fake.
    """
    client: CalDavHttpClient = http_client or UrllibCalDavHttpClient()

    prepared: list[tuple[ActionDescriptor, bool, Callable]] = []

    # -- ICS list ---------------------------------------------------------
    def call_ics_list(action: BodyAction, started: str) -> BodyActionResult:
        path = _require_path(action.args, ics_path)
        days = action.args.get("days", 7)
        try:
            days_int = int(days)
        except (TypeError, ValueError):
            raise CalendarError(f"'days' must be an integer, got {days!r}")
        events = read_ics_file(path)
        for event in events:
            event.source = str(path)
        upcoming = list_upcoming_events(events, days=days_int)
        output = _events_output(upcoming)
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=output,
            data={
                "provider_id": PROVIDER_ID,
                "tool": "ics_list_events",
                "path": str(path),
                "event_count": len(upcoming),
                "events": [_event_to_dict(e) for e in upcoming],
                "untrusted_external_evidence": False,
            },
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    prepared.append(
        (
            ActionDescriptor(
                action_id=ICS_LIST_EVENTS_ACTION_ID,
                provider=PROVIDER_ID,
                description=(
                    "List upcoming events from a local ICS calendar file. "
                    "Read-only: never modifies the file."
                ),
                body_action_kind=_body_kind(
                    ICS_LIST_EVENTS_ACTION_ID, read=True
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": (
                                "ICS file path; defaults to the attached one"
                            ),
                        },
                        "days": {
                            "type": "integer",
                            "description": (
                                "Look-ahead window in days (1..366)"
                            ),
                        },
                    },
                    "additionalProperties": False,
                },
                effect_class="read_only",
                required_authority=(),
                sensitivity="personal_calendar",
                preconditions=("an ICS file to read",),
                verification=("parsed events come from the named file",),
                replay_semantics="read_only",
                tags=("calendar", "ics", "read_only"),
            ),
            True,
            call_ics_list,
        )
    )

    # -- ICS create (approval-gated write) --------------------------------
    def call_ics_create(action: BodyAction, started: str) -> BodyActionResult:
        event = _build_event_from_args(action.args)
        path = _require_path(action.args, ics_path)
        existing: list[CalendarEvent] = []
        if path.exists():
            existing = read_ics_file(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
        for known in existing:
            if known.uid == event.uid:
                raise CalendarError(
                    f"event UID {event.uid!r} already exists in {path}"
                )
        text = render_ics([*existing, event])
        try:
            _atomic_write_text(path, text)
        except OSError as exc:
            raise CalendarError(
                f"cannot write ICS file {path}: {exc}"
            ) from exc
        # Postcondition: the event must be readable back.
        reread = read_ics_file(path)
        if event.uid not in {known.uid for known in reread}:
            raise CalendarError(
                f"write to {path} did not persist event {event.uid!r}"
            )
        output = _events_output([event])
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=output,
            data={
                "provider_id": PROVIDER_ID,
                "tool": "ics_create_event",
                "path": str(path),
                "uid": event.uid,
                "untrusted_external_evidence": False,
            },
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    prepared.append(
        (
            ActionDescriptor(
                action_id=ICS_CREATE_EVENT_ACTION_ID,
                provider=PROVIDER_ID,
                description=(
                    "Append one event to a local ICS calendar file. "
                    "Requires user approval before dispatch."
                ),
                body_action_kind=_body_kind(
                    ICS_CREATE_EVENT_ACTION_ID, read=False
                ),
                input_schema={
                    "type": "object",
                    "required": ["summary", "start"],
                    "properties": {
                        "path": {"type": "string"},
                        "summary": {"type": "string"},
                        "start": {
                            "type": "string",
                            "description": (
                                "ISO 8601 datetime, or YYYY-MM-DD for all-day"
                            ),
                        },
                        "end": {"type": "string"},
                        "description": {"type": "string"},
                        "location": {"type": "string"},
                        "uid": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                effect_class="reversible_side_effect",
                required_authority=("body_action",),
                sensitivity="personal_calendar",
                preconditions=("user approved the write via an approval card",),
                postconditions=("the event is readable back from the file",),
                verification=("fresh re-read of the ICS file contains the UID",),
                reversibility=(
                    "re-write the ICS file without the appended event"
                ),
                replay_semantics="verify_before_replay",
                tags=(
                    "calendar",
                    "ics",
                    "calendar_write",
                    f"approval:{APPROVAL_KIND}",
                ),
            ),
            False,
            call_ics_create,
        )
    )

    # -- CalDAV list ------------------------------------------------------
    def call_caldav_list(action: BodyAction, started: str) -> BodyActionResult:
        if caldav is None:
            raise CalendarError("CalDAV is not configured")
        days = action.args.get("days", 7)
        try:
            days_int = int(days)
        except (TypeError, ValueError):
            raise CalendarError(f"'days' must be an integer, got {days!r}")
        events = caldav_list_events(
            client, caldav, days=days_int, timeout_seconds=timeout_seconds
        )
        output = _events_output(events)
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=output,
            data={
                "provider_id": PROVIDER_ID,
                "tool": "caldav_list_events",
                "calendar_url": caldav.calendar_url,
                "event_count": len(events),
                "events": [_event_to_dict(e) for e in events],
                "untrusted_external_evidence": True,
            },
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    prepared.append(
        (
            ActionDescriptor(
                action_id=CALDAV_LIST_EVENTS_ACTION_ID,
                provider=PROVIDER_ID,
                description=(
                    "List upcoming events from a CalDAV calendar via a "
                    "time-range REPORT. Read-only."
                ),
                body_action_kind=_body_kind(
                    CALDAV_LIST_EVENTS_ACTION_ID, read=True
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "days": {
                            "type": "integer",
                            "description": (
                                "Look-ahead window in days (1..366)"
                            ),
                        },
                    },
                    "additionalProperties": False,
                },
                effect_class="read_only",
                required_authority=(),
                sensitivity="personal_calendar",
                preconditions=("a configured CalDAV server",),
                verification=(
                    "events come from the server's REPORT response",
                ),
                replay_semantics="read_only",
                tags=("calendar", "caldav", "read_only", "external"),
            ),
            True,
            call_caldav_list,
        )
    )

    # -- CalDAV create (approval-gated write) ------------------------------
    def call_caldav_create(
        action: BodyAction, started: str
    ) -> BodyActionResult:
        if caldav is None:
            raise CalendarError("CalDAV is not configured")
        event = _build_event_from_args(action.args)
        event.source = caldav.calendar_url
        resource_url = caldav_create_event(
            client, caldav, event, timeout_seconds=timeout_seconds
        )
        output = _events_output([event])
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=output,
            data={
                "provider_id": PROVIDER_ID,
                "tool": "caldav_create_event",
                "calendar_url": caldav.calendar_url,
                "resource_url": resource_url,
                "uid": event.uid,
                "untrusted_external_evidence": True,
            },
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    prepared.append(
        (
            ActionDescriptor(
                action_id=CALDAV_CREATE_EVENT_ACTION_ID,
                provider=PROVIDER_ID,
                description=(
                    "Create one event on a CalDAV calendar (PUT). "
                    "Requires user approval before dispatch."
                ),
                body_action_kind=_body_kind(
                    CALDAV_CREATE_EVENT_ACTION_ID, read=False
                ),
                input_schema={
                    "type": "object",
                    "required": ["summary", "start"],
                    "properties": {
                        "summary": {"type": "string"},
                        "start": {
                            "type": "string",
                            "description": (
                                "ISO 8601 datetime, or YYYY-MM-DD for all-day"
                            ),
                        },
                        "end": {"type": "string"},
                        "description": {"type": "string"},
                        "location": {"type": "string"},
                        "uid": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                effect_class="reversible_side_effect",
                required_authority=("body_action",),
                sensitivity="personal_calendar",
                preconditions=("user approved the write via an approval card",),
                postconditions=("the server accepted the PUT resource",),
                verification=(
                    "HTTP 200/201/204 on PUT; re-list before retrying on "
                    "failure since the effect state is uncertain"
                ),
                reversibility="DELETE the created resource URL",
                replay_semantics="verify_before_replay",
                tags=(
                    "calendar",
                    "caldav",
                    "calendar_write",
                    "external",
                    f"approval:{APPROVAL_KIND}",
                ),
            ),
            False,
            call_caldav_create,
        )
    )

    # -- register, with rollback on failure (OpenAPI adapter shape) --------
    probes = {
        ICS_LIST_EVENTS_ACTION_ID: _ics_probe(ics_path),
        ICS_CREATE_EVENT_ACTION_ID: _ics_probe(ics_path),
        CALDAV_LIST_EVENTS_ACTION_ID: _caldav_probe(caldav),
        CALDAV_CREATE_EVENT_ACTION_ID: _caldav_probe(caldav),
    }
    attached_kinds: list[tuple[str, bool]] = []
    registered: list[ActionDescriptor] = []
    action_ids: list[str] = []
    try:
        for descriptor, was_read, handler in prepared:
            if fabric.descriptor(descriptor.action_id) is not None:
                raise ValueError(
                    "Action Fabric already owns action "
                    f"{descriptor.action_id}"
                )
            assert descriptor.body_action_kind is not None
            kinds = (
                body._external_read_handlers
                if was_read
                else body._external_write_handlers
            )
            if descriptor.body_action_kind in kinds:
                raise ValueError("Body extension identifier collision")

        completed_identities: set[str] = set()

        for descriptor, was_read, handler in prepared:
            kind = descriptor.body_action_kind
            assert kind is not None

            def guarded(
                action: BodyAction,
                started: str,
                *,
                inner=handler,
                action_id=descriptor.action_id,
                tool=descriptor.action_id.split(".")[-1],
                read=was_read,
            ) -> BodyActionResult:
                if not read:
                    identity = mcp_write_replay_identity(
                        provider_id=PROVIDER_ID,
                        tool_name=tool,
                        args=action.args,
                        event_id=action.event_id,
                    )
                    if identity in completed_identities:
                        raise RuntimeError(
                            "calendar write replay refused: this exact write "
                            "occurrence already reached its target; re-list "
                            "before retrying instead of redispatching"
                        )
                    result = inner(action, started)
                    completed_identities.add(identity)
                    return result
                return inner(action, started)

            if was_read:
                body.register_external_read_handler(kind, guarded)
            else:
                body.register_external_write_handler(kind, guarded)
            attached_kinds.append((kind, was_read))
            fabric.register(descriptor, availability_probe=probes[descriptor.action_id])
            registered.append(descriptor)
            action_ids.append(descriptor.action_id)
    except Exception:
        for descriptor in registered:
            fabric.unregister(descriptor.action_id)
        for kind, was_read in attached_kinds:
            if was_read:
                body.unregister_external_read_handler(kind)
            else:
                body.unregister_external_write_handler(kind)
        raise
    return CalendarAttachment(fabric, body, attached_kinds, action_ids)


# ---------------------------------------------------------------------------
# Runtime binding: approval scopes (workspace_file_actions shape)
# ---------------------------------------------------------------------------


def _ics_write_scope(default_path: str | None):
    def resolver(args: Mapping[str, Any]) -> tuple[str, str, str]:
        path = str(args.get("path") or default_path or "(no file configured)")
        summary = str(args.get("summary") or "").strip()
        start = str(args.get("start") or "").strip()
        return (
            "calendar-ics-file",
            path,
            f"append event {summary!r} at {start} to {path}",
        )

    return resolver


def _caldav_write_scope(config: CalDavConfig | None):
    def resolver(args: Mapping[str, Any]) -> tuple[str, str, str]:
        target = config.calendar_url if config else "(no server configured)"
        summary = str(args.get("summary") or "").strip()
        start = str(args.get("start") or "").strip()
        return (
            "calendar-caldav",
            target,
            f"create event {summary!r} at {start} on {target}",
        )

    return resolver


def register_calendar_runtime(
    runtime: ActionExecutionRuntime,
    *,
    ics_path: str | None = None,
    caldav: CalDavConfig | None = None,
    http_client: CalDavHttpClient | None = None,
    timeout_seconds: float = 20.0,
) -> None:
    """Bind approval scopes and postcondition verifiers, like the
    workspace file actions do.

    Canonical scopes keep an ``always_allow`` rule from blessing anything
    beyond the one file or calendar; the verifiers re-observe the target
    (file re-read / CalDAV re-list) so a Body success is never taken as
    proof of the effect.
    """
    runtime.register_approval_scope(
        ICS_CREATE_EVENT_ACTION_ID, _ics_write_scope(ics_path)
    )
    runtime.register_approval_scope(
        CALDAV_CREATE_EVENT_ACTION_ID, _caldav_write_scope(caldav)
    )

    def observe_ics(
        request: ActionRequest, result: BodyActionResult | None
    ) -> ActionObservation:
        data = dict((result.data or {}) if result is not None else {})
        path = _require_path(request.args or {}, ics_path)
        try:
            uids = {event.uid for event in read_ics_file(path)}
        except CalendarError:
            uids = set()
        return ActionObservation(
            request.action_id,
            "ics_file_reread",
            data={**data, "reread_uids": sorted(uids)},
        )

    def verify_ics(
        request: ActionRequest,
        observation: ActionObservation,
        result: BodyActionResult | None,
    ) -> ActionVerification:
        uid = str(((result.data or {}) if result is not None else {}).get("uid") or "")
        if uid and uid in (observation.data or {}).get("reread_uids", ()):
            return ActionVerification(
                "verified",
                "fresh ICS re-read contains the written event UID",
            )
        return ActionVerification(
            "failed",
            "fresh ICS re-read does not contain the written event UID",
        )

    runtime.register_verification(
        ICS_CREATE_EVENT_ACTION_ID,
        observe=observe_ics,
        verify=verify_ics,
    )

    if caldav is not None:

        def observe_caldav(
            request: ActionRequest, result: BodyActionResult | None
        ) -> ActionObservation:
            client: CalDavHttpClient = http_client or UrllibCalDavHttpClient()
            try:
                uids = {
                    event.uid
                    for event in caldav_list_events(
                        client,
                        caldav,
                        days=366,
                        timeout_seconds=timeout_seconds,
                    )
                }
            except CalendarError:
                uids = set()
            return ActionObservation(
                request.action_id,
                "caldav_relist",
                data={"relisted_uids": sorted(uids)},
            )

        def verify_caldav(
            request: ActionRequest,
            observation: ActionObservation,
            result: BodyActionResult | None,
        ) -> ActionVerification:
            data = dict((result.data or {}) if result is not None else {})
            uid = str(data.get("uid") or "")
            if uid and uid in (observation.data or {}).get("relisted_uids", ()):
                return ActionVerification(
                    "verified",
                    "CalDAV re-list contains the written event UID",
                )
            return ActionVerification(
                "failed",
                "CalDAV re-list does not contain the written event UID",
            )

        runtime.register_verification(
            CALDAV_CREATE_EVENT_ACTION_ID,
            observe=observe_caldav,
            verify=verify_caldav,
        )
