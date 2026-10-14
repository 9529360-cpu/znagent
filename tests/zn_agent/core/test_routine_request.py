from __future__ import annotations

import unittest

from zn_agent.core.routine_request import (
    parse_routine_request,
    validate_routine_draft,
)


class ParseRoutineRequestTests(unittest.TestCase):
    def test_weekday_morning_summary(self):
        draft = parse_routine_request("每个工作日 9 点汇总昨天的进展")
        assert draft is not None
        self.assertEqual(draft.task, "汇总昨天的进展")
        self.assertEqual(draft.schedule_kind, "cron")
        self.assertEqual(draft.cron_expression, "0 9 * * 1-5")
        self.assertEqual(draft.missing, [])
        # All six confirmations are present on the draft.
        self.assertTrue(draft.owner)
        self.assertTrue(draft.timezone)
        self.assertTrue(draft.input_source)
        self.assertTrue(draft.expected_result)
        self.assertTrue(draft.approval_boundary)
        self.assertEqual(draft.missing_data_policy, "skip")

    def test_interval_hours(self):
        draft = parse_routine_request("每 2 小时检查一次收件箱")
        assert draft is not None
        self.assertEqual(draft.task, "检查一次收件箱")
        self.assertEqual(draft.schedule_kind, "interval")
        self.assertEqual(draft.interval_seconds, 7200)

    def test_daily_half_past(self):
        draft = parse_routine_request("每天早上 9 点半汇总进展")
        assert draft is not None
        self.assertEqual(draft.cron_expression, "30 9 * * *")
        self.assertEqual(draft.task, "汇总进展")

    def test_weekly_monday(self):
        draft = parse_routine_request("每周一 10 点开周会提醒")
        assert draft is not None
        self.assertEqual(draft.cron_expression, "0 10 * * 1")
        self.assertEqual(draft.task, "开周会提醒")

    def test_afternoon_and_beijing_timezone(self):
        draft = parse_routine_request("帮我每个工作日下午 3 点汇总进展，北京时间")
        assert draft is not None
        self.assertEqual(draft.cron_expression, "0 15 * * 1-5")
        self.assertEqual(draft.timezone, "Asia/Shanghai")
        self.assertEqual(draft.task, "汇总进展")

    def test_beijing_in_task_is_not_a_timezone(self):
        draft = parse_routine_request("每个工作日 9 点汇总北京分公司进展")
        assert draft is not None
        self.assertEqual(draft.task, "汇总北京分公司进展")

    def test_english_daily(self):
        draft = parse_routine_request("every day at 9am summarize progress")
        assert draft is not None
        self.assertEqual(draft.cron_expression, "0 9 * * *")
        self.assertEqual(draft.task, "summarize progress")

    def test_english_interval(self):
        draft = parse_routine_request("every 30 minutes check inbox")
        assert draft is not None
        self.assertEqual(draft.schedule_kind, "interval")
        self.assertEqual(draft.interval_seconds, 1800)
        self.assertEqual(draft.task, "check inbox")

    def test_no_schedule_reports_missing(self):
        draft = parse_routine_request("随便说点什么")
        assert draft is not None
        self.assertEqual(draft.schedule_kind, "")
        self.assertIn("schedule", draft.missing)
        self.assertEqual(draft.task, "随便说点什么")

    def test_empty_input_is_none(self):
        self.assertIsNone(parse_routine_request(""))
        self.assertIsNone(parse_routine_request("   "))

    def test_too_short_interval_is_not_a_schedule(self):
        draft = parse_routine_request("每 30 秒检查一次")
        assert draft is not None
        self.assertEqual(draft.schedule_kind, "")
        self.assertIn("schedule", draft.missing)


class ValidateRoutineDraftTests(unittest.TestCase):
    def _valid(self) -> dict:
        draft = parse_routine_request("每个工作日 9 点汇总昨天的进展")
        assert draft is not None
        return draft.to_dict()

    def test_valid_draft_passes(self):
        validated = validate_routine_draft(self._valid())
        self.assertEqual(validated.task, "汇总昨天的进展")

    def test_empty_task_rejected(self):
        raw = self._valid()
        raw["task"] = ""
        with self.assertRaisesRegex(ValueError, "task must not be empty"):
            validate_routine_draft(raw)

    def test_missing_schedule_rejected(self):
        raw = self._valid()
        raw["schedule_kind"] = ""
        with self.assertRaisesRegex(ValueError, "no parsed schedule"):
            validate_routine_draft(raw)

    def test_bad_missing_data_policy_rejected(self):
        raw = self._valid()
        raw["missing_data_policy"] = "guess"
        with self.assertRaisesRegex(ValueError, "missing-data policy"):
            validate_routine_draft(raw)

    def test_bad_auto_pause_rejected(self):
        raw = self._valid()
        raw["auto_pause_after_days"] = -1
        with self.assertRaisesRegex(ValueError, "auto_pause_after_days"):
            validate_routine_draft(raw)

    def test_zero_auto_pause_means_never(self):
        raw = self._valid()
        raw["auto_pause_after_days"] = 0
        validated = validate_routine_draft(raw)
        self.assertEqual(validated.auto_pause_after_days, 0)


if __name__ == "__main__":
    unittest.main()
