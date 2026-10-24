from __future__ import annotations

import unittest

from zn_agent.core.current_app_text_cleanup_goal import (
    CURRENT_APP_TEXT_CLEANUP_GOAL_KIND,
    TRIM_DROP_BLANK_DEDUPE_STABLE,
    deterministic_text_cleanup,
    text_sha256,
    validate_current_app_text_cleanup_goal,
)

class DeterministicCleanupTests(unittest.TestCase):
    def test_trim_drop_blank_stable_dedupe_preserves_order_and_crlf(self):
        source = "  客户已确认方案  \r\n\r\n等待合同\n 客户已确认方案\t\n 下周回访 \n等待合同  "
        result = deterministic_text_cleanup(source)
        self.assertEqual(result.result_text, "客户已确认方案\r\n等待合同\r\n下周回访")
        self.assertEqual(result.result_line_count, 3)
        self.assertEqual(result.removed_blank_line_count, 1)
        self.assertEqual(result.removed_duplicate_line_count, 2)
        self.assertEqual(result.source_sha256, text_sha256(source))
        self.assertEqual(result.result_sha256, text_sha256(result.result_text))
        self.assertNotIn("result_text", result.audit)

    def test_empty_and_oversize_results_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            deterministic_text_cleanup(" \r\n\t\n")
        with self.assertRaisesRegex(ValueError, "4096"):
            deterministic_text_cleanup("x" * 4097)


class TypedGoalValidationTests(unittest.TestCase):
    TASK = "把我现在这个软件里的这份工作记录整理一下：去掉空行和完全重复的行，每行首尾空格也去掉，保留原来的顺序，然后保存。"

    def _valid(self):
        return {
            "kind": CURRENT_APP_TEXT_CLEANUP_GOAL_KIND,
            "field_name": "工作记录",
            "save_button_name": "保存",
            "transform": TRIM_DROP_BLANK_DEDUPE_STABLE,
        }

    def test_semantic_goal_is_accepted(self):
        goal = validate_current_app_text_cleanup_goal(self.TASK, self._valid())
        self.assertIsNotNone(goal)
        self.assertEqual(goal.field_name, "工作记录")

    def test_model_cannot_mint_physical_authority_or_transformed_content(self):
        for forbidden in ("hwnd", "pid", "runtime_id", "screen_coordinate", "result_text", "body_action"):
            proposal = self._valid()
            proposal[forbidden] = "invented"
            with self.subTest(forbidden=forbidden):
                self.assertIsNone(validate_current_app_text_cleanup_goal(self.TASK, proposal))

    def test_unsupported_transform_or_unmentioned_names_are_rejected(self):
        unsupported = self._valid()
        unsupported["transform"] = "model_rewrite"
        self.assertIsNone(validate_current_app_text_cleanup_goal(self.TASK, unsupported))
        invented = self._valid()
        invented["field_name"] = "秘密字段"
        self.assertIsNone(validate_current_app_text_cleanup_goal(self.TASK, invented))
        invented = self._valid()
        invented["save_button_name"] = "提交"
        self.assertIsNone(validate_current_app_text_cleanup_goal(self.TASK, invented))


if __name__ == "__main__":
    unittest.main()
