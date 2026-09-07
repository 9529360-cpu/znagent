from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.worker_progress import (
    progress_snapshot,
    record_worker_progress,
    worker_stalled,
)


class WorkerProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "kernel.db"
        self.resident = build_resident_runtime(config={"model": {}}, store_path=self.db)
        self.ledger = self.resident.work_ledger
        self.ledger.create_thread(thread_id="progress", title="Progress")
        _, event = self.ledger.start(
            "progress",
            "Research, implement, and review one runnable result.",
            acceptance_criteria=["real result verified"],
        )
        self.root = self.ledger.work_item_for_event(event.event_id)
        assert self.root is not None
        self.child = self.ledger.create_child_item(
            root_work_item_id=self.root.work_item_id,
            objective="Research one current source",
            acceptance_criteria=["delegated_worker_evidence: research/research_page"],
        )
        self.run = self.ledger.start_worker_run(
            work_item_id=self.child.work_item_id,
            executor_kind="research",
            tool_scope=("managed_browser.read",),
            authority_scope=("web_read",),
        )

    def tearDown(self) -> None:
        self.resident.store.close()
        self.tmp.cleanup()

    def test_identical_heartbeat_does_not_refresh_progress_time(self) -> None:
        first = record_worker_progress(
            self.ledger,
            self.run.worker_run_id,
            stage="context_bound",
            evidence={
                "model_goal_id": self.run.model_goal_id,
                "private_text": "customer secret content must never persist",
            },
        )
        repeated = record_worker_progress(
            self.ledger,
            self.run.worker_run_id,
            stage="context_bound",
            evidence={
                "model_goal_id": self.run.model_goal_id,
                "private_text": "customer secret content must never persist",
            },
        )
        self.assertEqual(first, repeated)
        self.assertEqual(first["revision"], 1)

        persisted = self.ledger.worker_run(self.run.worker_run_id)
        self.assertIsNotNone(persisted)
        assert persisted is not None
        encoded = json.dumps(persisted.metrics, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("customer secret content", encoded)
        self.assertEqual(progress_snapshot(persisted)["last_progress_at"], first["last_progress_at"])

        changed = record_worker_progress(
            self.ledger,
            self.run.worker_run_id,
            stage="provider_result_observed",
            evidence={"model_goal_id": self.run.model_goal_id, "success": True},
        )
        self.assertEqual(changed["revision"], 2)
        self.assertNotEqual(changed["fingerprint"], first["fingerprint"])

    def test_progress_survives_restart_and_stall_is_age_based(self) -> None:
        progress = record_worker_progress(
            self.ledger,
            self.run.worker_run_id,
            stage="context_bound",
            evidence={"model_goal_id": self.run.model_goal_id},
        )
        self.assertFalse(worker_stalled(self.ledger.worker_run(self.run.worker_run_id), timeout_seconds=3600))
        self.assertTrue(worker_stalled(self.ledger.worker_run(self.run.worker_run_id), timeout_seconds=0))

        self.resident.store.close()
        restored = build_resident_runtime(config={"model": {}}, store_path=self.db)
        self.resident = restored
        persisted = restored.work_ledger.worker_run(self.run.worker_run_id)
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(progress_snapshot(persisted), progress)
        self.assertEqual(persisted.state, "running")


if __name__ == "__main__":
    unittest.main(verbosity=2)
