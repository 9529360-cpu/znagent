from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.application_goal import application_open_goal


class ApplicationGoalTests(unittest.TestCase):
    @staticmethod
    def _event(task: str, payload=None):
        return SimpleNamespace(kind="desktop_user_event", task=task, payload=payload or {})

    def test_chinese_open_application(self) -> None:
        goal = application_open_goal(self._event("打开 Chrome。"))
        self.assertIsNotNone(goal)
        self.assertEqual(goal.application_name, "Chrome")

    def test_english_launch_application(self) -> None:
        goal = application_open_goal(self._event("please launch VS Code"))
        self.assertIsNotNone(goal)
        self.assertEqual(goal.application_name, "VS Code")

    def test_file_url_and_raw_path_are_not_claimed_as_application_names(self) -> None:
        self.assertIsNone(application_open_goal(self._event("打开 report.pdf")))
        self.assertIsNone(application_open_goal(self._event("打开 https://example.com")))
        self.assertIsNone(application_open_goal(self._event(r"打开 C:\Windows\notepad.exe")))

    def test_structured_goal_contains_semantics_not_launch_material(self) -> None:
        goal = application_open_goal(self._event(
            "ignored",
            {"application_open_goal": {"kind": "open_installed_application", "application_name": "记事本"}},
        ))
        self.assertIsNotNone(goal)
        self.assertEqual(goal.application_name, "记事本")
        self.assertIsNone(application_open_goal(self._event(
            "ignored",
            {"application_open_goal": {"kind": "open_installed_application", "application_name": r"C:\evil.exe"}},
        )))


if __name__ == "__main__":
    unittest.main()
