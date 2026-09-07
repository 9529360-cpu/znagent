from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.config import load_zn_config
from zn_agent.core.delegated_work_coordinator import DelegatedWorkCoordinator
from zn_agent.core.provider_bridge import (
    build_resident_runtime,
    build_zn_cognitive_resource_plan,
)
from zn_agent.core.worker_progress import progress_snapshot


_REAL_FLAG = {"1", "true", "yes"}


class _RecordingWorker:
    def __init__(self, worker, owner) -> None:
        self.worker = worker
        self.owner = owner

    def run(self, goal, kernel_context):
        self.owner.worker_runs += 1
        self.owner.goal_ids.append(goal.goal_id)
        return self.worker.run(goal, kernel_context)


class _RecordingFactory:
    def __init__(self, inner) -> None:
        self.inner = inner
        self.creates = 0
        self.worker_runs = 0
        self.goal_ids: list[str] = []

    def set_health_observer(self, observer) -> None:
        setter = getattr(self.inner, "set_health_observer", None)
        if callable(setter):
            setter(observer)

    def create(self, route):
        self.creates += 1
        return _RecordingWorker(self.inner.create(route), self)


class E2E2834RealSupervisionRecoveryTests(unittest.TestCase):
    @staticmethod
    def _configured():
        if os.environ.get("ZN_E2E28_34_REAL_MODEL", "").strip().lower() not in _REAL_FLAG:
            raise unittest.SkipTest(
                "set ZN_E2E28_34_REAL_MODEL=1 only on the guarded real-model runner"
            )
        config = load_zn_config()
        plan = build_zn_cognitive_resource_plan(config)
        routes = [
            route
            for route in plan.routes
            if route.provider != "none" and str(route.model or "").strip()
        ]
        if not plan.available or not routes:
            raise unittest.SkipTest(
                "E2E-28/34 real acceptance requires one configured external cognitive resource"
            )
        return config, routes[0]

    @staticmethod
    def _attach_recording_factory(resident, config, route):
        plan = build_zn_cognitive_resource_plan(config)
        recording = _RecordingFactory(plan.worker_factory)
        observer = getattr(resident, "_observe_cognitive_resource_health", None)
        if callable(observer):
            recording.set_health_observer(observer)
        resident.kernel.reconfigure_resources(
            routes=[route],
            worker_factory=recording,
            max_attempts=1,
            resource_status={"available": True, "error": None},
        )
        return recording

    @staticmethod
    def _make_root_and_worker(resident, *, thread_id: str):
        ledger = resident.work_ledger
        ledger.create_thread(thread_id=thread_id, title="E2E28-34 supervision")
        _, event = ledger.start(
            thread_id,
            "Research one current fact as bounded delegated work and preserve restart safety.",
            acceptance_criteria=["delegated result remains evidence-bound"],
        )
        root = ledger.work_item_for_event(event.event_id)
        assert root is not None
        child = ledger.create_child_item(
            root_work_item_id=root.work_item_id,
            objective="Research one current fact",
            acceptance_criteria=["delegated_worker_evidence: research/research_page"],
        )
        worker = ledger.start_worker_run(
            work_item_id=child.work_item_id,
            executor_kind="research",
            tool_scope=("managed_browser.read",),
            authority_scope=("web_read",),
        )
        return event, root, child, worker

    def test_e2e34_real_provider_result_survives_restart_without_replay(self) -> None:
        config, route = self._configured()
        with tempfile.TemporaryDirectory(prefix="zn-e2e34-real-restart-") as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime(config=config, store_path=db)
            first_factory = self._attach_recording_factory(resident, config, route)
            try:
                _, _, child, worker = self._make_root_and_worker(
                    resident,
                    thread_id="e2e-34-real",
                )
                result = resident.kernel.run_goal(
                    "Return one concise factual observation for restart acceptance.",
                    required_capabilities=("general",),
                    metadata={
                        "cognition_request": {
                            "context": {"worker_run_id": worker.worker_run_id}
                        }
                    },
                    max_attempts_override=1,
                    goal_id=worker.model_goal_id,
                )
                self.assertTrue(result.worker_result.success, result.worker_result.error)
                self.assertEqual(first_factory.worker_runs, 1)
                self.assertEqual(first_factory.goal_ids, [worker.model_goal_id])
                self.assertEqual(
                    resident.work_ledger.worker_run(worker.worker_run_id).state,
                    "running",
                )
                worker_id = worker.worker_run_id
                model_goal_id = worker.model_goal_id
                child_id = child.work_item_id
            finally:
                resident.store.close()

            restored = build_resident_runtime(config=config, store_path=db)
            second_factory = self._attach_recording_factory(restored, config, route)
            try:
                coordinator = DelegatedWorkCoordinator(restored)
                coordinator.reconcile(thread_id="e2e-34-real")
                worker_after = restored.work_ledger.worker_run(worker_id)
                self.assertIsNotNone(worker_after)
                assert worker_after is not None
                progress = progress_snapshot(worker_after)
                self.assertEqual(progress["stage"], "provider_result_persisted")
                self.assertEqual(worker_after.state, "running")
                child_after = restored.work_ledger._work_item_by_id(child_id)
                self.assertIsNotNone(child_after)
                assert child_after is not None
                self.assertEqual(child_after.status, "running")

                resumed = restored.kernel.run_goal(
                    "Return one concise factual observation for restart acceptance.",
                    required_capabilities=("general",),
                    metadata={
                        "cognition_request": {
                            "context": {"worker_run_id": worker_id}
                        }
                    },
                    max_attempts_override=1,
                    goal_id=model_goal_id,
                )
                self.assertTrue(resumed.worker_result.success, resumed.worker_result.error)
                self.assertEqual(second_factory.creates, 0)
                self.assertEqual(second_factory.worker_runs, 0)
                print(
                    "ZN_E2E34_RESTART="
                    + json.dumps(
                        {
                            "worker_run_id": worker_id,
                            "model_goal_id": model_goal_id,
                            "model_route_id": resumed.route.route_id,
                            "provider": resumed.route.provider,
                            "provider_replayed_after_restart": False,
                            "progress_stage": progress["stage"],
                            "worker_state": worker_after.state,
                            "child_state": child_after.status,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            finally:
                restored.store.close()

    def test_e2e28_stalled_worker_gets_new_identity_and_real_model_continues(self) -> None:
        config, route = self._configured()
        with tempfile.TemporaryDirectory(prefix="zn-e2e28-real-stall-") as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime(config=config, store_path=db)
            recording = self._attach_recording_factory(resident, config, route)
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="e2e-28-real", title="E2E28 real stall")
                _, event = ledger.start(
                    "e2e-28-real",
                    "Research, implement, and review one bounded result.",
                    acceptance_criteria=["bounded result independently verified"],
                )
                event.payload["worker_stall_seconds"] = 1
                root = ledger.work_item_for_event(event.event_id)
                assert root is not None
                coordinator = DelegatedWorkCoordinator(resident)

                first_request = SimpleNamespace(
                    request_id="e2e28-first",
                    required_capabilities=("general",),
                    context={},
                    question="Choose the next bounded step.",
                )
                coordinator.prepare_request(event, root, first_request, [])
                first_runs = ledger.list_worker_runs(thread_id="e2e-28-real", limit=16)
                self.assertEqual(len(first_runs), 1)
                first = first_runs[0]

                metrics = dict(first.metrics)
                progress = dict(metrics.get("supervision_progress") or {})
                progress["last_progress_at"] = "2000-01-01T00:00:00+00:00"
                metrics["supervision_progress"] = progress
                with ledger._lock, ledger._connect() as conn:
                    conn.execute(
                        "UPDATE worker_runs SET metrics_json=? WHERE worker_run_id=?",
                        (
                            json.dumps(metrics, ensure_ascii=False, separators=(",", ":")),
                            first.worker_run_id,
                        ),
                    )
                    conn.commit()

                retry_request = SimpleNamespace(
                    request_id="e2e28-retry",
                    required_capabilities=("general",),
                    context={},
                    question="Continue safely from the durable failure evidence.",
                )
                coordinator.prepare_request(event, root, retry_request, [])
                all_runs = ledger.list_worker_runs(thread_id="e2e-28-real", limit=16)
                self.assertEqual(len(all_runs), 2)
                failed, replacement = all_runs
                self.assertEqual(failed.worker_run_id, first.worker_run_id)
                self.assertEqual(failed.state, "failed")
                self.assertEqual(failed.verification_status, "stalled")
                self.assertNotEqual(replacement.worker_run_id, failed.worker_run_id)
                self.assertEqual(replacement.state, "running")
                delegated = retry_request.context.get("delegated_worker")
                self.assertIsInstance(delegated, dict)
                assert isinstance(delegated, dict)
                self.assertEqual(delegated["worker_run_id"], replacement.worker_run_id)
                self.assertEqual(
                    f"goal-{retry_request.request_id}",
                    replacement.model_goal_id,
                )

                real_result = resident.kernel.run_goal(
                    retry_request.question,
                    required_capabilities=tuple(retry_request.required_capabilities),
                    priority=event.priority,
                    metadata={
                        "resident_event_id": event.event_id,
                        "cognition_request": {
                            "request_id": retry_request.request_id,
                            "context": dict(retry_request.context),
                        },
                    },
                    max_attempts_override=1,
                    goal_id=replacement.model_goal_id,
                )
                self.assertTrue(real_result.worker_result.success, real_result.worker_result.error)
                self.assertEqual(recording.worker_runs, 1)
                self.assertEqual(real_result.route.route_id, route.route_id)
                coordinator.reconcile(thread_id="e2e-28-real")
                replacement_after = ledger.worker_run(replacement.worker_run_id)
                self.assertIsNotNone(replacement_after)
                assert replacement_after is not None
                self.assertEqual(
                    progress_snapshot(replacement_after)["stage"],
                    "provider_result_persisted",
                )
                print(
                    "ZN_E2E28_RECOVERY="
                    + json.dumps(
                        {
                            "failed_worker_run_id": failed.worker_run_id,
                            "failed_status": failed.verification_status,
                            "replacement_worker_run_id": replacement.worker_run_id,
                            "replacement_model_goal_id": replacement.model_goal_id,
                            "model_route_id": real_result.route.route_id,
                            "provider": real_result.route.provider,
                            "model_invocations_after_stall": recording.worker_runs,
                            "replacement_progress": progress_snapshot(replacement_after),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
