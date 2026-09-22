from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.windows_audio import validate_volume_percent
from zn_agent.core.windows_audio_intent import (
    windows_audio_volume_read_goal,
    windows_audio_volume_set_goal,
)


def _event(task: str, *, kind: str = "desktop_user_event", payload=None):
    return SimpleNamespace(
        kind=kind,
        task=task,
        payload=payload or {},
    )


class WindowsAudioIntentTests(unittest.TestCase):
    def test_absolute_volume_set_matches_narrow_chinese_phrases(self) -> None:
        cases = {
            "把音量调到 40%": 40.0,
            "声音调到 25": 25.0,
            "把音量设成 60%": 60.0,
            "请把系统音量设置为 42.5％": 42.5,
        }
        for task, expected in cases.items():
            with self.subTest(task=task):
                goal = windows_audio_volume_set_goal(_event(task))
                self.assertIsNotNone(goal)
                self.assertEqual(goal.level_percent, expected)



    def test_absolute_volume_set_matches_narrow_english_phrases(self) -> None:
        cases = {
            "set volume to 40%": 40.0,
            "please set the system volume to 25": 25.0,
            "change volume to 60": 60.0,
        }
        for task, expected in cases.items():
            with self.subTest(task=task):
                goal = windows_audio_volume_set_goal(_event(task))
                self.assertIsNotNone(goal)
                self.assertEqual(goal.level_percent, expected)

    def test_volume_read_matches_direct_queries(self) -> None:
        for task in (
            "现在音量是多少",
            "当前声音多少？",
            "告诉我系统音量是多少",
            "what is the current volume?",
            "what's the system volume",
        ):
            with self.subTest(task=task):
                self.assertIsNotNone(windows_audio_volume_read_goal(_event(task)))



    def test_relative_or_ambiguous_audio_phrases_do_not_match(self) -> None:
        for task in (
            "声音大一点",
            "把音量调高",
            "音量降低一点",
            "帮我处理一下声音问题",
            "音量调到多少合适",
            "把音量调到 40% 然后打开 Chrome",
        ):
            with self.subTest(task=task):
                self.assertIsNone(windows_audio_volume_set_goal(_event(task)))
                self.assertIsNone(windows_audio_volume_read_goal(_event(task)))

    def test_existing_native_or_body_payload_does_not_reenter_reflex(self) -> None:
        for payload in ({"body_action": "x"}, {"native_action": "x"}):
            with self.subTest(payload=payload):
                event = _event("把音量调到 40%", payload=payload)
                self.assertIsNone(windows_audio_volume_set_goal(event))
                self.assertIsNone(windows_audio_volume_read_goal(event))



    def test_out_of_range_absolute_request_is_not_clamped(self) -> None:
        goal = windows_audio_volume_set_goal(_event("把音量调到 150%"))
        self.assertIsNotNone(goal)
        self.assertEqual(goal.level_percent, 150.0)
        with self.assertRaises(ValueError):
            validate_volume_percent(goal.level_percent)

    def test_non_desktop_event_and_oversized_task_do_not_match(self) -> None:
        self.assertIsNone(
            windows_audio_volume_set_goal(
                _event("把音量调到 40%", kind="scheduled_event")
            )
        )
        self.assertIsNone(
            windows_audio_volume_read_goal(
                _event("现在音量是多少" + "啊" * 180)
            )
        )


if __name__ == "__main__":
    unittest.main()
