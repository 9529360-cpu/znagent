from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack
from agent.kernel.repo_test_semantics import test_source_has_discoverable_unittest_case


class RepoAutoTargetedTestDiscoveryTests(unittest.TestCase):
    @staticmethod
    def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
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
            for item in reversed(resident.body.recent_actions(200))
            if item.event_id == event_id
        ]

    def test_discoverable_unittest_case_requires_top_level_testcase_and_test_method(self):
        self.assertTrue(
            test_source_has_discoverable_unittest_case(
                "import unittest as unit\n"
                "class Sample(unit.TestCase):\n"
                "    def test_value(self):\n"
                "        pass\n"
            )
        )
        self.assertTrue(
            test_source_has_discoverable_unittest_case(
                "from unittest import TestCase as Case\n"
                "class Sample(Case):\n"
                "    def test_value(self):\n"
                "        pass\n"
            )
        )
        for source in (
            "import unittest\nclass Sample(unittest.TestCase):\n    def helper(self):\n        pass\n",
            "import unittest\ndef factory():\n    class Sample(unittest.TestCase):\n        def test_value(self):\n            pass\n",
            "class Sample:\n    def test_value(self):\n        pass\n",
        ):
            with self.subTest(source=source):
                self.assertFalse(test_source_has_discoverable_unittest_case(source))

    def test_direct_import_without_discoverable_case_cannot_create_command_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            self._git(root, "init")
            self._git(root, "config", "user.name", "ZN Test")
            self._git(root, "config", "user.email", "zn-test@example.invalid")
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
            (root / "tests/agent/kernel/test_sample.py").write_text(
                "from agent.kernel.sample import current_value\n\n"
                "def helper_only():\n"
                "    return current_value()\n",
                encoding="utf-8",
            )
            (root / ".github/workflows/zn-ci.yml").write_text(
                "name: Test\nsteps:\n"
                "  - run: uv run python -m unittest discover "
                "-s tests/agent/kernel -p 'test_*.py' -v\n",
                encoding="utf-8",
            )
            self._git(root, "add", ".")
            self._git(root, "commit", "-m", "baseline")

            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )
            event = resident.enqueue(
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

            result = self._run_to_terminal(resident)

            self.assertTrue(result.success)
            self.assertNotIn("targeted unittest", result.reason)
            commands = [
                item
                for item in self._actions(resident, event.event_id)
                if item.kind == "command"
            ]
            self.assertEqual(commands, [])
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
