from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core import (
    CapabilityResult,
    EmbodiedResidentRuntime,
    ExactTaskCapability,
    IntentionalResidentRuntime,
    KernelStore,
    ModelRoute,
    WorkerResult,
    ZNKernelRuntime,
)


class _UnusedWorker:
    def run(self, goal, kernel_context):
        return WorkerResult(success=True, response="unused")


class _UnusedFactory:
    def create(self, route):
        return _UnusedWorker()


def _resident(runtime_cls, db: Path):
    kernel = ZNKernelRuntime(
        store=KernelStore(db),
        routes=[ModelRoute("primary", "test", "model", {"general": 0.8})],
        worker_factory=_UnusedFactory(),
    )
    resident = runtime_cls(kernel=kernel)
    resident.capabilities.register(
        ExactTaskCapability(
            name="richer-local-completion",
            triggers=("complete richer locally",),
            handler=lambda event, state: CapabilityResult(
                success=True,
                response="richer durable success",
            ),
        )
    )
    return resident


class CompletionObservationEmbodiedTests(unittest.TestCase):
    def test_all_richer_birth_sequences_own_completion_observation_journal(self):
        for runtime_cls in (EmbodiedResidentRuntime, IntentionalResidentRuntime):
            with self.subTest(runtime=runtime_cls.__name__), tempfile.TemporaryDirectory() as tmp:
                resident = _resident(runtime_cls, Path(tmp) / "kernel.db")
                try:
                    result = resident.submit("complete richer locally")
                    observation = resident.completion_observations.state(result.event.event_id)

                    self.assertTrue(result.success)
                    self.assertEqual(result.response, "richer durable success")
                    self.assertIsNotNone(observation)
                    self.assertEqual(observation["status"], "completed")
                    self.assertEqual(
                        resident.life.snapshot().last_event_id,
                        result.event.event_id,
                    )
                finally:
                    resident.store.close()


if __name__ == "__main__":
    unittest.main()
