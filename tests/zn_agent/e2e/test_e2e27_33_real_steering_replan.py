from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.delegated_work_coordinator import DelegatedWorkCoordinator
from zn_agent.core.provider_bridge import (
    build_resident_runtime,
    build_zn_cognitive_resource_plan,
)
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_restore_control import RestoreAwareWorkControl
from zn_agent.core.worker_progress import progress_snapshot


_REAL_FLAG = {"1", "true", "yes"}
STEERING = "昨天那个产品继续。登录先别做，先把核心记账跑起来。"


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


class E2E2733RealSteeringReplanTests(unittest.TestCase):
    @staticmethod
    def _configured():
        if os.environ.get("ZN_E2E27_33_REAL_MODEL", "").strip().lower() not in _REAL_FLAG:
            raise unittest.SkipTest(
                "set ZN_E2E27_33_REAL_MODEL=1 only on the guarded real-model runner"
            )
        config = __import__("zn_agent.core.config", fromlist=["load_zn_config"]).load_zn_config()
        plan = build_zn_cognitive_resource_plan(config)
        routes = [
            route
            for route in plan.routes
            if route.provider != "none" and str(route.model or "").strip()
        ]
        if not plan.available or not routes:
            raise unittest.SkipTest(
                "E2E-27/33 real acceptance requires one configured external cognitive resource"
            )
        return config, routes[0]

    @staticmethod
    def _make_yesterday(ledger, thread_id: str) -> None:
        thread = ledger.get_thread(thread_id)
        assert thread is not None
        thread.updated_at = (datetime.now().astimezone() - timedelta(days=1)).isoformat()
        ledger._save_thread(thread)

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
        resolver = getattr(resident, "_resolve_cognitive_resource_health", None)
        route_setter = getattr(resident.kernel.router, "set_health_resolver", None)
        if callable(resolver) and callable(route_setter):
            route_setter(resolver)
        return recording

    @staticmethod
    def _seed_old_plan(ledger, workspace: Path):
        ledger.create_thread(thread_id="product", title="Personal ledger product")
        ledger.attach_workspace("product", workspace, name="Product workspace")
        _, old_event = ledger.start(
            "product",
            "开发个人记账产品：登录、核心记账和本地保存都做。",
            acceptance_criteria=[
                "新增收入和支出能通过真实运行路径写入本地数据",
                "重启后的新进程能读回已保存记录",
            ],
        )
        old_root = ledger.work_item_for_event(old_event.event_id)
        assert old_root is not None

        completed_child = ledger.create_child_item(
            root_work_item_id=old_root.work_item_id,
            objective="确认本地优先记账产品的核心行为",
            acceptance_criteria=["delegated_worker_evidence: research/research_page"],
            title="Accepted historical research",
        )
        completed_worker = ledger.start_worker_run(
            work_item_id=completed_child.work_item_id,
            executor_kind="research",
            tool_scope=("managed_browser.read",),
            authority_scope=("web_read",),
        )
        ledger.complete_worker_run(
            completed_worker.worker_run_id,
            result_summary="verified local-first product evidence",
            verification_status="accepted",
        )
        ledger.complete_child_item(
            completed_child.work_item_id,
            result="verified local-first product evidence",
        )

        stale_child = ledger.create_child_item(
            root_work_item_id=old_root.work_item_id,
            objective="实现旧计划里的登录流程",
            acceptance_criteria=["delegated_worker_evidence: coding/write_file"],
            title="Old login worker",
        )
        stale_worker = ledger.start_worker_run(
            work_item_id=stale_child.work_item_id,
            executor_kind="coding",
            tool_scope=("workspace.read", "workspace.write", "terminal.python"),
            authority_scope=("workspace_read", "workspace_write", "terminal_execute"),
        )
        return old_event, old_root, completed_child, completed_worker, stale_child, stale_worker

    def test_natural_yesterday_steering_creates_new_plan_worker_and_survives_restart(self) -> None:
        config, route = self._configured()
        with tempfile.TemporaryDirectory(prefix="zn-e2e27-33-real-steer-") as tmp:
            root_dir = Path(tmp)
            workspace = root_dir / "workspace"
            workspace.mkdir()
            marker = workspace / "already-completed.txt"
            marker.write_text("historical-effect-once", encoding="utf-8")
            db = root_dir / "kernel.db"

            resident = build_resident_runtime(config=config, store_path=db)
            recording = self._attach_recording_factory(resident, config, route)
            try:
                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
                ledger = control.ledger
                (
                    old_event,
                    old_root,
                    completed_child,
                    _completed_worker,
                    _stale_child,
                    stale_worker,
                ) = self._seed_old_plan(ledger, workspace)
                self._make_yesterday(ledger, "product")
                ledger.create_thread(thread_id="fresh-ui", title="Fresh UI ingress")

                snapshot, new_event = control.start("fresh-ui", STEERING)
                self.assertEqual(snapshot[0].thread_id, "product")
                self.assertNotEqual(new_event.event_id, old_event.event_id)
                self.assertEqual(ledger.plan_version("product"), 2)
                self.assertEqual(new_event.payload["work_plan_version"], 2)
                self.assertFalse(new_event.payload["work_steering"]["replay_previous_event"])
                self.assertEqual(
                    new_event.payload["work_steering"]["previous_event_id"],
                    old_event.event_id,
                )

                old_root_after = ledger.work_item_for_event(old_event.event_id)
                new_root = ledger.work_item_for_event(new_event.event_id)
                self.assertIsNotNone(old_root_after)
                self.assertIsNotNone(new_root)
                assert old_root_after is not None and new_root is not None
                self.assertEqual(old_root_after.status, "superseded")
                self.assertEqual(old_root_after.plan_version, 1)
                self.assertEqual(new_root.status, "running")
                self.assertEqual(new_root.plan_version, 2)

                historical = ledger._work_item_by_id(completed_child.work_item_id)
                self.assertIsNotNone(historical)
                assert historical is not None
                self.assertEqual(historical.status, "completed")
                self.assertEqual(historical.plan_version, 1)
                self.assertEqual(historical.result, "verified local-first product evidence")

                old_worker_after = ledger.worker_run(stale_worker.worker_run_id)
                self.assertIsNotNone(old_worker_after)
                assert old_worker_after is not None
                self.assertEqual(old_worker_after.state, "stale")
                self.assertEqual(old_worker_after.verification_status, "stale_plan")

                request = SimpleNamespace(
                    request_id="phase3-new-plan",
                    required_capabilities=("general",),
                    context={},
                    question="Choose the next bounded current-plan step.",
                )
                coordinator = DelegatedWorkCoordinator(resident)
                coordinator.prepare_request(new_event, new_root, request, [])
                delegated = request.context.get("delegated_worker")
                self.assertIsInstance(delegated, dict)
                assert isinstance(delegated, dict)
                new_worker_id = str(delegated["worker_run_id"])
                new_worker = ledger.worker_run(new_worker_id)
                self.assertIsNotNone(new_worker)
                assert new_worker is not None
                self.assertEqual(new_worker.plan_version, 2)
                self.assertNotEqual(new_worker.worker_run_id, stale_worker.worker_run_id)
                self.assertEqual(new_worker.model_goal_id, f"goal-{request.request_id}")

                real_result = resident.kernel.run_goal(
                    request.question,
                    required_capabilities=tuple(request.required_capabilities),
                    priority=new_event.priority,
                    metadata={
                        "resident_event_id": new_event.event_id,
                        "cognition_request": {
                            "request_id": request.request_id,
                            "context": dict(request.context),
                        },
                    },
                    max_attempts_override=1,
                    goal_id=new_worker.model_goal_id,
                )
                self.assertTrue(real_result.worker_result.success, real_result.worker_result.error)
                self.assertEqual(recording.worker_runs, 1)
                self.assertEqual(real_result.route.route_id, route.route_id)
                coordinator.reconcile(thread_id="product")
                new_worker_after = ledger.worker_run(new_worker.worker_run_id)
                self.assertIsNotNone(new_worker_after)
                assert new_worker_after is not None
                self.assertEqual(
                    progress_snapshot(new_worker_after)["stage"],
                    "provider_result_persisted",
                )
                self.assertEqual(marker.read_text(encoding="utf-8"), "historical-effect-once")

                new_event_id = new_event.event_id
                old_event_id = old_event.event_id
                historical_id = completed_child.work_item_id
                new_worker_id = new_worker.worker_run_id
            finally:
                resident.store.close()

            restored = build_resident_runtime(config=config, store_path=db)
            try:
                restored_control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(restored))
                restored_ledger = restored_control.ledger
                self.assertEqual(restored_ledger.plan_version("product"), 2)
                self.assertEqual(
                    restored_ledger.get_run(old_event_id).ledger_state,
                    "stale_finalized",
                )
                self.assertEqual(restored_ledger.worker_run(stale_worker.worker_run_id).state, "stale")
                self.assertEqual(restored_ledger.worker_run(new_worker_id).plan_version, 2)
                historical_after = restored_ledger._work_item_by_id(historical_id)
                self.assertIsNotNone(historical_after)
                assert historical_after is not None
                self.assertEqual(historical_after.status, "completed")
                self.assertEqual(historical_after.result, "verified local-first product evidence")

                restored_ledger.create_thread(thread_id="restart-ui", title="Restart UI ingress")
                resumed_snapshot, resumed_event = restored_control.start(
                    "restart-ui",
                    "上次那个继续",
                )
                self.assertEqual(resumed_snapshot[0].thread_id, "product")
                self.assertEqual(resumed_event.event_id, new_event_id)
                self.assertEqual(marker.read_text(encoding="utf-8"), "historical-effect-once")

                print(
                    "ZN_E2E27_33_REPLAN="
                    + json.dumps(
                        {
                            "thread_id": "product",
                            "old_event_id": old_event_id,
                            "new_event_id": new_event_id,
                            "plan_version": restored_ledger.plan_version("product"),
                            "historical_completed_preserved": True,
                            "old_worker_state": restored_ledger.worker_run(stale_worker.worker_run_id).state,
                            "new_worker_run_id": new_worker_id,
                            "new_worker_plan_version": restored_ledger.worker_run(new_worker_id).plan_version,
                            "model_route_id": real_result.route.route_id,
                            "provider": real_result.route.provider,
                            "real_model_invocations": recording.worker_runs,
                            "restart_resumed_exact_event": resumed_event.event_id == new_event_id,
                            "historical_effect_replayed": False,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            finally:
                restored.store.close()

    def test_late_old_worker_completion_and_verification_never_advance_current_plan(self) -> None:
        config, _route = self._configured()
        with tempfile.TemporaryDirectory(prefix="zn-e2e27-stale-worker-") as tmp:
            root_dir = Path(tmp)
            workspace = root_dir / "workspace"
            workspace.mkdir()
            resident = build_resident_runtime(config=config, store_path=root_dir / "kernel.db")
            try:
                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
                ledger = control.ledger
                old_event, _old_root, completed_child, _completed_worker, _stale_child, stale_worker = (
                    self._seed_old_plan(ledger, workspace)
                )
                self._make_yesterday(ledger, "product")
                ledger.create_thread(thread_id="fresh-ui-2", title="Fresh UI")
                _, new_event = control.start("fresh-ui-2", STEERING)
                new_root = ledger.work_item_for_event(new_event.event_id)
                self.assertIsNotNone(new_root)
                assert new_root is not None

                late = ledger.complete_worker_run(
                    stale_worker.worker_run_id,
                    result_summary="late old-plan login worker says complete",
                    claimed_completion=True,
                    verification_status="accepted",
                )
                after_verification = ledger.record_worker_verification(
                    stale_worker.worker_run_id,
                    verification_status="accepted",
                )
                self.assertEqual(late.state, "stale")
                self.assertEqual(after_verification.state, "stale")
                self.assertEqual(after_verification.verification_status, "stale_plan")
                self.assertEqual(ledger.plan_version("product"), 2)
                current_root = ledger.work_item_for_event(new_event.event_id)
                self.assertIsNotNone(current_root)
                assert current_root is not None
                self.assertEqual(current_root.status, "running")
                self.assertFalse(control.progress("product", new_event.event_id).get("accepted", False))

                historical = ledger._work_item_by_id(completed_child.work_item_id)
                self.assertIsNotNone(historical)
                assert historical is not None
                self.assertEqual(historical.status, "completed")
                self.assertEqual(historical.result, "verified local-first product evidence")
                old_progress = control.progress("product", old_event.event_id)
                self.assertTrue(old_progress["stale"])
                self.assertFalse(old_progress["accepted"])

                print(
                    "ZN_E2E27_STALE_GATE="
                    + json.dumps(
                        {
                            "old_worker_run_id": stale_worker.worker_run_id,
                            "old_worker_state": after_verification.state,
                            "old_worker_verification": after_verification.verification_status,
                            "current_plan_version": ledger.plan_version("product"),
                            "current_root_status": current_root.status,
                            "late_result_advanced_current_plan": False,
                            "historical_completed_preserved": True,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
