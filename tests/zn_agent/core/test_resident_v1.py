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
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class FakeWorker:
    def __init__(self, result):
        self.result = result

    def run(self, goal, kernel_context):
        return self.result


class FakeFactory:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def create(self, route):
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        return FakeWorker(result)


def resident_for(db: Path, factory: FakeFactory) -> ZNResidentRuntime:
    kernel = ZNKernelRuntime(
        store=KernelStore(db),
        routes=[ModelRoute("primary", "test", "model", {"general": 0.8})],
        worker_factory=factory,
    )
    return ZNResidentRuntime(kernel=kernel)


class ResidentV1Tests(unittest.TestCase):
    def test_structured_fact_uses_zero_model_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            factory = FakeFactory([WorkerResult(success=True, response="should not run")])
            resident = resident_for(Path(tmp) / "kernel.db", factory)
            resident.memory.remember("project", "znagent", aliases=("current project",))

            result = resident.submit("current project")

            self.assertTrue(result.success)
            self.assertEqual(result.response, "znagent")
            self.assertEqual(result.model_invocations, 0)
            self.assertEqual(factory.calls, 0)
            self.assertIsNone(resident.life.snapshot().current_impasse)
            self.assertEqual(resident.store.get_runtime_metrics().model_dependency_ratio, 0.0)
            resident.store.close()

    def test_compiled_capability_uses_zero_model_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            factory = FakeFactory([WorkerResult(success=True, response="should not run")])
            resident = resident_for(Path(tmp) / "kernel.db", factory)
            resident.capabilities.register(
                ExactTaskCapability(
                    name="hello-local",
                    triggers=("hello zn",),
                    handler=lambda event, state: CapabilityResult(
                        success=True,
                        response="hello from resident code",
                    ),
                )
            )

            result = resident.submit("hello zn")

            self.assertTrue(result.success)
            self.assertEqual(result.response, "hello from resident code")
            self.assertEqual(result.model_invocations, 0)
            self.assertEqual(factory.calls, 0)
            self.assertIsNone(resident.life.snapshot().current_impasse)
            resident.store.close()

    def test_unknown_task_opens_impasse_then_external_solution_stages_learning(self):
        with tempfile.TemporaryDirectory() as tmp:
            factory = FakeFactory(
                [
                    WorkerResult(
                        success=True,
                        response="model result",
                        verification_passed=True,
                        metrics={"model_invoked": True},
                    )
                ]
            )
            resident = resident_for(Path(tmp) / "kernel.db", factory)

            result = resident.submit("novel task")
            state = resident.life.snapshot()
            impasses = resident.life.recent_impasses(5)
            candidates = resident.life.recent_learning_candidates(5)

            self.assertTrue(result.success)
            self.assertEqual(result.model_invocations, 1)
            self.assertEqual(factory.calls, 1)
            self.assertIsNone(state.current_impasse)
            self.assertEqual(len(impasses), 1)
            self.assertEqual(impasses[0].status, "resolved")
            self.assertEqual(impasses[0].event_id, result.event.event_id)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].event_id, result.event.event_id)
            self.assertEqual(candidates[0].resolution_source, "external:primary")
            self.assertIn(candidates[0].candidate_id, state.learning_candidates)
            self.assertEqual(resident.store.get_runtime_metrics().model_dependency_ratio, 1.0)
            resident.store.close()

    def test_model_policy_never_leaves_persistent_impasse_without_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            factory = FakeFactory([WorkerResult(success=True, response="should not run")])
            resident = resident_for(Path(tmp) / "kernel.db", factory)

            result = resident.submit(
                "unknown local-only task",
                payload={"model_policy": "never"},
            )
            state = resident.life.snapshot()

            self.assertFalse(result.success)
            self.assertEqual(result.model_invocations, 0)
            self.assertEqual(factory.calls, 0)
            self.assertIsNotNone(state.current_impasse)
            self.assertEqual(state.current_impasse.event_id, result.event.event_id)
            self.assertEqual(state.current_impasse.status, "open")
            self.assertEqual(resident.life.recent_learning_candidates(5), [])
            resident.store.close()

    def test_processing_event_is_recovered_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = resident_for(db, FakeFactory([WorkerResult(success=True, response="unused")]))
            event = first.enqueue("resume me")
            claimed = first.store.claim_next_event()
            self.assertEqual(claimed.event_id, event.event_id)
            first.store.close()

            second_factory = FakeFactory(
                [
                    WorkerResult(
                        success=True,
                        response="resumed",
                        verification_passed=True,
                        metrics={"model_invoked": True},
                    )
                ]
            )
            second = resident_for(db, second_factory)
            result = second.run_once()
            self.assertIsNotNone(result)
            self.assertEqual(result.event.event_id, event.event_id)
            second.store.close()

    def test_resident_boots_and_local_capability_works_without_any_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            resident.capabilities.register(
                ExactTaskCapability(
                    name="offline",
                    triggers=("offline hello",),
                    handler=lambda event, state: CapabilityResult(
                        success=True,
                        response="alive",
                    ),
                )
            )

            local = resident.submit("offline hello")
            self.assertTrue(local.success)
            self.assertEqual(local.response, "alive")
            self.assertEqual(local.model_invocations, 0)

            unknown = resident.submit("novel unknown task")
            state = resident.life.snapshot()
            self.assertFalse(unknown.success)
            self.assertEqual(unknown.model_invocations, 0)
            self.assertIn("No System 2 model is configured", unknown.reason)
            self.assertIsNotNone(state.current_impasse)
            self.assertEqual(state.current_impasse.event_id, unknown.event.event_id)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()