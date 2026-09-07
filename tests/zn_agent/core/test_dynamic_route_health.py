from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.health_aware_resident import HealthAwareResidentRuntime
from zn_agent.core.models import Goal, ModelRoute
from zn_agent.core.provider_bridge import apply_zn_cognitive_config
from zn_agent.core.runtime import ZNKernelRuntime
from zn_agent.core.store import KernelStore


class _PrimaryResource:
    def __init__(self) -> None:
        self.failures_remaining = 3
        self.calls = 0

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls += 1
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise ConnectionError("primary provider temporarily unavailable private-detail")
        return CognitiveIncrement(
            text="primary recovered",
            provider="primary-provider",
            model="private-primary-model",
        )


class _FallbackResource:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls += 1
        return CognitiveIncrement(
            text="fallback served",
            provider="fallback-provider",
            model="private-fallback-model",
        )


class DynamicRouteHealthTests(unittest.TestCase):
    @staticmethod
    def _routes() -> list[ModelRoute]:
        return [
            ModelRoute(
                route_id="primary-route",
                provider="primary-provider",
                model="private-primary-model",
                capabilities={"general": 0.95},
                reliability=0.99,
                metadata={
                    "health_failure_threshold": 3,
                    "health_backoff_seconds": 60,
                },
            ),
            ModelRoute(
                route_id="fallback-route",
                provider="fallback-provider",
                model="private-fallback-model",
                capabilities={"general": 0.95},
                reliability=0.20,
            ),
        ]

    @classmethod
    def _resident(
        cls,
        store_path: Path,
        primary: _PrimaryResource,
        fallback: _FallbackResource,
    ) -> HealthAwareResidentRuntime:
        routes = cls._routes()
        resources = {
            "primary-route": primary,
            "fallback-route": fallback,
        }
        factory = CognitiveResourceWorkerFactory(
            resource_builder=lambda route: resources[route.route_id],
        )
        kernel = ZNKernelRuntime(
            store=KernelStore(store_path),
            routes=routes,
            worker_factory=factory,
            max_attempts=1,
        )
        return HealthAwareResidentRuntime(kernel=kernel)

    def test_persisted_provider_health_hard_filters_route_until_real_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            primary = _PrimaryResource()
            fallback = _FallbackResource()
            resident = self._resident(store_path, primary, fallback)

            # Pin only the setup failures. This isolates the health threshold from
            # SelfModel soft-score learning: the test is proving that once the
            # durable health circuit is open, the normal unpinned route selection
            # hard-filters primary before scoring and falls back legally.
            for index in range(3):
                result = resident.kernel.run_goal(
                    f"health failure {index}",
                    goal_id=f"health-failure-{index}",
                    metadata={"route_policy": {"pinned_provider": "primary-provider"}},
                )
                self.assertEqual(result.route.route_id, "primary-route")
                self.assertFalse(result.worker_result.success)

            primary_route = self._routes()[0]
            organ = resident._cognitive_resource_health_organ(primary_route)
            observed = resident.health.get(organ)
            self.assertIsNotNone(observed)
            assert observed is not None
            self.assertFalse(observed["healthy"])
            self.assertEqual(observed["consecutive_failures"], 3)
            self.assertEqual(observed["last_failure_class"], "network_or_service")

            rerouted = resident.kernel.run_goal(
                "route around unhealthy provider",
                goal_id="health-reroute",
            )
            self.assertTrue(rerouted.worker_result.success)
            self.assertEqual(rerouted.route.route_id, "fallback-route")
            self.assertEqual(primary.calls, 3)
            self.assertEqual(fallback.calls, 1)
            resident.store.close()

            restored = self._resident(store_path, primary, fallback)
            try:
                after_restart = restored.kernel.run_goal(
                    "health survives restart",
                    goal_id="health-reroute-after-restart",
                )
                self.assertTrue(after_restart.worker_result.success)
                self.assertEqual(after_restart.route.route_id, "fallback-route")
                self.assertEqual(primary.calls, 3)
                self.assertEqual(fallback.calls, 2)

                # This is an actual provider-worker success, not a synthetic
                # journal reset. It models the half-open probe that a later
                # supervision slice may schedule after the bounded cooldown.
                probe = restored.kernel.worker_factory.create(primary_route).run(
                    Goal(goal_id="health-half-open-probe", task="probe recovered provider"),
                    "bounded probe context",
                )
                self.assertTrue(probe.success)
                recovered = restored.health.get(organ)
                self.assertIsNotNone(recovered)
                assert recovered is not None
                self.assertTrue(recovered["healthy"])
                self.assertEqual(recovered["consecutive_failures"], 0)

                selected_again = restored.kernel.run_goal(
                    "use recovered provider",
                    goal_id="health-primary-recovered",
                    metadata={"route_policy": {"pinned_provider": "primary-provider"}},
                )
                self.assertTrue(selected_again.worker_result.success)
                self.assertEqual(selected_again.route.route_id, "primary-route")
                self.assertEqual(primary.calls, 5)
            finally:
                restored.store.close()

    def test_health_resolver_failure_does_not_replace_router_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = _PrimaryResource()
            primary.failures_remaining = 0
            fallback = _FallbackResource()
            resident = self._resident(Path(tmp) / "kernel.db", primary, fallback)
            try:
                resident.kernel.router.set_health_resolver(
                    lambda route: (_ for _ in ()).throw(RuntimeError("health lookup unavailable"))
                )

                result = resident.kernel.run_goal(
                    "health lookup failure",
                    goal_id="health-resolver-isolation",
                )
                self.assertTrue(result.worker_result.success)
                self.assertEqual(result.route.route_id, "primary-route")
            finally:
                resident.store.close()

    def test_hot_reconfiguration_rebinds_dynamic_health_resolver_and_thresholds(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = _PrimaryResource()
            fallback = _FallbackResource()
            resident = self._resident(Path(tmp) / "kernel.db", primary, fallback)
            try:
                resolver = resident.kernel.resource_health_resolver

                plan = apply_zn_cognitive_config(
                    resident.kernel,
                    {
                        "zn_kernel": {
                            "routes": [
                                {
                                    "id": "hot-local",
                                    "provider": "ollama",
                                    "model": "local-model",
                                    "base_url": "http://127.0.0.1:11434/v1",
                                    "capabilities": {"general": 0.9},
                                    "health_failure_threshold": 2,
                                    "health_backoff_seconds": 7,
                                }
                            ]
                        }
                    },
                )

                self.assertIs(resident.kernel.router._health_resolver, resolver)
                self.assertEqual(plan.routes[0].metadata["health_failure_threshold"], 2)
                self.assertEqual(plan.routes[0].metadata["health_backoff_seconds"], 7)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
