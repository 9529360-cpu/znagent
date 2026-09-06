from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.cognition import CognitiveIncrement
from zn_agent.core.provider_bridge import build_resident_runtime


class WorkerScopeAdmissionTests(unittest.TestCase):
    def test_research_worker_write_proposal_is_durably_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            workspace = root_dir / "workspace"
            workspace.mkdir()
            resident = build_resident_runtime(config={"model": {}}, store_path=root_dir / "kernel.db")
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="scope", title="Scope")
                ledger.attach_workspace("scope", workspace, name="Workspace")
                _, event = ledger.start(
                    "scope",
                    "Research before changing the workspace.",
                    acceptance_criteria=["current-world evidence and independent verification"],
                )
                root = ledger.work_item_for_event(event.event_id)
                assert root is not None
                child = ledger.create_child_item(
                    root_work_item_id=root.work_item_id,
                    objective="Research one authoritative source",
                    acceptance_criteria=["delegated_worker_evidence: research/research_page"],
                )
                worker = ledger.start_worker_run(
                    work_item_id=child.work_item_id,
                    executor_kind="research",
                    tool_scope=("managed_browser.navigate", "managed_browser.read"),
                    authority_scope=("web_read",),
                )
                increment = CognitiveIncrement.create(
                    event_id=event.event_id,
                    impasse_id="imp-scope",
                    source="external:only-route",
                    question="bounded research",
                    content=json.dumps(
                        {
                            "zn_work_step": {
                                "objective": "write despite research-only authority",
                                "action": {
                                    "kind": "write_file",
                                    "path": "forbidden.txt",
                                    "content": "must not execute",
                                },
                                "acceptance": {
                                    "kind": "text_equals",
                                    "path": "forbidden.txt",
                                    "expected_text": "must not execute",
                                },
                            }
                        }
                    ),
                    quality=1.0,
                    confidence=1.0,
                )
                state = resident.store.get_working_state()
                state.data["cognition_request"] = {
                    "context": {
                        "delegated_worker": {
                            "worker_run_id": worker.worker_run_id,
                            "work_item_id": child.work_item_id,
                            "root_work_item_id": root.work_item_id,
                            "plan_version": root.plan_version,
                            "executor_kind": "research",
                            "expected_action": "research_page",
                            "model_goal_id": worker.model_goal_id,
                        }
                    }
                }
                state.data["cognitive_increment"] = increment.to_dict()

                marker = object()
                with patch.object(resident, "_accept_borrowed_increment", return_value=None), patch.object(
                    resident,
                    "_return_to_investigation_after_rejection",
                    return_value=marker,
                ):
                    result = resident._cognition_integration_step(
                        event,
                        state,
                        readiness=None,
                    )

                self.assertIs(result, marker)
                rejected = ledger.worker_run(worker.worker_run_id)
                self.assertIsNotNone(rejected)
                assert rejected is not None
                self.assertEqual(rejected.state, "failed")
                self.assertEqual(rejected.verification_status, "scope_rejected")
                self.assertEqual(rejected.model_route_id, "only-route")
                self.assertIn("cannot expand tool/authority scope", rejected.error or "")
                blocked = next(
                    item for item in ledger.list_work_items("scope")
                    if item.work_item_id == child.work_item_id
                )
                self.assertEqual(blocked.status, "blocked")
                self.assertFalse((workspace / "forbidden.txt").exists())
                root_after = ledger.work_item_for_event(event.event_id)
                assert root_after is not None
                self.assertNotEqual(root_after.status, "completed")
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
