from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognitive_factory import ZNCognitiveResourceWorkerFactory
from zn_agent.core.cognitive_resource import (
    CognitiveIncrement,
    CognitiveResourceWorkerFactory,
)
from zn_agent.core.health_aware_resident import HealthAwareResidentRuntime
from zn_agent.core.models import Goal, ModelRoute
from zn_agent.core.provider_bridge import apply_zn_cognitive_config
from zn_agent.core.runtime import ZNKernelRuntime
from zn_agent.core.store import KernelStore


class _FlakyResource:
    def __init__(self):
        self.failures_remaining = 3

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise ConnectionError("provider unavailable private-detail")
        return CognitiveIncrement(
            text="recovered",
            provider="test-provider",
            model="secret-model-name",
        )


class CognitiveResourceHealthTests(unittest.TestCase):
    @staticmethod
    def _route() -> ModelRoute:
        return ModelRoute(
            route_id="sensitive-route-name",
            provider="test-provider",
            model="secret-model-name",
            capabilities={"general": 0.8},
        )

    @staticmethod
    def _resident(tmp: str, resource: _FlakyResource):
        route = CognitiveResourceHealthTests._route()
        factory = CognitiveResourceWorkerFactory(
            resource_builder=lambda _route: resource,
        )
        kernel = ZNKernelRuntime(
            store=KernelStore(Path(tmp) / "kernel.db"),
            routes=[route],
            worker_factory=factory,
            max_attempts=1,
        )
        return HealthAwareResidentRuntime(kernel=kernel)

    def test_real_provider_failures_enter_privacy_safe_resident_health_and_recover(self):
        with tempfile.TemporaryDirectory() as tmp:
            resource = _FlakyResource()
            resident = self._resident(tmp, resource)
            route = self._route()
            factory = resident.kernel.worker_factory

            for expected in range(1, 4):
                result = factory.create(route).run(
                    Goal(goal_id=f"g-{expected}", task="bounded cognition"),
                    "ctx",
                )
                self.assertFalse(result.success)
                health_snapshot = resident.health.snapshot()
                self.assertEqual(health_snapshot["organ_count"], 1)
                health = health_snapshot["organs"][0]
                self.assertTrue(health["organ"].startswith("cognition:test-provider:"))
                self.assertEqual(health["total_failures"], expected)
                self.assertEqual(health["consecutive_failures"], expected)
                self.assertEqual(health["repeat_fingerprint_failures"], expected)
                self.assertEqual(health["last_exception_type"], "ConnectionError")
                self.assertEqual(health["last_failure_class"], "network_or_service")
                self.assertFalse(health["maintenance_candidate"])

            status_text = repr(resident.status())
            self.assertNotIn("sensitive-route-name", status_text)
            self.assertNotIn("secret-model-name", status_text)
            self.assertNotIn("private-detail", status_text)

            result = factory.create(route).run(
                Goal(goal_id="g-recovered", task="bounded cognition"),
                "ctx",
            )
            self.assertTrue(result.success)
            health = resident.health.snapshot()["organs"][0]
            self.assertTrue(health["healthy"])
            self.assertEqual(health["consecutive_failures"], 0)
            self.assertEqual(health["repeat_fingerprint_failures"], 0)
            self.assertIsNotNone(health["last_success_at"])
            resident.store.close()

    def test_health_journal_failure_cannot_replace_provider_worker_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            resource = _FlakyResource()
            resident = self._resident(tmp, resource)
            route = self._route()
            factory = resident.kernel.worker_factory

            original_failure = resident.health.record_failure
            resident.health.record_failure = lambda organ, error: (_ for _ in ()).throw(
                RuntimeError("health unavailable")
            )
            try:
                failed = factory.create(route).run(
                    Goal(goal_id="g-fail", task="bounded cognition"),
                    "ctx",
                )
            finally:
                resident.health.record_failure = original_failure
            self.assertFalse(failed.success)
            self.assertIn("ConnectionError", failed.error or "")

            resource.failures_remaining = 0
            original_success = resident.health.record_success
            resident.health.record_success = lambda organ: (_ for _ in ()).throw(
                RuntimeError("health unavailable")
            )
            try:
                succeeded = factory.create(route).run(
                    Goal(goal_id="g-success", task="bounded cognition"),
                    "ctx",
                )
            finally:
                resident.health.record_success = original_success
            self.assertTrue(succeeded.success)
            self.assertEqual(succeeded.response, "recovered")
            resident.store.close()

    def test_zn_resource_construction_failure_enters_health_before_kernel_flattens_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            route = ModelRoute(
                route_id="private-construction-route",
                provider="custom",
                model="private-construction-model",
                capabilities={"general": 0.8},
            )
            kernel = ZNKernelRuntime(
                store=KernelStore(Path(tmp) / "kernel.db"),
                routes=[route],
                worker_factory=ZNCognitiveResourceWorkerFactory(),
                max_attempts=1,
            )
            resident = HealthAwareResidentRuntime(kernel=kernel)

            result = resident.kernel.run_goal("bounded cognition")

            self.assertFalse(result.worker_result.success)
            self.assertTrue(result.worker_result.metrics.get("worker_factory_failed"))
            self.assertFalse(result.worker_result.metrics.get("model_invoked"))
            health = resident.health.snapshot()["organs"][0]
            self.assertTrue(health["organ"].startswith("cognition:custom:"))
            self.assertEqual(health["total_failures"], 1)
            self.assertEqual(health["last_exception_type"], "ValueError")
            self.assertEqual(
                health["last_failure_class"], "configuration_or_environment"
            )
            self.assertFalse(health["maintenance_candidate"])
            status_text = repr(resident.status())
            self.assertNotIn("private-construction-route", status_text)
            self.assertNotIn("private-construction-model", status_text)
            resident.store.close()

    def test_factory_health_failure_cannot_replace_kernel_factory_failure_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            route = ModelRoute(
                route_id="factory-health-isolation",
                provider="custom",
                model="private-model",
                capabilities={"general": 0.8},
            )
            kernel = ZNKernelRuntime(
                store=KernelStore(Path(tmp) / "kernel.db"),
                routes=[route],
                worker_factory=ZNCognitiveResourceWorkerFactory(),
                max_attempts=1,
            )
            resident = HealthAwareResidentRuntime(kernel=kernel)
            original_failure = resident.health.record_failure
            resident.health.record_failure = lambda organ, error: (_ for _ in ()).throw(
                RuntimeError("health unavailable")
            )
            try:
                result = resident.kernel.run_goal("bounded cognition")
            finally:
                resident.health.record_failure = original_failure

            self.assertFalse(result.worker_result.success)
            self.assertIn("ValueError", result.worker_result.error or "")
            self.assertTrue(result.worker_result.metrics.get("worker_factory_failed"))
            resident.store.close()

    def test_hot_provider_reconfiguration_rebinds_existing_resident_observer(self):
        with tempfile.TemporaryDirectory() as tmp:
            resource = _FlakyResource()
            resident = self._resident(tmp, resource)
            observer = resident.kernel.resource_health_observer

            plan = apply_zn_cognitive_config(
                resident.kernel,
                {
                    "zn_kernel": {
                        "routes": [
                            {
                                "id": "local-hot-route",
                                "provider": "ollama",
                                "model": "local-model",
                                "base_url": "http://127.0.0.1:11434/v1",
                            }
                        ]
                    }
                },
            )

            self.assertIs(resident.kernel.worker_factory, plan.worker_factory)
            self.assertIs(plan.worker_factory.health_observer, observer)
            self.assertIs(resident.kernel.resource_health_observer, observer)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()