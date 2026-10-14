from __future__ import annotations

import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from zn_agent.core.routine_schedule import (
    RoutineSchedule,
    count_cron_occurrences,
    next_cron_occurrence,
    parse_cron,
    resolve_timezone,
)


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


class CronParseTests(unittest.TestCase):
    def test_weekday_morning(self):
        expr = parse_cron("0 9 * * 1-5")
        self.assertEqual(expr.minute, frozenset({0}))
        self.assertEqual(expr.hour, frozenset({9}))
        self.assertEqual(expr.day_of_week, frozenset({1, 2, 3, 4, 5}))

    def test_step_and_names(self):
        expr = parse_cron("*/15 9-17 * * mon-fri")
        self.assertEqual(expr.minute, frozenset({0, 15, 30, 45}))
        self.assertEqual(expr.day_of_week, frozenset({1, 2, 3, 4, 5}))

    def test_sunday_seven_equals_zero(self):
        expr = parse_cron("0 9 * * 7")
        self.assertIn(7, expr.day_of_week)
        self.assertTrue(expr.matches(_at("2026-09-20T09:00:00+00:00")))

    def test_invalid_expressions(self):
        for bad in (
            "0 9 * *",
            "0 9 * * * *",
            "60 9 * * *",
            "0 24 * * *",
            "0 9 32 * *",
            "0 9 * 13 *",
            "0 9 * * 8",
            "0 9 10-5 * *",
            "0 9 * * foo",
            "0 9 * * */0",
            "",
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_cron(bad)


class CronNextOccurrenceTests(unittest.TestCase):
    def test_daily_strictly_after(self):
        expr = parse_cron("0 9 * * *")
        tz = ZoneInfo("UTC")
        self.assertEqual(
            next_cron_occurrence(expr, _at("2026-09-16T08:00:00+00:00"), tz),
            _at("2026-09-16T09:00:00+00:00"),
        )
        # At the occurrence itself, the next one is tomorrow (strictly after).
        self.assertEqual(
            next_cron_occurrence(expr, _at("2026-09-16T09:00:00+00:00"), tz),
            _at("2026-09-17T09:00:00+00:00"),
        )

    def test_weekdays_skip_weekend(self):
        expr = parse_cron("0 9 * * 1-5")
        tz = ZoneInfo("UTC")
        # Friday 10:00 -> Monday 09:00.
        self.assertEqual(
            next_cron_occurrence(expr, _at("2026-09-18T10:00:00+00:00"), tz),
            _at("2026-09-21T09:00:00+00:00"),
        )

    def test_monthly_and_leap_day(self):
        expr = parse_cron("30 8 1 * *")
        tz = ZoneInfo("UTC")
        self.assertEqual(
            next_cron_occurrence(expr, _at("2026-09-16T00:00:00+00:00"), tz),
            _at("2026-10-01T08:30:00+00:00"),
        )
        leap = parse_cron("0 0 29 2 *")
        self.assertEqual(
            next_cron_occurrence(leap, _at("2026-09-16T00:00:00+00:00"), tz),
            _at("2028-02-29T00:00:00+00:00"),
        )

    def test_timezone_wall_clock(self):
        expr = parse_cron("0 9 * * *")
        tz = ZoneInfo("Asia/Shanghai")
        # 00:30 UTC == 08:30 Shanghai; next 09:00 Shanghai == 01:00 UTC.
        self.assertEqual(
            next_cron_occurrence(expr, _at("2026-09-16T00:30:00+00:00"), tz),
            _at("2026-09-16T01:00:00+00:00"),
        )

    def test_dom_or_dow_when_both_restricted(self):
        # Vixie semantics: 1st of month OR Monday.
        expr = parse_cron("0 9 1 * 1")
        tz = ZoneInfo("UTC")
        # 2026-09-16 is a Wednesday; next is Monday 2026-09-21.
        self.assertEqual(
            next_cron_occurrence(expr, _at("2026-09-16T00:00:00+00:00"), tz),
            _at("2026-09-21T09:00:00+00:00"),
        )

    def test_count_occurrences_capped(self):
        expr = parse_cron("0 9 * * *")
        tz = ZoneInfo("UTC")
        self.assertEqual(
            count_cron_occurrences(
                expr,
                _at("2026-09-14T09:00:00+00:00"),
                _at("2026-09-17T09:00:00+00:00"),
                tz,
            ),
            3,
        )
        self.assertEqual(
            count_cron_occurrences(
                expr,
                _at("2026-09-14T09:00:00+00:00"),
                _at("2026-09-17T09:00:00+00:00"),
                tz,
                cap=2,
            ),
            2,
        )


class RoutineScheduleTests(unittest.TestCase):
    def test_interval_bounds(self):
        with self.assertRaisesRegex(ValueError, "at least 60 seconds"):
            RoutineSchedule(kind="interval", interval_seconds=30)
        with self.assertRaisesRegex(ValueError, "at most"):
            RoutineSchedule(kind="interval", interval_seconds=366 * 24 * 3600 + 1)

    def test_unknown_timezone(self):
        with self.assertRaisesRegex(ValueError, "unknown routine timezone"):
            RoutineSchedule(kind="interval", interval_seconds=120, timezone="Mars/Olympus")

    def test_resolve_timezone(self):
        self.assertIsInstance(resolve_timezone("Asia/Shanghai"), ZoneInfo)

    def test_cron_schedule_next_due(self):
        schedule = RoutineSchedule(
            kind="cron", cron_expression="0 9 * * 1-5", timezone="UTC"
        )
        self.assertEqual(
            schedule.next_due_after(_at("2026-09-18T10:00:00+00:00")),
            _at("2026-09-21T09:00:00+00:00"),
        )

    def test_describe(self):
        self.assertEqual(
            RoutineSchedule(kind="interval", interval_seconds=7200).describe(),
            "every 2 hour(s)",
        )
        self.assertEqual(
            RoutineSchedule(
                kind="cron", cron_expression="0 9 * * *", timezone="UTC"
            ).describe(),
            "cron 0 9 * * * (UTC)",
        )


if __name__ == "__main__":
    unittest.main()
