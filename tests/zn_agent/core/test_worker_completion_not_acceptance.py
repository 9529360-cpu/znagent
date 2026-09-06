from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime


class WorkerCompletionNotAcceptanceTests(unittest.TestCase):
    def test_worker_claimed_completion_cannot_complete_child_or_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            workspace = root_dir / "workspace"
            workspace.mkdir()
            resident = build_resident_runtime(config={"model": {}}, store_path=root_dir / "kernel.db")
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="claim", title="Claim")
                ledger.attach_workspace("claim", workspace, name="Workspace")
                _, event = ledger.start(
                    "claim",
                    "Build a real runnable result and verify it.",
                    acceptance_criteria=["real workspace/world evidence satisfies the goal"],
                )
                root = ledger.work_item_for_event(event.event_id)
                assert root is not None
                child = ledger.create_child_item(
                    root_work_item_id=root.work_item_id,
                    objective="Review real result",
                    acceptance_criteria=["delegated_worker_evidence: review/run_python"],
                )
                run = ledger.start_worker_run(
                    work_item_id=child.work_item_id,
                    executor_kind="review",
                    tool_scope=("workspace.read", "terminal.test"),
                    authority_scope=("workspace_read", "terminal_verify"),
                )

                worker = ledger.complete_worker_run(
                    run.worker_run_id,
                    result_summary="任务已完成 / task completed",
                    claimed_completion=True,
                    verification_status="scope_admitted",
                    model_route_id="only-route",
                )

                self.assertEqual(worker.state, "completed")
                self.assertTrue(worker.claimed_completion)
                child_after = next(
                    item for item in ledger.list_work_items("claim")
                    if item.work_item_id == child.work_item_id
                )
                root_after = ledger.work_item_for_event(event.event_id)
                assert root_after is not None
                self.assertNotEqual(child_after.status, "completed")
                self.assertNotEqual(root_after.status, "completed")
                self.assertFalse(ledger.progress("claim", event.event_id).get("accepted", False))
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
