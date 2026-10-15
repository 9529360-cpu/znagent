from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from zn_agent.core.project_team import assemble_team
from zn_agent.core.specialist_debug import DebugTurn, SpecialistDebugSession
from zn_agent.core.specialist_workspace import materialize_team_workspaces


@dataclass
class FakeIncrement:
    text: str


class FakeCognition:
    """Records every (question, context) and echoes the prompt it saw."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def invoke(self, *, question: str, context: str) -> FakeIncrement:
        self.calls.append({"question": question, "context": context})
        # Echo the SOUL line the prompt carried, so the reply proves
        # which file version this turn ran under.
        soul = ""
        for line in context.splitlines():
            if "人格" in line:
                soul = line
                break
        return FakeIncrement(text=f"reply-to:{question}|saw:{soul}")


def _team_with_workspace(tmp: str):
    team = assemble_team("X", ["researcher"], team_id="t1", workspace_root=tmp)
    materialize_team_workspaces(tmp, team)
    return team


class SpecialistDebugTests(unittest.TestCase):
    def test_soul_edit_takes_effect_next_turn_without_restart(self):
        # The core FastClaw guarantee: same session object, edit the
        # file between turns, the next turn runs under the new persona.
        with tempfile.TemporaryDirectory() as tmp:
            team = _team_with_workspace(tmp)
            member = team.members[0]
            soul_path = Path(tmp) / member.name / "SOUL.md"
            soul_path.write_text("人格：只给结论。\n", encoding="utf-8")
            cognition = FakeCognition()
            session = SpecialistDebugSession(
                team=team, specialist_name=member.name, cognition=cognition
            )

            first = session.turn("你好")
            self.assertIn("只给结论", first.reply)
            self.assertFalse(first.prompt_changed)
            self.assertEqual(first.turn_index, 1)

            soul_path.write_text("人格：先问三个澄清问题。\n", encoding="utf-8")
            second = session.turn("继续")
            self.assertIn("先问三个澄清问题", second.reply)
            self.assertTrue(second.prompt_changed)
            self.assertNotEqual(second.prompt_sha, first.prompt_sha)
            self.assertEqual(second.turn_index, 2)
            # The prompt itself was re-read, not just the echo: the old
            # SOUL text must be gone from the prompt portion (it may
            # still appear inside the conversation history, as the
            # previous reply legitimately quoted it).
            prompt_part = cognition.calls[1]["context"].split("# CONVERSATION")[0]
            self.assertIn("先问三个澄清问题", prompt_part)
            self.assertNotIn("只给结论", prompt_part)

    def test_memory_edit_takes_effect_next_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            team = _team_with_workspace(tmp)
            member = team.members[0]
            memory_path = Path(tmp) / member.name / "MEMORY.md"
            cognition = FakeCognition()
            session = SpecialistDebugSession(
                team=team, specialist_name=member.name, cognition=cognition
            )
            session.turn("第一轮")
            memory_path.write_text(
                "# MEMORY\n\n- 用户偏好短回答。\n", encoding="utf-8"
            )
            session.turn("第二轮")
            self.assertIn("用户偏好短回答", cognition.calls[1]["context"])

    def test_history_carries_into_next_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            team = _team_with_workspace(tmp)
            member = team.members[0]
            cognition = FakeCognition()
            session = SpecialistDebugSession(
                team=team, specialist_name=member.name, cognition=cognition
            )
            session.turn("我的项目叫 Alpha")
            session.turn("它叫什么？")
            self.assertIn("我的项目叫 Alpha", cognition.calls[1]["context"])
            self.assertEqual(
                [entry["role"] for entry in session.history],
                ["user", "assistant", "user", "assistant"],
            )

    def test_malformed_config_falls_back_to_builtin_fragment(self):
        with tempfile.TemporaryDirectory() as tmp:
            team = _team_with_workspace(tmp)
            member = team.members[0]
            (Path(tmp) / member.name / "agent.json").write_text(
                "{broken", encoding="utf-8"
            )
            cognition = FakeCognition()
            session = SpecialistDebugSession(
                team=team, specialist_name=member.name, cognition=cognition
            )
            first = session.turn("你好")
            self.assertIsInstance(first, DebugTurn)
            self.assertIn(member.prompt_fragment, cognition.calls[0]["context"])

    def test_unknown_specialist_and_empty_message_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            team = _team_with_workspace(tmp)
            cognition = FakeCognition()
            with self.assertRaises(ValueError):
                SpecialistDebugSession(
                    team=team, specialist_name="no-such-one", cognition=cognition
                )
            session = SpecialistDebugSession(
                team=team,
                specialist_name=team.members[0].name,
                cognition=cognition,
            )
            with self.assertRaises(ValueError):
                session.turn("   ")
            self.assertEqual(cognition.calls, [])

    def test_current_prompt_and_workspace_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            team = _team_with_workspace(tmp)
            member = team.members[0]
            cognition = FakeCognition()
            session = SpecialistDebugSession(
                team=team, specialist_name=member.name, cognition=cognition
            )
            self.assertEqual(
                session.workspace_path(), Path(tmp) / member.name
            )
            (Path(tmp) / member.name / "SOUL.md").write_text(
                "人格：调试中。\n", encoding="utf-8"
            )
            self.assertIn("调试中", session.current_prompt())
            # Reading the prompt does not count as a turn.
            self.assertEqual(session.history, [])

    def test_no_workspace_root_still_debugs_with_builtin_fragment(self):
        team = assemble_team("X", ["researcher"], team_id="t1")
        member = team.members[0]
        cognition = FakeCognition()
        session = SpecialistDebugSession(
            team=team, specialist_name=member.name, cognition=cognition
        )
        self.assertIsNone(session.workspace_path())
        first = session.turn("你好")
        self.assertIn(member.prompt_fragment, cognition.calls[0]["context"])
        self.assertIn("reply-to:你好", first.reply)


if __name__ == "__main__":
    unittest.main()
