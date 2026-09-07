from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.delegated_work_coordinator import DelegatedWorkCoordinator
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.worker_progress import record_worker_progress


class DelegatedWorkerStallBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root_dir = Path(self.tmp.name)
        self.workspace = root_dir / "workspace"
        self.workspace.mkdir()
        self.resident = build_resident_runtime(
            config={"model": {}},
            store_path=root_dir / "kernel.db",
        )
        self.ledger = self.resident.work_ledger
        self.ledger.create_thread(thread_id="stall-budget", title="Stall budget")
        self.ledger.attach_workspace("stall-budget", self.workspace, name="Workspace")
        _, self.event = self.ledger.start(
            "stall-budget",
            "Research, implement, and review one runnable result.",
            acceptance_criteria=["runnable result independently verified"],
        )
        self.event.payload["worker_stall_seconds"] = 1
        self.root = self.ledger.work_item_for_event(self.event.event_id)
        assert self.root is not None
        self.coordinator = DelegatedWorkCoordinator(self.resident)

    def tearDown(self) -> None:
        self.resident.store.close()
        self.tmp.cleanup()

    def _request(self, suffix: str):
        return SimpleNamespace(
            request_id=f"request-{suffix}",
            required_capabilities=("general",),
            context={},
            question="Choose the next bounded step.",
        )

    def _active_run(self):
        runs = self.ledger.list_worker_runs(thread_id="stall-budget", limit=256)
        active = [run for run in runs if run.state in {"queued", "running"}]
        self.assertLessEqual(len(active), 1)
        return active[0] if active else None

    def _age_progress(self, worker_run_id: str) -> None:
        run = self.ledger.worker_run(worker_run_id)
        self.assertIsNotNone(run)
        assert run is not None
        if not isinstance(run.metrics.get("supervision_progress"), dict):
            record_worker_progress(
                self.ledger,
                worker_run_id,
                stage="context_bound",
                evidence={"model_goal_id": run.model_goal_id},
            )
            run = self.ledger.worker_run(worker_run_id)
            assert run is not None
        metrics = dict(run.metrics)
        progress = dict(metrics.get("supervision_progress") or {})
        progress["last_progress_at"] = "2000-01-01T00:00:00+00:00"
        metrics["supervision_progress"] = progress
        with self.ledger._lock, closing(self.ledger._connect()) as conn:
            conn.execute(
                "UPDATE worker_runs SET metrics_json=? WHERE worker_run_id=?",
                (
                    json.dumps(metrics, ensure_ascii=False, separators=(",", ":")),
                    worker_run_id,
                ),
            )
            conn.commit()

    def test_stalled_worker_retries_get_new_identity_then_stop_at_bounded_budget(self) -> None:
        first_request = self.coordinator.prepare_request(
            self.event,
            self.root,
            self._request("first"),
            [],
        )
        first = self._active_run()
        self.assertIsNotNone(first)
        assert first is not None
        self.assertEqual(first.executor_kind, "research")
        self.assertIn("delegated_worker", first_request.context)

        ids = [first.worker_run_id]
        for index in range(2):
            current = self._active_run()
            assert current is not None
            self._age_progress(current.worker_run_id)
            request = self.coordinator.prepare_request(
                self.event,
                self.root,
                self._request(f"retry-{index}"),
                [],
            )
            failed = self.ledger.worker_run(current.worker_run_id)
            self.assertIsNotNone(failed)
            assert failed is not None
            self.assertEqual(failed.state, "failed")
            self.assertEqual(failed.verification_status, "stalled")
            self.assertEqual(failed.metrics.get("supervision_failure"), "no_progress")

            replacement = self._active_run()
            self.assertIsNotNone(replacement)
            assert replacement is not None
            self.assertNotIn(replacement.worker_run_id, ids)
            ids.append(replacement.worker_run_id)
            self.assertIn("delegated_worker", request.context)

        third = self._active_run()
        assert third is not None
        self._age_progress(third.worker_run_id)
        exhausted_request = self.coordinator.prepare_request(
            self.event,
            self.root,
            self._request("exhausted"),
            [],
        )
        third_failed = self.ledger.worker_run(third.worker_run_id)
        self.assertIsNotNone(third_failed)
        assert third_failed is not None
        self.assertEqual(third_failed.state, "failed")
        self.assertIsNone(self._active_run())

        supervision = exhausted_request.context.get("delegated_supervision")
        self.assertEqual(
            supervision,
            {
                "status": "attempt_budget_exhausted",
                "executor_kind": "research",
                "expected_action": "research_page",
                "attempts": 3,
            },
        )
        all_runs = self.ledger.list_worker_runs(thread_id="stall-budget", limit=256)
        self.assertEqual(len(all_runs), 3)
        self.assertEqual(len({run.worker_run_id for run in all_runs}), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
