from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime


class WorkerStalePlanResultTests(unittest.TestCase):
    def test_late_worker_result_is_retained_as_stale_and_never_advances_new_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            workspace = root_dir / "workspace"
            workspace.mkdir()
            resident = build_resident_runtime(config={"model": {}}, store_path=root_dir / "kernel.db")
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="stale-worker", title="Stale worker")
                ledger.attach_workspace("stale-worker", workspace, name="Workspace")
                _, event = ledger.start(
                    "stale-worker",
                    "old plan",
                    acceptance_criteria=["fresh current-plan verification"],
                )
                root = ledger.work_item_for_event(event.event_id)
                assert root is not None
                child = ledger.create_child_item(
                    root_work_item_id=root.work_item_id,
                    objective="old research",
                    acceptance_criteria=["delegated_worker_evidence: research/research_page"],
                )
                run = ledger.start_worker_run(
                    work_item_id=child.work_item_id,
                    executor_kind="research",
                    tool_scope=("managed_browser.read",),
                    authority_scope=("web_read",),
                )

                ledger._set_plan_version("stale-worker", 2)
                ledger._supersede_items_before("stale-worker", 2)
                late = ledger.complete_worker_run(
                    run.worker_run_id,
                    result_summary="late successful old-plan result",
                    model_route_id="only-route",
                )

                self.assertEqual(late.state, "stale")
                self.assertEqual(late.verification_status, "stale_plan")
                self.assertIn("late successful old-plan result", late.result_summary or "")
                self.assertEqual(ledger.plan_version("stale-worker"), 2)
                stale_child = next(
                    item for item in ledger.list_work_items("stale-worker")
                    if item.work_item_id == child.work_item_id
                )
                self.assertNotEqual(stale_child.status, "completed")
                self.assertFalse(ledger.progress("stale-worker", event.event_id).get("accepted", False))
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
