from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from zn_agent.core.veteran_engineering import (
    VeteranCodexWorker,
    VeteranEngineeringCapability,
    VeteranMcpClient,
    VeteranMissionRef,
    VeteranRuntimeCommand,
    VeteranSidecarError,
    VeteranWorkerRunExecutor,
    configure_veteran_project_validation,
    discover_veteran_codex_worker,
    ensure_veteran_operator_policy,
    stable_veteran_request_id,
    veteran_node_validation_policy,
    veteran_operator_policy_for_codex,
    vendored_veteran_root,
)


@dataclass
class _Run:
    worker_run_id: str = "worker-1"
    executor_kind: str = "coding"
    state: str = "running"
    metrics: dict = None

    def __post_init__(self) -> None:
        if self.metrics is None:
            self.metrics = {}


class _Ledger:
    def __init__(self) -> None:
        self.run = _Run()
        self.updates: list[dict] = []
        self.stale_on_checkpoint = False

    def worker_run(self, worker_run_id: str):
        return self.run if worker_run_id == self.run.worker_run_id else None

    def update_worker_run_metrics(self, worker_run_id: str, *, metrics: dict):
        assert worker_run_id == self.run.worker_run_id
        if self.stale_on_checkpoint and not metrics:
            self.run.state = "stale"
            return self.run
        self.run.metrics = {**self.run.metrics, **metrics}
        self.updates.append(metrics)
        return self.run


class _Capability:
    def __init__(self) -> None:
        self.open_calls = 0
        self.plan_calls = 0
        self.execute_calls = 0
        self.status_calls = 0

    def open_project(self, repo_path, *, name=""):
        self.open_calls += 1
        return {"id": "project-1"}

    def plan_mission(self, **kwargs):
        self.plan_calls += 1
        return (
            VeteranMissionRef("project-1", "mission-1", "abc123"),
            {"mission": {"id": "mission-1"}},
        )

    def execute(self, mission_id: str, *, run_workers: bool):
        self.execute_calls += 1
        return {"missionId": mission_id, "runWorkers": run_workers}

    def mission_status(self, mission_id: str):
        self.status_calls += 1
        return {
            "mission": {
                "id": mission_id,
                "status": "ready",
                "phase": "execution",
            },
            "tasks": [
                {
                    "id": "T1",
                    "status": "done",
                    "integrationSha": "def456",
                }
            ],
        }

    def evidence_items(self, *, mission_id: str, limit: int = 50):
        return (
            {
                "id": "evidence-1",
                "missionId": mission_id,
                "type": "worker",
            },
        )


