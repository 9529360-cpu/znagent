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
        response = queue.pop(0)
        self.factory.calls.append(
            {
                "route_id": self.route.route_id,
                "task": goal.task,
                "context": kernel_context,
            }
        )
        return WorkerResult(success=True, response=response)


class _ScriptedFactory:
    def __init__(self, responses):
        self.responses = {key: list(value) for key, value in responses.items()}
        self.calls = []

    def create(self, route):
        return _ScriptedWorker(self, route)

    def set_health_observer(self, observer):
        return None


class MaintenanceCognitiveRepairTests(unittest.TestCase):
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
        (runtime_core / "unrelated.py").write_text("UNCHANGED = True\n", encoding="utf-8")
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

    @staticmethod
    def _open_task(resident: CognitiveMaintenanceResidentRuntime) -> dict:
        for _ in range(3):
            resident.health.record_failure(
                "channel:cognitive-repair-test",
                AssertionError("cognitive-repair-regression"),
            )
        task = resident.health.maintenance_task("channel:cognitive-repair-test")
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

    def _resident(self, tmp: str, responses) -> tuple[CognitiveMaintenanceResidentRuntime, _ScriptedFactory]:
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )
        self.assertIsInstance(resident, CognitiveMaintenanceResidentRuntime)
        factory = _ScriptedFactory(responses)
        resident.kernel.reconfigure_resources(
            routes=self._routes(),
            worker_factory=factory,
            max_attempts=1,
            resource_status={"available": True, "error": None},
        )
        return resident, factory

    def test_formal_resident_derives_executes_and_semantically_accepts_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            target = "runtime/python/zn_agent/core/repair_fixture.py"
            responses = {
                "author": [
                    json.dumps({"paths": [target], "rationale": "fixture value is stale"}),
                    json.dumps(
                        {
                            "replacements": {target: "VALUE = 2\n"},
                            "rationale": "align fixture with regression contract",
                        }
                    ),
                ],
                "reviewer": [
                    json.dumps(
                        {
                            "decision": "accept",
                            "reason_code": "minimal_regression_fix",
                            "rationale": "single-value correction matches the failing contract",
                        }
                    )
                ],
            }
            resident, factory = self._resident(tmp, responses)
            task = self._open_task(resident)
            branch = f"work/self-maintenance-{task['task_id'][:12]}-cognitive"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "cognitive-one"
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

                self.assertTrue(result["regression_passed"])
                self.assertEqual(result["changed_paths"], [target])
                self.assertEqual(result["semantic_review"]["decision"], "accept")
                self.assertTrue(result["semantic_review"]["independent_route"])
                self.assertEqual(result["investigation"]["acceptance_state"], "accepted")
                self.assertEqual((source_root / target).read_text(encoding="utf-8"), "VALUE = 1\n")
                self.assertEqual((attempt_root / target).read_text(encoding="utf-8"), "VALUE = 2\n")
                self.assertEqual([call["route_id"] for call in factory.calls], ["author", "author", "reviewer"])

                status = resident.status()["maintenance_cognitive_repairs"]
                self.assertTrue(status["available"])
                self.assertEqual(status["candidate_count"], 1)
                self.assertEqual(status["review_count"], 1)
                self.assertNotIn("VALUE = 2", repr(status))
                self.assertNotIn(str(source_root), repr(status))
                self.assertNotIn(str(attempt_root), repr(status))
            finally:
                self._cleanup_worktree(source_root, attempt_root, branch)
                resident.managed_browser.close()
                resident.store.close()

    def test_model_cannot_expand_repair_outside_selected_catalog_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            target = "runtime/python/zn_agent/core/repair_fixture.py"
            responses = {
                "author": [
                    json.dumps({"paths": [target], "rationale": "inspect fixture"}),
                    json.dumps(
                        {
                            "replacements": {"docs/escape.py": "OWNED = True\n"},
                            "rationale": "escape attempt",
                        }
                    ),
                ],
                "reviewer": [],
            }
            resident, _ = self._resident(tmp, responses)
            task = self._open_task(resident)
            branch = f"work/self-maintenance-{task['task_id'][:12]}-escape"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "cognitive-escape"
            try:
                resident.investigate_maintenance_source(
                    task["task_id"],
                    source_root=source_root,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )
                with self.assertRaisesRegex(ValueError, "unselected path"):
                    resident.run_cognitive_maintenance_repair(
                        task["task_id"],
                        source_root=source_root,
                        attempt_root=attempt_root,
                        branch_ref=branch,
                    )
                self.assertFalse(attempt_root.exists())
                self.assertEqual(
                    self._git(source_root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode,
                    1,
                )
            finally:
                resident.managed_browser.close()
                resident.store.close()

    def test_semantic_rejection_does_not_grant_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            target = "runtime/python/zn_agent/core/repair_fixture.py"
            responses = {
                "author": [
                    json.dumps({"paths": [target], "rationale": "inspect fixture"}),
                    json.dumps({"replacements": {target: "VALUE = 2\n"}, "rationale": "candidate"}),
                ],
                "reviewer": [
                    json.dumps(
                        {
                            "decision": "reject",
                            "reason_code": "insufficient_semantic_basis",
                            "rationale": "oracle is too narrow to justify this change",
                        }
                    )
                ],
            }
            resident, _ = self._resident(tmp, responses)
            task = self._open_task(resident)
            branch = f"work/self-maintenance-{task['task_id'][:12]}-reject"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "cognitive-reject"
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
                self.assertTrue(result["regression_passed"])
                self.assertEqual(result["semantic_review"]["decision"], "reject")
                self.assertEqual(result["investigation"]["status"], "rejected")
                self.assertNotEqual(result["investigation"]["acceptance_state"], "accepted")
            finally:
                self._cleanup_worktree(source_root, attempt_root, branch)
                resident.managed_browser.close()
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
