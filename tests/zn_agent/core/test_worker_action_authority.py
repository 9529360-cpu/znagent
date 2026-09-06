from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.action import NativeActionIntent
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
            payload={"workspace_path": str(workspace)},
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

    def test_active_action_cycle_derives_thread_identity_from_durable_work_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident, event, workspace, context = self._resident_with_worker(
                root,
                "coding",
                "write_file",
            )
            target = workspace / "cycle-bound.txt"
            try:
                state = resident.store.get_working_state()
                state.current_event_id = event.event_id
                state.data[resident._DELEGATED_PENDING_KEY] = {
                    "worker_run_id": context.worker_run_id,
                    "work_item_id": context.work_item_id,
                    "expected_action": context.expected_action,
                }
                intent = NativeActionIntent(
                    intent_id="authority-cycle-binding",
                    event_id=event.event_id,
                    kind="write_text",
                    args={"path": str(target), "content": "bound"},
                    expected_outcome={
                        "kind": "text_equals",
                        "path": str(target),
                        "expected_text": "bound",
                    },
                    source="resident_broad_goal_choice",
                )

                resident._begin_native_action_cycle(event, state, intent)
                resident.store.save_working_state(state)

                persisted = resident.store.get_working_state()
                raw_intent = persisted.data.get("native_action_intent")
                self.assertIsInstance(raw_intent, dict)
                authority = raw_intent["args"]["__zn_authority_context"]
                self.assertEqual(authority["work_thread_id"], context.work_thread_id)
                self.assertEqual(authority["work_item_id"], context.work_item_id)
                self.assertEqual(authority["worker_run_id"], context.worker_run_id)
                self.assertEqual(authority["plan_version"], context.plan_version)
                self.assertEqual(authority["workspace_root"], str(workspace))
            finally:
                resident.store.close()

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
                # The gate reads the current durable plan immediately before the
                # real effect. This regression isolates that race deterministically;
                # active-steering E2E separately proves how the version advances.
                with patch.object(
                    resident.work_ledger,
                    "plan_version",
                    return_value=context.plan_version + 1,
                ):
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
