from __future__ import annotations

import unittest

from zn_agent.core.investigation import NativeInvestigator
from zn_agent.core.models import AgentEvent


class InvestigationPathExistenceIntentTests(unittest.TestCase):
    @staticmethod
    def _answer(task: str) -> str:
        event = AgentEvent(
            event_id="evt-investigation-existence",
            task=task,
            payload={"workspace_path": "C:/repo"},
        )
        facts = {
            "paths": [
                {
                    "path": "C:/repo",
                    "exists": True,
                    "type": "directory",
                    "size_bytes": 0,
                }
            ]
        }
        return NativeInvestigator._answer_from_native_facts(event, facts)

    def test_explicit_english_existence_questions_still_resolve(self) -> None:
        self.assertEqual(
            self._answer("Does this workspace exist?"),
            "C:/repo: exists",
        )
        self.assertEqual(
            self._answer("Check the existence of this workspace."),
            "C:/repo: exists",
        )

    def test_existing_is_not_misread_as_an_existence_question(self) -> None:
        self.assertEqual(
            self._answer(
                "Change the program output while preserving the existing test contract."
            ),
            "",
        )

    def test_chinese_existence_questions_still_resolve(self) -> None:
        self.assertEqual(
            self._answer("这个工作区存在吗？"),
            "C:/repo: exists",
        )
        self.assertEqual(
            self._answer("这个目录有没有？"),
            "C:/repo: exists",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
