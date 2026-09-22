from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.windows_power_intent import (
    windows_battery_charging_read_goal,
    windows_battery_level_read_goal,
    windows_battery_saver_read_goal,
    windows_power_source_read_goal,
)


def _event(task: str, *, kind: str = "desktop_user_event", payload=None):
    return SimpleNamespace(
        kind=kind,
        task=task,
        payload=payload or {},
    )


class WindowsPowerIntentTests(unittest.TestCase):
    def test_battery_level_queries_match_direct_read_only_phrases(self) -> None:
        for task in (
            "现在电量是多少",
            "电脑电量还剩多少？",
            "告诉我当前电池电量几%",
            "how much battery is left?",
            "what is the current battery percentage?",
        ):
            with self.subTest(task=task):
                self.assertIsNotNone(windows_battery_level_read_goal(_event(task)))

    def test_power_source_queries_match_without_confusing_charging(self) -> None:
        for task in (
            "电脑现在插电了吗",
            "笔记本接电源了吗？",
            "现在在用电池还是电源",
            "is the laptop plugged in?",
            "what is the current power source?",
        ):
            with self.subTest(task=task):
                self.assertIsNotNone(windows_power_source_read_goal(_event(task)))
                self.assertIsNone(windows_battery_charging_read_goal(_event(task)))

    def test_charging_queries_match_direct_state_requests(self) -> None:
        for task in (
            "现在电池在充电吗",
            "电脑正在充电吗？",
            "笔记本充电了吗",
            "is the battery charging?",
            "is the laptop charging?",
        ):
            with self.subTest(task=task):
                self.assertIsNotNone(windows_battery_charging_read_goal(_event(task)))

    def test_battery_saver_queries_are_read_only(self) -> None:
        for task in (
            "现在省电模式开着吗",
            "当前节电模式什么状态？",
            "is battery saver on?",
            "what is the power saver status?",
        ):
            with self.subTest(task=task):
                self.assertIsNotNone(windows_battery_saver_read_goal(_event(task)))

    def test_mutations_and_broad_power_tasks_do_not_match(self) -> None:
        for task in (
            "打开省电模式",
            "关闭省电模式",
            "帮我省点电",
            "把电脑关机",
            "重启电脑",
            "电池好像有问题帮我检查一下",
            "看看电量然后打开 Chrome",
        ):
            with self.subTest(task=task):
                self.assertIsNone(windows_battery_level_read_goal(_event(task)))
                self.assertIsNone(windows_power_source_read_goal(_event(task)))
                self.assertIsNone(windows_battery_charging_read_goal(_event(task)))
                self.assertIsNone(windows_battery_saver_read_goal(_event(task)))

    def test_existing_native_or_body_payload_does_not_reenter(self) -> None:
        for payload in ({"body_action": "x"}, {"native_action": "x"}):
            with self.subTest(payload=payload):
                event = _event("现在电量是多少", payload=payload)
                self.assertIsNone(windows_battery_level_read_goal(event))
                self.assertIsNone(windows_power_source_read_goal(event))

    def test_non_desktop_and_oversized_tasks_do_not_match(self) -> None:
        self.assertIsNone(
            windows_battery_level_read_goal(
                _event("现在电量是多少", kind="scheduled_event")
            )
        )
        self.assertIsNone(
            windows_battery_saver_read_goal(
                _event("现在省电模式开着吗" + "啊" * 180)
            )
        )


if __name__ == "__main__":
    unittest.main()
