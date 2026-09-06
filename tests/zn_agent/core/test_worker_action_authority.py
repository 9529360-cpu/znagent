from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action_authority import ActionAuthorityContext, bind_worker_authority_arg
from zn_agent.core.provider_bridge import build_resident_runtime


class WorkerActionAuthorityTests(unittest.TestCase):
    def _resident_with_worker(self, root: Path, executor_kind: str, expected_action: str):
        workspace = root / "workspace"
        workspace.mkdir(exist_ok=True)
        resident = build_resident_runtime(config={"model": {}}, store_path=root / "kernel.db")
        ledger = resident.work_ledger
        thread_id = f"authority-{executor_kind}"
        ledger.create_thread(thread_id=thread_id, title="Worker authority")
        ledger.attach_workspace(thread_id, workspace, name="Workspace")
        _, event = ledger.start(
            thread_id,
            "Exercise bounded worker authority",
            acceptance_criteria=["bounded action is independently observable"],
        )
        root_item = ledger.work_item_for_event(event.event_id)
        assert root_item is not None
        child = ledger.create_child_item(
            root_work_item_id=root_item.work_item_id,
            objective=f"{executor_kind} bounded action",
            acceptance_criteria=[f"delegated_worker_evidence: {executor_kind}/{expected_action}"],
            title=f"{executor_kind} worker",
        )
        profile = resident._WORKER_SCOPE_PROFILES[executor_kind]
        worker = ledger.start_worker_run(
            work_item_id=child.work_item_id,
            executor_kind=executor_kind,
            tool_scope=profile["tool_scope"],
            authority_scope=profile["authority_scope"],
        )
        context = ActionAuthorityContext(
            work_thread_id=thread_id,
            work_item_id=child.work_item_id,
            worker_run_id=worker.worker_run_id,
            plan_version=worker.plan_version,
            executor_kind=executor_kind,
            expected_action=expected_action,
            tool_scope=tuple(worker.tool_scope),
            authority_scope=tuple(worker.authority_scope),
            workspace_root=str(workspace),
        )
        return resident, event, workspace, context

    def test_review_worker_cannot_mutate_workspace_through_low_level_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident, event, workspace, context = self._resident_with_worker(root, "review", "run_python")
            target = workspace / "review-must-not-write.txt"
            try:
                result = resident.body.act(
                    "write_text",
                    event_id=event.event_id,
                    **bind_worker_authority_arg(
                        {"path": str(target), "content": "forbidden"},
                        context,
                    ),
                )
                self.assertFalse(result.success)
                self.assertIn("not authorized for workspace mutation", result.error or "")
                self.assertFalse(target.exists())
                audited = resident.body.recent_actions(limit=5)
                self.assertTrue(any(item.action_id == result.action_id and not item.success for item in audited))
            finally:
                resident.store.close()

    def test_research_worker_cannot_mutate_workspace_through_low_level_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident, event, workspace, context = self._resident_with_worker(root, "research", "research_page")
            target = workspace / "research-must-not-write.txt"
            try:
                result = resident.body.act(
                    "write_file",
                    event_id=event.event_id,
                    **bind_worker_authority_arg(
                        {"path": str(target), "content": "forbidden"},
                        context,
                    ),
                )
                self.assertFalse(result.success)
                self.assertFalse(target.exists())
            finally:
                resident.store.close()

    def test_coding_worker_can_write_only_inside_attached_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident, event, workspace, context = self._resident_with_worker(root, "coding", "write_file")
            inside = workspace / "allowed.txt"
            outside = root / "outside.txt"
            try:
                allowed = resident.body.act(
                    "write_text",
                    event_id=event.event_id,
                    **bind_worker_authority_arg(
                        {"path": str(inside), "content": "allowed"},
                        context,
                    ),
                )
                self.assertTrue(allowed.success, allowed.error)
                self.assertEqual(inside.read_text(encoding="utf-8"), "allowed")

                denied = resident.body.act(
                    "write_text",
                    event_id=event.event_id,
                    **bind_worker_authority_arg(
                        {"path": str(outside), "content": "escape"},
                        context,
                    ),
                )
                self.assertFalse(denied.success)
                self.assertIn("outside the attached workspace", denied.error or "")
                self.assertFalse(outside.exists())
            finally:
                resident.store.close()

    def test_stale_plan_context_is_rejected_at_body_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident, event, workspace, context = self._resident_with_worker(root, "coding", "write_file")
            target = workspace / "stale.txt"
            try:
                # Re-steering advances the durable plan while the already-built
                # action context remains tied to the previous version.
                resident.work_ledger.steer(
                    context.work_thread_id,
                    "Newer user direction supersedes the old worker action",
                )
                denied = resident.body.act(
                    "write_text",
                    event_id=event.event_id,
                    **bind_worker_authority_arg(
                        {"path": str(target), "content": "stale"},
                        context,
                    ),
                )
                self.assertFalse(denied.success)
                self.assertIn("stale Work plan", denied.error or "")
                self.assertFalse(target.exists())
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
