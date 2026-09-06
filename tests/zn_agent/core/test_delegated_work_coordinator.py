from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.delegated_work_coordinator import DelegatedWorkCoordinator
from zn_agent.core.models import ModelRoute, WorkerResult
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.runtime import ZNKernelRuntime
from zn_agent.core.store import KernelStore


class _RouteCaptureWorker:
    def __init__(self, factory, route):
        self.factory = factory
        self.route = route

    def run(self, goal, kernel_context):
        self.factory.route_ids.append(self.route.route_id)
        return WorkerResult(
            success=True,
            response=f"served by {self.route.route_id}",
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class _RouteCaptureFactory:
    def __init__(self):
        self.route_ids: list[str] = []

    def create(self, route):
        return _RouteCaptureWorker(self, route)


class DelegatedWorkCoordinatorTests(unittest.TestCase):
    def test_active_product_runtime_composes_one_internal_coordinator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                first = resident._delegated_work_coordinator()
                second = resident._delegated_work_coordinator()
                self.assertIs(first, second)
                self.assertIsInstance(first, DelegatedWorkCoordinator)
                self.assertIs(first.resident, resident)
                self.assertIs(first.resident.work_ledger, resident.work_ledger)
                self.assertIs(first.resident.kernel.router, resident.kernel.router)
                self.assertIs(first.resident.body, resident.body)
            finally:
                resident.store.close()

    def test_active_prepare_path_routes_through_coordinator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                coordinator = resident._delegated_work_coordinator()
                sentinel = SimpleNamespace(bound=True)
                event = SimpleNamespace()
                root = SimpleNamespace()
                request = SimpleNamespace()
                completed = []
                with patch.object(coordinator, "prepare_request", return_value=sentinel) as prepare:
                    result = resident._prepare_delegated_worker_request(
                        event,
                        root,
                        request,
                        completed,
                    )
                self.assertIs(result, sentinel)
                prepare.assert_called_once_with(event, root, request, completed)
            finally:
                resident.store.close()

    def test_coordinator_reconciles_stale_runs_through_same_work_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                coordinator = resident._delegated_work_coordinator()
                with patch.object(
                    resident.work_ledger,
                    "reconcile_stale_worker_runs",
                    return_value=2,
                ) as reconcile:
                    result = coordinator.reconcile(thread_id="durable-thread")
                self.assertIsNone(result)
                reconcile.assert_called_once_with(thread_id="durable-thread")
                self.assertIs(coordinator.resident.work_ledger, resident.work_ledger)
            finally:
                resident.store.close()

    @staticmethod
    def _bound_research_request(resident, *, payload):
        coordinator = resident._delegated_work_coordinator()
        root = SimpleNamespace(
            work_thread_id="route-thread",
            work_item_id="root-route-thread",
            objective="research current evidence then build the requested result",
            plan_version=1,
        )
        child = SimpleNamespace(
            work_item_id="item-research",
            objective="research the bounded current source",
            acceptance_criteria=("delegated_worker_evidence: research/research_page",),
        )
        worker = SimpleNamespace(
            worker_run_id="worker-research",
            work_item_id=child.work_item_id,
            model_goal_id="goal-cog-worker-research",
            cognition_request_id="cog-worker-research",
            executor_kind="research",
            tool_scope=("managed_browser.navigate", "managed_browser.read"),
            authority_scope=("web_read",),
        )
        request = SimpleNamespace(
            request_id="original",
            required_capabilities=("general",),
            context={"existing": "kept"},
            question="research this",
        )
        event = SimpleNamespace(payload=dict(payload))
        with patch.object(resident.work_ledger, "list_work_items", return_value=[]):
            return coordinator.bind_worker_request(
                event,
                root,
                request,
                worker,
                child,
                expected_action="research_page",
                completed=[],
            )

    def test_delegated_user_deny_policy_reaches_kernel_before_soft_scoring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "resident.db",
            )
            try:
                request = self._bound_research_request(
                    resident,
                    payload={
                        "route_policy": {"denied_providers": ["blocked-cloud"]},
                        "data_classification": "cloud_allowed",
                    },
                )
                self.assertEqual(
                    request.context["route_policy"],
                    {"denied_providers": ["blocked-cloud"]},
                )
                self.assertEqual(
                    request.context["worker_context_pack"]["data_classification"],
                    "cloud_allowed",
                )

                factory = _RouteCaptureFactory()
                kernel = ZNKernelRuntime(
                    store=KernelStore(Path(tmp) / "routing.db"),
                    routes=[
                        ModelRoute(
                            "tempting-denied",
                            "blocked-cloud",
                            "model-b",
                            {"research": 1.0, "reasoning": 1.0},
                            reliability=1.0,
                        ),
                        ModelRoute(
                            "allowed",
                            "approved-cloud",
                            "model-a",
                            {"research": 0.2, "reasoning": 0.2},
                            reliability=0.1,
                        ),
                    ],
                    worker_factory=factory,
                    max_attempts=1,
                )
                try:
                    result = kernel.run_goal(
                        request.question,
                        required_capabilities=request.required_capabilities,
                        metadata={"cognition_request": {"context": request.context}},
                        max_attempts_override=1,
                    )
                    self.assertTrue(result.assessment.success)
                    self.assertEqual(result.goal.route_id, "allowed")
                    self.assertEqual(factory.route_ids, ["allowed"])
                finally:
                    kernel.store.close()
            finally:
                resident.store.close()

    def test_cloud_denied_worker_context_removes_cloud_route_before_factory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "resident.db",
            )
            try:
                request = self._bound_research_request(
                    resident,
                    payload={"data_classification": "cloud_denied"},
                )
                self.assertEqual(
                    request.context["worker_context_pack"]["data_classification"],
                    "cloud_denied",
                )

                factory = _RouteCaptureFactory()
                kernel = ZNKernelRuntime(
                    store=KernelStore(Path(tmp) / "routing.db"),
                    routes=[
                        ModelRoute(
                            "cloud-high-score",
                            "cloud-provider",
                            "cloud-model",
                            {"research": 1.0, "reasoning": 1.0},
                            reliability=1.0,
                            metadata={"local": False},
                        ),
                        ModelRoute(
                            "local-low-score",
                            "local-provider",
                            "local-model",
                            {"research": 0.2, "reasoning": 0.2},
                            reliability=0.1,
                            metadata={"local": True},
                        ),
                    ],
                    worker_factory=factory,
                    max_attempts=1,
                )
                try:
                    result = kernel.run_goal(
                        request.question,
                        required_capabilities=request.required_capabilities,
                        metadata={"cognition_request": {"context": request.context}},
                        max_attempts_override=1,
                    )
                    self.assertTrue(result.assessment.success)
                    self.assertEqual(result.goal.route_id, "local-low-score")
                    self.assertEqual(factory.route_ids, ["local-low-score"])
                finally:
                    kernel.store.close()
            finally:
                resident.store.close()

    def test_malformed_delegated_route_policy_is_preserved_for_router_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                request = self._bound_research_request(
                    resident,
                    payload={"route_policy": "allow everything"},
                )
                self.assertEqual(request.context["route_policy"], "allow everything")
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
