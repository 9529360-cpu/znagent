from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.kernel import KernelStore, ModelRoute, WorkerResult, ZNKernelRuntime, ZNResidentRuntime


class _Worker:
    def run(self, goal, kernel_context):
        return WorkerResult(
            success=True,
            response="external cognition resolved the gap",
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class _Factory:
    def create(self, route):
        return _Worker()


class LearningConsolidationTests(unittest.TestCase):
    def test_one_external_solution_does_not_create_a_tiny_capability(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = ZNKernelRuntime(
                store=KernelStore(Path(tmp) / "kernel.db"),
                routes=[ModelRoute("primary", "test", "model", {"general": 0.8})],
                worker_factory=_Factory(),
            )
            resident = ZNResidentRuntime(kernel=kernel)
            before = resident.capabilities.names()

            result = resident.submit("novel task")
            learning = resident.life.recent_learning_candidates(5)

            self.assertTrue(result.success)
            self.assertEqual(len(learning), 1)
            self.assertEqual(resident.capabilities.names(), before)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
