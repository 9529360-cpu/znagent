from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core import (
    CapabilityResult,
    ExactTaskCapability,
    KernelStore,
    ModelRoute,
    WorkerResult,
    ZNKernelRuntime,
    ZNResidentRuntime,
)
from zn_agent.core.models import EventStatus


class FakeWorker:
    def run(self, goal, kernel_context):
        return WorkerResult(success=True, response="unused")


class FakeFactory:
    def create(self, route):
        return FakeWorker()


def resident_for(db: Path, runtime_cls=ZNResidentRuntime) -> ZNResidentRuntime:
    kernel = ZNKernelRuntime(
        store=KernelStore(db),
        routes=[ModelRoute("primary", "test", "model", {"general": 0.8})],
        worker_factory=FakeFactory(),
    )
    resident = runtime_cls(kernel=kernel)
    resident.capabilities.register(
        ExactTaskCapability(
            name="local-completion",
            triggers=("complete locally", "complete after hook"),
            handler=lambda event, state: CapabilityResult(
                success=True,
                response="durable success",
            ),
        )
    )
    return resident


class ExplodingPostCompletionResident(ZNResidentRuntime):
    def _complete_result(self, event, result):
        completed = super()._complete_result(event, result)
        raise RuntimeError("post-completion hook failed after durable outcome")


class CompletionObservationRecoveryTests(unittest.TestCase):
    def test_life_observation_failure_does_not_reclassify_durable_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = resident_for(db)

            def fail_observation(run):
                raise RuntimeError("living-state write unavailable")

            resident.life.observe_action = fail_observation
            result = resident.submit("complete locally")

            self.assertTrue(result.success)
            self.assertEqual(result.response, "durable success")
            event = resident.store.get_event(result.event.event_id)
            outcome = resident.store.get_event_outcome(result.event.event_id)
            observation = resident.completion_observations.state(result.event.event_id)
            self.assertIsNotNone(event)
            self.assertEqual(event.status, EventStatus.COMPLETED)
            self.assertIsNotNone(outcome)
            self.assertTrue(outcome.success)
            self.assertIsNotNone(observation)
            self.assertEqual(observation["status"], "pending")
            self.assertEqual(observation["attempts"], 1)
            self.assertIn("living-state write unavailable", observation["last_error"])
            resident.store.close()

    def test_health_summary_is_sanitized_and_counts_pending_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = resident_for(Path(tmp) / "kernel.db")

            def fail_observation(run):
                raise RuntimeError("secret internal repair detail")

            resident.life.observe_action = fail_observation
            resident.submit("complete locally")

            health = resident.completion_observations.health()
            rendered = repr(health)
            self.assertFalse(health["healthy"])
            self.assertEqual(health["pending_count"], 1)
            self.assertEqual(health["waiting_count"], 1)
            self.assertEqual(health["running_count"], 0)
            self.assertEqual(health["stages"], {"life": 1})
            self.assertNotIn("secret internal repair detail", rendered)
            self.assertNotIn("last_error", rendered)
            resident.store.close()

    def test_pending_life_observation_repairs_on_resident_restart_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = resident_for(db)

            def fail_observation(run):
                raise RuntimeError("temporary life observation failure")

            first.life.observe_action = fail_observation
            completed = first.submit("complete locally")
            event_id = completed.event.event_id
            self.assertEqual(first.completion_observations.state(event_id)["status"], "pending")
            self.assertEqual(completed.event.attempts, 1)
            first.store.close()

            second = resident_for(db)
            repaired = second.completion_observations.state(event_id)
            persisted = second.store.get_event(event_id)
            outcome = second.store.get_event_outcome(event_id)

            self.assertIsNotNone(repaired)
            self.assertEqual(repaired["status"], "completed")
            self.assertEqual(repaired["attempts"], 2)
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.status, EventStatus.COMPLETED)
            self.assertEqual(persisted.attempts, 1)
            self.assertIsNotNone(outcome)
            self.assertTrue(outcome.success)
            self.assertEqual(second.life.snapshot().last_event_id, event_id)
            self.assertEqual(
                second.completion_observations.health(),
                {
                    "healthy": True,
                    "pending_count": 0,
                    "waiting_count": 0,
                    "running_count": 0,
                    "stages": {},
                },
            )
            second.store.close()

    def test_exception_after_completion_returns_existing_outcome_instead_of_failing_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = resident_for(
                Path(tmp) / "kernel.db",
                runtime_cls=ExplodingPostCompletionResident,
            )

            result = resident.submit("complete after hook")
            outcome = resident.store.get_event_outcome(result.event.event_id)

            self.assertTrue(result.success)
            self.assertEqual(result.response, "durable success")
            self.assertIsNotNone(outcome)
            self.assertTrue(outcome.success)
            self.assertEqual(result.event.status, EventStatus.COMPLETED)
            self.assertEqual(result.event.attempts, 1)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
