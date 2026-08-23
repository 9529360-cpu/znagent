from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.investigation import NativeInvestigator
from zn_agent.core.models import AgentEvent
from zn_agent.core.provider_bridge import build_resident_runtime


class ResidentGitStageResolutionTests(unittest.TestCase):
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
        return target

    @staticmethod
    def _event(root: Path, target: Path, event_id: str = "evt-git-satisfied") -> AgentEvent:
        return AgentEvent(
            event_id=event_id,
            task="stage this repository path in the current Git index",
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

    @staticmethod
    def _facts(root: Path, target: Path, *, staged=False, unstaged=False, conflicted=False):
        rel = target.relative_to(root).as_posix()
        return {
            "paths": [
                {
                    "path": str(target),
                    "exists": True,
                    "type": "file",
                    "size_bytes": target.stat().st_size,
                }
            ],
            "git": {
                "available": True,
                "root": str(root),
                "staged_paths": [rel] if staged else [],
                "unstaged_paths": [rel] if unstaged else [],
                "untracked_paths": [],
                "conflicted_paths": [rel] if conflicted else [],
            },
        }

    @staticmethod
    def _run_to_terminal(resident, limit: int = 80):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach a terminal result")

    def test_native_facts_resolve_only_exclusively_staged_current_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "tracked.txt"
            target.write_text("changed\n", encoding="utf-8")
            event = self._event(root, target)

            response = NativeInvestigator._answer_from_native_facts(
                event,
                self._facts(root, target, staged=True),
            )
            self.assertIn("already satisfied", response)
            self.assertIn("tracked.txt", response)

            for name, facts in (
                (
                    "staged_and_unstaged",
                    self._facts(root, target, staged=True, unstaged=True),
                ),
                ("conflicted", self._facts(root, target, staged=True, conflicted=True)),
                ("missing_git", {"paths": self._facts(root, target)["paths"]}),
                ("missing_path", {"git": self._facts(root, target, staged=True)["git"]}),
            ):
                with self.subTest(case=name):
                    self.assertEqual(
                        NativeInvestigator._answer_from_native_facts(event, facts),
                        "",
                    )

    def test_active_resident_finishes_satisfied_goal_without_mutation_or_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = self._repo(root)
            target.write_text("changed\n", encoding="utf-8")
            self._git(root, "add", "--", target.name)

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

            result = self._run_to_terminal(resident)

            self.assertTrue(result.success)
            self.assertEqual(result.model_invocations, 0)
            self.assertIn("already satisfied", result.response)
            self.assertEqual(resident.verified_experiences.for_event(event.event_id), [])

            movements = [
                item.kind
                for item in resident.body.recent_actions(50)
                if item.event_id == event.event_id
            ]
            self.assertIn("inspect_path", movements)
            self.assertIn("git_state", movements)
            self.assertNotIn("command", movements)
            self.assertEqual(
                self._git(root, "diff", "--cached", "--name-only", "--", target.name),
                target.name,
            )
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
