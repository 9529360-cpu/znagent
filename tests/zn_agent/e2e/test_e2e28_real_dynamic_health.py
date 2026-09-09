from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.config import load_zn_config
from zn_agent.core.models import ModelRoute, WorkerResult
from zn_agent.core.provider_bridge import (
    build_resident_runtime,
    build_zn_cognitive_resource_plan,
)
from zn_agent.core.router import NoRouteAvailable


_REAL_FLAG = {"1", "true", "yes"}


class _InjectedFailureWorker:
    def __init__(self, route, owner) -> None:
        self.route = route
        self.owner = owner

    def run(self, goal, kernel_context):
        self.owner.injected_runs += 1
        error = ConnectionError("injected provider outage for dynamic-health acceptance")
        if self.owner.health_observer is not None:
            self.owner.health_observer(self.route, error)
        return WorkerResult(
            success=False,
            error=f"{type(error).__name__}: {error}",
            metrics={"model_invoked": True, "injected_resource_failure": True},
        )


class _RecordingRealWorker:
    def __init__(self, worker, owner) -> None:
        self.worker = worker
        self.owner = owner

    def run(self, goal, kernel_context):
        self.owner.real_runs += 1
        return self.worker.run(goal, kernel_context)


class _HealthFallbackFactory:
    def __init__(self, *, injected_route_id: str, real_factory) -> None:
        self.injected_route_id = injected_route_id
        self.real_factory = real_factory
        self.health_observer = None
        self.injected_runs = 0
        self.real_runs = 0

    def set_health_observer(self, observer) -> None:
        self.health_observer = observer
        setter = getattr(self.real_factory, "set_health_observer", None)
        if callable(setter):
            setter(observer)

    def create(self, route):
        if route.route_id == self.injected_route_id:
            return _InjectedFailureWorker(route, self)
        return _RecordingRealWorker(self.real_factory.create(route), self)


class E2E28RealDynamicHealthTests(unittest.TestCase):
    @staticmethod
    def _configured():
        if os.environ.get("ZN_E2E28_34_REAL_MODEL", "").strip().lower() not in _REAL_FLAG:
            raise unittest.SkipTest(
                "set ZN_E2E28_34_REAL_MODEL=1 only on the guarded real-model runner"
            )
        config = load_zn_config()
        plan = build_zn_cognitive_resource_plan(config)
        routes = [
            route
            for route in plan.routes
            if route.provider != "none" and str(route.model or "").strip()
        ]
        if not plan.available or not routes:
            raise unittest.SkipTest(
                "E2E-28 dynamic-health acceptance requires one configured real cognitive resource"
            )
        return config, plan, routes[0]

    def test_dynamic_health_hard_filters_failed_route_then_real_fallback_respects_policy(self) -> None:
        config, plan, real_route = self._configured()
        with tempfile.TemporaryDirectory(prefix="zn-e2e28-real-health-") as tmp:
            resident = build_resident_runtime(
                config=config,
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                injected = ModelRoute(
                    route_id="e2e28-injected-unhealthy",
                    provider="e2e28-injected-provider",
                    model="fault-injection-only",
                    capabilities={"general": 1.0},
                    reliability=1.0,
                    cost_weight=0.0,
                    latency_weight=0.0,
                    metadata={
                        "health_failure_threshold": 3,
                        "health_backoff_seconds": 300,
                    },
                )
                factory = _HealthFallbackFactory(
                    injected_route_id=injected.route_id,
                    real_factory=plan.worker_factory,
                )
                observer = resident._observe_cognitive_resource_health
                factory.set_health_observer(observer)
                resident.kernel.reconfigure_resources(
                    routes=[injected, real_route],
                    worker_factory=factory,
                    max_attempts=1,
                    resource_status={"available": True, "error": None},
                )
                resolver = resident.kernel.resource_health_resolver
                resident.kernel.router.set_health_resolver(resolver)

                for index in range(3):
                    failed = resident.kernel.run_goal(
                        f"injected health failure {index}",
                        goal_id=f"e2e28-health-failure-{index}",
                        metadata={
                            "route_policy": {
                                "pinned_provider": injected.provider,
                            }
                        },
                    )
                    self.assertEqual(failed.route.route_id, injected.route_id)
                    self.assertFalse(failed.worker_result.success)

                organ = resident._cognitive_resource_health_organ(injected)
                health = resident.health.get(organ)
                self.assertIsNotNone(health)
                assert health is not None
                self.assertEqual(health["consecutive_failures"], 3)
                self.assertFalse(health["healthy"])

                # Prove explicit policy fail-closed while the breaker is still
                # deterministically OPEN. The Router intentionally caps dynamic
                # health backoff at 60 seconds before allowing one HALF_OPEN
                # probe, so this assertion must not be placed after an
                # unbounded-duration real provider call.
                with self.assertRaises(NoRouteAvailable):
                    resident.kernel.run_goal(
                        "Do not violate the pinned provider policy just to recover.",
                        required_capabilities=("general",),
                        goal_id="e2e28-health-policy-fail-closed",
                        metadata={
                            "route_policy": {
                                "pinned_provider": injected.provider,
                            }
                        },
                    )
                self.assertEqual(factory.injected_runs, 3)
                self.assertEqual(factory.real_runs, 0)

                fallback = resident.kernel.run_goal(
                    "Return one concise observation after the failed route is isolated.",
                    required_capabilities=("general",),
                    goal_id="e2e28-health-real-fallback",
                )
                self.assertTrue(fallback.worker_result.success, fallback.worker_result.error)
                self.assertEqual(fallback.route.route_id, real_route.route_id)
                self.assertEqual(factory.injected_runs, 3)
                self.assertEqual(factory.real_runs, 1)

                print(
                    "ZN_E2E28_DYNAMIC_HEALTH="
                    + str(
                        {
                            "failed_route": injected.route_id,
                            "consecutive_failures": health["consecutive_failures"],
                            "fallback_route": fallback.route.route_id,
                            "fallback_provider": fallback.route.provider,
                            "real_model_invocations": factory.real_runs,
                            "policy_fail_closed": True,
                        }
                    ),
                    flush=True,
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
