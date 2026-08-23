from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action import derive_native_action_intent
from zn_agent.core.models import AgentEvent
from zn_agent.core.path_context import resolve_context_path, resolved_within


class WorkspaceFileContextTests(unittest.TestCase):
    def test_relative_native_file_action_is_anchored_to_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "project"
            workspace.mkdir()
            event = AgentEvent(
                event_id="evt-relative-workspace-file",
                task="ensure notes/result.txt contains the requested content",
                payload={
                    "workspace_path": str(workspace),
                    "workdir": str(workspace),
                    "path": "notes/result.txt",
                    "content": "workspace anchored",
                },
            )

            intent = derive_native_action_intent(event, facts={"paths": []})

            self.assertIsNotNone(intent)
            assert intent is not None
            self.assertEqual(intent.kind, "write_text")
            self.assertEqual(
                intent.args["path"],
                str(workspace / "notes" / "result.txt"),
            )

    def test_explicit_body_action_path_and_workdir_inherit_workspace_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "project"
            workspace.mkdir()
            event = AgentEvent(
                event_id="evt-explicit-workspace-file",
                task="perform the requested body movement",
                payload={
                    "workspace_path": str(workspace),
                    "workdir": str(workspace),
                    "body_action": {
                        "kind": "write_text",
                        "args": {"path": "nested/file.txt", "content": "text"},
                    },
                },
            )

            intent = derive_native_action_intent(event)

            self.assertIsNotNone(intent)
            assert intent is not None
            self.assertEqual(intent.args["path"], str(workspace / "nested" / "file.txt"))
            self.assertEqual(intent.args["workdir"], str(workspace))

    def test_context_path_does_not_rebase_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            absolute = root / "outside.txt"
            self.assertEqual(
                resolve_context_path(absolute, {"workspace_path": str(workspace)}),
                absolute,
            )

    def test_resolved_within_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()
            target = outside / "secret.txt"
            target.write_text("secret", encoding="utf-8")
            link = workspace / "escaped.txt"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")

            self.assertIsNone(resolved_within(workspace, link))


if __name__ == "__main__":
    unittest.main()
