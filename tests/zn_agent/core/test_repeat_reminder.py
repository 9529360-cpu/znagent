"""DSH-4 tiered repeat reminders: thresholds, identity, reset, advisory-only.

Unit tests for the pure ``repeat_reminder`` module. The resident-loop
wiring (reminder injected into the next cognition question, execution
continuing) is covered in test_team_feedback_loop.py.
"""

from __future__ import annotations

import unittest

from zn_agent.core.repeat_reminder import (
    canonical_tool_identity,
    observe_tool_call,
    pending_reminder,
    reminder_for_streak,
)


def _observe(history, *, run_id="run-1", message_id="msg-1", **kwargs):
    observe_tool_call(
        history, run_id=run_id, message_id=message_id, **kwargs
    )
    return pending_reminder(history, run_id=run_id, message_id=message_id)


class CanonicalIdentityTests(unittest.TestCase):
    def test_key_order_does_not_change_identity(self):
        """Deep-sorted keys: reordered keys are the same call."""
        first = canonical_tool_identity(
            "write_file",
            {"path": "app.py", "content": {"a": 1, "b": {"c": 2, "d": 3}}},
        )
        reordered = canonical_tool_identity(
            "write_file",
            {"content": {"b": {"d": 3, "c": 2}, "a": 1}, "path": "app.py"},
        )
        self.assertEqual(first, reordered)

    def test_different_values_are_different_calls(self):
        base = canonical_tool_identity(
            "write_file", {"path": "app.py", "content": "x\n"}
        )
        self.assertNotEqual(
            base,
            canonical_tool_identity(
                "write_file", {"path": "app.py", "content": "y\n"}
            ),
        )
        self.assertNotEqual(
            base,
            canonical_tool_identity(
                "write_file", {"path": "other.py", "content": "x\n"}
            ),
        )

    def test_different_tools_are_different_calls(self):
        self.assertNotEqual(
            canonical_tool_identity("write_file", {"path": "app.py"}),
            canonical_tool_identity("run_python", {"path": "app.py"}),
        )

    def test_non_json_values_normalize_without_raising(self):
        identity = canonical_tool_identity(
            "run_python", {"path": "s.py", "args": [("a", "b"), {1, 2}]}
        )
        self.assertIsInstance(identity, str)
        self.assertTrue(identity)


class ThresholdTests(unittest.TestCase):
    def test_reminders_fire_exactly_at_3_5_8(self):
        """Short at 3, detailed (tool + params named) at 5 and 8."""
        history: dict = {}
        seen: list = []
        for _ in range(9):
            seen.append(
                _observe(
                    history,
                    tool="run_python",
                    params={"path": "s.py", "command": "python s.py"},
                    params_display="path=s.py, command='python s.py'",
                )
            )
        self.assertIsNone(seen[0])
        self.assertIsNone(seen[1])
        self.assertIsNotNone(seen[2])
        assert seen[2] is not None
        self.assertIn("连续 3 次", seen[2])
        self.assertNotIn("参数为", seen[2])
        self.assertIsNone(seen[3])
        self.assertIsNotNone(seen[4])
        assert seen[4] is not None
        self.assertIn("连续 5 次", seen[4])
        self.assertIn("run_python", seen[4])
        self.assertIn("path=s.py", seen[4])
        self.assertIsNone(seen[5])
        self.assertIsNone(seen[6])
        self.assertIsNotNone(seen[7])
        assert seen[7] is not None
        self.assertIn("连续 8 次", seen[7])
        self.assertIn("run_python", seen[7])
        self.assertIsNone(seen[8])

    def test_reminder_for_streak_is_none_off_threshold(self):
        for streak in (1, 2, 4, 6, 7, 9, 100):
            self.assertIsNone(
                reminder_for_streak(
                    streak=streak, tool="run_python", params_display="x"
                )
            )

    def test_different_call_resets_streak(self):
        """Consecutive counting: any other call restarts the streak."""
        history: dict = {}
        same = {
            "tool": "run_python",
            "params": {"path": "s.py", "command": "python s.py"},
            "params_display": "path=s.py",
        }
        other = {
            "tool": "write_file",
            "params": {"path": "s.py", "content": "x"},
            "params_display": "path=s.py",
        }
        _observe(history, **same)
        _observe(history, **same)
        _observe(history, **other)
        # Two more identical calls: streak is 2, not 4 -- no reminder.
        _observe(history, **same)
        self.assertIsNone(_observe(history, **same))
        # Third consecutive identical call: short reminder again.
        reminder = _observe(history, **same)
        self.assertIsNotNone(reminder)
        assert reminder is not None
        self.assertIn("连续 3 次", reminder)


class ResetTests(unittest.TestCase):
    def test_new_user_message_clears_count(self):
        """A new work_message_id resets the streak to 1."""
        history: dict = {}
        same = {
            "tool": "run_python",
            "params": {"path": "s.py", "command": "python s.py"},
            "params_display": "path=s.py",
        }
        _observe(history, message_id="msg-1", **same)
        _observe(history, message_id="msg-1", **same)
        # New user message: the stored pending state is not shown...
        self.assertIsNone(
            pending_reminder(history, run_id="run-1", message_id="msg-2")
        )
        # ...and the next identical call starts a fresh streak of 1.
        self.assertIsNone(_observe(history, message_id="msg-2", **same))
        self.assertIsNone(_observe(history, message_id="msg-2", **same))

    def test_new_run_clears_count(self):
        history: dict = {}
        same = {
            "tool": "run_python",
            "params": {"path": "s.py", "command": "python s.py"},
            "params_display": "path=s.py",
        }
        _observe(history, run_id="run-1", **same)
        _observe(history, run_id="run-1", **same)
        self.assertIsNone(
            pending_reminder(history, run_id="run-2", message_id="msg-1")
        )
        self.assertIsNone(_observe(history, run_id="run-2", **same))

    def test_pending_reminder_needs_a_dict(self):
        self.assertIsNone(
            pending_reminder(None, run_id="run-1", message_id="msg-1")
        )
        self.assertIsNone(
            pending_reminder("not-a-dict", run_id="run-1", message_id="msg-1")
        )


if __name__ == "__main__":
    unittest.main()
