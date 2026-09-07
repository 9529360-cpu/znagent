from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.config import load_zn_config
from zn_agent.core.models import ModelRoute, WorkerResult
from zn_agent.core.provider_bridge import build_resident_runtime, build_zn_cognitive_resource_plan
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.router import NoRouteAvailable
from zn_agent.core.runtime import ZNKernelRuntime
from zn_agent.core.store import KernelStore
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


GOAL = (
    "帮我开发一个本地个人记账小产品。先调研一个权威的当前资料来确认核心功能，"
    "然后开发一个可运行的最小版本，实际运行测试，再做一次独立 review/test。"
    "不要做登录，不要发布，不要发消息；最终必须用当前工作区和持久化数据的真实证据验收。"
)
_MAX_PULSES = 560


def _copy_route(route: ModelRoute, *, capabilities: dict[str, float], reliability: float) -> ModelRoute:
    return ModelRoute(
        route_id=route.route_id,
        provider=route.provider,
        model=route.model,
        capabilities=dict(capabilities),
        reliability=reliability,
        cost_weight=route.cost_weight,
        latency_weight=route.latency_weight,
        metadata=dict(route.metadata),
    )


def _two_distinct_provider_routes(routes: list[ModelRoute]) -> tuple[ModelRoute, ModelRoute] | None:
    usable = [
        route
        for route in routes
        if route.provider != "none" and str(route.provider).strip() and str(route.model).strip()
    ]
    for index, first in enumerate(usable):
        for second in usable[index + 1 :]:
            if first.provider.strip().lower() != second.provider.strip().lower():
                return first, second
    return None


def _kernel_route_snapshot(resident, model_goal_id: str) -> dict:
    goal = resident.store.get_goal(model_goal_id)
    if goal is None or not isinstance(goal.metadata, dict):
        return {}
    durable = goal.metadata.get("_durable_external_run")
    if not isinstance(durable, dict):
        return {}
    attempts = durable.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        return {}
    last = attempts[-1]
    route = last.get("route") if isinstance(last, dict) else None
    return dict(route) if isinstance(route, dict) else {}


class _RecordingWorker:
    def __init__(self, route, delegate, deliveries):
        self.route = route
        self.delegate = delegate
        self.deliveries = deliveries

    def run(self, goal, kernel_context):
        context = str(kernel_context or "")
        self.deliveries.append(
            {
                "route_id": self.route.route_id,
                "provider": self.route.provider,
                "goal_id": goal.goal_id,
                "context_sha256": hashlib.sha256(context.encode("utf-8")).hexdigest(),
                "has_worker_context_pack": '"worker_context_pack"' in context,
            }
        )
        return self.delegate.run(goal, kernel_context)


class _RecordingFactory:
    def __init__(self, delegate, *, fail_route_id: str | None = None):
        self.delegate = delegate
        self.fail_route_id = fail_route_id
        self.created: list[str] = []
        self.deliveries: list[dict[str, object]] = []

    def create(self, route):
        self.created.append(route.route_id)
        if route.route_id == self.fail_route_id:
            return _InjectedFailureWorker(route.route_id)
        return _RecordingWorker(route, self.delegate.create(route), self.deliveries)


class _InjectedFailureWorker:
    def __init__(self, route_id: str):
        self.route_id = route_id

    def run(self, goal, kernel_context):
        return WorkerResult(
            success=False,
            error=f"controlled transient failure for {self.route_id}",
            metrics={"model_invoked": False, "controlled_failure": True},
        )


