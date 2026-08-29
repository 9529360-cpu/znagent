from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognitive_maintenance_resident import CognitiveMaintenanceResidentRuntime
from zn_agent.core.provider_bridge import build_resident_runtime


class MaintenanceAttemptLifecycleTests(unittest.TestCase):
    @staticmethod
    def _git(root: Path, *parts: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(root), *parts],
            check=check,
            capture_output=True,
            text=True,
        )

    @classmethod
    def _make_repo(cls, root: Path) -> None:
        runtime_core = root / "runtime" / "python" / "zn_agent" / "core"
        tests_core = root / "tests" / "zn_agent" / "core"
        runtime_core.mkdir(parents=True)
        tests_core.mkdir(parents=True)
        (root / "ZN.md").write_text("# ZN\n", encoding="utf-8")
        (root / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
        (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (root / "tests" / "zn_agent" / "__init__.py").write_text("", encoding="utf-8")
        (tests_core / "__init__.py").write_text("", encoding="utf-8")
        (root / "runtime" / "python" / "zn_agent" / "__init__.py").write_text("", encoding="utf-8")
        (runtime_core / "__init__.py").write_text("", encoding="utf-8")
        (runtime_core / "repair_fixture.py").write_text("VALUE = 1\n", encoding="utf-8")
        (tests_core / "test_regression.py").write_text(
            "import unittest\n"
            "from zn_agent.core.repair_fixture import VALUE\n\n"
            "class RegressionTest(unittest.TestCase):\n"
            "    def test_value(self):\n"
            "        self.assertEqual(VALUE, 2)\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "init", "-b", "dev/zn-agent", str(root)],
            check=True,
            capture_output=True,
        )
        cls._git(root, "config", "user.email", "zn@example.invalid")
        cls._git(root, "config", "user.name", "ZN Test")
        cls._git(root, "add", ".")
        cls._git(root, "commit", "-m", "baseline")
        cls._git(
            root,
            "remote",
            "add",
            "origin",
            "https://github.com/9529360-cpu/znagent.git",
        )

    @staticmethod
    def _resident(tmp: str) -> CognitiveMaintenanceResidentRuntime:
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )
        assert isinstance(resident, CognitiveMaintenanceResidentRuntime)
        return resident

    @staticmethod
    def _open_task(resident: CognitiveMaintenanceResidentRuntime) -> dict:
        for _ in range(3):
            resident.health.record_failure(
                "channel:lifecycle-test",
                AssertionError("attempt-lifecycle-regression"),
            )
        task = resident.health.maintenance_task("channel:lifecycle-test")
        assert task is not None
        return task

    def _attempt(
        self,
        resident: CognitiveMaintenanceResidentRuntime,
        source_root: Path,
        task: dict,
        branch: str,
        attempt_root: Path,
    ) -> dict:
        resident.investigate_maintenance_source(
            task["task_id"],
            source_root=source_root,
            regression_oracle="test:tests/zn_agent/core/test_regression.py",
        )
        return resident.run_maintenance_repair_attempt(
            task["task_id"],
            source_root=source_root,
            attempt_root=attempt_root,
            branch_ref=branch,
            replacements={
                "runtime/python/zn_agent/core/repair_fixture.py": "VALUE = 2\n"
            },
        )

    def test_rejected_attempt_cleanup_removes_only_dedicated_worktree_and_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            resident = self._resident(tmp)
            task = self._open_task(resident)
            branch = f"work/self-maintenance-{task['task_id'][:12]}-cleanup"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "cleanup-one"
            try:
                attempt = self._attempt(resident, source_root, task, branch, attempt_root)
                self.assertTrue(attempt["regression_passed"])
                resident.maintenance.reject(task["task_id"], reason="semantic_rejected")

                cleanup = resident.cleanup_rejected_maintenance_repair(
                    task["task_id"], source_root=source_root
                )
                self.assertEqual(cleanup["disposition"], "rejected_removed")
                self.assertFalse(attempt_root.exists())
                self.assertNotIn(str(attempt_root), repr(cleanup))
                self.assertEqual(
                    self._git(
                        source_root,
                        "show-ref",
                        "--verify",
                        "--quiet",
                        f"refs/heads/{branch}",
                        check=False,
                    ).returncode,
                    1,
                )

                again = resident.cleanup_rejected_maintenance_repair(
                    task["task_id"], source_root=source_root
                )
                self.assertEqual(again["attempt_key"], cleanup["attempt_key"])
                status = resident.status()["maintenance_attempt_cleanup"]
                self.assertTrue(status["available"])
                self.assertEqual(status["cleanup_count"], 1)
            finally:
                resident.managed_browser.close()
                resident.store.close()

    def test_accepted_attempt_is_retained_and_cleanup_is_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            resident = self._resident(tmp)
            task = self._open_task(resident)
            branch = f"work/self-maintenance-{task['task_id'][:12]}-accepted"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "accepted-one"
            try:
                attempt = self._attempt(resident, source_root, task, branch, attempt_root)
                resident.maintenance.accept(
                    task["task_id"], attempt_key=str(attempt["attempt_key"])
                )
                with self.assertRaisesRegex(RuntimeError, "retained for publication"):
                    resident.cleanup_rejected_maintenance_repair(
                        task["task_id"], source_root=source_root
                    )
                self.assertTrue(attempt_root.exists())
                self.assertEqual(
                    self._git(
                        source_root,
                        "show-ref",
                        "--verify",
                        "--quiet",
                        f"refs/heads/{branch}",
                        check=False,
                    ).returncode,
                    0,
                )
            finally:
                if attempt_root.exists():
                    self._git(source_root, "worktree", "remove", "--force", str(attempt_root), check=False)
                self._git(source_root, "branch", "-D", branch, check=False)
                resident.managed_browser.close()
                resident.store.close()

    def test_rejected_attempt_that_advanced_from_baseline_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            resident = self._resident(tmp)
            task = self._open_task(resident)
            branch = f"work/self-maintenance-{task['task_id'][:12]}-advanced"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "advanced-one"
            try:
                self._attempt(resident, source_root, task, branch, attempt_root)
                resident.maintenance.reject(task["task_id"], reason="semantic_rejected")
                self._git(attempt_root, "add", ".")
                self._git(attempt_root, "commit", "-m", "unexpected advance")

                with self.assertRaisesRegex(RuntimeError, "advanced from baseline"):
                    resident.cleanup_rejected_maintenance_repair(
                        task["task_id"], source_root=source_root
                    )
                self.assertTrue(attempt_root.exists())
                self.assertEqual(
                    self._git(
                        source_root,
                        "show-ref",
                        "--verify",
                        "--quiet",
                        f"refs/heads/{branch}",
                        check=False,
                    ).returncode,
                    0,
                )
            finally:
                if attempt_root.exists():
                    self._git(source_root, "worktree", "remove", "--force", str(attempt_root), check=False)
                self._git(source_root, "branch", "-D", branch, check=False)
                resident.managed_browser.close()
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
