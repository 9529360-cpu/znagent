from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognitive_maintenance_resident import CognitiveMaintenanceResidentRuntime
from zn_agent.core.models import ModelRoute, WorkerResult
from zn_agent.core.provider_bridge import build_resident_runtime


class _JournalWorker:
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
        if isinstance(response, BaseException):
            raise response
        return WorkerResult(success=True, response=str(response))


class _JournalFactory:
    def __init__(self, responses):
        self.responses = {key: list(value) for key, value in responses.items()}
        self.calls = []

    def create(self, route):
        return _JournalWorker(self, route)

    def set_health_observer(self, observer):
        return None


class MaintenanceCognitionJournalTests(unittest.TestCase):
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
                "channel:cognition-journal-test",
                AssertionError("cognition-journal-regression"),
            )
        task = resident.health.maintenance_task("channel:cognition-journal-test")
        assert task is not None
        return task

    def _resident(self, tmp: str, responses):
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )
        self.assertIsInstance(resident, CognitiveMaintenanceResidentRuntime)
        factory = _JournalFactory(responses)
        resident.kernel.reconfigure_resources(
            routes=self._routes(),
            worker_factory=factory,
            max_attempts=1,
            resource_status={"available": True, "error": None},
        )
        return resident, factory

    def test_ambiguous_provider_exception_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            target = "runtime/python/zn_agent/core/repair_fixture.py"
            selection = json.dumps({"paths": [target], "rationale": "inspect fixture"})
            resident, factory = self._resident(
                tmp,
                {"author": [RuntimeError("simulated provider disconnect"), selection], "reviewer": []},
            )
            task = self._open_task(resident)
            branch = f"work/self-maintenance-{task['task_id'][:12]}-journal"
            try:
                resident.investigate_maintenance_source(
                    task["task_id"],
                    source_root=source_root,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )
                orchestrator = resident._maintenance_cognitive_orchestrator()

                with self.assertRaisesRegex(RuntimeError, "outcome is uncertain"):
                    orchestrator.derive_candidate(
                        task["task_id"],
                        source_root=source_root,
                        branch_ref=branch,
                    )
                self.assertEqual(len(factory.calls), 1)

                with self.assertRaisesRegex(RuntimeError, "automatic replay is blocked"):
                    orchestrator.derive_candidate(
                        task["task_id"],
                        source_root=source_root,
                        branch_ref=branch,
                    )
                self.assertEqual(len(factory.calls), 1)
                self.assertEqual(len(factory.responses["author"]), 1)

                status = resident.status()["maintenance_cognitive_repairs"]
                self.assertEqual(status["dispatch_count"], 1)
                self.assertEqual(status["dispatches"][0]["phase"], "target_selection")
                self.assertEqual(status["dispatches"][0]["status"], "outcome_uncertain")
                self.assertEqual(status["dispatches"][0]["error_type"], "RuntimeError")
                self.assertNotIn(target, repr(status))
                self.assertNotIn(str(source_root), repr(status))
                self.assertNotIn("simulated provider disconnect", repr(status))
            finally:
                resident.managed_browser.close()
                resident.store.close()

    def test_successful_calls_record_only_fingerprints_and_route_metadata(self):
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
                            "replacements": {target: "VALUE = 2\n"},
                            "rationale": "repair fixture",
                        }
                    ),
                ],
                "reviewer": [
                    json.dumps(
                        {
                            "decision": "accept",
                            "reason_code": "minimal_regression_fix",
                            "rationale": "bounded fix",
                        }
                    )
                ],
            }
            resident, factory = self._resident(tmp, responses)
            task = self._open_task(resident)
            branch = f"work/self-maintenance-{task['task_id'][:12]}-success"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "journal-success"
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
                self.assertEqual(result["semantic_review"]["decision"], "accept")
                self.assertEqual(len(factory.calls), 3)

                status = resident.status()["maintenance_cognitive_repairs"]
                self.assertEqual(status["dispatch_count"], 3)
                self.assertEqual(
                    {item["phase"] for item in status["dispatches"]},
                    {"target_selection", "repair_authoring", "semantic_review"},
                )
                self.assertTrue(all(item["status"] == "completed" for item in status["dispatches"]))
                self.assertTrue(all(len(item["input_fingerprint"]) == 64 for item in status["dispatches"]))
                self.assertTrue(all(len(item["output_fingerprint"]) == 64 for item in status["dispatches"]))
                self.assertNotIn("VALUE = 2", repr(status))
                self.assertNotIn(target, repr(status))
                self.assertNotIn(str(source_root), repr(status))
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
