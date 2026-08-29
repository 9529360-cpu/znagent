from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognitive_maintenance_resident import CognitiveMaintenanceResidentRuntime
from zn_agent.core.models import ModelRoute, WorkerResult
from zn_agent.core.provider_bridge import build_resident_runtime


class _ScriptedWorker:
    def __init__(self, factory, route):
        self.factory = factory
        self.route = route

    def run(self, goal, kernel_context):
        queue = self.factory.responses.setdefault(self.route.route_id, [])
        if not queue:
            return WorkerResult(success=False, error="no scripted response")
        return WorkerResult(success=True, response=queue.pop(0))


class _ScriptedFactory:
    def __init__(self, responses):
        self.responses = {key: list(value) for key, value in responses.items()}

    def create(self, route):
        return _ScriptedWorker(self, route)

    def set_health_observer(self, observer):
        return None


class MaintenancePublicationPreparationTests(unittest.TestCase):
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
        cls._git(root, "remote", "add", "origin", "https://github.com/9529360-cpu/znagent.git")

    @staticmethod
    def _routes():
        return [
            ModelRoute(
                route_id="author",
                provider="test",
                model="author-model",
                capabilities={"general": 1.0},
                reliability=1.0,
                cost_weight=0.0,
                latency_weight=0.0,
            ),
            ModelRoute(
                route_id="reviewer",
                provider="test",
                model="review-model",
                capabilities={"general": 0.9},
                reliability=0.9,
                cost_weight=0.0,
                latency_weight=0.0,
            ),
        ]

    def _resident(self, tmp: str, responses=None) -> CognitiveMaintenanceResidentRuntime:
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )
        self.assertIsInstance(resident, CognitiveMaintenanceResidentRuntime)
        if responses is not None:
            resident.kernel.reconfigure_resources(
                routes=self._routes(),
                worker_factory=_ScriptedFactory(responses),
                max_attempts=1,
                resource_status={"available": True, "error": None},
            )
        return resident

    @staticmethod
    def _open_task(resident: CognitiveMaintenanceResidentRuntime, organ: str) -> dict:
        for _ in range(3):
            resident.health.record_failure(organ, AssertionError("publication-regression"))
        task = resident.health.maintenance_task(organ)
        assert task is not None
        return task

    @staticmethod
    def _cleanup(source_root: Path, attempt_root: Path, branch: str) -> None:
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

    @staticmethod
    def _responses(target: str):
        return {
            "author": [
                json.dumps({"paths": [target], "rationale": "repair fixture"}),
                json.dumps({"replacements": {target: "VALUE = 2\n"}, "rationale": "match contract"}),
            ],
            "reviewer": [
                json.dumps(
                    {
                        "decision": "accept",
                        "reason_code": "minimal_regression_fix",
                        "rationale": "bounded change matches incident and oracle",
                    }
                )
            ],
        }

    def test_accepted_cognitive_repair_becomes_local_publication_commit_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            target = "runtime/python/zn_agent/core/repair_fixture.py"
            resident = self._resident(tmp, self._responses(target))
            task = self._open_task(resident, "channel:publication-test")
            branch = f"work/self-maintenance-{task['task_id'][:12]}-publication"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "publication-one"
            baseline = self._git(source_root, "rev-parse", "HEAD").stdout.strip()
            try:
                resident.investigate_maintenance_source(
                    task["task_id"],
                    source_root=source_root,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )
                result = resident.run_cognitive_maintenance_repair(
                    task["task_id"],
                    source_root=source_root,
                    attempt_root=attempt_root,
                    branch_ref=branch,
                )
                prepared = result["publication_preparation"]
                self.assertTrue(prepared["completed"])
                self.assertEqual(prepared["authority"], "local_commit_only")
                self.assertEqual(result["semantic_review"]["decision"], "accept")
                self.assertEqual((source_root / target).read_text(encoding="utf-8"), "VALUE = 1\n")
                self.assertEqual((attempt_root / target).read_text(encoding="utf-8"), "VALUE = 2\n")
                self.assertEqual(self._git(attempt_root, "status", "--porcelain=v1").stdout, "")
                commit_sha = self._git(attempt_root, "rev-parse", "HEAD").stdout.strip()
                parent = self._git(attempt_root, "rev-parse", "HEAD^").stdout.strip()
                self.assertEqual(commit_sha, prepared["commit_sha"])
                self.assertEqual(parent, baseline)
                changed = [
                    item
                    for item in self._git(
                        attempt_root,
                        "diff-tree",
                        "--no-commit-id",
                        "--name-only",
                        "-r",
                        "HEAD",
                    ).stdout.splitlines()
                    if item
                ]
                self.assertEqual(changed, [target])

                again = resident.prepare_accepted_maintenance_publication(
                    task["task_id"], source_root=source_root
                )
                self.assertEqual(again["commit_sha"], commit_sha)
                status = resident.status()["maintenance_publication_preparation"]
                self.assertTrue(status["available"])
                self.assertEqual(status["prepared_count"], 1)
                self.assertNotIn(str(source_root), repr(status))
                self.assertNotIn(str(attempt_root), repr(status))
                self.assertNotIn("VALUE = 2", repr(status))
            finally:
                self._cleanup(source_root, attempt_root, branch)
                resident.managed_browser.close()
                resident.store.close()

    def test_manual_ledger_acceptance_without_semantic_review_cannot_prepare_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            target = "runtime/python/zn_agent/core/repair_fixture.py"
            resident = self._resident(tmp)
            task = self._open_task(resident, "channel:publication-no-review")
            branch = f"work/self-maintenance-{task['task_id'][:12]}-no-review"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "publication-no-review"
            try:
                resident.investigate_maintenance_source(
                    task["task_id"],
                    source_root=source_root,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )
                attempt = resident.run_maintenance_repair_attempt(
                    task["task_id"],
                    source_root=source_root,
                    attempt_root=attempt_root,
                    branch_ref=branch,
                    replacements={target: "VALUE = 2\n"},
                )
                resident.maintenance.accept(task["task_id"], attempt_key=attempt["attempt_key"])
                with self.assertRaisesRegex(RuntimeError, "semantic acceptance"):
                    resident.prepare_accepted_maintenance_publication(
                        task["task_id"], source_root=source_root
                    )
                self.assertEqual(self._git(attempt_root, "rev-parse", "HEAD").stdout.strip(), attempt["baseline_head"])
                self.assertNotEqual(self._git(attempt_root, "status", "--porcelain=v1").stdout, "")
            finally:
                self._cleanup(source_root, attempt_root, branch)
                resident.managed_browser.close()
                resident.store.close()

    def test_accepted_repair_diff_drift_is_rejected_before_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            target = "runtime/python/zn_agent/core/repair_fixture.py"
            resident = self._resident(tmp, self._responses(target))
            task = self._open_task(resident, "channel:publication-drift")
            branch = f"work/self-maintenance-{task['task_id'][:12]}-drift"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "publication-drift"
            try:
                resident.investigate_maintenance_source(
                    task["task_id"],
                    source_root=source_root,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )
                result = resident._maintenance_cognitive_orchestrator().derive_execute_and_review(
                    task["task_id"],
                    source_root=source_root,
                    attempt_root=attempt_root,
                    branch_ref=branch,
                )
                self.assertEqual(result["semantic_review"]["decision"], "accept")
                (attempt_root / target).write_text("VALUE = 3\n", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "diff drifted"):
                    resident.prepare_accepted_maintenance_publication(
                        task["task_id"], source_root=source_root
                    )
                self.assertEqual(
                    self._git(attempt_root, "rev-parse", "HEAD").stdout.strip(),
                    result["investigation"]["baseline_ref"].removeprefix("commit:"),
                )
            finally:
                self._cleanup(source_root, attempt_root, branch)
                resident.managed_browser.close()
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
