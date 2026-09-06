from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognition import CognitiveIncrement
from zn_agent.core.provider_bridge import build_resident_runtime


class WorkerMalformedRetryIdentityTests(unittest.TestCase):
    def test_malformed_delegated_result_terminates_worker_before_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            workspace = root_dir / "workspace"
            workspace.mkdir()
            resident = build_resident_runtime(config={"model": {}}, store_path=root_dir / "kernel.db")
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="malformed-worker", title="Malformed worker")
                ledger.attach_workspace("malformed-worker", workspace, name="Workspace")
                _, event = ledger.start(
                    "malformed-worker",
                    "Research, implement, and review a bounded local product.",
                    acceptance_criteria=["runnable product", "independent review"],
                )
                root = ledger.work_item_for_event(event.event_id)
                assert root is not None
                child = ledger.create_child_item(
                    root_work_item_id=root.work_item_id,
                    objective="Implement bounded repair",
                    acceptance_criteria=["delegated_worker_evidence: coding/write_file"],
                )
                profile = resident._WORKER_SCOPE_PROFILES["coding"]
                first = ledger.start_worker_run(
                    work_item_id=child.work_item_id,
                    executor_kind="coding",
                    tool_scope=profile["tool_scope"],
                    authority_scope=profile["authority_scope"],
                )
                state = resident.store.get_working_state()
                state.data["cognition_request"] = {
                    "request_id": first.cognition_request_id,
                    "context": {
                        "delegated_worker": {
                            "worker_run_id": first.worker_run_id,
                            "work_item_id": child.work_item_id,
                            "root_work_item_id": root.work_item_id,
                            "plan_version": root.plan_version,
                            "executor_kind": "coding",
                            "expected_action": "write_file",
                            "model_goal_id": first.model_goal_id,
                        }
                    },
                }
                increment = CognitiveIncrement.create(
                    event_id=event.event_id,
                    impasse_id="imp-malformed",
                    source="external:only-route",
                    question="repair",
                    content='{"zn_work_step":{"objective":"repair","action":{"kind":"write_file"}',
                    quality=1.0,
                    confidence=1.0,
                )
                resident._reject_malformed_structured_proposal(event, state, increment)

                failed = ledger.worker_run(first.worker_run_id)
                assert failed is not None
                self.assertEqual(failed.state, "failed")
                self.assertEqual(failed.verification_status, "schema_rejected")
                self.assertEqual(failed.model_route_id, "only-route")
                self.assertTrue(failed.metrics.get("malformed_envelope"))
                blocked = next(
                    item for item in ledger.list_work_items(root.work_thread_id)
                    if item.work_item_id == child.work_item_id
                )
                self.assertEqual(blocked.status, "blocked")

                items = ledger.list_work_items(root.work_thread_id, limit=256)
                runs = ledger.list_worker_runs(thread_id=root.work_thread_id, limit=256)
                phase = resident._next_worker_phase(root, items, runs)
                self.assertEqual(phase, ("research", "research_page"))

                research_profile = resident._WORKER_SCOPE_PROFILES["research"]
                retry_child = ledger.create_child_item(
                    root_work_item_id=root.work_item_id,
                    objective="Retry with a fresh bounded request",
                    acceptance_criteria=["delegated_worker_evidence: research/research_page"],
                )
                retry = ledger.start_worker_run(
                    work_item_id=retry_child.work_item_id,
                    executor_kind="research",
                    tool_scope=research_profile["tool_scope"],
                    authority_scope=research_profile["authority_scope"],
                )
                self.assertNotEqual(first.worker_run_id, retry.worker_run_id)
                self.assertNotEqual(first.cognition_request_id, retry.cognition_request_id)
                self.assertNotEqual(first.model_goal_id, retry.model_goal_id)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
