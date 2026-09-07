from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.delegated_work_coordinator import DelegatedWorkCoordinator
from zn_agent.core.models import ModelRoute, WorkerResult
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.worker_progress import progress_snapshot, record_worker_progress


class _Worker:
    def run(self, goal, kernel_context):
        return WorkerResult(
            success=True,
            response=f"durable provider result for {goal.goal_id}",
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class _Factory:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, route):
        self.calls += 1
        return _Worker()


class DelegatedKernelRestartReconciliationTests(unittest.TestCase):
    @staticmethod
    def _route() -> ModelRoute:
        return ModelRoute(
            route_id="restart-route",
            provider="restart-provider",
            model="restart-model",
            capabilities={"general": 1.0, "research": 1.0, "reasoning": 1.0},
        )

    @classmethod
    def _configure(cls, resident, factory: _Factory) -> None:
        resident.kernel.reconfigure_resources(
            routes=[cls._route()],
            worker_factory=factory,
            max_attempts=1,
            resource_status={"available": True, "error": None},
        )

    def test_restart_observes_kernel_final_result_before_stall_without_provider_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            workspace = root_dir / "workspace"
            workspace.mkdir()
            db = root_dir / "kernel.db"
            factory = _Factory()

            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            self._configure(resident, factory)
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="restart-reconcile", title="Restart reconcile")
                ledger.attach_workspace("restart-reconcile", workspace, name="Workspace")
                _, event = ledger.start(
                    "restart-reconcile",
                    "Research one source before continuing the durable root work.",
                    acceptance_criteria=["current evidence is independently verified"],
                )
                root = ledger.work_item_for_event(event.event_id)
                assert root is not None
                child = ledger.create_child_item(
                    root_work_item_id=root.work_item_id,
                    objective="Research one current source",
                    acceptance_criteria=["delegated_worker_evidence: research/research_page"],
                )
                worker = ledger.start_worker_run(
                    work_item_id=child.work_item_id,
                    executor_kind="research",
                    tool_scope=("managed_browser.read",),
                    authority_scope=("web_read",),
                )
                before = record_worker_progress(
                    ledger,
                    worker.worker_run_id,
                    stage="context_bound",
                    evidence={
                        "model_goal_id": worker.model_goal_id,
                        "work_item_id": worker.work_item_id,
                    },
                )

                kernel_result = resident.kernel.run_goal(
                    "bounded delegated research cognition",
                    required_capabilities=("research", "reasoning"),
                    metadata={
                        "cognition_request": {
                            "context": {"worker_run_id": worker.worker_run_id}
                        }
                    },
                    max_attempts_override=1,
                    goal_id=worker.model_goal_id,
                )
                self.assertTrue(kernel_result.worker_result.success)
                self.assertEqual(factory.calls, 1)
                still_running = ledger.worker_run(worker.worker_run_id)
                self.assertIsNotNone(still_running)
                assert still_running is not None
                self.assertEqual(still_running.state, "running")
                self.assertEqual(progress_snapshot(still_running), before)
                worker_id = worker.worker_run_id
                model_goal_id = worker.model_goal_id
            finally:
                resident.store.close()

            restored = build_resident_runtime(config={"model": {}}, store_path=db)
            self._configure(restored, factory)
            try:
                coordinator = DelegatedWorkCoordinator(restored)
                coordinator.reconcile(thread_id="restart-reconcile")

                reconciled = restored.work_ledger.worker_run(worker_id)
                self.assertIsNotNone(reconciled)
                assert reconciled is not None
                progress = progress_snapshot(reconciled)
                self.assertEqual(progress["stage"], "provider_result_persisted")
                self.assertGreater(progress["revision"], before["revision"])
                self.assertEqual(reconciled.state, "running")
                persisted_child = restored.work_ledger._work_item_by_id(reconciled.work_item_id)
                self.assertIsNotNone(persisted_child)
                assert persisted_child is not None
                self.assertEqual(persisted_child.status, "running")

                # Resume the exact Kernel goal after restart. Kernel must return
                # its durable final result rather than dispatching the provider a
                # second time. Work integration still owns later validation.
                resumed = restored.kernel.run_goal(
                    "bounded delegated research cognition",
                    required_capabilities=("research", "reasoning"),
                    metadata={
                        "cognition_request": {
                            "context": {"worker_run_id": worker_id}
                        }
                    },
                    max_attempts_override=1,
                    goal_id=model_goal_id,
                )
                self.assertTrue(resumed.worker_result.success)
                self.assertEqual(factory.calls, 1)

                first_reconcile = progress_snapshot(
                    restored.work_ledger.worker_run(worker_id)
                )
                coordinator.reconcile(thread_id="restart-reconcile")
                second_reconcile = progress_snapshot(
                    restored.work_ledger.worker_run(worker_id)
                )
                self.assertEqual(first_reconcile, second_reconcile)
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
