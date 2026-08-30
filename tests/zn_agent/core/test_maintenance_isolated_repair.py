from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.health_aware_resident import HealthAwareResidentRuntime
from zn_agent.core.provider_bridge import build_resident_runtime


class MaintenanceIsolatedRepairTests(unittest.TestCase):
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
        cls._git(root, "remote", "add", "origin", "https://example.invalid/zn-source.git")

    @staticmethod
    def _resident(tmp: str) -> HealthAwareResidentRuntime:
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )
        assert isinstance(resident, HealthAwareResidentRuntime)
        return resident

    @staticmethod
    def _open_task(resident: HealthAwareResidentRuntime) -> dict:
        for _ in range(3):
            resident.health.record_failure(
                "channel:repair-test",
                AssertionError("isolated-repair-regression"),
            )
        task = resident.health.maintenance_task("channel:repair-test")
        assert task is not None
        return task

    @staticmethod
    def _cleanup_worktree(source_root: Path, attempt_root: Path, branch: str) -> None:
        if attempt_root.exists():
            subprocess.run(
                ["git", "-C", str(source_root), "worktree", "remove", "--force", str(attempt_root)],
                check=False,
                capture_output=True,
                text=True,
            )
        subprocess.run(
            ["git", "-C", str(source_root), "branch", "-D", branch],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_formal_resident_forms_verified_isolated_repair_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            resident = self._resident(tmp)
            task = self._open_task(resident)
            branch = f"work/self-maintenance-{task['task_id'][:12]}-repair"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "attempt-one"
            try:
                observed = resident.investigate_maintenance_source(
                    task["task_id"],
                    source_root=source_root,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )
                self.assertFalse(observed["dirty"])
                self.assertEqual(len(observed["origin_fingerprint"]), 64)

                result = resident.run_maintenance_repair_attempt(
                    task["task_id"],
                    source_root=source_root,
                    attempt_root=attempt_root,
                    branch_ref=branch,
                    replacements={
                        "runtime/python/zn_agent/core/repair_fixture.py": "VALUE = 2\n"
                    },
                )

                self.assertEqual(result["branch_ref"], branch)
                self.assertEqual(result["authority"], "isolated_source_write")
                self.assertTrue(result["diff_check_passed"])
                self.assertTrue(result["regression_passed"])
                self.assertEqual(
                    result["changed_paths"],
                    ["runtime/python/zn_agent/core/repair_fixture.py"],
                )
                self.assertEqual(result["investigation"]["attempt_count"], 1)
                self.assertEqual(result["investigation"]["acceptance_state"], "unreviewed")

                source_value = (source_root / "runtime/python/zn_agent/core/repair_fixture.py").read_text(
                    encoding="utf-8"
                )
                attempt_value = (attempt_root / "runtime/python/zn_agent/core/repair_fixture.py").read_text(
                    encoding="utf-8"
                )
                self.assertEqual(source_value, "VALUE = 1\n")
                self.assertEqual(attempt_value, "VALUE = 2\n")

                status_after_oracle = self._git(
                    attempt_root,
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                ).stdout.splitlines()
                self.assertEqual(
                    status_after_oracle,
                    [" M runtime/python/zn_agent/core/repair_fixture.py"],
                )

                status = resident.status()["maintenance_repair_attempts"]
                self.assertTrue(status["available"])
                self.assertEqual(status["attempt_evidence_count"], 1)
                self.assertEqual(status["attempts"][0]["branch_ref"], branch)
                self.assertTrue(status["attempts"][0]["regression_passed"])
                self.assertNotIn(str(attempt_root), repr(status))
                self.assertNotIn("VALUE = 2", repr(status))
            finally:
                self._cleanup_worktree(source_root, attempt_root, branch)
                resident.managed_browser.close()
                resident.store.close()

    def test_origin_drift_is_rejected_before_worktree_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            resident = self._resident(tmp)
            task = self._open_task(resident)
            branch = f"work/self-maintenance-{task['task_id'][:12]}-origin-drift"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "attempt-origin-drift"
            try:
                resident.investigate_maintenance_source(
                    task["task_id"],
                    source_root=source_root,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )
                self._git(source_root, "remote", "set-url", "origin", "https://example.invalid/rebound.git")

                with self.assertRaisesRegex(RuntimeError, "source origin changed"):
                    resident.run_maintenance_repair_attempt(
                        task["task_id"],
                        source_root=source_root,
                        attempt_root=attempt_root,
                        branch_ref=branch,
                        replacements={
                            "runtime/python/zn_agent/core/repair_fixture.py": "VALUE = 2\n"
                        },
                    )
                self.assertFalse(attempt_root.exists())
                self.assertEqual(
                    self._git(source_root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode,
                    1,
                )
            finally:
                resident.managed_browser.close()
                resident.store.close()

    def test_stale_baseline_is_rejected_before_worktree_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            resident = self._resident(tmp)
            task = self._open_task(resident)
            branch = f"work/self-maintenance-{task['task_id'][:12]}-stale"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "attempt-stale"
            try:
                resident.investigate_maintenance_source(
                    task["task_id"],
                    source_root=source_root,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )
                (source_root / "README.md").write_text("drift\n", encoding="utf-8")
                self._git(source_root, "add", "README.md")
                self._git(source_root, "commit", "-m", "advance baseline")

                with self.assertRaisesRegex(RuntimeError, "HEAD drifted"):
                    resident.run_maintenance_repair_attempt(
                        task["task_id"],
                        source_root=source_root,
                        attempt_root=attempt_root,
                        branch_ref=branch,
                        replacements={
                            "runtime/python/zn_agent/core/repair_fixture.py": "VALUE = 2\n"
                        },
                    )
                self.assertFalse(attempt_root.exists())
                self.assertEqual(
                    self._git(source_root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode,
                    1,
                )
            finally:
                resident.managed_browser.close()
                resident.store.close()

    def test_dirty_source_is_rejected_before_worktree_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            resident = self._resident(tmp)
            task = self._open_task(resident)
            branch = f"work/self-maintenance-{task['task_id'][:12]}-dirty"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "attempt-dirty"
            try:
                resident.investigate_maintenance_source(
                    task["task_id"],
                    source_root=source_root,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )
                (source_root / "runtime/python/zn_agent/core/repair_fixture.py").write_text(
                    "VALUE = 99\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(RuntimeError, "became dirty"):
                    resident.run_maintenance_repair_attempt(
                        task["task_id"],
                        source_root=source_root,
                        attempt_root=attempt_root,
                        branch_ref=branch,
                        replacements={
                            "runtime/python/zn_agent/core/repair_fixture.py": "VALUE = 2\n"
                        },
                    )
                self.assertFalse(attempt_root.exists())
            finally:
                resident.managed_browser.close()
                resident.store.close()

    def test_replacement_outside_core_boundary_is_rejected_without_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            resident = self._resident(tmp)
            task = self._open_task(resident)
            branch = f"work/self-maintenance-{task['task_id'][:12]}-escape"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "attempt-escape"
            try:
                resident.investigate_maintenance_source(
                    task["task_id"],
                    source_root=source_root,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )
                with self.assertRaisesRegex(ValueError, "outside the ZN core repair boundary"):
                    resident.run_maintenance_repair_attempt(
                        task["task_id"],
                        source_root=source_root,
                        attempt_root=attempt_root,
                        branch_ref=branch,
                        replacements={"docs/escape.py": "changed = True\n"},
                    )
                self.assertFalse(attempt_root.exists())
                self.assertEqual(
                    self._git(source_root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode,
                    1,
                )
            finally:
                resident.managed_browser.close()
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
