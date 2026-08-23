from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.git_semantics import (
    current_git_goal_from_intent,
    git_path_stage_state,
    git_stage_command,
)


class GitStagingSemanticsTests(unittest.TestCase):
    def test_persisted_goal_must_preserve_root_path_relative_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "nested" / "file name.txt"
            target.parent.mkdir()
            target.write_text("content", encoding="utf-8")
            raw = {
                "kind": "git_path_staged",
                "root": str(root),
                "path": str(target),
                "relative_path": "nested/file name.txt",
                "action_variant": "git_add",
            }

            normalized = current_git_goal_from_intent(raw)

            self.assertIsNotNone(normalized)
            self.assertEqual(normalized["root"], str(root))
            self.assertEqual(normalized["path"], str(target))
            self.assertEqual(normalized["relative_path"], "nested/file name.txt")
            self.assertEqual(
                git_stage_command("git_add", normalized["relative_path"]),
                "git add -- 'nested/file name.txt'",
            )
            corrupted = dict(raw)
            corrupted["relative_path"] = "other.txt"
            self.assertIsNone(current_git_goal_from_intent(corrupted))

    def test_git_state_satisfaction_requires_exclusive_staged_state(self):
        rel = "tracked.txt"
        satisfied = git_path_stage_state(
            {
                "available": True,
                "staged_paths": [rel],
                "unstaged_paths": [],
                "untracked_paths": [],
                "conflicted_paths": [],
            },
            rel,
        )
        partially_staged = git_path_stage_state(
            {
                "available": True,
                "staged_paths": [rel],
                "unstaged_paths": [rel],
                "untracked_paths": [],
                "conflicted_paths": [],
            },
            rel,
        )

        self.assertTrue(satisfied["satisfied"])
        self.assertFalse(satisfied["stageable"])
        self.assertFalse(partially_staged["satisfied"])
        self.assertTrue(partially_staged["stageable"])


if __name__ == "__main__":
    unittest.main()
