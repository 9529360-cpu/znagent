from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.windows_brightness_intent import (
    windows_brightness_read_goal,
    windows_brightness_set_goal,
)


def _event(task: str, *, kind: str = "desktop_user_event", payload=None):
    return SimpleNamespace(
        kind=kind,
        task=task,
        payload=payload or {},
    )


class WindowsBrightnessIntentTests(unittest.TestCase):
    def test_absolute_brightness_set_matches_narrow_chinese_phrases(self) -> None:
        cases = {
            "把亮度调到 40%": 40.0,
            "屏幕亮度调到 25": 25.0,
            "把系统亮度设成 60%": 60.0,
            "请把屏幕亮度设置为 42％": 42.0,
        }
        for task, expected in cases.items():
            with self.subTest(task=task):
                goal = windows_brightness_set_goal(_event(task))
                self.assertIsNotNone(goal)
                self.assertEqual(goal.level_percent, expected)

    def test_absolute_brightness_set_matches_narrow_english_phrases(self) -> None:
        cases = {
            "set brightness to 40%": 40.0,
            "please set the screen brightness to 25": 25.0,
            "change brightness to 60": 60.0,
        }
        for task, expected in cases.items():
            with self.subTest(task=task):
                goal = windows_brightness_set_goal(_event(task))
                self.assertIsNotNone(goal)
                self.assertEqual(goal.level_percent, expected)

    def test_brightness_read_matches_direct_queries(self) -> None:
        for task in (
            "现在亮度是多少",
            "当前屏幕亮度多少？",
            "告诉我系统亮度是多少",
            "what is the current brightness?",
            "what's the screen brightness",
        ):
            with self.subTest(task=task):
                self.assertIsNotNone(windows_brightness_read_goal(_event(task)))

    def test_relative_automatic_or_ambiguous_phrases_do_not_match(self) -> None:
        for task in (
            "亮一点",
            "把亮度调高",
            "亮度降低一点",
            "打开自动亮度",
            "把键盘亮度调到 40%",
            "帮我处理一下屏幕太暗的问题",
            "亮度调到多少合适",
            "把亮度调到 40% 然后打开 Chrome",
        ):
            with self.subTest(task=task):
                self.assertIsNone(windows_brightness_set_goal(_event(task)))
                self.assertIsNone(windows_brightness_read_goal(_event(task)))

    def test_existing_native_or_body_payload_does_not_reenter_reflex(self) -> None:
        for payload in ({"body_action": "x"}, {"native_action": "x"}):
            with self.subTest(payload=payload):
                event = _event("把亮度调到 40%", payload=payload)
                self.assertIsNone(windows_brightness_set_goal(event))
                self.assertIsNone(windows_brightness_read_goal(event))

    def test_out_of_range_and_fractional_requests_are_preserved_not_clamped(self) -> None:
        out_of_range = windows_brightness_set_goal(_event("把亮度调到 150%"))
        fractional = windows_brightness_set_goal(_event("把亮度调到 42.5%"))

        self.assertIsNotNone(out_of_range)
        self.assertEqual(out_of_range.level_percent, 150.0)
        self.assertIsNotNone(fractional)
        self.assertEqual(fractional.level_percent, 42.5)

    def test_non_desktop_event_and_oversized_task_do_not_match(self) -> None:
        self.assertIsNone(
            windows_brightness_set_goal(
                _event("把亮度调到 40%", kind="scheduled_event")
            )
        )
        self.assertIsNone(
            windows_brightness_read_goal(
                _event("现在亮度是多少" + "啊" * 180)
            )
        )


if __name__ == "__main__":
    unittest.main()
