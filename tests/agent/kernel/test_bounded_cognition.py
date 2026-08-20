from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.kernel import (
    CapabilityResult,
    ExactTaskCapability,
    KernelStore,
    ModelRoute,
    WorkerResult,
    ZNKernelRuntime,
    ZNResidentRuntime,
)


class _CaptureWorker:
    def __init__(self, factory):
        self.factory = factory

    def run(self, goal, kernel_context):
        self.factory.goals.append(goal)
        self.factory.contexts.append(kernel_context)
        return WorkerResult(
            success=True,
            response="bounded answer",
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class _CaptureFactory:
    def __init__(self):
        self.goals = []
        self.contexts = []

    def create(self, route):
        return _CaptureWorker(self)


def _resident(db: Path, factory: _CaptureFactory) -> ZNResidentRuntime:
    kernel = ZNKernelRuntime(
        store=KernelStore(db),
        routes=[ModelRoute("primary", "test", "model", {"general": 0.8})],
        worker_factory=factory,
    )
    return ZNResidentRuntime(kernel=kernel)


class BoundedCognitionTests(unittest.TestCase):
    def test_explicit_unknown_is_sent_without_full_private_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            factory = _CaptureFactory()
            resident = _resident(Path(tmp) / "kernel.db", factory)
            original_task = (
                "Private project background with many details that the external "
                "brain does not need"
            )
            question = "What does SQLite SQLITE_BUSY mean during a transaction?"

            result = resident.submit(
                original_task,
                payload={
                    "cognition_question": question,
                    "private_note": "never forward this unrelated note",
                    "required_capabilities": ["database"],
                },
            )

            self.assertTrue(result.success)
            self.assertEqual(len(factory.goals), 1)
            self.assertEqual(factory.goals[0].task, question)
            self.assertEqual(result.event.task, original_task)

            context = factory.contexts[0]
            self.assertNotIn(original_task, context)
            self.assertNotIn("never forward this unrelated note", context)
            self.assertNotIn("private_note", context)
            self.assertNotIn("known_weaknesses", context)
            self.assertNotIn("kernel_version", context)
            resident.store.close()

    def test_local_failure_becomes_the_specific_external_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            factory = _CaptureFactory()
            resident = _resident(Path(tmp) / "kernel.db", factory)
            task = "repair sqlite writer"
            resident.capabilities.register(
                ExactTaskCapability(
                    name="local-sqlite-repair",
                    triggers=(task,),
                    handler=lambda event, state: CapabilityResult(
                        success=False,
                        error="SQLITE_BUSY while acquiring the writer lock",
                    ),
                )
            )

            result = resident.submit(
                task,
                payload={"required_capabilities": ["database"]},
            )

            self.assertTrue(result.success)
            self.assertEqual(len(factory.goals), 1)
            self.assertIn("SQLITE_BUSY", factory.goals[0].task)
            self.assertNotEqual(factory.goals[0].task, task)
            self.assertIn(task, factory.contexts[0])
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
