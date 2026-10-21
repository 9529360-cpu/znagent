from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import zn_agent.core.device_health_connector as connector_module
from zn_agent.core import KernelStore
from zn_agent.core.action_execution import ActionExecutionRuntime, ActionRequest
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.approval_cards import ApprovalCardStore, ApprovalGate
from zn_agent.core.body import NativeBody
from zn_agent.core.device_health_connector import (
    LIST_METRICS_ACTION_ID,
    QUERY_RECORDS_ACTION_ID,
    SUMMARIZE_ACTION_ID,
    HealthDataError,
    attach_device_health_tools,
    list_metric_types,
    parse_health_export,
    query_health_records,
    read_health_export_file,
    summarize_health,
)
from zn_agent.core.skill_evals import eval_skills_root

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SKILLS_ROOT = REPO_ROOT / "skills"

# Synthetic fixture: Apple Health-style export.xml with two days of fake
# data. All sources/values are invented ("TestPhone") — no real personal
# data anywhere in this file.
_FIXTURE_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData [
<!ENTITY testentity "EXPANDED">
]>
<HealthData locale="en_US">
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="TestPhone" unit="count" value="3000" startDate="2026-10-18 08:00:00 -0400" endDate="2026-10-18 08:30:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="TestPhone" unit="count" value="5000" startDate="2026-10-18 18:00:00 -0400" endDate="2026-10-18 18:45:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierDistanceWalkingRunning" sourceName="TestPhone" unit="km" value="2.5" startDate="2026-10-18 08:00:00 -0400" endDate="2026-10-18 08:30:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierDistanceWalkingRunning" sourceName="TestPhone" unit="m" value="1000" startDate="2026-10-18 18:00:00 -0400" endDate="2026-10-18 18:45:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierActiveEnergyBurned" sourceName="TestPhone" unit="kcal" value="200" startDate="2026-10-18 08:00:00 -0400" endDate="2026-10-18 08:30:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierActiveEnergyBurned" sourceName="TestPhone" unit="cal" value="50000" startDate="2026-10-18 18:00:00 -0400" endDate="2026-10-18 18:45:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierAppleExerciseTime" sourceName="TestPhone" unit="min" value="30" startDate="2026-10-18 08:00:00 -0400" endDate="2026-10-18 08:30:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierAppleExerciseTime" sourceName="TestPhone" unit="s" value="1800" startDate="2026-10-18 18:00:00 -0400" endDate="2026-10-18 18:45:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="TestPhone" unit="count/min" value="70" startDate="2026-10-18 08:05:00 -0400" endDate="2026-10-18 08:05:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="TestPhone" unit="count/min" value="80" startDate="2026-10-18 12:00:00 -0400" endDate="2026-10-18 12:00:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="TestPhone" unit="count/min" value="90" startDate="2026-10-18 18:30:00 -0400" endDate="2026-10-18 18:30:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierRestingHeartRate" sourceName="TestPhone" unit="count/min" value="60" startDate="2026-10-18 07:00:00 -0400" endDate="2026-10-18 07:00:00 -0400"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="TestPhone" value="HKCategoryValueSleepAnalysisAsleep" startDate="2026-10-17 23:00:00 -0400" endDate="2026-10-18 06:30:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="TestPhone" unit="count" value="4500" startDate="2026-10-19 09:00:00 -0400" endDate="2026-10-19 09:40:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierDistanceWalkingRunning" sourceName="TestPhone" unit="mi" value="1.5" startDate="2026-10-19 09:00:00 -0400" endDate="2026-10-19 09:40:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierActiveEnergyBurned" sourceName="TestPhone" unit="kcal" value="100" startDate="2026-10-19 09:00:00 -0400" endDate="2026-10-19 09:40:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierAppleExerciseTime" sourceName="TestPhone" unit="min" value="15" startDate="2026-10-19 09:00:00 -0400" endDate="2026-10-19 09:40:00 -0400"/>
 <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="TestPhone" unit="count/min" value="75" startDate="2026-10-19 09:20:00 -0400" endDate="2026-10-19 09:20:00 -0400"/>
 <ActivitySummary dateComponents="2026-10-18" stepCount="8100" distance="3.6" distanceUnit="km" activeEnergyBurned="255" activeEnergyBurnedUnit="kcal" appleExerciseTime="62" appleExerciseTimeUnit="min" appleStandHours="12" appleStandHoursUnit="count"/>
