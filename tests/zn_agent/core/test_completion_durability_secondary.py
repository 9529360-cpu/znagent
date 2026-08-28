from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.models import WorkerResult
from zn_agent.core.self_model import SelfModel
from tests.zn_agent.core.test_completion_durability_boundaries import (
    _CountingFactory,
    _kernel,
    _resident,
)


class CompletionDurabilitySecondaryTests(unittest.TestCase):
    def test_external_success_resumes_secondary_learning_after_accounting_without_model_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first_factory = _CountingFactory(
                WorkerResult(
                    success=True,
                    response="secondary learning answer",
                    verification_passed=True,
                    metrics={"model_invoked": True},
                )
            )
            first = _resident(db, first_factory)
            event = first.enqueue("novel secondary learning boundary")

            with patch.object(
                first.investigator,
                "resolve_from_external",
                side_effect=RuntimeError("crash before investigation learning integration"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "crash before investigation learning integration"
                ):
                    first.run_once(target_event_id=event.event_id)

            self.assertEqual(first_factory.run_calls, 1)
            self.assertEqual(first.store.get_working_state().stage, "external_completion")
            self.assertEqual(first.store.get_runtime_metrics().tasks_total, 1)
            self.assertEqual(first.kernel.self_model.knowledge("general").evidence_count, 1)
            self.assertEqual(len(first.life.recent_learning_candidates(10)), 1)
            investigation = first.investigator.current(event.event_id)
            self.assertIsNotNone(investigation)
            self.assertFalse(str(investigation.status).startswith("resolved"))
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
                self.assertEqual(second_factory.run_calls, 0)
                self.assertEqual(second.store.get_runtime_metrics().tasks_total, 1)
                self.assertEqual(second.kernel.self_model.knowledge("general").evidence_count, 1)
                self.assertEqual(len(second.life.recent_learning_candidates(10)), 1)
                investigation = second.investigator.current(event.event_id)
                self.assertIsNotNone(investigation)
                self.assertTrue(str(investigation.status).startswith("resolved"))
            finally:
                second.store.close()

    def test_external_failure_resumes_life_state_after_metrics_without_model_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first_factory = _CountingFactory(
                WorkerResult(
                    success=False,
                    error="bounded external failure",
                    metrics={"model_invoked": True},
                )
            )
            first = _resident(db, first_factory)
            event = first.enqueue("novel failure life boundary")

            with patch.object(
                first.life,
                "mark_impasse_unresolved",
                side_effect=RuntimeError("crash before unresolved life publication"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "crash before unresolved life publication"
                ):
                    first.run_once(target_event_id=event.event_id)

            self.assertEqual(first_factory.run_calls, 1)
            self.assertEqual(first.store.get_working_state().stage, "external_completion")
            self.assertEqual(first.store.get_runtime_metrics().tasks_total, 1)
            self.assertEqual(first.kernel.self_model.knowledge("general").evidence_count, 0)
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
                self.assertEqual(second_factory.run_calls, 0)
                self.assertEqual(second.store.get_runtime_metrics().tasks_total, 1)
                self.assertEqual(second.kernel.self_model.knowledge("general").evidence_count, 0)
                self.assertIsNotNone(second.life.snapshot().current_impasse)
            finally:
                second.store.close()

    def test_kernel_route_learning_is_not_duplicated_if_settle_checkpoint_crashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first_factory = _CountingFactory(
                WorkerResult(
                    success=True,
                    response="route-learning durable answer",
                    verification_passed=True,
                    metrics={"model_invoked": True},
                )
            )
            first = _kernel(db, first_factory)
            real_save_goal = first.store.save_goal
            crashed = False

            def crash_after_settle(goal):
                nonlocal crashed
                real_save_goal(goal)
                durable = goal.metadata.get(first._DURABLE_RUN_KEY)
                attempts = durable.get("attempts") if isinstance(durable, dict) else None
                if (
                    not crashed
                    and isinstance(attempts, list)
                    and attempts
                    and attempts[-1].get("status") == "settled"
                    and not isinstance(durable.get("final"), dict)
                ):
                    crashed = True
                    raise RuntimeError("crash after route learning settle")

            with patch.object(first.store, "save_goal", side_effect=crash_after_settle):
                with self.assertRaisesRegex(RuntimeError, "crash after route learning settle"):
                    first.run_goal(
                        "bounded route-learning durability",
                        goal_id="goal-route-learning-settle",
                    )

            route_key = SelfModel.route_capability_key("primary", "general")
            self.assertEqual(first.store.get_capability(route_key).evidence_count, 1)
            self.assertEqual(first_factory.run_calls, 1)
            first.store.close()

            second_factory = _CountingFactory(
                WorkerResult(success=True, response="must not be used")
            )
            second = _kernel(db, second_factory)
            try:
                result = second.run_goal(
                    "bounded route-learning durability",
                    goal_id="goal-route-learning-settle",
                )
                self.assertTrue(result.assessment.success)
                self.assertEqual(second_factory.run_calls, 0)
                self.assertEqual(second.store.get_capability(route_key).evidence_count, 1)
                self.assertEqual(len(result.experiences), 1)
            finally:
                second.store.close()


if __name__ == "__main__":
    unittest.main()
