from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognitive_maintenance_resident import CognitiveMaintenanceResidentRuntime
from zn_agent.core.models import ModelRoute, WorkerResult
from zn_agent.core.provider_bridge import build_resident_runtime


class _RecoveryWorker:
    def __init__(self, factory, route):
        self.factory = factory
        self.route = route

    def run(self, goal, kernel_context):
        queue = self.factory.responses.setdefault(self.route.route_id, [])
        if not queue:
            return WorkerResult(success=False, error="no scripted response")
        response = queue.pop(0)
        self.factory.calls.append(self.route.route_id)
        return WorkerResult(success=True, response=response)


class _RecoveryFactory:
    def __init__(self, responses):
        self.responses = {key: list(value) for key, value in responses.items()}
        self.calls = []

    def create(self, route):
        return _RecoveryWorker(self, route)

    def set_health_observer(self, observer):
        return None


class MaintenanceReviewRecoveryTests(unittest.TestCase):
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
        subprocess.run(["git", "init", "-b", "dev/zn-agent", str(root)], check=True, capture_output=True)
        cls._git(root, "config", "user.email", "zn@example.invalid")
        cls._git(root, "config", "user.name", "ZN Test")
        cls._git(root, "add", ".")
        cls._git(root, "commit", "-m", "baseline")
        cls._git(root, "remote", "add", "origin", "https://github.com/9529360-cpu/znagent.git")

    @staticmethod
    def _route(route_id: str, reliability: float) -> ModelRoute:
        return ModelRoute(
            route_id=route_id,
            provider="test",
            model=f"{route_id}-model",
            capabilities={"general": reliability},
            reliability=reliability,
            cost_weight=0.0,
            latency_weight=0.0,
        )

    @staticmethod
    def _open_task(resident: CognitiveMaintenanceResidentRuntime) -> dict:
        for _ in range(3):
            resident.health.record_failure(
                "channel:review-recovery-test",
                AssertionError("review-recovery-regression"),
            )
        task = resident.health.maintenance_task("channel:review-recovery-test")
        assert task is not None
        return task

    def test_unreviewed_attempt_resumes_when_independent_route_appears(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            target = "runtime/python/zn_agent/core/repair_fixture.py"
            resident = build_resident_runtime(config={"model": {}}, store_path=Path(tmp) / "kernel.db")
            self.assertIsInstance(resident, CognitiveMaintenanceResidentRuntime)
            author_factory = _RecoveryFactory(
                {
                    "author": [
                        json.dumps({"paths": [target], "rationale": "inspect fixture"}),
                        json.dumps({"replacements": {target: "VALUE = 2\n"}, "rationale": "repair"}),
                    ]
                }
            )
            resident.kernel.reconfigure_resources(
                routes=[self._route("author", 1.0)],
                worker_factory=author_factory,
                max_attempts=1,
                resource_status={"available": True, "error": None},
            )
            task = self._open_task(resident)
            branch = f"work/self-maintenance-{task['task_id'][:12]}-recover"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "review-recovery"
            try:
                resident.investigate_maintenance_source(
                    task["task_id"],
                    source_root=source_root,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )
                initial = resident.run_cognitive_maintenance_repair(
                    task["task_id"],
                    source_root=source_root,
                    attempt_root=attempt_root,
                    branch_ref=branch,
                )
                self.assertEqual(initial["semantic_review"]["decision"], "unreviewed")
                self.assertEqual(author_factory.calls, ["author", "author"])

                reviewer_factory = _RecoveryFactory(
                    {
                        "author": [],
                        "reviewer": [
                            json.dumps(
                                {
                                    "decision": "accept",
                                    "reason_code": "independent_recovery_review",
                                    "rationale": "reconstructed diff is bounded and correct",
                                }
                            )
                        ],
                    }
                )
                resident.kernel.reconfigure_resources(
                    routes=[self._route("author", 1.0), self._route("reviewer", 0.9)],
                    worker_factory=reviewer_factory,
                    max_attempts=1,
                    resource_status={"available": True, "error": None},
                )
                recovered = resident.resume_pending_maintenance_review(
                    task["task_id"], source_root=source_root
                )

                self.assertEqual(reviewer_factory.calls, ["reviewer"])
                self.assertEqual(recovered["semantic_review"]["decision"], "accept")
                self.assertTrue(recovered["semantic_review"]["independent_route"])
                self.assertEqual(recovered["investigation"]["acceptance_state"], "accepted")
                self.assertTrue(recovered["publication_preparation"]["completed"])
                self.assertEqual(recovered["publication_preparation"]["authority"], "local_commit_only")
                self.assertEqual((source_root / target).read_text(encoding="utf-8"), "VALUE = 1\n")
                self.assertEqual(self._git(attempt_root, "status", "--porcelain=v1").stdout, "")

                status = resident.status()["maintenance_cognitive_repairs"]
                self.assertEqual(status["dispatch_count"], 3)
                self.assertEqual(status["reviews"][0]["decision"], "accept")
                self.assertTrue(status["reviews"][0]["independent_route"])
            finally:
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
                resident.managed_browser.close()
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
