from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.models import ModelRoute, WorkerResult
from zn_agent.core.provider_bridge import build_resident_runtime


class _Worker:
    def run(self, goal, kernel_context):
        return WorkerResult(
            success=True,
            response=f"bounded result for {goal.goal_id}",
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class _Factory:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, route):
        self.calls += 1
        return _Worker()


class SingleRouteMultipleWorkerRunsTests(unittest.TestCase):
    def test_three_worker_runs_share_one_existing_model_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            workspace = root_dir / "workspace"
            workspace.mkdir()
            db = root_dir / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                factory = _Factory()
                resident.kernel.reconfigure_resources(
                    routes=[
                        ModelRoute(
                            route_id="single-external-route",
                            provider="fixture",
                            model="one-model",
                            capabilities={
                                "general": 1.0,
                                "research": 1.0,
                                "coding": 1.0,
                                "reasoning": 1.0,
                            },
                        )
                    ],
                    worker_factory=factory,
                    max_attempts=1,
                    resource_status={"available": True, "error": None},
                )
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="single-route", title="Single route")
                ledger.attach_workspace("single-route", workspace, name="Workspace")
                _, event = ledger.start(
                    "single-route",
                    "Research, code, and review.",
                    acceptance_criteria=["independently verified runnable result"],
                )
                root = ledger.work_item_for_event(event.event_id)
                assert root is not None

                specs = [
                    ("research", ("managed_browser.read",), ("web_read",), ("research", "reasoning")),
                    ("coding", ("workspace.write", "terminal.python"), ("workspace_write", "terminal_execute"), ("coding", "reasoning")),
                    ("review", ("workspace.read", "terminal.test"), ("workspace_read", "terminal_verify"), ("coding", "reasoning")),
                ]
                runs = []
                for kind, tools, authority, capabilities in specs:
                    child = ledger.create_child_item(
                        root_work_item_id=root.work_item_id,
                        objective=f"{kind} bounded work",
                        acceptance_criteria=[f"delegated_worker_evidence: {kind}/run"],
                    )
                    run = ledger.start_worker_run(
                        work_item_id=child.work_item_id,
                        executor_kind=kind,
                        tool_scope=tools,
                        authority_scope=authority,
                    )
                    kernel_result = resident.kernel.run_goal(
                        f"bounded {kind} cognition",
                        required_capabilities=capabilities,
                        metadata={"cognition_request": {"context": {"worker_run_id": run.worker_run_id}}},
                        max_attempts_override=1,
                        goal_id=run.model_goal_id,
                    )
                    persisted = ledger.complete_worker_run(
                        run.worker_run_id,
                        result_summary=kernel_result.worker_result.response,
                        model_route_id=kernel_result.route.route_id,
                    )
                    runs.append(persisted)

                self.assertEqual(len({run.worker_run_id for run in runs}), 3)
                self.assertEqual(len({run.model_goal_id for run in runs}), 3)
                self.assertEqual({run.model_route_id for run in runs}, {"single-external-route"})
                self.assertEqual({run.provider for run in runs}, {"fixture"})
                self.assertGreater(len(runs), len({run.model_route_id for run in runs}))
                self.assertEqual(factory.calls, 3)
                worker_ids = [run.worker_run_id for run in runs]
            finally:
                resident.store.close()

            restarted = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                persisted = [restarted.work_ledger.worker_run(worker_id) for worker_id in worker_ids]
                self.assertTrue(all(run is not None for run in persisted))
                self.assertEqual(
                    {run.provider for run in persisted if run is not None},
                    {"fixture"},
                )
                self.assertEqual(
                    {run.model_route_id for run in persisted if run is not None},
                    {"single-external-route"},
                )
            finally:
                restarted.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)