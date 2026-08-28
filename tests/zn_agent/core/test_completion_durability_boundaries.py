from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.capability_recovery_resident import CapabilityRecoveryResidentRuntime
from zn_agent.core.models import ModelRoute, WorkerResult
from zn_agent.core.runtime import ZNKernelRuntime
from zn_agent.core.self_model import SelfModel
from zn_agent.core.store import KernelStore


class _CountingWorker:
    def __init__(self, factory):
        self.factory = factory

    def run(self, goal, kernel_context):
        self.factory.run_calls += 1
        if self.factory.base_exception is not None:
            raise self.factory.base_exception
        if self.factory.exception is not None:
            raise self.factory.exception
        return self.factory.result


class _CountingFactory:
    def __init__(
        self,
        result: WorkerResult | None = None,
        *,
        exception: Exception | None = None,
        base_exception: BaseException | None = None,
    ):
        self.result = result or WorkerResult(success=True, response="unused")
        self.exception = exception
        self.base_exception = base_exception
        self.create_calls = 0
        self.run_calls = 0

    def create(self, route):
        self.create_calls += 1
        return _CountingWorker(self)


def _kernel(db: Path, factory: _CountingFactory) -> ZNKernelRuntime:
    return ZNKernelRuntime(
        store=KernelStore(db),
        routes=[ModelRoute("primary", "test", "model", {"general": 0.8})],
        worker_factory=factory,
    )


def _resident(db: Path, factory: _CountingFactory) -> CapabilityRecoveryResidentRuntime:
    return CapabilityRecoveryResidentRuntime(kernel=_kernel(db, factory))


