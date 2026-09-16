from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognitive_resource import CognitiveResourceWorkerFactory
from zn_agent.core.health_aware_resident import HealthAwareResidentRuntime
from zn_agent.core.models import Goal, ModelRoute
from zn_agent.core.runtime import ZNKernelRuntime
from zn_agent.core.store import KernelStore


class _ProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class _FailingResource:
    def __init__(self, error: BaseException):
        self.error = error

    def invoke(self, *, question: str, context: str):
        raise self.error


class CognitiveFailureHealthIntegrationTests(unittest.TestCase):
    @staticmethod
    def _route() -> ModelRoute:
        return ModelRoute(
            route_id="provider-health-scope",
            provider="test-provider",
            model="private-model",
            capabilities={"general": 0.9},
            metadata={
                "health_failure_threshold": 1,
                "health_backoff_seconds": 60,
            },
        )

    @classmethod
    def _resident(cls, tmp: str, error: BaseException) -> HealthAwareResidentRuntime:
        route = cls._route()
        factory = CognitiveResourceWorkerFactory(
            resource_builder=lambda _route: _FailingResource(error),
        )
        kernel = ZNKernelRuntime(
            store=KernelStore(Path(tmp) / "kernel.db"),
            routes=[route],
            worker_factory=factory,
            max_attempts=1,
        )
        return HealthAwareResidentRuntime(kernel=kernel)

    def test_context_overflow_does_not_poison_durable_route_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(
                tmp,
                _ProviderError(
                    "maximum context length exceeded",
                    status_code=400,
                    code="context_length_exceeded",
                ),
            )
            try:
                route = self._route()
                for index in range(3):
                    result = resident.kernel.worker_factory.create(route).run(
                        Goal(goal_id=f"overflow-{index}", task="bounded cognition"),
                        "ctx",
                    )
                    self.assertFalse(result.success)

                # Request pressure is still a failed WorkerResult, but it is not
                # durable evidence that an independent future use of the provider
                # route is unhealthy.
                self.assertEqual(resident.health.snapshot()["organ_count"], 0)
                self.assertIsNone(resident.kernel.resource_health_resolver(route))
            finally:
                resident.store.close()

    def test_rate_limit_enters_existing_route_health_owner_with_semantic_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(
                tmp,
                _ProviderError("too many requests", status_code=429),
            )
            try:
                route = self._route()
                result = resident.kernel.worker_factory.create(route).run(
                    Goal(goal_id="rate-limited", task="bounded cognition"),
                    "ctx",
                )
                self.assertFalse(result.success)

                health = resident.kernel.resource_health_resolver(route)
                self.assertIsNotNone(health)
                assert health is not None
                self.assertFalse(health["healthy"])
                self.assertEqual(health["consecutive_failures"], 1)
                self.assertEqual(health["last_failure_class"], "rate_limit")
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
