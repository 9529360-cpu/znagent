from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.veteran_engineering import VeteranMissionRef
from zn_agent.core.veteran_work_owner import VeteranEngineeringWorkOwner


class _Client:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


class _Capability:
    def __init__(self) -> None:
        self.plan_calls = 0
        self.open_calls = 0
        self.advance_calls = 0
        self.index = 0
        self.project_environment = None
        self.phases = [
            ("execution", "ready"),
            ("validation", "ready"),
            ("review", "ready"),
            ("semantic-review", "ready"),
            ("candidate", "ready"),
            ("candidate", "candidate-ready"),
            ("finalize", "candidate-ready"),
            ("finalize", "awaiting-operator-merge"),
        ]

    def open_project(
        self,
        repo_path,
        *,
        name="",
        request_scope="project_open",
    ):
        self.open_calls += 1
        result = {"id": "project-1"}
        if self.project_environment is not None:
            result["environmentProfile"] = self.project_environment
        return result

    def plan_mission(self, **kwargs):
        self.plan_calls += 1
        self.assert_planner_mode(kwargs)
        return (
            VeteranMissionRef("project-1", "mission-1", "a" * 40),
            {"mission": {"id": "mission-1"}},
        )

    @staticmethod
    def assert_planner_mode(kwargs) -> None:
        if kwargs.get("tasks", "missing") is not None:
            raise AssertionError("owner must omit explicit tasks and use the read-only planner")

    def mission_status(self, mission_id: str):
        phase, status = self.phases[self.index]
        task_state = "planned" if self.index == 0 else "done"
        payload = {
            "mission": {
                "id": mission_id,
                "phase": phase,
                "status": status,
                "activeCandidateId": None,
                "activeMergeProposalId": None,
            },
            "tasks": [
                {
                    "id": "T1",
                    "status": task_state,
                    "integrationSha": None if task_state == "planned" else "b" * 40,
                }
            ],
        }
        if status == "awaiting-operator-merge":
            payload["mission"].update(
                {
                    "activeCandidateId": "candidate-1",
                    "activeMergeProposalId": "merge-1",
                }
            )
            payload["candidates"] = [
                {
                    "id": "candidate-1",
                    "commitSha": "c" * 40,
                    "sourceHead": "a" * 40,
                    "ref": "refs/veteran/candidates/candidate-1",
                }
            ]
            payload["mergeProposals"] = [
                {
                    "id": "merge-1",
                    "candidateId": "candidate-1",
                    "candidateCommitSha": "c" * 40,
                    "expectedSourceHead": "a" * 40,
                    "status": "proposed",
                    "automaticMerge": False,
                    "automaticPush": False,
                    "requiresOperatorAction": True,
                    "proof": {
                        "validation": {"status": "skipped"},
                        "review": {"status": "passed"},
                        "semanticReview": {"status": "skipped"},
                    },
                }
            ]
        return payload

    def advance(self, mission_id: str, *, run_workers: bool):
        if not run_workers:
            raise AssertionError("engineering owner must allow the bounded worker")
        self.advance_calls += 1
        if self.index < len(self.phases) - 1:
            self.index += 1
        return {"missionId": mission_id}

    def execute(self, mission_id: str, *, run_workers: bool):
        return self.advance(mission_id, run_workers=run_workers)

    def evidence_items(self, *, mission_id: str, limit: int = 50):
        return (
            {"id": "evidence-1", "missionId": mission_id, "type": "fixture"},
        )


class _Projector:
    calls = 0

    def __init__(self, workspace):
        self.workspace = Path(workspace)

    def project(self, candidate):
        type(self).calls += 1
        return SimpleNamespace(paths=("app.py",), already_applied=False)


class VeteranWorkOwnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        self.resident = build_resident_runtime(
            config={"model": {}},
            store_path=root / "kernel.db",
        )
        self.ledger = self.resident.work_ledger
        self.ledger.create_thread(thread_id="veteran", title="Veteran")
        self.ledger.attach_workspace("veteran", self.workspace, name="Workspace")
        _, event = self.ledger.start(
            "veteran",
            "Implement the requested repository change.",
            acceptance_criteria=["focused tests pass"],
        )
        self.root = self.ledger.work_item_for_event(event.event_id)
        assert self.root is not None
        self.capability = _Capability()
        self.state_root = root / "veteran-state"
        _Projector.calls = 0

    def tearDown(self) -> None:
        self.resident.store.close()
        self.temp.cleanup()

    def _owner(self):
        return VeteranEngineeringWorkOwner(
            ledger=self.ledger,
            env={"ZN_VETERAN_STATE_ROOT": str(self.state_root)},
            client_factory=lambda **kwargs: _Client(),
            projector_factory=_Projector,
        )

    def test_owner_plans_once_advances_one_phase_per_call_and_projects(self) -> None:
        with (
            patch(
                "zn_agent.core.veteran_work_owner.ensure_veteran_operator_policy",
                return_value=self.state_root / "operator.json",
            ),
            patch(
                "zn_agent.core.veteran_work_owner.VeteranEngineeringCapability",
                return_value=self.capability,
            ),
        ):
            first = self._owner().advance(
                root=self.root,
                workspace=self.workspace,
                goal=self.root.objective,
                done_definition="focused tests pass",
                risk_envelope="low",
            )
            self.assertEqual(first.state, "planned")
            self.assertEqual(self.capability.plan_calls, 1)
            self.assertEqual(self.capability.advance_calls, 0)

            restarted = self._owner()
            second = restarted.advance(
                root=self.root,
                workspace=self.workspace,
                goal=self.root.objective,
                done_definition="focused tests pass",
                risk_envelope="low",
            )
            self.assertEqual(second.state, "advanced")
            self.assertEqual(self.capability.plan_calls, 1)
            self.assertEqual(self.capability.advance_calls, 1)

            current = second
            for _ in range(10):
                if current.state == "projected":
                    break
                current = restarted.advance(
                    root=self.root,
                    workspace=self.workspace,
                    goal=self.root.objective,
                    done_definition="focused tests pass",
                    risk_envelope="low",
                )
            self.assertEqual(current.state, "projected")
            self.assertEqual(current.candidate_commit, "c" * 40)
            self.assertEqual(current.projected_paths, ("app.py",))
            self.assertEqual(_Projector.calls, 1)

        child = next(
            item
            for item in self.ledger.list_work_items(self.root.work_thread_id)
            if item.parent_work_item_id == self.root.work_item_id
        )
        self.assertEqual(child.status, "completed")
        runs = self.ledger.list_worker_runs(work_item_id=child.work_item_id)
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual(run.state, "completed")
        self.assertEqual(run.verification_status, "veteran_candidate_projected")
        checkpoint = run.metrics["veteran_engineering"]
        self.assertEqual(checkpoint["mission_id"], "mission-1")
        self.assertEqual(checkpoint["candidate_commit"], "c" * 40)
        self.assertEqual(checkpoint["projected_paths"], ["app.py"])

    def test_node_validation_policy_is_bound_before_mission_planning(self) -> None:
        self.capability.project_environment = {
            "node": {
                "validationScriptNames": ["test", "build"],
            },
            "packageManagers": {
                "node": {
                    "selected": "npm",
                    "ambiguous": False,
                }
            },
        }
        self.state_root.mkdir(parents=True, exist_ok=True)
        operator = self.state_root / "operator.json"
        operator.write_text(
            json.dumps(
                {
                    "znManaged": {
                        "contract": "zn-veteran-operator-v1",
                        "version": 1,
                    },
                    "defaults": {
                        "workerPolicy": {
                            "enabled": True,
                            "maxWorkers": 1,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        with (
            patch(
                "zn_agent.core.veteran_work_owner.ensure_veteran_operator_policy",
                return_value=operator,
            ),
            patch(
                "zn_agent.core.veteran_work_owner.VeteranEngineeringCapability",
                return_value=self.capability,
            ),
        ):
            configured = self._owner().advance(
                root=self.root,
                workspace=self.workspace,
                goal=self.root.objective,
                done_definition="focused tests pass",
                risk_envelope="low",
            )
            self.assertEqual(configured.state, "configured")
            self.assertEqual(configured.phase, "planning")
            self.assertEqual(self.capability.plan_calls, 0)
            policy = json.loads(operator.read_text(encoding="utf-8"))
            project_policy = policy["projects"][str(self.workspace.resolve())]
            self.assertTrue(project_policy["requireValidation"])
            self.assertEqual(
                project_policy["requiredValidationCapabilities"],
                ["node-test"],
            )

            planned = self._owner().advance(
                root=self.root,
                workspace=self.workspace,
                goal=self.root.objective,
                done_definition="focused tests pass",
                risk_envelope="low",
            )
            self.assertEqual(planned.state, "planned")
            self.assertEqual(self.capability.plan_calls, 1)

    def test_handles_only_explicit_veteran_mode(self) -> None:
        event = SimpleNamespace(payload={"engineering_mode": "veteran"})
        self.assertTrue(VeteranEngineeringWorkOwner.handles(event))
        self.assertFalse(
            VeteranEngineeringWorkOwner.handles(
                SimpleNamespace(payload={"engineering_mode": "ordinary"})
            )
        )
        self.assertFalse(VeteranEngineeringWorkOwner.handles(SimpleNamespace(payload={})))

    def test_policy_gate_blocks_cloud_denied_and_provider_conflicts(self) -> None:
        self.assertIn(
            "cloud model use is forbidden",
            VeteranEngineeringWorkOwner.policy_block_reason(
                SimpleNamespace(
                    payload={
                        "engineering_mode": "veteran",
                        "data_classification": "cloud_denied",
                    }
                )
            ),
        )
        self.assertIn(
            "outside the provider allowlist",
            VeteranEngineeringWorkOwner.policy_block_reason(
                SimpleNamespace(
                    payload={
                        "engineering_mode": "veteran",
                        "route_policy": {"allowed_providers": ["local-provider"]},
                    }
                )
            ),
        )
        self.assertIn(
            "explicitly denied",
            VeteranEngineeringWorkOwner.policy_block_reason(
                SimpleNamespace(
                    payload={
                        "engineering_mode": "veteran",
                        "route_policy": {"denied_providers": ["openai"]},
                    }
                )
            ),
        )

    def test_policy_gate_allows_explicit_openai_codex_cloud_route(self) -> None:
        self.assertIsNone(
            VeteranEngineeringWorkOwner.policy_block_reason(
                SimpleNamespace(
                    payload={
                        "engineering_mode": "veteran",
                        "data_classification": "cloud_allowed",
                        "route_policy": {
                            "allowed_providers": ["openai"],
                            "pinned_provider": "openai",
                        },
                    }
                )
            )
        )
        self.assertIsNone(
            VeteranEngineeringWorkOwner.policy_block_reason(
                SimpleNamespace(
                    payload={
                        "engineering_mode": "veteran",
                        "route_policy": {"allowed_providers": "openai"},
                    }
                )
            )
        )

    def test_policy_gate_fails_closed_for_unbound_model_policy(self) -> None:
        reason = VeteranEngineeringWorkOwner.policy_block_reason(
            SimpleNamespace(
                payload={
                    "engineering_mode": "veteran",
                    "route_policy": {"pinned_model": "gpt-fixed"},
                }
            )
        )
        self.assertIsNotNone(reason)
        self.assertIn("cannot yet prove Codex model identity", reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
