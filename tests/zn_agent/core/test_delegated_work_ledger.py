from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime


class DelegatedWorkLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        self.resident = build_resident_runtime(config={"model": {}}, store_path=root / "kernel.db")
        self.ledger = self.resident.work_ledger
        self.ledger.create_thread(thread_id="delegated", title="Delegated")
        self.ledger.attach_workspace("delegated", self.workspace, name="Workspace")
        _, self.event = self.ledger.start(
            "delegated",
            "Research, implement, and review a runnable local result.",
            acceptance_criteria=["real runnable result independently verified"],
        )
        self.root = self.ledger.work_item_for_event(self.event.event_id)
        assert self.root is not None

    def tearDown(self) -> None:
        self.resident.store.close()
        self.tmp.cleanup()

    def test_public_worker_lifecycle_binds_current_root_plan_and_immutable_scopes(self) -> None:
        child = self.ledger.create_child_item(
            root_work_item_id=self.root.work_item_id,
            objective="Research one current source",
            acceptance_criteria=["delegated_worker_evidence: research/research_page"],
        )
        run = self.ledger.start_worker_run(
            work_item_id=child.work_item_id,
            executor_kind="research",
            tool_scope=("managed_browser.read",),
            authority_scope=("web_read",),
        )
        self.assertEqual(run.work_item_id, child.work_item_id)
        self.assertEqual(run.plan_version, self.root.plan_version)
        self.assertEqual(run.model_goal_id, f"goal-cog-{run.worker_run_id}")
        self.assertEqual(run.cognition_request_id, f"cog-{run.worker_run_id}")
        self.assertEqual(run.tool_scope, ("managed_browser.read",))
        self.assertEqual(run.authority_scope, ("web_read",))

        completed = self.ledger.complete_worker_run(
            run.worker_run_id,
            result_summary='{"zn_work_step":{}}',
            model_route_id="only-route",
        )
        self.assertEqual(completed.state, "completed")
        self.assertEqual(completed.model_route_id, "only-route")
        with self.assertRaises(ValueError):
            self.ledger.start_worker_run(
                work_item_id=self.root.work_item_id,
                executor_kind="research",
                tool_scope=("managed_browser.read",),
                authority_scope=("web_read",),
            )

    def test_schema_is_restart_safe_and_worker_rows_survive_restart(self) -> None:
        child = self.ledger.create_child_item(
            root_work_item_id=self.root.work_item_id,
            objective="Review current implementation",
            acceptance_criteria=["delegated_worker_evidence: review/run_python"],
        )
        run = self.ledger.start_worker_run(
            work_item_id=child.work_item_id,
            executor_kind="review",
            tool_scope=("workspace.read", "terminal.test"),
            authority_scope=("workspace_read", "terminal_verify"),
        )
        checkpointed = self.ledger.update_worker_run_metrics(
            run.worker_run_id,
            metrics={
                "executor": "veteran-engineer",
                "mission_id": "mission-123",
                "base_head": "abc123",
            },
        )
        self.assertEqual(checkpointed.state, "running")
        self.assertEqual(checkpointed.metrics["mission_id"], "mission-123")

        db = Path(self.tmp.name) / "kernel.db"
        self.resident.store.close()
        restored = build_resident_runtime(config={"model": {}}, store_path=db)
        self.resident = restored
        persisted = restored.work_ledger.worker_run(run.worker_run_id)
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(persisted.work_item_id, child.work_item_id)
        self.assertEqual(persisted.state, "running")
        self.assertEqual(
            persisted.metrics,
            {
                "executor": "veteran-engineer",
                "mission_id": "mission-123",
                "base_head": "abc123",
            },
        )

    def test_live_worker_metrics_checkpoint_is_bounded_to_current_plan(self) -> None:
        child = self.ledger.create_child_item(
            root_work_item_id=self.root.work_item_id,
            objective="Implement one bounded repository change",
            acceptance_criteria=["delegated_worker_evidence: coding/repository_change"],
        )
        run = self.ledger.start_worker_run(
            work_item_id=child.work_item_id,
            executor_kind="coding",
            tool_scope=("workspace.read", "workspace.write"),
            authority_scope=("workspace_read", "workspace_write"),
        )
        first = self.ledger.update_worker_run_metrics(
            run.worker_run_id,
            metrics={"mission_id": "mission-1"},
        )
        second = self.ledger.update_worker_run_metrics(
            run.worker_run_id,
            metrics={"integration_sha": "deadbeef"},
        )
        self.assertEqual(first.metrics, {"mission_id": "mission-1"})
        self.assertEqual(
            second.metrics,
            {
                "mission_id": "mission-1",
                "integration_sha": "deadbeef",
            },
        )

        completed = self.ledger.complete_worker_run(
            run.worker_run_id,
            result_summary="done",
            metrics=second.metrics,
        )
        self.assertEqual(completed.state, "completed")
        with self.assertRaises(ValueError):
            self.ledger.update_worker_run_metrics(
                run.worker_run_id,
                metrics={"mission_id": "mission-2"},
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
