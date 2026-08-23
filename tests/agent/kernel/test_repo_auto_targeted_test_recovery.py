from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class RepoAutoTargetedTestRecoveryTests(unittest.TestCase):
    @staticmethod
    def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

    @classmethod
    def _repo(cls, root: Path) -> tuple[Path, Path, Path]:
        cls._git(root, "init")
        cls._git(root, "config", "user.name", "ZN Test")
        cls._git(root, "config", "user.email", "zn-test@example.invalid")
        (root / "agent/kernel").mkdir(parents=True)
        (root / "tests/agent/kernel").mkdir(parents=True)
        (root / ".github/workflows").mkdir(parents=True)
        (root / "agent/__init__.py").write_text("", encoding="utf-8")
        (root / "agent/kernel/__init__.py").write_text("", encoding="utf-8")
        target = root / "agent/kernel/sample.py"
        target.write_text(
            'def current_value():\n    return "before"\n',
            encoding="utf-8",
        )
        test_file = root / "tests/agent/kernel/test_sample.py"
        test_file.write_text(
            "import unittest\n"
            "from agent.kernel.sample import current_value\n\n"
            "class SampleTests(unittest.TestCase):\n"
            "    def test_current_value(self):\n"
            "        self.assertEqual(current_value(), 'after')\n",
            encoding="utf-8",
        )
        ci_file = root / ".github/workflows/zn-ci.yml"
        ci_file.write_text(
            "name: Test\n"
            "jobs:\n"
            "  kernel:\n"
            "    steps:\n"
            "      - run: uv run python -m unittest discover "
            "-s tests/agent/kernel -p 'test_*.py' -v\n",
            encoding="utf-8",
        )
        cls._git(root, "add", ".")
        cls._git(root, "commit", "-m", "baseline")
        return target, test_file, ci_file

    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 40) -> None:
        for _ in range(limit):
            if resident.store.get_working_state().stage == stage:
                return
            result = resident.live_once()
            if result is not None:
                raise AssertionError(
                    f"event reached terminal result before stage {stage}: {result}"
                )
        raise AssertionError(
            f"resident did not reach stage {stage}; current="
            f"{resident.store.get_working_state().stage}"
        )

    @staticmethod
    def _run_to_terminal(resident, limit: int = 72):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach terminal result")

    @staticmethod
    def _actions(resident, event_id: str):
        return [
            item
            for item in reversed(resident.body.recent_actions(240))
            if item.event_id == event_id
        ]

    @staticmethod
    def _enqueue(resident, root: Path, target: Path):
        return resident.enqueue(
            f"replace {target} with the requested content",
            payload={
                "path": str(target),
                "content": 'def current_value():\n    return "after"\n',
                "append": False,
                "workspace_path": str(root),
                "required_capabilities": ["filesystem", "it/git"],
                "model_policy": "never",
            },
        )

    def test_restart_preserves_resident_formed_test_as_required_verifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            target, _, _ = self._repo(root)
            db = base / "resident" / "kernel.db"
            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            event = self._enqueue(first, root, target)
            self._advance_until_stage(first, "native_action")

            self.assertIsNone(first.live_once())
            state = first.store.get_working_state()
            self.assertEqual(state.stage, "native_verification")
            targeted = state.data["native_repo_text_baseline"]["targeted_test"]
            self.assertEqual(targeted["identity_source"], "resident_repo_evidence")
            self.assertEqual(
                targeted["relative_path"],
                "tests/agent/kernel/test_sample.py",
            )
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            result = self._run_to_terminal(second)
            self.assertTrue(result.success)
            self.assertIn("resident-derived targeted unittest", result.reason)
            commands = [
                item
                for item in self._actions(second, event.event_id)
                if item.kind == "command"
            ]
            self.assertEqual(len(commands), 1)
            second.store.close()

    def test_ci_evidence_changed_after_write_blocks_test_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            target, _, ci_file = self._repo(root)
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )
            event = self._enqueue(resident, root, target)
            self._advance_until_stage(resident, "native_action")
            self.assertIsNone(resident.live_once())
            self.assertEqual(
                resident.store.get_working_state().stage,
                "native_verification",
            )

            ci_file.write_text(
                ci_file.read_text(encoding="utf-8") + "\n# stale after movement\n",
                encoding="utf-8",
            )
            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertIn(
                "kernel CI contract has unstaged changes",
                state.data["local_failure"],
            )
            commands = [
                item
                for item in self._actions(resident, event.event_id)
                if item.kind == "command"
            ]
            self.assertEqual(commands, [])
            resident.store.close()

    def test_test_source_changed_after_write_blocks_test_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            target, test_file, _ = self._repo(root)
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )
            event = self._enqueue(resident, root, target)
            self._advance_until_stage(resident, "native_action")
            self.assertIsNone(resident.live_once())

            test_file.write_text(
                test_file.read_text(encoding="utf-8") + "\n# stale after movement\n",
                encoding="utf-8",
            )
            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertIn(
                "targeted test has unstaged changes",
                state.data["local_failure"],
            )
            commands = [
                item
                for item in self._actions(resident, event.event_id)
                if item.kind == "command"
            ]
            self.assertEqual(commands, [])
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
