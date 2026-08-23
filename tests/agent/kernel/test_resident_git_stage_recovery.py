from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.kernel.body import BodyActionResult
from agent.kernel.models import ExecutionPath
from agent.kernel.provider_bridge import build_resident_runtime


class ResidentGitStageRecoveryTests(unittest.TestCase):
    @staticmethod
    def _git(root: Path, *args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise AssertionError(proc.stderr or proc.stdout)
        return proc.stdout.strip()

    @classmethod
    def _repo(cls, root: Path) -> Path:
        cls._git(root, "init", "-q")
        cls._git(root, "config", "user.email", "zn-tests@example.invalid")
        cls._git(root, "config", "user.name", "ZN Tests")
        target = root / "tracked.txt"
        target.write_text("base\n", encoding="utf-8")
        cls._git(root, "add", "--", target.name)
        cls._git(root, "commit", "-qm", "initial")
        target.write_text("changed\n", encoding="utf-8")
        return target

    @staticmethod
    def _run_to_terminal(resident, limit: int = 120):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach a terminal result")

    def test_body_failure_on_porcelain_recovers_to_plumbing_and_reverifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = self._repo(root)
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / ".zn" / "kernel.db",
            )
            event = resident.enqueue(
                "stage this repository path in the current Git index",
                payload={
                    "path": str(target),
                    "repo_path": str(root),
                    "expected_outcome": {
                        "kind": "git_path_staged",
                        "path": str(target),
                    },
                    "model_policy": "never",
                    "required_capabilities": ["it/git", "filesystem"],
                },
            )

            original_dispatch = resident.body._dispatch
            failed_once = False

            def dispatch(action, started):
                nonlocal failed_once
                command = str(action.args.get("command") or "")
                if (
                    not failed_once
                    and action.kind == "command"
                    and command.startswith("git add -- ")
                ):
                    failed_once = True
                    return BodyActionResult(
                        action_id=action.action_id,
                        kind=action.kind,
                        success=False,
                        data={"command": command},
                        error="synthetic porcelain staging failure",
                        event_id=action.event_id,
                        started_at=started,
                    )
                return original_dispatch(action, started)

            with patch.object(resident.body, "_dispatch", side_effect=dispatch):
                result = self._run_to_terminal(resident)

            self.assertTrue(failed_once)
            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.BODY)
            self.assertEqual(result.model_invocations, 0)
            self.assertEqual(self._git(root, "diff", "--name-only", "--", target.name), "")
            self.assertEqual(
                self._git(root, "diff", "--cached", "--name-only", "--", target.name),
                target.name,
            )

            commands = [
                item
                for item in resident.body.recent_actions(80)
                if item.event_id == event.event_id and item.kind == "command"
            ]
            self.assertEqual(len(commands), 2)
            self.assertFalse(commands[0].success)
            self.assertTrue(
                str(commands[0].data.get("command") or "").startswith("git add -- ")
            )
            self.assertTrue(commands[1].success)
            self.assertTrue(
                str(commands[1].data.get("command") or "").startswith(
                    "git update-index --add -- "
                )
            )

            experiences = resident.verified_experiences.for_event(event.event_id)
            self.assertEqual(len(experiences), 1)
            self.assertEqual(experiences[0].verdict, "verified")
            self.assertEqual(
                experiences[0].expected_outcome["action_variant"],
                "git_update_index",
            )
            self.assertNotIn(str(target), str(experiences[0].expected_outcome))
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