</HealthData>
"""

_FIXTURE_END = date(2026, 10, 19)


class HealthExportParseTests(unittest.TestCase):
    def test_parse_fixture_end_to_end(self):
        export = parse_health_export(_FIXTURE_XML)
        self.assertEqual(len(export.records), 18)
        self.assertEqual(len(export.summaries), 1)
        self.assertEqual(export.skipped_records, 0)

        steps = [r for r in export.records if r.metric == "steps"]
        self.assertEqual(len(steps), 3)
        first = steps[0]
        self.assertEqual(first.value, 3000.0)
        self.assertEqual(first.unit, "count")
        self.assertEqual(first.source, "TestPhone")
        self.assertEqual(first.start.isoformat(), "2026-10-18T08:00:00-04:00")

        sleep = [r for r in export.records if r.metric == "sleep"]
        self.assertEqual(len(sleep), 1)
        self.assertIsNone(sleep[0].value)
        self.assertEqual(
            sleep[0].value_raw, "HKCategoryValueSleepAnalysisAsleep"
        )

        summary = export.summaries[0]
        self.assertEqual(summary.day, date(2026, 10, 18))
        self.assertEqual(summary.steps, 8100.0)
        self.assertEqual(summary.active_energy, 255.0)
        self.assertEqual(summary.exercise_min, 62.0)

    def test_doctype_internal_subset_is_stripped(self):
        # The fixture carries a DOCTYPE with an internal entity
        # definition; it parses, which proves the doctype never reaches
        # the XML parser.
        export = parse_health_export(_FIXTURE_XML)
        self.assertEqual(len(export.records), 18)

    def test_reference_to_stripped_entity_is_refused(self):
        xml = _FIXTURE_XML.replace(
            'sourceName="TestPhone" unit="count" value="3000"',
            'sourceName="&testentity;" unit="count" value="3000"',
            1,
        )
        with self.assertRaises(HealthDataError):
            parse_health_export(xml)

    def test_malformed_xml_is_explicit(self):
        with self.assertRaises(HealthDataError):
            parse_health_export("this is not xml at all")
        with self.assertRaises(HealthDataError):
            parse_health_export("<NotHealthData></NotHealthData>")

    def test_record_missing_attributes_is_skipped_not_fatal(self):
        xml = _FIXTURE_XML.replace(
            "</HealthData>",
            ' <Record type="HKQuantityTypeIdentifierStepCount"/>\n</HealthData>',
        )
        export = parse_health_export(xml)
        self.assertEqual(len(export.records), 18)
        self.assertEqual(export.skipped_records, 1)

    def test_bad_max_records_is_explicit(self):
        with self.assertRaises(HealthDataError):
            parse_health_export(_FIXTURE_XML, max_records=0)

    def test_record_bound_refuses_huge_exports(self):
        with self.assertRaises(HealthDataError) as ctx:
            parse_health_export(_FIXTURE_XML, max_records=5)
        self.assertIn("more than 5 records", str(ctx.exception))

    def test_unknown_apple_type_is_kept_not_dropped(self):
        xml = _FIXTURE_XML.replace(
            "</HealthData>",
            ' <Record type="HKQuantityTypeIdentifierFutureMetric"'
            ' sourceName="TestPhone" unit="furlong" value="7"'
            ' startDate="2026-10-18 10:00:00 -0400"'
            ' endDate="2026-10-18 10:01:00 -0400"/>\n</HealthData>',
        )
        export = parse_health_export(xml)
        unknown = [
            r
            for r in export.records
            if r.metric == "HKQuantityTypeIdentifierFutureMetric"
        ]
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0].value, 7.0)


class HealthExportFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_file_round_trip(self):
        path = self.root / "export.xml"
        path.write_text(_FIXTURE_XML, encoding="utf-8")
        export = read_health_export_file(path)
        self.assertEqual(len(export.records), 18)
        self.assertEqual(export.path, str(path))

    def test_missing_file_is_explicit(self):
        with self.assertRaises(HealthDataError) as ctx:
            read_health_export_file(self.root / "nope.xml")
        self.assertIn("not found", str(ctx.exception))

    def test_directory_path_is_explicit(self):
        with self.assertRaises(HealthDataError) as ctx:
            read_health_export_file(self.root)
        self.assertIn("not a file", str(ctx.exception))

    def test_oversize_file_is_refused(self):
        path = self.root / "big.xml"
        path.write_text("<HealthData></HealthData>", encoding="utf-8")
        with self.assertRaises(HealthDataError) as ctx:
            read_health_export_file(path, max_bytes=10)
        self.assertIn("over the", str(ctx.exception))


class HealthSummarizeTests(unittest.TestCase):
    def setUp(self):
        self.export = parse_health_export(_FIXTURE_XML)

    def test_daily_totals(self):
        days = summarize_health(
            self.export.records,
            self.export.summaries,
            days=2,
            end=_FIXTURE_END,
        )
        self.assertEqual(len(days), 2)
        first, second = days
        self.assertEqual(first.day, date(2026, 10, 18))
        self.assertEqual(first.steps, 8000.0)
        self.assertAlmostEqual(first.distance_km, 3.5)
        self.assertAlmostEqual(first.active_energy_kcal, 250.0)
        self.assertAlmostEqual(first.exercise_min, 60.0)
        self.assertAlmostEqual(first.heart_rate_avg, 80.0)
        self.assertEqual(first.heart_rate_min, 70.0)
        self.assertEqual(first.heart_rate_max, 90.0)
        self.assertAlmostEqual(first.resting_heart_rate_avg, 60.0)
        self.assertEqual(first.sources, ("TestPhone",))
        self.assertEqual(first.record_count, 12)

        self.assertEqual(second.day, date(2026, 10, 19))
        self.assertEqual(second.steps, 4500.0)
        self.assertAlmostEqual(second.distance_km, 1.5 * 1.60934)
        self.assertAlmostEqual(second.active_energy_kcal, 100.0)
        self.assertAlmostEqual(second.exercise_min, 15.0)
        self.assertAlmostEqual(second.heart_rate_avg, 75.0)
        self.assertIsNone(second.resting_heart_rate_avg)

    def test_watch_summary_is_attached_per_day(self):
        days = summarize_health(
            self.export.records,
            self.export.summaries,
            days=2,
            end=_FIXTURE_END,
        )
        watch = days[0].watch
        self.assertIsNotNone(watch)
        self.assertEqual(watch.steps, 8100.0)
        self.assertIsNone(days[1].watch)

    def test_days_bounds_are_explicit(self):
        with self.assertRaises(HealthDataError):
            summarize_health(
                self.export.records, self.export.summaries,
                days=0, end=_FIXTURE_END,
            )
        with self.assertRaises(HealthDataError):
            summarize_health(
                self.export.records, self.export.summaries,
                days=91, end=_FIXTURE_END,
            )

    def test_empty_window_is_honest(self):
        days = summarize_health(
            self.export.records,
            self.export.summaries,
            days=3,
            end=date(2020, 1, 3),
        )
        self.assertEqual(len(days), 3)
        for day in days:
            self.assertEqual(day.steps, 0.0)
            self.assertEqual(day.record_count, 0)
            self.assertIsNone(day.heart_rate_avg)
            self.assertIsNone(day.watch)


class HealthMetricsQueryTests(unittest.TestCase):
    def setUp(self):
        self.export = parse_health_export(_FIXTURE_XML)

    def test_list_metric_types(self):
        infos = list_metric_types(self.export.records, self.export.summaries)
        by_metric = {info.metric: info for info in infos}
        self.assertEqual(by_metric["steps"].count, 3)
        self.assertEqual(by_metric["steps"].unit, "count")
        self.assertEqual(by_metric["heart_rate"].count, 4)
        self.assertEqual(by_metric["sleep"].count, 1)
        self.assertIn("activity_summary", by_metric)
        self.assertEqual(by_metric["activity_summary"].count, 1)
        self.assertIsNotNone(by_metric["steps"].first_start)
        self.assertIsNotNone(by_metric["steps"].last_end)

    def test_query_records_metric_filter(self):
        rows = query_health_records(
            self.export.records, self.export.summaries, metric="steps"
        )
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["metric"] == "steps" for row in rows))
        self.assertEqual(
            [row["value"] for row in rows], [3000.0, 5000.0, 4500.0]
        )

    def test_query_records_date_and_source_filters(self):
        rows = query_health_records(
            self.export.records,
            self.export.summaries,
            metric="steps",
            start=date(2026, 10, 19),
            end=date(2026, 10, 19),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value"], 4500.0)

        rows = query_health_records(
            self.export.records,
            self.export.summaries,
            source="NoSuchDevice",
        )
        self.assertEqual(rows, [])

    def test_query_records_limit_is_capped(self):
        rows = query_health_records(
            self.export.records, self.export.summaries, limit=5
        )
        self.assertEqual(len(rows), 5)
        with self.assertRaises(HealthDataError):
            query_health_records(
                self.export.records, self.export.summaries, limit=0
            )
        with self.assertRaises(HealthDataError):
            query_health_records(
                self.export.records, self.export.summaries, limit=1001
            )

    def test_query_records_bad_date_is_explicit(self):
        with self.assertRaises(HealthDataError):
            query_health_records(
                self.export.records,
                self.export.summaries,
                start="not-a-date",
            )

    def test_query_activity_summaries(self):
        rows = query_health_records(
            self.export.records,
            self.export.summaries,
            metric="activity_summary",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["metric"], "activity_summary")
        self.assertEqual(rows[0]["day"], "2026-10-18")
        self.assertEqual(rows[0]["steps"], 8100.0)


class DeviceHealthAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.export_path = self.root / "export.xml"
        self.export_path.write_text(_FIXTURE_XML, encoding="utf-8")
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(
            store=KernelStore(self.root / "kernel.db")
        )
        self.attachment = attach_device_health_tools(
            self.fabric,
            self.body,
            health_path=str(self.export_path),
        )

    def tearDown(self):
        self.attachment.detach()
        self.body.store.close()
        self.tmp.cleanup()

    def _runtime(self):
        store = ApprovalCardStore(str(self.root / "approvals.db"))
        runtime = ActionExecutionRuntime(
            self.fabric, self.body, approval_gate=ApprovalGate(store)
        )
        return runtime, store

    def test_all_three_actions_registered_read_only(self):
        expectations = {
            SUMMARIZE_ACTION_ID: "read_only",
            LIST_METRICS_ACTION_ID: "read_only",
            QUERY_RECORDS_ACTION_ID: "read_only",
        }
        for action_id, effect in expectations.items():
            descriptor = self.fabric.descriptor(action_id)
            self.assertIsNotNone(descriptor, action_id)
            self.assertEqual(descriptor.effect_class, effect)
            self.assertEqual(descriptor.sensitivity, "personal_health")
            self.assertEqual(descriptor.replay_semantics, "read_only")
            self.assertIn("device_health", descriptor.tags)
            self.assertNotIn("approval:production_change", descriptor.tags)

    def test_detach_removes_everything(self):
        self.attachment.detach()
        for action_id in (
            SUMMARIZE_ACTION_ID,
            LIST_METRICS_ACTION_ID,
            QUERY_RECORDS_ACTION_ID,
        ):
            self.assertIsNone(self.fabric.descriptor(action_id))

    def test_summarize_via_runtime(self):
        runtime, _ = self._runtime()
        execution = runtime.execute(
            ActionRequest(
                SUMMARIZE_ACTION_ID,
                {"days": 2, "end": "2026-10-19"},
                event_id="evt-health-summarize-1",
            )
        )
        self.assertTrue(execution.success, execution.error)
        days = json.loads(execution.body_result.output)
        self.assertEqual(len(days), 2)
        self.assertEqual(days[0]["day"], "2026-10-18")
        self.assertEqual(days[0]["steps"], 8000.0)
        self.assertAlmostEqual(days[0]["distance_km"], 3.5)
        self.assertAlmostEqual(days[0]["heart_rate_avg"], 80.0)
        self.assertEqual(
            days[0]["watch_activity_summary"]["steps"], 8100.0
        )
        self.assertEqual(days[1]["day"], "2026-10-19")
        self.assertEqual(days[1]["steps"], 4500.0)

    def test_list_metrics_via_runtime(self):
        runtime, _ = self._runtime()
        execution = runtime.execute(
            ActionRequest(
                LIST_METRICS_ACTION_ID,
                {},
                event_id="evt-health-metrics-1",
            )
        )
        self.assertTrue(execution.success, execution.error)
        metrics = json.loads(execution.body_result.output)
        by_metric = {item["metric"]: item for item in metrics}
        self.assertEqual(by_metric["steps"]["count"], 3)
        self.assertIn("activity_summary", by_metric)

    def test_query_records_via_runtime(self):
        runtime, _ = self._runtime()
        execution = runtime.execute(
            ActionRequest(
                QUERY_RECORDS_ACTION_ID,
                {"metric": "heart_rate", "limit": 2},
                event_id="evt-health-query-1",
            )
        )
        self.assertTrue(execution.success, execution.error)
        rows = json.loads(execution.body_result.output)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["metric"] == "heart_rate" for row in rows))
        self.assertTrue(execution.body_result.data["truncated"])

    def test_reads_are_not_gated(self):
        runtime, store = self._runtime()
        execution = runtime.execute(
            ActionRequest(
                SUMMARIZE_ACTION_ID,
                {"days": 2, "end": "2026-10-19"},
                event_id="evt-health-summarize-2",
            )
        )
        self.assertTrue(execution.success, execution.error)
        self.assertEqual(store.pending_requests(), [])

    def test_missing_path_is_explicit_via_runtime(self):
        fabric = ActionFabricRegistry()
        body = NativeBody(store=KernelStore(self.root / "kernel2.db"))
        attachment = attach_device_health_tools(fabric, body)
        try:
            store = ApprovalCardStore(str(self.root / "approvals2.db"))
            runtime = ActionExecutionRuntime(
                fabric, body, approval_gate=ApprovalGate(store)
            )
            execution = runtime.execute(
                ActionRequest(
                    SUMMARIZE_ACTION_ID,
                    {"days": 2},
                    event_id="evt-health-summarize-3",
                )
            )
        finally:
            attachment.detach()
            body.store.close()
        self.assertFalse(execution.success)
        self.assertIn("no health export file configured", execution.error or "")

    def test_bad_days_is_explicit_via_runtime(self):
        runtime, _ = self._runtime()
        execution = runtime.execute(
            ActionRequest(
                SUMMARIZE_ACTION_ID,
                {"days": 91},
                event_id="evt-health-summarize-4",
            )
        )
        self.assertFalse(execution.success)
        self.assertIn("1..90", execution.error or "")


class DeviceHealthPrivacyTests(unittest.TestCase):
    """The privacy boundary: local-read-only, data never leaves the machine."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.export_path = self.root / "export.xml"
        self.export_path.write_text(_FIXTURE_XML, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_module_imports_no_network_stack(self):
        source = Path(connector_module.__file__).read_text(encoding="utf-8")
        import_lines = [
            line
            for line in source.splitlines()
            if re.match(r"\s*(import|from)\s+", line)
        ]
        forbidden = (
            "socket",
            "urllib",
            "http.client",
            "http.server",
            "requests",
            "httpx",
            "ssl",
            "aiohttp",
        )
        for line in import_lines:
            for name in forbidden:
                self.assertNotRegex(
                    line,
                    rf"(import|from)\s+{re.escape(name)}(\s|\.|$)",
                    f"network import in local-only connector: {line!r}",
                )

    def test_full_summarize_path_needs_no_network(self):
        fabric = ActionFabricRegistry()
        body = NativeBody(store=KernelStore(self.root / "kernel.db"))
        attachment = attach_device_health_tools(
            fabric, body, health_path=str(self.export_path)
        )
        try:
            runtime = ActionExecutionRuntime(fabric, body)
            with (
                mock.patch(
                    "socket.socket",
                    side_effect=AssertionError("network egress attempted"),
                ),
                mock.patch(
                    "urllib.request.urlopen",
                    side_effect=AssertionError("network egress attempted"),
                ),
            ):
                execution = runtime.execute(
                    ActionRequest(
                        SUMMARIZE_ACTION_ID,
                        {"days": 2, "end": "2026-10-19"},
                        event_id="evt-health-privacy-1",
                    )
                )
                metrics_execution = runtime.execute(
                    ActionRequest(
                        LIST_METRICS_ACTION_ID,
                        {},
                        event_id="evt-health-privacy-2",
                    )
                )
        finally:
            attachment.detach()
            body.store.close()
        self.assertTrue(execution.success, execution.error)
        days = json.loads(execution.body_result.output)
        self.assertEqual(days[0]["steps"], 8000.0)
        self.assertTrue(metrics_execution.success, metrics_execution.error)


class DeviceHealthSkillEvalTests(unittest.TestCase):
    def test_repo_device_health_skill_passes_skill_evals(self):
        report = eval_skills_root(REPO_SKILLS_ROOT)
        device_health = [
            item for item in report.tier1 if item.skill_name == "device-health"
        ]
        self.assertEqual(len(device_health), 1, report.to_dict())
        self.assertTrue(device_health[0].passed, device_health[0].violations)
        self.assertTrue(report.tier2.passed, report.to_dict()["tier2"])
        self.assertTrue(report.passed, report.to_dict())


if __name__ == "__main__":
    unittest.main()
