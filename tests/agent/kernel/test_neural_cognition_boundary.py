from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.kernel import (
    IntentionalResidentRuntime,
    KernelStore,
    ModelRoute,
    WorkerResult,
    ZNKernelRuntime,
)


class _CaptureWorker:
    def __init__(self, factory):
        self.factory = factory

    def run(self, goal, kernel_context):
        self.factory.goals.append(goal.task)
        self.factory.contexts.append(kernel_context)
        return WorkerResult(
            success=True,
            response="bounded external answer",
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class _CaptureFactory:
    def __init__(self):
        self.goals: list[str] = []
        self.contexts: list[dict] = []

    def create(self, route):
        return _CaptureWorker(self)


class NeuralCognitionBoundaryTests(unittest.TestCase):
    def test_lived_neural_trace_informs_zn_but_is_not_dumped_to_external_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            factory = _CaptureFactory()
            kernel = ZNKernelRuntime(
                store=KernelStore(Path(tmp) / "kernel.db"),
                routes=[ModelRoute("primary", "test", "model", {"database": 0.9})],
                worker_factory=factory,
            )
            resident = IntentionalResidentRuntime(kernel=kernel)
            secret = "ALPHA-NEURAL-PRIVATE-SCENE"
            resident.perceive_visual(
                f"{secret}: sqlite writer lock failed beside a private dashboard",
                features=("sqlite", "writer", "lock", "database"),
                salience=0.92,
                valence=-0.55,
                arousal=0.80,
            )

            event = resident.enqueue(
                "repair sqlite writer lock contention",
                payload={"required_capabilities": ["database"]},
            )
            readiness = resident.kernel.self_model.assess_task(
                event.task,
                resident._required_capabilities(event),
            )
            internal = resident._related_learning_evidence(event, readiness, limit=3)

            self.assertTrue(
                any(
                    item.get("resolution_source") == "neural:vision"
                    and secret in str(item.get("resolution_summary"))
                    for item in internal
                )
            )

            result = resident.submit(
                "repair sqlite writer lock contention",
                payload={"required_capabilities": ["database"]},
            )

            self.assertTrue(result.success)
            self.assertEqual(len(factory.contexts), 1)
            external_context = json.dumps(factory.contexts[0], ensure_ascii=False, default=str)
            self.assertNotIn(secret, external_context)
            self.assertNotIn("private dashboard", external_context)
            self.assertEqual(len(factory.goals), 1)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