class VeteranEngineeringTests(unittest.TestCase):
    def test_request_id_is_stable_and_payload_sensitive(self) -> None:
        first = stable_veteran_request_id(
            "worker-1",
            "mission_plan",
            {"b": 2, "a": 1},
        )
        reordered = stable_veteran_request_id(
            "worker-1",
            "mission_plan",
            {"a": 1, "b": 2},
        )
        changed = stable_veteran_request_id(
            "worker-1",
            "mission_plan",
            {"a": 1, "b": 3},
        )
        self.assertEqual(first, reordered)
        self.assertNotEqual(first, changed)

    def test_worker_run_prepare_is_restart_idempotent(self) -> None:
        ledger = _Ledger()
        capability = _Capability()
        executor = VeteranWorkerRunExecutor(
            ledger=ledger,
            capability=capability,
        )

        ref = executor.prepare(
            worker_run_id="worker-1",
            repo_path=".",
            goal="fix it",
            done_definition="fixed",
            tasks=[
                {
                    "id": "T1",
                    "contract": "fix",
                    "owner": "a.py",
                    "writeSet": ["a.py"],
                    "risk": "low",
                }
            ],
            risk_envelope="low",
        )
        self.assertEqual(ref.mission_id, "mission-1")
        self.assertEqual(capability.open_calls, 1)
        self.assertEqual(capability.plan_calls, 1)

        restarted = VeteranWorkerRunExecutor(
            ledger=ledger,
            capability=capability,
        )
        second = restarted.prepare(
            worker_run_id="worker-1",
            repo_path=".",
            goal="fix it",
            done_definition="fixed",
            tasks=[],
        )
        self.assertEqual(second, ref)
        self.assertEqual(capability.open_calls, 1)
        self.assertEqual(capability.plan_calls, 1)

    def test_worker_run_execute_refreshes_durable_identity(self) -> None:
        ledger = _Ledger()
        capability = _Capability()
        executor = VeteranWorkerRunExecutor(
            ledger=ledger,
            capability=capability,
        )
        executor.prepare(
            worker_run_id="worker-1",
            repo_path=".",
            goal="fix it",
            done_definition="fixed",
            tasks=[
                {
                    "id": "T1",
                    "contract": "fix",
                    "owner": "a.py",
                    "writeSet": ["a.py"],
                    "risk": "low",
                }
            ],
        )
        outcome = executor.execute(
            worker_run_id="worker-1",
            run_workers=True,
        )
        self.assertEqual(outcome.integration_sha, "def456")
        self.assertEqual(outcome.task_states, (("T1", "done"),))
        self.assertEqual(outcome.evidence_ids, ("evidence-1",))
        checkpoint = ledger.run.metrics["veteran_engineering"]
        self.assertEqual(checkpoint["mission_id"], "mission-1")
        self.assertEqual(checkpoint["integration_sha"], "def456")
        self.assertEqual(checkpoint["evidence_ids"], ["evidence-1"])

    def test_codex_policy_binds_read_only_planner_and_bounded_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex = root / "codex.exe"
            planner = root / "python.exe"
            codex.write_text("fixture", encoding="utf-8")
            planner.write_text("fixture", encoding="utf-8")
            worker = VeteranCodexWorker(
                command=codex,
                codex_home=root / "codex-home",
                windows_sandbox="unelevated",
            )
            policy = veteran_operator_policy_for_codex(
                worker,
                planner_command=planner,
            )
            defaults = policy["defaults"]
            planner_policy = defaults["plannerProvider"]
            self.assertEqual(planner_policy["command"], str(planner.resolve()))
            self.assertEqual(
                planner_policy["args"],
                ["-m", "zn_agent.core.veteran_codex_planner"],
            )
            self.assertEqual(
                planner_policy["envAllowlist"],
                ["CODEX_HOME", "ZN_VETERAN_CODEX"],
            )
            worker_policy = defaults["workerPolicy"]
            self.assertEqual(worker_policy["defaultWorker"], "codex")
            self.assertEqual(worker_policy["maxWorkers"], 1)
            self.assertFalse(worker_policy["allowUnconfinedCustomWorkers"])
            self.assertFalse(worker_policy["allowRawValidation"])
            self.assertIn(
                'windows.sandbox="unelevated"',
                worker_policy["codex"]["extraArgs"],
            )
            self.assertNotIn(
                "--dangerously-bypass-approvals-and-sandbox",
                worker_policy["codex"]["extraArgs"],
            )

    def test_zn_managed_operator_policy_refreshes_but_custom_policy_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "codex-first.exe"
            second = root / "codex-second.exe"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")
            state = root / "state"

            target = ensure_veteran_operator_policy(
                state,
                env={"ZN_VETERAN_CODEX": str(first)},
            )
            self.assertIsNotNone(target)
            assert target is not None
            created = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(
                created["znManaged"]["contract"],
                "zn-veteran-operator-v1",
            )
            self.assertEqual(
                created["defaults"]["workerPolicy"]["codex"]["command"],
                str(first.absolute()),
            )

            project_overrides = {
                str((root / "repo").resolve()): {
                    "requireValidation": True,
                    "requiredValidationCapabilities": ["node-test"],
                    "validationCapabilities": [
                        {
                            "name": "node-test",
                            "command": ["npm.cmd", "run", "test"],
                            "cwd": ".",
                        }
                    ],
                }
            }
            created["projects"] = project_overrides
            target.write_text(
                json.dumps(created, indent=2) + "\n",
                encoding="utf-8",
            )

            refreshed = ensure_veteran_operator_policy(
                state,
                env={"ZN_VETERAN_CODEX": str(second)},
            )
            self.assertEqual(refreshed, target)
            updated = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(
                updated["defaults"]["workerPolicy"]["codex"]["command"],
                str(second.absolute()),
            )
            self.assertEqual(updated["projects"], project_overrides)

            custom = {
                "defaults": {
                    "workerPolicy": {
                        "enabled": False,
                    }
                }
            }
            target.write_text(json.dumps(custom), encoding="utf-8")
            ensure_veteran_operator_policy(
                state,
                env={"ZN_VETERAN_CODEX": str(first)},
            )
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")),
                custom,
            )

    def test_node_validation_policy_prefers_repository_test_script(self) -> None:
        project = {
            "environmentProfile": {
                "node": {
                    "validationScriptNames": ["lint", "test", "build"],
                },
                "packageManagers": {
                    "node": {
                        "selected": "npm",
                        "ambiguous": False,
                    }
                },
            }
        }
        policy = veteran_node_validation_policy(
            project,
            platform_name="win32",
        )
        self.assertIsNotNone(policy)
        assert policy is not None
        capability = policy["requiredValidationCapabilities"][0]
        self.assertEqual(capability, "node-test")
        validation = policy["validationCapabilities"][0]
        self.assertEqual(validation["command"], ["npm.cmd", "run", "test"])
        self.assertTrue(policy["requireValidation"])
        self.assertEqual(policy["validationPolicy"]["maxParallel"], 1)

    def test_node_validation_policy_uses_npm_for_plain_package_json_without_lockfile(self) -> None:
        project = {
            "environmentProfile": {
                "manifests": [
                    {"path": "package.json", "kind": "node-package"},
                ],
                "node": {
                    "validationScriptNames": ["test"],
                },
                "packageManagers": {
                    "node": {
                        "selected": None,
                        "declared": None,
                        "lockfileCandidates": [],
                        "ambiguous": False,
                    }
                },
            }
        }
        policy = veteran_node_validation_policy(
            project,
            platform_name="win32",
        )
        self.assertIsNotNone(policy)
        assert policy is not None
        self.assertEqual(
            policy["validationCapabilities"][0]["command"],
            ["npm.cmd", "run", "test"],
        )

    def test_project_validation_binding_only_mutates_zn_managed_policy(self) -> None:
        project = {
            "environmentProfile": {
                "node": {
                    "validationScriptNames": ["test"],
                },
                "packageManagers": {
                    "node": {
                        "selected": "npm",
                        "ambiguous": False,
                    }
                },
            }
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "repo"
            workspace.mkdir()
            state = root / "state"
            state.mkdir()
            managed = veteran_operator_policy_for_codex(
                VeteranCodexWorker(
                    command=root / "codex.exe",
                    codex_home=root / "codex-home",
                    windows_sandbox="unelevated",
                )
            )
            target = state / "operator.json"
            target.write_text(json.dumps(managed), encoding="utf-8")
            bound = configure_veteran_project_validation(
                state,
                workspace=workspace,
                project=project,
                platform_name="win32",
            )
            self.assertEqual(bound, "node-test")
            updated = json.loads(target.read_text(encoding="utf-8"))
            project_policy = updated["projects"][str(workspace.resolve())]
            self.assertTrue(project_policy["requireValidation"])
            self.assertEqual(
                project_policy["requiredValidationCapabilities"],
                ["node-test"],
            )

            custom = {
                "defaults": {"workerPolicy": {"enabled": False}},
                "projects": {},
            }
            target.write_text(json.dumps(custom), encoding="utf-8")
            before = target.read_bytes()
            self.assertIsNone(
                configure_veteran_project_validation(
                    state,
                    workspace=workspace,
                    project=project,
                    platform_name="win32",
                )
            )
            self.assertEqual(target.read_bytes(), before)

    def test_codex_discovery_preserves_stable_command_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            command = Path(temp) / "codex.exe"
            command.write_text("fixture", encoding="utf-8")
            worker = discover_veteran_codex_worker(
                {"ZN_VETERAN_CODEX": str(command)},
                platform_name="win32",
            )
            self.assertIsNotNone(worker)
            assert worker is not None
            self.assertEqual(worker.command, command.absolute())

    def test_stale_plan_blocks_veteran_execution_before_side_effect(self) -> None:
        ledger = _Ledger()
        capability = _Capability()
        executor = VeteranWorkerRunExecutor(
            ledger=ledger,
            capability=capability,
        )
        executor.prepare(
            worker_run_id="worker-1",
            repo_path=".",
            goal="fix it",
            done_definition="fixed",
            tasks=[
                {
                    "id": "T1",
                    "contract": "fix",
                    "owner": "a.py",
                    "writeSet": ["a.py"],
                    "risk": "low",
                }
            ],
        )
        ledger.stale_on_checkpoint = True
        with self.assertRaisesRegex(VeteranSidecarError, "stale Work plan"):
            executor.execute(
                worker_run_id="worker-1",
                run_workers=True,
            )
        self.assertEqual(capability.execute_calls, 0)

    def test_rejects_non_coding_worker(self) -> None:
        ledger = _Ledger()
        ledger.run.executor_kind = "research"
        executor = VeteranWorkerRunExecutor(
            ledger=ledger,
            capability=_Capability(),
        )
        with self.assertRaises(VeteranSidecarError):
            executor.prepare(
                worker_run_id="worker-1",
                repo_path=".",
                goal="x",
                done_definition="x",
                tasks=[],
            )

    def test_real_vendored_sidecar_handshake_and_health(self) -> None:
        node = os.environ.get("ZN_VETERAN_NODE")
        if not node:
            import shutil

            node = shutil.which("node")
        if not node:
            self.skipTest("Node is unavailable")
        runtime_root = vendored_veteran_root()
        if not runtime_root.is_dir():
            self.skipTest("vendored Veteran runtime is unavailable")
        with tempfile.TemporaryDirectory() as temp:
            command = VeteranRuntimeCommand(
                argv=(node, str(runtime_root / "mcp" / "server.mjs")),
                env={},
                runtime_root=runtime_root,
            )
            with VeteranMcpClient(
                state_root=Path(temp) / "state",
                command=command,
                timeout_seconds=10,
            ) as client:
                health = client.call_tool("runtime_health")
        self.assertEqual(health["name"], "veteran-engineer")
        self.assertEqual(health["version"], "0.5.0")
        self.assertGreaterEqual(int(health["toolCount"]), 30)


if __name__ == "__main__":
    unittest.main()