class E2E30And42RealMultiRoutePolicyTests(unittest.TestCase):
    def _plan_and_pair(self):
        if os.environ.get("ZN_E2E30_42_REAL_MODELS", "").strip().lower() not in {"1", "true", "yes"}:
            self.skipTest("set ZN_E2E30_42_REAL_MODELS=1 only on the guarded real-model runner")
        config = load_zn_config()
        plan = build_zn_cognitive_resource_plan(config)
        self.assertTrue(plan.available, plan.error)
        pair = _two_distinct_provider_routes(plan.routes)
        self.assertIsNotNone(
            pair,
            "E2E-30/42 requires at least two actually configured routes from distinct real providers",
        )
        assert pair is not None
        return config, plan, pair

    @staticmethod
    def _start_root(resident, root_dir: Path, *, thread_id: str, task: str, payload: dict):
        workspace = root_dir / "workspace"
        workspace.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(workspace)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
        ledger = control.ledger
        ledger.create_thread(thread_id=thread_id, title=thread_id)
        ledger.attach_workspace(thread_id, workspace, name=f"{thread_id} workspace")
        _, event = control.start(thread_id, task, payload={"model_policy": "on_demand", **payload})
        return ledger, event, workspace

    def test_real_delegated_work_uses_two_providers_by_capability_and_keeps_durable_provenance(self) -> None:
        config, plan, pair = self._plan_and_pair()
        research_base, coding_base = pair
        research_route = _copy_route(
            research_base,
            capabilities={
                "general": 0.70,
                "reasoning": 1.0,
                "research": 1.0,
                "language_understanding": 1.0,
            },
            reliability=0.95,
        )
        coding_route = _copy_route(
            coding_base,
            capabilities={
                "general": 0.75,
                "reasoning": 1.0,
                "coding": 1.0,
                "language_understanding": 0.8,
            },
            reliability=0.95,
        )

        with tempfile.TemporaryDirectory(prefix="zn-e2e30-42-multiroute-") as tmp:
            root_dir = Path(tmp)
            resident = build_resident_runtime(config=config, store_path=root_dir / "kernel.db")
            resident.kernel.reconfigure_resources(
                routes=[research_route, coding_route],
                worker_factory=plan.worker_factory,
                max_attempts=1,
                resource_status={"available": True, "error": None},
            )
            _, event, _ = self._start_root(
                resident,
                root_dir,
                thread_id="e2e-30-42-real",
                task=GOAL,
                payload={},
            )
            work = resident.work_ledger

            terminal = None
            try:
                for pulse in range(1, _MAX_PULSES + 1):
                    candidate = resident.live_once()
                    if candidate is not None and candidate.event.event_id == event.event_id:
                        terminal = candidate
                        break
                    if pulse % 50 == 0:
                        runs = work.list_worker_runs(thread_id="e2e-30-42-real", limit=96)
                        print(
                            "ZN_E2E30_42_HEARTBEAT="
                            + json.dumps(
                                {
                                    "pulse": pulse,
                                    "workers": [
                                        {
                                            "id": run.worker_run_id,
                                            "kind": run.executor_kind,
                                            "state": run.state,
                                            "route": run.model_route_id,
                                            "provider": run.provider,
                                            "verification": run.verification_status,
                                        }
                                        for run in runs[-12:]
                                    ],
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )

                self.assertIsNotNone(terminal, "real multi-provider Work did not reach Root verification")
                assert terminal is not None
                self.assertTrue(terminal.success, terminal.reason)
                version = work.plan_version("e2e-30-42-real")
                root = work.work_item_for_event(event.event_id)
                self.assertIsNotNone(root)
                assert root is not None
                self.assertEqual(root.plan_version, version)
                self.assertEqual(root.status, "completed")
                self.assertIn("zn_independent_acceptance", root.result or "")

                runs = [
                    run
                    for run in work.list_worker_runs(thread_id="e2e-30-42-real", limit=96)
                    if run.plan_version == version and run.verification_status == "accepted"
                ]
                research = next(run for run in runs if run.executor_kind == "research")
                coding = next(run for run in runs if run.executor_kind == "coding")
                review = next(run for run in runs if run.executor_kind == "review")
                self.assertEqual(research.model_route_id, research_route.route_id)
                self.assertEqual(coding.model_route_id, coding_route.route_id)
                self.assertEqual(review.model_route_id, coding_route.route_id)
                self.assertNotEqual(research.model_route_id, coding.model_route_id)
                self.assertEqual(research.provider, research_route.provider)
                self.assertEqual(coding.provider, coding_route.provider)
                self.assertEqual(review.provider, coding_route.provider)

                provenance = []
                for run in (research, coding, review):
                    route = _kernel_route_snapshot(resident, run.model_goal_id)
                    self.assertEqual(route.get("route_id"), run.model_route_id)
                    self.assertEqual(route.get("provider"), run.provider)
                    self.assertTrue(str(run.provider or "").strip())
                    self.assertTrue(str(route.get("model") or "").strip())
                    provenance.append(
                        {
                            "worker_run_id": run.worker_run_id,
                            "work_item_id": run.work_item_id,
                            "plan_version": run.plan_version,
                            "model_route_id": run.model_route_id,
                            "provider": run.provider,
                            "model": route.get("model"),
                            "executor_kind": run.executor_kind,
                        }
                    )
                print(
                    "ZN_E2E30_42_ROUTES="
                    + json.dumps(
                        {
                            "research": {
                                "route_id": research_route.route_id,
                                "provider": research_route.provider,
                                "model": research_route.model,
                            },
                            "coding": {
                                "route_id": coding_route.route_id,
                                "provider": coding_route.provider,
                                "model": coding_route.model,
                            },
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                print("ZN_E2E30_42_WORKERS=" + json.dumps(provenance, ensure_ascii=False), flush=True)
                print("ZN_E2E30_42_ROOT_ACCEPTANCE=" + str(root.result or ""), flush=True)
            finally:
                resident.store.close()

    def test_real_allowlist_filters_before_provider_construction_and_persists_after_restart(self) -> None:
        config, plan, pair = self._plan_and_pair()
        forbidden_base, allowed_base = pair
        full_capabilities = {
            "general": 1.0,
            "reasoning": 1.0,
            "research": 1.0,
            "coding": 1.0,
            "language_understanding": 1.0,
        }
        forbidden = _copy_route(
            forbidden_base,
            capabilities=full_capabilities,
            reliability=1.0,
        )
        allowed = _copy_route(
            allowed_base,
            capabilities=full_capabilities,
            reliability=0.5,
        )
        factory = _RecordingFactory(plan.worker_factory)
        policy = {
            "allowed_providers": [allowed.provider],
            "denied_providers": [forbidden.provider],
        }

        with tempfile.TemporaryDirectory(prefix="zn-e2e42-policy-") as tmp:
            root_dir = Path(tmp)
            db = root_dir / "kernel.db"
            resident = build_resident_runtime(config=config, store_path=db)
            resident.kernel.reconfigure_resources(
                routes=[forbidden, allowed],
                worker_factory=factory,
                max_attempts=1,
                resource_status={"available": True, "error": None},
            )
            ledger, event, _ = self._start_root(
                resident,
                root_dir,
                thread_id="e2e-42-policy",
                task=GOAL,
                payload={"route_policy": policy},
            )
            try:
                delegated_deliveries: list[dict[str, object]] = []
                for _ in range(260):
                    candidate = resident.live_once()
                    if candidate is not None and not candidate.success:
                        self.fail(candidate.reason or "policy Work failed before delegated context delivery")
                    delegated_deliveries = [
                        delivery
                        for delivery in factory.deliveries
                        if delivery.get("has_worker_context_pack") is True
                    ]
                    if delegated_deliveries:
                        break

                self.assertTrue(
                    delegated_deliveries,
                    "policy acceptance never reached a real delegated WorkerContextPack provider call",
                )
                self.assertTrue(factory.created)
                self.assertEqual(set(factory.created), {allowed.route_id})
                self.assertNotIn(forbidden.route_id, factory.created)
                self.assertEqual(
                    {str(item.get("route_id") or "") for item in factory.deliveries},
                    {allowed.route_id},
                )
                self.assertEqual(
                    {str(item.get("route_id") or "") for item in delegated_deliveries},
                    {allowed.route_id},
                )
                self.assertTrue(
                    all(str(item.get("context_sha256") or "") for item in delegated_deliveries)
                )

                runs = ledger.list_worker_runs(thread_id="e2e-42-policy", limit=64)
                delivered_goal_ids = {
                    str(item.get("goal_id") or "") for item in delegated_deliveries
                }
                delivered_runs = [run for run in runs if run.model_goal_id in delivered_goal_ids]
                self.assertTrue(delivered_runs)

                thread = ledger.get_thread("e2e-42-policy")
                self.assertIsNotNone(thread)
                assert thread is not None
                self.assertEqual(thread.metadata.get("route_policy"), policy)
                print(
                    "ZN_E2E42_NON_RECEIPT="
                    + json.dumps(
                        {
                            "forbidden_route": forbidden.route_id,
                            "forbidden_provider": forbidden.provider,
                            "constructed_routes": factory.created,
                            "delivered_routes": sorted(
                                {str(item.get("route_id") or "") for item in factory.deliveries}
                            ),
                            "delegated_context_routes": sorted(
                                {str(item.get("route_id") or "") for item in delegated_deliveries}
                            ),
                            "delegated_context_hashes": [
                                str(item.get("context_sha256") or "")
                                for item in delegated_deliveries
                            ],
                            "worker_run_ids": [run.worker_run_id for run in delivered_runs],
                            "policy": thread.metadata.get("route_policy"),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            finally:
                resident.store.close()

            restarted = build_resident_runtime(config=config, store_path=db)
            try:
                thread = restarted.work_ledger.get_thread("e2e-42-policy")
                self.assertIsNotNone(thread)
                assert thread is not None
                self.assertEqual(thread.metadata.get("route_policy"), policy)
                persisted_event = restarted.store.get_event(event.event_id)
                self.assertIsNotNone(persisted_event)
                assert persisted_event is not None
                self.assertEqual(persisted_event.payload.get("route_policy"), policy)
            finally:
                restarted.store.close()

    def test_local_only_work_fails_closed_before_cloud_provider_construction(self) -> None:
        config, plan, pair = self._plan_and_pair()
        cloud = [route for route in pair if not bool(route.metadata.get("local"))]
        self.assertTrue(cloud, "E2E-42 locality fail-closed needs at least one configured cloud route")
        routes = [
            _copy_route(
                route,
                capabilities={
                    "general": 1.0,
                    "reasoning": 1.0,
                    "language_understanding": 1.0,
                },
                reliability=1.0,
            )
            for route in cloud
        ]

        cases = (
            (
                "local_only",
                "这个项目只允许本地模型处理。开发一个可运行的小工具。",
                {},
                "ZN_E2E42_LOCAL_ONLY_FAIL_CLOSED",
            ),
            (
                "cloud_denied",
                "开发一个可运行的小工具，但这个 Work 的数据禁止发送到云端模型。",
                {"data_classification": "cloud_denied"},
                "ZN_E2E42_CLOUD_DENIED_FAIL_CLOSED",
            ),
        )
        for classification, task, payload, marker in cases:
            with self.subTest(classification=classification):
                factory = _RecordingFactory(plan.worker_factory)
                with tempfile.TemporaryDirectory(prefix=f"zn-e2e42-{classification}-") as tmp:
                    root_dir = Path(tmp)
                    resident = build_resident_runtime(
                        config=config,
                        store_path=root_dir / "kernel.db",
                    )
                    resident.kernel.reconfigure_resources(
                        routes=routes,
                        worker_factory=factory,
                        max_attempts=1,
                        resource_status={"available": True, "error": None},
                    )
                    ledger, _, _ = self._start_root(
                        resident,
                        root_dir,
                        thread_id=f"e2e-42-{classification}",
                        task=task,
                        payload=payload,
                    )
                    try:
                        fail_closed = False
                        for _ in range(40):
                            try:
                                candidate = resident.live_once()
                            except NoRouteAvailable:
                                fail_closed = True
                                break
                            if candidate is not None and not candidate.success:
                                fail_closed = True
                                break
                            if factory.created:
                                break
                        self.assertTrue(
                            fail_closed,
                            f"{classification} Work did not surface a fail-closed no-route outcome",
                        )
                        self.assertEqual(factory.created, [])
                        thread = ledger.get_thread(f"e2e-42-{classification}")
                        self.assertIsNotNone(thread)
                        assert thread is not None
                        self.assertEqual(
                            thread.metadata.get("route_policy"),
                            {"data_classification": classification},
                        )
                        print(
                            marker
                            + "="
                            + json.dumps(
                                {
                                    "configured_cloud_routes": [route.route_id for route in routes],
                                    "constructed_routes": factory.created,
                                    "policy": thread.metadata.get("route_policy"),
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
                    finally:
                        resident.store.close()

    def test_legal_fallback_rechecks_policy_and_invokes_only_still_eligible_real_provider(self) -> None:
        _, plan, pair = self._plan_and_pair()
        first_base, second_base = pair
        first = _copy_route(
            first_base,
            capabilities={"general": 1.0, "reasoning": 1.0},
            reliability=1.0,
        )
        second = _copy_route(
            second_base,
            capabilities={"general": 1.0, "reasoning": 1.0},
            reliability=0.8,
        )

        with tempfile.TemporaryDirectory(prefix="zn-e2e30-fallback-") as tmp:
            factory = _RecordingFactory(plan.worker_factory, fail_route_id=first.route_id)
            kernel = ZNKernelRuntime(
                store=KernelStore(Path(tmp) / "kernel.db"),
                routes=[first, second],
                worker_factory=factory,
                max_attempts=2,
            )
            try:
                result = kernel.run_goal(
                    "Return a concise acknowledgement that the bounded fallback route is alive.",
                    required_capabilities=("general", "reasoning"),
                    metadata={
                        "cognition_request": {
                            "context": {
                                "route_policy": {
                                    "allowed_providers": [first.provider, second.provider]
                                }
                            }
                        }
                    },
                    max_attempts_override=2,
                    goal_id="e2e30-legal-fallback",
                )
                self.assertTrue(result.assessment.success, result.worker_result.error)
                self.assertEqual(factory.created, [first.route_id, second.route_id])
                self.assertEqual(result.goal.route_id, second.route_id)
                print(
                    "ZN_E2E30_LEGAL_FALLBACK="
                    + json.dumps(
                        {
                            "failed_route": first.route_id,
                            "fallback_route": second.route_id,
                            "fallback_provider": second.provider,
                            "constructed_routes": factory.created,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            finally:
                kernel.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)