from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.cognition import CognitiveIncrement
from zn_agent.core.broad_goal_completion_resident import BroadGoalCompletionResidentRuntime
from zn_agent.core.provider_bridge import build_resident_runtime


class WorkerWriteRepairContractTests(unittest.TestCase):
    def test_write_repair_instruction_requires_complete_replacement_and_exact_text(self) -> None:
        instruction = BroadGoalCompletionResidentRuntime._delegated_worker_instruction(
            "coding", "write_file"
        )
        self.assertIn("COMPLETE replacement", instruction)
        self.assertIn("acceptance.expected_text must exactly equal action.content", instruction)
        self.assertIn("not a diff, patch, search/replace helper", instruction)

    def test_same_kind_invalid_write_reports_exact_schema_failure_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            workspace = root_dir / "workspace"
            workspace.mkdir()
            target = workspace / "app.py"
            target.write_text("print('before')\n", encoding="utf-8")
            resident = build_resident_runtime(config={"model": {}}, store_path=root_dir / "kernel.db")
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="write-repair", title="Write repair")
                ledger.attach_workspace("write-repair", workspace, name="Workspace")
                _, event = ledger.start(
                    "write-repair",
                    "Research, implement, and review a bounded local product.",
                    acceptance_criteria=["runnable product and independent review"],
                )
                root = ledger.work_item_for_event(event.event_id)
                assert root is not None
                child = ledger.create_child_item(
                    root_work_item_id=root.work_item_id,
                    objective="Repair the implementation",
                    acceptance_criteria=["delegated_worker_evidence: coding/write_file"],
                )
                profile = resident._WORKER_SCOPE_PROFILES["coding"]
                worker = ledger.start_worker_run(
                    work_item_id=child.work_item_id,
                    executor_kind="coding",
                    tool_scope=profile["tool_scope"],
                    authority_scope=profile["authority_scope"],
                )
                proposal = json.dumps(
                    {
                        "zn_work_step": {
                            "objective": "repair app",
                            "action": {
                                "kind": "write_file",
                                "path": "app.py",
                                "content": "print('after')\n",
                            },
                            "acceptance": {
                                "kind": "text_equals",
                                "path": "app.py",
                                "expected_text": "print('different')\n",
                            },
                        }
                    }
                )
                increment = CognitiveIncrement.create(
                    event_id=event.event_id,
                    impasse_id="imp-write-repair",
                    source="external:only-route",
                    question="repair",
                    content=proposal,
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
                            "executor_kind": "coding",
                            "expected_action": "write_file",
                            "model_goal_id": worker.model_goal_id,
                        }
                    }
                }
                state.data["cognitive_increment"] = increment.to_dict()
                marker = object()
                with patch.object(resident, "_accept_borrowed_increment", return_value=None), patch.object(
                    resident, "_return_to_investigation_after_rejection", return_value=marker
                ):
                    result = resident._cognition_integration_step(event, state, readiness=None)
                self.assertIs(result, marker)
                rejected = ledger.worker_run(worker.worker_run_id)
                assert rejected is not None
                self.assertEqual(rejected.verification_status, "schema_rejected")
                self.assertEqual(rejected.model_route_id, "only-route")
                self.assertIn(
                    "acceptance.expected_text must exactly equal action.content",
                    rejected.error or "",
                )
                self.assertEqual(target.read_text(encoding="utf-8"), "print('before')\n")
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
