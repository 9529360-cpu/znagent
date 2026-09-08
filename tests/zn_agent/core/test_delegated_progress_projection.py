from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.work_restore_control import RestoreAwareWorkControl
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.worker_progress import record_worker_progress


class DelegatedProgressProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "kernel.db"
        self.resident = build_resident_runtime(config={"model": {}}, store_path=self.db)
        self.control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(self.resident))
        self.ledger = self.control.ledger
        self.ledger.create_thread(thread_id="delegated-progress", title="Delegated progress")
        _, event = self.ledger.start(
            "delegated-progress",
            "Research, implement, and review one durable result.",
            acceptance_criteria=["verified result"],
        )
        self.event_id = event.event_id
        root = self.ledger.work_item_for_event(event.event_id)
        assert root is not None
        self.root = root

    def tearDown(self) -> None:
        self.resident.store.close()
        self.tmp.cleanup()

    def _child_run(self, kind: str):
        child = self.ledger.create_child_item(
            root_work_item_id=self.root.work_item_id,
            objective=f"{kind} delegated phase",
            acceptance_criteria=[f"delegated_worker_evidence: {kind}"],
        )
        run = self.ledger.start_worker_run(
            work_item_id=child.work_item_id,
            executor_kind=kind,
            tool_scope=("read",),
            authority_scope=("workspace",),
        )
        return child, run

    def _set_run_state(self, worker_run_id: str, state: str) -> None:
        with self.ledger._lock, closing(self.ledger._connect()) as conn:
            conn.execute(
                "UPDATE worker_runs SET state=? WHERE worker_run_id=?",
                (state, worker_run_id),
            )
            conn.commit()

    def test_running_delegation_projects_bounded_current_progress(self) -> None:
        research_child, research = self._child_run("research")
        self.ledger.complete_worker_run(
            research.worker_run_id,
            result_summary="research complete",
            verification_status="scope_admitted",
        )
        self.ledger.complete_child_item(research_child.work_item_id, result="research complete")

        _, coding = self._child_run("coding")
        record_worker_progress(
            self.ledger,
            coding.worker_run_id,
            stage="effect_started",
            evidence={"effect": "durable"},
        )

        _, review = self._child_run("review")
        self._set_run_state(review.worker_run_id, "queued")

        delegation = self.control.progress("delegated-progress", self.event_id)["delegation"]
        self.assertEqual(delegation["plan_version"], 1)
        self.assertEqual(delegation["status"], "running")
        self.assertEqual(delegation["current_phase"], "coding")
        self.assertEqual(
            delegation["counts"],
            {"pending": 1, "running": 1, "completed": 1, "failed": 0, "superseded": 0},
        )
        phases = {phase["kind"]: phase for phase in delegation["phases"]}
        self.assertEqual(phases["research"]["stage"], "completed")
        self.assertEqual(phases["coding"]["stage"], "acting")
        self.assertEqual(phases["review"]["stage"], "waiting")

    def test_internal_fields_context_and_raw_errors_never_leak(self) -> None:
        _, run = self._child_run("coding")
        secret_context = "SECRET-CONTEXT-CONTENT"
        record_worker_progress(
            self.ledger,
            run.worker_run_id,
            stage="context_bound",
            evidence={"private_text": secret_context},
        )
        with self.ledger._lock, closing(self.ledger._connect()) as conn:
            conn.execute(
                "UPDATE worker_runs SET model_goal_id=?,model_route_id=?,provider=?,error=? WHERE worker_run_id=?",
                (
                    "SECRET-GOAL",
                    "SECRET-ROUTE",
                    "SECRET-PROVIDER",
                    "SECRET-ERROR",
                    run.worker_run_id,
                ),
            )
            conn.commit()

        projection = self.control.progress("delegated-progress", self.event_id)["delegation"]
        encoded = json.dumps(projection, ensure_ascii=False, sort_keys=True)
        for private_value in (
            run.worker_run_id,
            run.work_item_id,
            "SECRET-GOAL",
            "SECRET-ROUTE",
            "SECRET-PROVIDER",
            "SECRET-ERROR",
            secret_context,
            "fingerprint",
            "tool_scope",
            "authority_scope",
            "metrics",
        ):
            self.assertNotIn(private_value, encoded)

    def test_restart_reconstructs_same_projection_from_durable_truth(self) -> None:
        _, coding = self._child_run("coding")
        record_worker_progress(
            self.ledger,
            coding.worker_run_id,
            stage="effect_started",
            evidence={"effect": "durable"},
        )
        before = self.control.progress("delegated-progress", self.event_id)["delegation"]

        self.resident.store.close()
        restored = build_resident_runtime(config={"model": {}}, store_path=self.db)
        self.resident = restored
        self.control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(restored))
        self.ledger = self.control.ledger
        after = self.control.progress("delegated-progress", self.event_id)["delegation"]
        self.assertEqual(after, before)

    def test_steering_marks_old_plan_worker_superseded_not_running(self) -> None:
        _, old = self._child_run("coding")
        self.ledger._set_plan_version("delegated-progress", 2)
        self.ledger.reconcile_stale_worker_runs(thread_id="delegated-progress")
        old_after = self.ledger.worker_run(old.worker_run_id)
        assert old_after is not None
        self.assertEqual(old_after.state, "stale")

        current_root = self.ledger.work_item_for_event(self.event_id)
        assert current_root is not None
        current_root.plan_version = 2
        current_root.status = "running"
        self.ledger._save_item(current_root)
        self.root = current_root
        _, current = self._child_run("coding")
        record_worker_progress(
            self.ledger,
            current.worker_run_id,
            stage="context_bound",
            evidence={"plan": 2},
        )

        progress = self.ledger.progress("delegated-progress", self.event_id)
        progress["current_plan_version"] = 2
        projection = self.control._delegation_projection("delegated-progress", progress)
        assert projection is not None
        self.assertEqual(projection["current_phase"], "coding")
        self.assertEqual(projection["counts"]["running"], 1)
        self.assertGreaterEqual(projection["counts"]["superseded"], 1)
        old_phase = [phase for phase in projection["phases"] if phase["status"] == "superseded"]
        self.assertTrue(old_phase)

    def test_failed_worker_is_coarse_and_raw_error_is_hidden(self) -> None:
        _, run = self._child_run("review")
        failed = self.ledger.fail_worker_run(
            run.worker_run_id,
            error="SECRET-RAW-PROVIDER-ERROR",
            verification_status="failed",
        )
        self.assertEqual(failed.state, "failed")
        projection = self.control.progress("delegated-progress", self.event_id)["delegation"]
        phase = next(item for item in projection["phases"] if item["kind"] == "review")
        self.assertEqual(phase["status"], "failed")
        self.assertEqual(phase["stage"], "failed")
        self.assertNotIn("SECRET-RAW-PROVIDER-ERROR", json.dumps(projection))

    def test_unknown_internal_stage_falls_back_to_working(self) -> None:
        _, run = self._child_run("coding")
        with self.ledger._lock, closing(self.ledger._connect()) as conn:
            conn.execute(
                "UPDATE worker_runs SET metrics_json=? WHERE worker_run_id=?",
                (
                    json.dumps(
                        {
                            "supervision_progress": {
                                "revision": 7,
                                "stage": "SECRET-UNBOUNDED-STAGE",
                                "fingerprint": "SECRET-FINGERPRINT",
                                "last_progress_at": "2026-09-08T00:00:00+00:00",
                            }
                        }
                    ),
                    run.worker_run_id,
                ),
            )
            conn.commit()
        projection = self.control.progress("delegated-progress", self.event_id)["delegation"]
        phase = next(item for item in projection["phases"] if item["kind"] == "coding")
        self.assertEqual(phase["stage"], "working")
        encoded = json.dumps(projection)
        self.assertNotIn("SECRET-UNBOUNDED-STAGE", encoded)
        self.assertNotIn("SECRET-FINGERPRINT", encoded)

    def test_projection_is_read_only(self) -> None:
        _, run = self._child_run("research")
        record_worker_progress(
            self.ledger,
            run.worker_run_id,
            stage="context_bound",
            evidence={"bound": True},
        )
        before_runs = [
            (item.worker_run_id, item.state, item.plan_version, dict(item.metrics))
            for item in self.ledger.list_worker_runs(thread_id="delegated-progress")
        ]
        before_plan = self.ledger.plan_version("delegated-progress")
        before_events = len(self.resident.store.list_events(limit=256))

        for _ in range(3):
            projection = self.control.progress("delegated-progress", self.event_id)["delegation"]
            self.assertEqual(projection["current_phase"], "research")

        after_runs = [
            (item.worker_run_id, item.state, item.plan_version, dict(item.metrics))
            for item in self.ledger.list_worker_runs(thread_id="delegated-progress")
        ]
        self.assertEqual(after_runs, before_runs)
        self.assertEqual(self.ledger.plan_version("delegated-progress"), before_plan)
        self.assertEqual(len(self.resident.store.list_events(limit=256)), before_events)

    def test_existing_work_progress_rpc_carries_delegation(self) -> None:
        _, run = self._child_run("research")
        record_worker_progress(
            self.ledger,
            run.worker_run_id,
            stage="worker_started",
            evidence={"started": True},
        )
        server = ResidentRpcServer(
            resident=self.resident,
            input_stream=io.StringIO(),
            output_stream=io.StringIO(),
        )
        response = server.handle(
            {
                "id": "delegated-progress-rpc",
                "method": "work_progress",
                "params": {
                    "thread_id": "delegated-progress",
                    "event_id": self.event_id,
                },
            }
        )
        self.assertTrue(response["ok"])
        delegation = response["result"]["progress"]["delegation"]
        self.assertEqual(delegation["current_phase"], "research")
        self.assertEqual(delegation["phases"][0]["stage"], "starting")

    def test_non_delegated_work_remains_backward_compatible(self) -> None:
        self.ledger.create_thread(thread_id="plain-work", title="Plain work")
        _, event = self.ledger.start("plain-work", "ordinary resident work")
        progress = self.control.progress("plain-work", event.event_id)
        self.assertNotIn("delegation", progress)
        self.assertEqual(progress["event_id"], event.event_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
