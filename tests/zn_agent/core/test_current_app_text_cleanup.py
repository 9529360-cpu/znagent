from __future__ import annotations

import unittest

from zn_agent.core.automation_text_content import (
    AutomationTextRead,
    AutomationTextTargetSnapshot,
    AutomationValueReplacementResult,
    NativeAutomationTextContentSense,
    NativeAutomationValueReplacementBody,
    text_sha256,
)
from zn_agent.core.current_app_text_cleanup_goal import (
    CURRENT_APP_TEXT_CLEANUP_GOAL_KIND,
    TRIM_DROP_BLANK_DEDUPE_STABLE,
    deterministic_text_cleanup,
    validate_current_app_text_cleanup_goal,
)
from zn_agent.core.models import AgentEvent


RID = (42, 7, 99)


def _target(
    *,
    runtime_id=RID,
    process_id=222,
    process_name="fixture.exe",
    name="工作记录",
    password=False,
    value=True,
    read_only=False,
    enabled=True,
    offscreen=False,
):
    return AutomationTextTargetSnapshot(
        runtime_id=tuple(runtime_id),
        process_id=process_id,
        process_name=process_name,
        window_handle=8181,
        name=name,
        control_type=50004,
        class_name="WindowsForms10.EDIT.app.0",
        is_enabled=enabled,
        is_offscreen=offscreen,
        is_password=password,
        is_value_pattern_available=value,
        value_is_read_only=read_only,
        captured_at="2026-09-12T00:00:00+00:00",
        source="test-uia",
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


class TextContentSenseContractTests(unittest.TestCase):
    def _sense(self, read):
        return NativeAutomationTextContentSense(read_probe_fn=lambda **_: read)

    def test_exact_safe_edit_returns_transient_raw_and_safe_audit(self):
        target = _target()
        read = AutomationTextRead(text=" A \r\nA", before=target, after=target)
        observed = self._sense(read).read_exact(
            process_id=222,
            process_name="fixture.exe",
            window_handle=8181,
            name="工作记录",
            runtime_id=RID,
        )
        self.assertEqual(observed.text, " A \r\nA")
        self.assertEqual(observed.audit["sha256"], text_sha256(" A \r\nA"))
        self.assertNotIn("text", observed.audit)

    def test_password_oversize_runtime_process_and_value_pattern_fail_closed(self):
        cases = [
            (AutomationTextRead("secret", _target(password=True), _target(password=True)), "safe exact-Edit"),
            (AutomationTextRead("x" * 4097, _target(), _target()), "oversized"),
            (AutomationTextRead("a", _target(), _target(runtime_id=(8, 8))), "RuntimeId"),
            (AutomationTextRead("a", _target(), _target(process_id=333)), "process identity"),
            (AutomationTextRead("a", _target(value=False), _target(value=False)), "safe exact-Edit"),
        ]
        for read, pattern in cases:
            with self.subTest(pattern=pattern), self.assertRaisesRegex((ValueError, TypeError), pattern):
                self._sense(read).read_exact(
                    process_id=222,
                    process_name="fixture.exe",
                    window_handle=8181,
                    name="工作记录",
                    runtime_id=RID,
                )

    def test_read_only_is_allowed_only_for_verification(self):
        target = _target(read_only=True, name="保存内容")
        read = AutomationTextRead("客户已确认方案", target, target)
        sense = self._sense(read)
        with self.assertRaisesRegex(ValueError, "read-only"):
            sense.read_exact(
                process_id=222,
                process_name="fixture.exe",
                window_handle=8181,
                name="保存内容",
                runtime_id=RID,
            )
        self.assertEqual(
            sense.read_exact(
                process_id=222,
                process_name="fixture.exe",
                window_handle=8181,
                name="保存内容",
                runtime_id=RID,
                allow_read_only=True,
            ).text,
            "客户已确认方案",
        )


class ReplacementBodyContractTests(unittest.TestCase):
    def test_happy_replacement_requires_exact_postcondition(self):
        source = " A \r\nA"
        replacement = "A"

        def replace(**kwargs):
            return AutomationValueReplacementResult(
                success=True,
                mutation_dispatched=True,
                postcondition_verified=True,
                process_id=kwargs["process_id"],
                process_name=kwargs["process_name"],
                window_handle=kwargs["window_handle"],
                name=kwargs["name"],
                runtime_id=kwargs["runtime_id"],
                source_chars=kwargs["source_chars"],
                source_sha256=kwargs["source_sha256"],
                result_chars=kwargs["result_chars"],
                result_sha256=kwargs["result_sha256"],
            )

        body = NativeAutomationValueReplacementBody(replace_probe_fn=replace)
        result = body.replace_exact(
            process_id=222,
            process_name="fixture.exe",
            window_handle=8181,
            name="工作记录",
            runtime_id=RID,
            source_chars=len(source),
            source_sha256=text_sha256(source),
            replacement_text=replacement,
            result_chars=len(replacement),
            result_sha256=text_sha256(replacement),
        )
        self.assertTrue(result.success)
        self.assertTrue(result.postcondition_verified)
        self.assertNotIn("replacement_text", result.audit)

    def test_wrong_process_foreground_precondition_hash_and_postread_are_rejected(self):
        replacement = "A"
        result_hash = text_sha256(replacement)
        cases = [
            AutomationValueReplacementResult(True, True, True, 333, "fixture.exe", 8181, "工作记录", RID, 1, text_sha256("x"), 1, result_hash),
            AutomationValueReplacementResult(True, True, True, 222, "other.exe", 8181, "工作记录", RID, 1, text_sha256("x"), 1, result_hash),
            AutomationValueReplacementResult(True, True, True, 222, "fixture.exe", 9999, "工作记录", RID, 1, text_sha256("x"), 1, result_hash),
            AutomationValueReplacementResult(True, True, True, 222, "fixture.exe", 8181, "工作记录", (9, 9), 1, text_sha256("x"), 1, result_hash),
            AutomationValueReplacementResult(True, True, False, 222, "fixture.exe", 8181, "工作记录", RID, 1, text_sha256("x"), 1, result_hash),
        ]
        for returned in cases:
            with self.subTest(returned=returned), self.assertRaises(ValueError):
                NativeAutomationValueReplacementBody(replace_probe_fn=lambda **_: returned).replace_exact(
                    process_id=222,
                    process_name="fixture.exe",
                    window_handle=8181,
                    name="工作记录",
                    runtime_id=RID,
                    source_chars=1,
                    source_sha256=text_sha256("x"),
                    replacement_text=replacement,
                    result_chars=1,
                    result_sha256=result_hash,
                )


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
