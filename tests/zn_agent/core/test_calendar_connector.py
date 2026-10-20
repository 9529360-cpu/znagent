from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zn_agent.core import KernelStore
from zn_agent.core.action_execution import ActionExecutionRuntime, ActionRequest
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.approval_cards import ApprovalCardStore, ApprovalGate
from zn_agent.core.body import NativeBody
from zn_agent.core.calendar_connector import (
    CALDAV_CREATE_EVENT_ACTION_ID,
    CALDAV_LIST_EVENTS_ACTION_ID,
    ICS_CREATE_EVENT_ACTION_ID,
    ICS_LIST_EVENTS_ACTION_ID,
    CalDavConfig,
    CalDavHttpResponse,
    CalendarError,
    CalendarEvent,
    attach_calendar_tools,
    list_upcoming_events,
    parse_ics,
    read_ics_file,
    register_calendar_runtime,
    render_ics,
)
from zn_agent.core.skill_evals import eval_skills_root

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SKILLS_ROOT = REPO_ROOT / "skills"

_FIXTURE_ICS = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//ZN//tests//EN
BEGIN:VEVENT
UID:evt-past-1
DTSTAMP:20261020T000000Z
DTSTART:20261010T090000Z
DTEND:20261010T100000Z
SUMMARY:Past standup
END:VEVENT
BEGIN:VEVENT
UID:evt-soon-1
DTSTAMP:20261020T000000Z
DTSTART:20261021T090000Z
DTEND:20261021T100000Z
SUMMARY:Team sync
DESCRIPTION:Weekly\\, with the team
LOCATION:Meeting room A
END:VEVENT
BEGIN:VEVENT
UID:evt-soon-2
DTSTAMP:20261020T000000Z
DTSTART:20261023
SUMMARY:Release day
END:VEVENT
BEGIN:VEVENT
UID:evt-far-1
DTSTAMP:20261020T000000Z
DTSTART:20261130T090000Z
SUMMARY:Far future
END:VEVENT
END:VCALENDAR
"""

_FIXTURE_NOW = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)


class _FakeCalDav:
    """Mock CalDAV server: records requests, answers from canned ICS."""

    def __init__(self, ics_text: str):
        self.ics_text = ics_text
        self.calls: list[dict] = []
        self.report_status = 207
        self.put_status = 201
        self.transport_error: Exception | None = None
        self.stored: dict[str, bytes] = {}

    def _multistatus_xml(self, payloads: list[bytes]) -> bytes:
        responses = []
        for index, payload in enumerate(payloads):
            escaped = (
                payload.decode("utf-8")
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            responses.append(
                f"<d:response><d:href>/cal/evt-{index}.ics</d:href>"
                "<d:propstat><d:prop>"
                f"<d:getetag>\"{index}\"</d:getetag>"
                f"<c:calendar-data>{escaped}</c:calendar-data>"
                "</d:prop></d:propstat></d:response>"
            )
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:multistatus xmlns:d="DAV:" '
            'xmlns:c="urn:ietf:params:xml:ns:caldav">'
            + "".join(responses)
            + "</d:multistatus>"
        ).encode("utf-8")

    def request(self, method, url, *, headers, data, timeout_seconds):
        self.calls.append({"method": method, "url": url, "data": data})
        if self.transport_error is not None:
            raise self.transport_error
        if method == "REPORT":
            if self.report_status == 401:
                return CalDavHttpResponse(401, {}, b"unauthorized")
            if self.report_status != 207:
                return CalDavHttpResponse(self.report_status, {}, b"boom")
            payloads = [self.ics_text.encode("utf-8")]
            payloads.extend(self.stored.values())
            return CalDavHttpResponse(
                207, {}, self._multistatus_xml(payloads)
            )
        if method == "PUT":
            if self.put_status in (200, 201, 204):
                self.stored[url] = data or b""
            return CalDavHttpResponse(self.put_status, {}, b"")
        return CalDavHttpResponse(405, {}, b"nope")


def _approval_runtime(tmp: Path, fabric, body, *, gate: bool):
    store = ApprovalCardStore(str(tmp / "approvals.db"))
    approval_gate = ApprovalGate(store) if gate else None
    runtime = ActionExecutionRuntime(
        fabric, body, approval_gate=approval_gate
    )
    return runtime, store


class CalendarIcsTests(unittest.TestCase):
    def test_parse_fixture_end_to_end(self):
        events = parse_ics(_FIXTURE_ICS)
        self.assertEqual(len(events), 4)
        by_uid = {event.uid: event for event in events}
        sync = by_uid["evt-soon-1"]
        self.assertEqual(sync.summary, "Team sync")
        self.assertEqual(sync.description, "Weekly, with the team")
        self.assertEqual(sync.location, "Meeting room A")
        self.assertEqual(
            sync.start,
            datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc),
        )
        release = by_uid["evt-soon-2"]
        self.assertTrue(release.all_day)

    def test_upcoming_window_filters_and_sorts(self):
        events = parse_ics(_FIXTURE_ICS)
        upcoming = list_upcoming_events(
            events, days=7, now=_FIXTURE_NOW
        )
        self.assertEqual(
            [event.uid for event in upcoming],
            ["evt-soon-1", "evt-soon-2"],
        )

    def test_days_bounds_are_explicit(self):
        events = parse_ics(_FIXTURE_ICS)
        with self.assertRaises(CalendarError):
            list_upcoming_events(events, days=0)
        with self.assertRaises(CalendarError):
            list_upcoming_events(events, days=999)

    def test_malformed_ics_is_explicit(self):
        with self.assertRaises(CalendarError):
            parse_ics("this is not a calendar")
        with self.assertRaises(CalendarError):
            parse_ics(
                "BEGIN:VCALENDAR\r\n"
                "BEGIN:VEVENT\r\n"
                "SUMMARY:no uid or start\r\n"
                "END:VEVENT\r\n"
                "END:VCALENDAR\r\n"
            )

    def test_folded_lines_parse(self):
        text = (
            "BEGIN:VCALENDAR\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:fold-1\r\n"
            "DTSTART:20261021T090000Z\r\n"
            "SUMMARY:A very long summary that folds\r\n"
            " over two lines\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        events = parse_ics(text)
        self.assertEqual(len(events), 1)
        self.assertEqual(
            events[0].summary, "A very long summary that foldsover two lines"
        )

    def test_missing_file_is_explicit(self):
        with self.assertRaises(CalendarError) as caught:
            read_ics_file("/nonexistent/zn-test-calendar.ics")
        self.assertIn("not found", str(caught.exception))

    def test_render_round_trip(self):
        events = parse_ics(_FIXTURE_ICS)
        reparsed = parse_ics(render_ics(events))
        self.assertEqual(
            {event.uid for event in reparsed},
            {event.uid for event in events},
        )


class CalendarAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ics_path = self.root / "calendar.ics"
        self.ics_path.write_text(_FIXTURE_ICS, encoding="utf-8")
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(
            store=KernelStore(self.root / "kernel.db")
        )
        self.fake_caldav = _FakeCalDav(_FIXTURE_ICS)
        self.config = CalDavConfig(
            server_url="https://cal.example",
            calendar_path="/user/cal/",
            username="user",
            password="pw",
        )
        self.attachment = attach_calendar_tools(
            self.fabric,
            self.body,
            ics_path=str(self.ics_path),
            caldav=self.config,
            http_client=self.fake_caldav,
        )

    def tearDown(self):
        self.attachment.detach()
        self.body.store.close()
        self.tmp.cleanup()

    def _runtime(self):
        runtime, store = _approval_runtime(
            self.root, self.fabric, self.body, gate=True
        )
        register_calendar_runtime(
            runtime,
            ics_path=str(self.ics_path),
            caldav=self.config,
            http_client=self.fake_caldav,
        )
        return runtime, store

    def test_all_four_actions_registered_with_effect_classes(self):
        expectations = {
            ICS_LIST_EVENTS_ACTION_ID: "read_only",
            CALDAV_LIST_EVENTS_ACTION_ID: "read_only",
            ICS_CREATE_EVENT_ACTION_ID: "reversible_side_effect",
            CALDAV_CREATE_EVENT_ACTION_ID: "reversible_side_effect",
        }
        for action_id, effect in expectations.items():
            descriptor = self.fabric.descriptor(action_id)
            self.assertIsNotNone(descriptor, action_id)
            self.assertEqual(descriptor.effect_class, effect)
        for action_id in (
            ICS_CREATE_EVENT_ACTION_ID,
            CALDAV_CREATE_EVENT_ACTION_ID,
        ):
            tags = self.fabric.descriptor(action_id).tags
            self.assertIn("approval:production_change", tags)

    def test_detach_removes_everything(self):
        self.attachment.detach()
        for action_id in (
            ICS_LIST_EVENTS_ACTION_ID,
            ICS_CREATE_EVENT_ACTION_ID,
            CALDAV_LIST_EVENTS_ACTION_ID,
            CALDAV_CREATE_EVENT_ACTION_ID,
        ):
            self.assertIsNone(self.fabric.descriptor(action_id))

    def test_ics_list_via_runtime(self):
        runtime, _ = self._runtime()
        execution = runtime.execute(
            ActionRequest(
                ICS_LIST_EVENTS_ACTION_ID,
                {"path": str(self.ics_path), "days": 60},
                event_id="evt-ics-list-1",
            )
        )
        self.assertTrue(execution.success, execution.error)
        events = json.loads(execution.body_result.output)
        uids = {event["uid"] for event in events}
        self.assertIn("evt-soon-1", uids)
        self.assertIn("evt-soon-2", uids)
        self.assertIn("evt-far-1", uids)
        self.assertNotIn("evt-past-1", uids)

    def test_ics_list_reads_are_not_gated(self):
        runtime, store = self._runtime()
        execution = runtime.execute(
            ActionRequest(
                ICS_LIST_EVENTS_ACTION_ID,
                {"path": str(self.ics_path), "days": 30},
                event_id="evt-ics-list-2",
            )
        )
        self.assertTrue(execution.success, execution.error)
        self.assertEqual(store.pending_requests(), [])

    def test_ics_write_denied_never_touches_disk(self):
        runtime, store = self._runtime()
        before = hashlib.sha256(
            self.ics_path.read_bytes()
        ).hexdigest()
        execution = runtime.execute(
            ActionRequest(
                ICS_CREATE_EVENT_ACTION_ID,
                {
                    "path": str(self.ics_path),
                    "summary": "Denied meeting",
                    "start": "2026-10-25T10:00:00+00:00",
                },
                event_id="evt-ics-write-deny-1",
            )
        )
        self.assertFalse(execution.success)
        self.assertIn("approval_required", execution.error or "")
        pending = store.pending_requests()
        self.assertEqual(len(pending), 1)
        store.decide(pending[0].request_id, "deny")
        retry = runtime.execute(
            ActionRequest(
                ICS_CREATE_EVENT_ACTION_ID,
                {
                    "path": str(self.ics_path),
                    "summary": "Denied meeting",
                    "start": "2026-10-25T10:00:00+00:00",
                },
                event_id="evt-ics-write-deny-1",
            )
        )
        self.assertFalse(retry.success)
        after = hashlib.sha256(
            self.ics_path.read_bytes()
        ).hexdigest()
        self.assertEqual(before, after)
        self.assertNotIn("Denied meeting", self.ics_path.read_text())

    def test_ics_write_allowed_persists_and_reads_back(self):
        runtime, store = self._runtime()
        first = runtime.execute(
            ActionRequest(
                ICS_CREATE_EVENT_ACTION_ID,
                {
                    "path": str(self.ics_path),
                    "summary": "Approved meeting",
                    "start": "2026-10-25T10:00:00+00:00",
                    "end": "2026-10-25T11:00:00+00:00",
                    "uid": "evt-approved-1",
                },
                event_id="evt-ics-write-allow-1",
            )
        )
        self.assertFalse(first.success)
        request = store.pending_requests()[0]
        self.assertEqual(request.action_kind, "production_change")
        store.decide(request.request_id, "allow_once")
        second = runtime.execute(
            ActionRequest(
                ICS_CREATE_EVENT_ACTION_ID,
                {
                    "path": str(self.ics_path),
                    "summary": "Approved meeting",
                    "start": "2026-10-25T10:00:00+00:00",
                    "end": "2026-10-25T11:00:00+00:00",
                    "uid": "evt-approved-1",
                },
                event_id="evt-ics-write-allow-1",
            )
        )
        self.assertTrue(second.success, second.error)
        reread = read_ics_file(self.ics_path)
        by_uid = {event.uid: event for event in reread}
        self.assertIn("evt-approved-1", by_uid)
        self.assertEqual(by_uid["evt-approved-1"].summary, "Approved meeting")

    def test_ics_write_validates_inputs_after_approval(self):
        runtime, store = self._runtime()
        before = self.ics_path.read_bytes()
        first = runtime.execute(
            ActionRequest(
                ICS_CREATE_EVENT_ACTION_ID,
                {
                    "path": str(self.ics_path),
                    "summary": "  ",
                    "start": "not-a-date",
                },
                event_id="evt-ics-write-bad-1",
            )
        )
        # The gate holds first: no write before approval.
        self.assertFalse(first.success)
        self.assertIn("approval_required", first.error or "")
        store.decide(store.pending_requests()[0].request_id, "allow_once")
        second = runtime.execute(
            ActionRequest(
                ICS_CREATE_EVENT_ACTION_ID,
                {
                    "path": str(self.ics_path),
                    "summary": "  ",
                    "start": "not-a-date",
                },
                event_id="evt-ics-write-bad-1",
            )
        )
        self.assertFalse(second.success)
        self.assertIn("must not be empty", second.error or "")
        self.assertEqual(self.ics_path.read_bytes(), before)

    def test_caldav_list_via_runtime(self):
        runtime, _ = self._runtime()
        execution = runtime.execute(
            ActionRequest(
                CALDAV_LIST_EVENTS_ACTION_ID,
                {"days": 60},
                event_id="evt-caldav-list-1",
            )
        )
        self.assertTrue(execution.success, execution.error)
        report = [call for call in self.fake_caldav.calls if call["method"] == "REPORT"]
        self.assertEqual(len(report), 1)
        self.assertIn(b"time-range", report[0]["data"])
        events = json.loads(execution.body_result.output)
        self.assertTrue(any(event["uid"] == "evt-soon-1" for event in events))

    def test_caldav_write_denied_never_reaches_server(self):
        runtime, store = self._runtime()
        execution = runtime.execute(
            ActionRequest(
                CALDAV_CREATE_EVENT_ACTION_ID,
                {
                    "summary": "Denied server meeting",
                    "start": "2026-10-26T10:00:00+00:00",
                },
                event_id="evt-caldav-write-deny-1",
            )
        )
        self.assertFalse(execution.success)
        self.assertIn("approval_required", execution.error or "")
        store.decide(store.pending_requests()[0].request_id, "deny")
        retry = runtime.execute(
            ActionRequest(
                CALDAV_CREATE_EVENT_ACTION_ID,
                {
                    "summary": "Denied server meeting",
                    "start": "2026-10-26T10:00:00+00:00",
                },
                event_id="evt-caldav-write-deny-1",
            )
        )
        self.assertFalse(retry.success)
        puts = [call for call in self.fake_caldav.calls if call["method"] == "PUT"]
        self.assertEqual(puts, [])

    def test_caldav_write_allowed_puts_resource(self):
        runtime, store = self._runtime()
        first = runtime.execute(
            ActionRequest(
                CALDAV_CREATE_EVENT_ACTION_ID,
                {
                    "summary": "Approved server meeting",
                    "start": "2026-10-26T10:00:00+00:00",
                    "uid": "evt-caldav-approved-1",
                },
                event_id="evt-caldav-write-allow-1",
            )
        )
        self.assertFalse(first.success)
        store.decide(store.pending_requests()[0].request_id, "allow_once")
        second = runtime.execute(
            ActionRequest(
                CALDAV_CREATE_EVENT_ACTION_ID,
                {
                    "summary": "Approved server meeting",
                    "start": "2026-10-26T10:00:00+00:00",
                    "uid": "evt-caldav-approved-1",
                },
                event_id="evt-caldav-write-allow-1",
            )
        )
        self.assertTrue(second.success, second.error)
        puts = [call for call in self.fake_caldav.calls if call["method"] == "PUT"]
        self.assertEqual(len(puts), 1)
        self.assertTrue(
            puts[0]["url"].endswith("/user/cal/evt-caldav-approved-1.ics")
        )
        self.assertIn(b"Approved server meeting", puts[0]["data"])

    def test_caldav_http_failure_is_explicit(self):
        self.fake_caldav.report_status = 500
        runtime, _ = self._runtime()
        execution = runtime.execute(
            ActionRequest(
                CALDAV_LIST_EVENTS_ACTION_ID,
                {"days": 7},
                event_id="evt-caldav-list-fail-1",
            )
        )
        self.assertFalse(execution.success)
        self.assertIn("500", execution.error or "")

    def test_caldav_transport_failure_is_explicit(self):
        self.fake_caldav.transport_error = ConnectionError("network down")
        runtime, _ = self._runtime()
        execution = runtime.execute(
            ActionRequest(
                CALDAV_LIST_EVENTS_ACTION_ID,
                {"days": 7},
                event_id="evt-caldav-list-fail-2",
            )
        )
        self.assertFalse(execution.success)
        self.assertIn("REPORT", execution.error or "")

    def test_caldav_unconfigured_reports_unavailable(self):
        self.attachment.detach()
        attachment = attach_calendar_tools(
            self.fabric,
            self.body,
            ics_path=str(self.ics_path),
            http_client=self.fake_caldav,
        )
        self.addCleanup(attachment.detach)
        runtime, _ = self._runtime()
        execution = runtime.execute(
            ActionRequest(
                CALDAV_LIST_EVENTS_ACTION_ID,
                {"days": 7},
                event_id="evt-caldav-unconfigured-1",
            )
        )
        self.assertFalse(execution.success)
        self.assertIn("not currently available", execution.error or "")
        self.assertIn("no CalDAV server configured", execution.error or "")


class CalendarSkillEvalTests(unittest.TestCase):
    def test_repo_calendar_skill_passes_skill_evals(self):
        report = eval_skills_root(REPO_SKILLS_ROOT)
        calendar = [
            item for item in report.tier1 if item.skill_name == "calendar"
        ]
        self.assertEqual(len(calendar), 1, report.to_dict())
        self.assertTrue(calendar[0].passed, calendar[0].violations)
        self.assertTrue(report.tier2.passed, report.to_dict()["tier2"])
        self.assertTrue(report.passed, report.to_dict())


if __name__ == "__main__":
    unittest.main()