class CompletionDurabilityBoundaryTests(unittest.TestCase):
    def test_memory_checkpoint_precedes_accounting_and_restart_finishes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first_factory = _CountingFactory()
            first = _resident(db, first_factory)
            first.memory.remember("project", "znagent", aliases=("current project",))
            event = first.enqueue("current project")

            with patch.object(
                first.resident_accounting,
                "record_memory_success",
                side_effect=RuntimeError("crash before memory accounting"),
            ):
                with self.assertRaisesRegex(RuntimeError, "crash before memory accounting"):
                    first.run_once(target_event_id=event.event_id)

            checkpoint = first.store.get_working_state()
            self.assertEqual(checkpoint.stage, "resident_completion")
            self.assertEqual(first.store.get_runtime_metrics().tasks_total, 0)
            self.assertEqual(first.kernel.self_model.knowledge("general").evidence_count, 0)
            self.assertEqual(first_factory.run_calls, 0)
            first.store.close()

            second_factory = _CountingFactory()
            second = _resident(db, second_factory)
            try:
                with patch.object(
                    second.memory,
                    "recall",
                    side_effect=AssertionError("memory lookup must not replay after checkpoint"),
                ):
                    result = second.run_once(target_event_id=event.event_id)

                self.assertIsNotNone(result)
                assert result is not None
                self.assertTrue(result.success)
                self.assertEqual(result.response, "znagent")
                self.assertEqual(second.store.get_runtime_metrics().tasks_total, 1)
                self.assertEqual(second.kernel.self_model.knowledge("general").evidence_count, 1)
                self.assertEqual(second_factory.run_calls, 0)
            finally:
                second.store.close()

    def test_memory_accounting_is_not_duplicated_if_terminal_publish_crashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = _resident(db, _CountingFactory())
            first.memory.remember("project", "znagent", aliases=("current project",))
            event = first.enqueue("current project")

            with patch.object(
                first.store,
                "complete_event",
                side_effect=RuntimeError("crash before terminal publish"),
            ):
                with self.assertRaisesRegex(RuntimeError, "crash before terminal publish"):
                    first.run_once(target_event_id=event.event_id)

            self.assertEqual(first.store.get_working_state().stage, "resident_completion")
            self.assertEqual(first.store.get_runtime_metrics().tasks_total, 1)
            self.assertEqual(first.kernel.self_model.knowledge("general").evidence_count, 1)
            first.store.close()

            second = _resident(db, _CountingFactory())
            try:
                result = second.run_once(target_event_id=event.event_id)
                self.assertIsNotNone(result)
                self.assertEqual(second.store.get_runtime_metrics().tasks_total, 1)
                self.assertEqual(second.kernel.self_model.knowledge("general").evidence_count, 1)
            finally:
                second.store.close()

    def test_investigation_checkpoint_precedes_accounting_and_restart_finishes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first_factory = _CountingFactory()
            first = _resident(db, first_factory)
            event = first.enqueue("what is my current working directory?")

            with patch.object(
                first.resident_accounting,
                "record_native_investigation_success",
                side_effect=RuntimeError("crash before investigation accounting"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "crash before investigation accounting"
                ):
                    first.run_once(target_event_id=event.event_id)

            checkpoint = first.store.get_working_state()
            self.assertEqual(checkpoint.stage, "investigation_completion")
            self.assertEqual(first.store.get_runtime_metrics().tasks_total, 0)
            self.assertEqual(first.kernel.self_model.get("general").evidence_count, 0)
            self.assertEqual(first.kernel.self_model.knowledge("general").evidence_count, 0)
            self.assertEqual(first_factory.run_calls, 0)
            first.store.close()

            second_factory = _CountingFactory()
            second = _resident(db, second_factory)
            try:
                with patch.object(
                    second.investigator,
                    "investigate",
                    side_effect=AssertionError("native investigation must not replay"),
                ):
                    result = second.run_once(target_event_id=event.event_id)

                self.assertIsNotNone(result)
                assert result is not None
                self.assertTrue(result.success)
                self.assertEqual(result.response, os.getcwd())
                self.assertEqual(second.store.get_runtime_metrics().tasks_total, 1)
                self.assertEqual(second.kernel.self_model.get("general").evidence_count, 1)
                self.assertEqual(second.kernel.self_model.knowledge("general").evidence_count, 1)
                self.assertEqual(second_factory.run_calls, 0)
            finally:
                second.store.close()

    def test_investigation_accounting_is_not_duplicated_if_terminal_publish_crashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = _resident(db, _CountingFactory())
            event = first.enqueue("what is my current working directory?")

            with patch.object(
                first.store,
                "complete_event",
                side_effect=RuntimeError("crash before investigation publish"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "crash before investigation publish"
                ):
                    first.run_once(target_event_id=event.event_id)

            self.assertEqual(first.store.get_working_state().stage, "investigation_completion")
            self.assertEqual(first.store.get_runtime_metrics().tasks_total, 1)
            self.assertEqual(first.kernel.self_model.get("general").evidence_count, 1)
            first.store.close()

            second = _resident(db, _CountingFactory())
            try:
                result = second.run_once(target_event_id=event.event_id)
                self.assertIsNotNone(result)
                self.assertEqual(second.store.get_runtime_metrics().tasks_total, 1)
                self.assertEqual(second.kernel.self_model.get("general").evidence_count, 1)
                self.assertEqual(second.kernel.self_model.knowledge("general").evidence_count, 1)
            finally:
                second.store.close()

    def test_external_success_restarts_from_completion_without_model_or_learning_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first_factory = _CountingFactory(
                WorkerResult(
                    success=True,
                    response="durable external answer",
                    verification_passed=True,
                    metrics={
                        "model_invoked": True,
                        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
                    },
                )
            )
            first = _resident(db, first_factory)
            event = first.enqueue("novel durability question")

            with patch.object(
                first.store,
                "complete_event",
                side_effect=RuntimeError("crash after external resident accounting"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "crash after external resident accounting"
                ):
                    first.run_once(target_event_id=event.event_id)

            self.assertEqual(first_factory.run_calls, 1)
            self.assertEqual(first.store.get_working_state().stage, "external_completion")
            self.assertEqual(first.store.get_runtime_metrics().tasks_total, 1)
            self.assertEqual(first.store.get_runtime_metrics().model_invocations, 1)
            self.assertEqual(first.kernel.self_model.knowledge("general").evidence_count, 1)
            route_key = SelfModel.route_capability_key("primary", "general")
            self.assertEqual(first.store.get_capability(route_key).evidence_count, 1)
            self.assertEqual(len(first.life.recent_learning_candidates(10)), 1)
            first.store.close()

            second_factory = _CountingFactory(
                WorkerResult(success=True, response="must not be used")
            )
            second = _resident(db, second_factory)
            try:
                result = second.run_once(target_event_id=event.event_id)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertTrue(result.success)
                self.assertEqual(result.response, "durable external answer")
                self.assertEqual(second_factory.create_calls, 0)
                self.assertEqual(second_factory.run_calls, 0)
                metrics = second.store.get_runtime_metrics()
                self.assertEqual(metrics.tasks_total, 1)
                self.assertEqual(metrics.tasks_model, 1)
                self.assertEqual(metrics.model_invocations, 1)
                self.assertEqual(metrics.prompt_tokens, 11)
                self.assertEqual(metrics.completion_tokens, 7)
                self.assertEqual(second.kernel.self_model.knowledge("general").evidence_count, 1)
                self.assertEqual(second.store.get_capability(route_key).evidence_count, 1)
                self.assertEqual(len(second.life.recent_learning_candidates(10)), 1)
            finally:
                second.store.close()

    def test_external_failure_checkpoint_precedes_metrics_and_restart_does_not_replay_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first_factory = _CountingFactory(
                WorkerResult(
                    success=False,
                    error="external failed",
                    metrics={"model_invoked": True},
                )
            )
            first = _resident(db, first_factory)
            event = first.enqueue("novel failing durability question")

            with patch.object(
                first.resident_accounting,
                "record_external_completion",
                side_effect=RuntimeError("crash before external metrics"),
            ):
                with self.assertRaisesRegex(RuntimeError, "crash before external metrics"):
                    first.run_once(target_event_id=event.event_id)

            self.assertEqual(first_factory.run_calls, 1)
            self.assertEqual(first.store.get_working_state().stage, "external_completion")
            self.assertEqual(first.store.get_runtime_metrics().tasks_total, 0)
            self.assertEqual(first.kernel.self_model.knowledge("general").evidence_count, 0)
            route_key = SelfModel.route_capability_key("primary", "general")
            self.assertEqual(first.store.get_capability(route_key).evidence_count, 1)
            first.store.close()

            second_factory = _CountingFactory(
                WorkerResult(success=True, response="must not be used")
            )
            second = _resident(db, second_factory)
            try:
                result = second.run_once(target_event_id=event.event_id)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertFalse(result.success)
                self.assertEqual(result.reason, "external failed")
                self.assertEqual(second_factory.create_calls, 0)
                self.assertEqual(second_factory.run_calls, 0)
                metrics = second.store.get_runtime_metrics()
                self.assertEqual(metrics.tasks_total, 1)
                self.assertEqual(metrics.tasks_model, 1)
                self.assertEqual(metrics.model_invocations, 1)
                self.assertEqual(second.kernel.self_model.knowledge("general").evidence_count, 0)
                self.assertEqual(second.store.get_capability(route_key).evidence_count, 1)
                self.assertEqual(second.life.recent_learning_candidates(10), [])
                self.assertIsNotNone(second.life.snapshot().current_impasse)
            finally:
                second.store.close()

    def test_kernel_resumes_observed_worker_result_without_provider_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            response = "x" * 2500
            first_factory = _CountingFactory(
                WorkerResult(
                    success=True,
                    response=response,
                    verification_passed=True,
                    metrics={"model_invoked": True},
                )
            )
            first = _kernel(db, first_factory)
            real_save_goal = first.store.save_goal
            crashed = False

            def crash_after_observed(goal):
                nonlocal crashed
                real_save_goal(goal)
                durable = goal.metadata.get(first._DURABLE_RUN_KEY)
                attempts = durable.get("attempts") if isinstance(durable, dict) else None
                if (
                    not crashed
                    and isinstance(attempts, list)
                    and attempts
                    and attempts[-1].get("status") == "worker_observed"
                ):
                    crashed = True
                    raise RuntimeError("crash after durable worker result")

            with patch.object(first.store, "save_goal", side_effect=crash_after_observed):
                with self.assertRaisesRegex(RuntimeError, "crash after durable worker result"):
                    first.run_goal("bounded kernel durability", goal_id="goal-durable-observed")

            self.assertEqual(first_factory.run_calls, 1)
            first.store.close()

            second_factory = _CountingFactory(
                WorkerResult(success=True, response="must not be used")
            )
            second = _kernel(db, second_factory)
            try:
                result = second.run_goal(
                    "bounded kernel durability",
                    goal_id="goal-durable-observed",
                )
                self.assertTrue(result.assessment.success)
                self.assertEqual(result.worker_result.response, response)
                self.assertEqual(second_factory.create_calls, 0)
                self.assertEqual(second_factory.run_calls, 0)
                self.assertEqual(len(result.experiences), 1)
                route_key = SelfModel.route_capability_key("primary", "general")
                self.assertEqual(second.store.get_capability(route_key).evidence_count, 1)
            finally:
                second.store.close()

    def test_kernel_does_not_replay_dispatch_with_unknown_provider_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first_factory = _CountingFactory(
                base_exception=KeyboardInterrupt("simulated process death")
            )
            first = _kernel(db, first_factory)

            with self.assertRaises(KeyboardInterrupt):
                first.run_goal("bounded uncertain dispatch", goal_id="goal-uncertain-dispatch")

            self.assertEqual(first_factory.run_calls, 1)
            first.store.close()

            second_factory = _CountingFactory(
                WorkerResult(success=True, response="must not be replayed")
            )
            second = _kernel(db, second_factory)
            try:
                result = second.run_goal(
                    "bounded uncertain dispatch",
                    goal_id="goal-uncertain-dispatch",
                )
                self.assertFalse(result.assessment.success)
                self.assertIn("outcome is unknown", result.worker_result.error or "")
                self.assertTrue(result.worker_result.metrics.get("outcome_uncertain"))
                self.assertEqual(second_factory.create_calls, 0)
                self.assertEqual(second_factory.run_calls, 0)
                self.assertIsNone(result.proposal)
                route_key = SelfModel.route_capability_key("primary", "general")
                self.assertIsNone(second.store.get_capability(route_key))
            finally:
                second.store.close()


if __name__ == "__main__":
    unittest.main()
