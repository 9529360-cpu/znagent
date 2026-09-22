from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.action_authority import (
    ActionAuthorityContext,
    WorkerActionAuthorityEnforcer,
    bind_worker_authority_arg,
)
from zn_agent.core.provider_bridge import build_resident_runtime


class WorkerActionAuthorityTests(unittest.TestCase):
    def _resident_with_context(
        self,
        root: Path,
        *,
        executor_kind: str,
        expected_action: str,
        tool_scope: tuple[str, ...],
        authority_scope: tuple[str, ...],
    ):
        workspace = root / "workspace"
        workspace.mkdir(exist_ok=True)
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=root / "kernel.db",
        )
        ledger = resident.work_ledger
        thread_id = f"authority-{executor_kind}"
        ledger.create_thread(thread_id=thread_id, title="Worker authority")
        ledger.attach_workspace(thread_id, workspace, name="Workspace")
        _, event = ledger.start(
            thread_id,
            "Exercise capability-bound worker authority",
            acceptance_criteria=["bounded action is independently observable"],
            payload={"workspace_path": str(workspace)},
        )
        root_item = ledger.work_item_for_event(event.event_id)
        assert root_item is not None
        child = ledger.create_child_item(
            root_work_item_id=root_item.work_item_id,
            objective="Exercise one bounded capability",
            acceptance_criteria=["capability-scoped worker evidence"],
            title="Capability worker",
        )
        worker = ledger.start_worker_run(
            work_item_id=child.work_item_id,
            executor_kind=executor_kind,
            tool_scope=tool_scope,
            authority_scope=authority_scope,
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

    def test_read_only_scope_cannot_mutate_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident, event, workspace, context = self._resident_with_context(
                root,
                executor_kind="evidence-reader",
                expected_action="read_file",
                tool_scope=("workspace.read",),
                authority_scope=("workspace_read",),
            )
            target = workspace / "must-not-write.txt"
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
                self.assertIn("outside the admitted action contract", result.error or "")
                self.assertFalse(target.exists())
            finally:
                resident.store.close()

    def test_write_scope_is_role_agnostic_but_workspace_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident, event, workspace, context = self._resident_with_context(
                root,
                executor_kind="arbitrary-capability-worker",
                expected_action="write_file",
                tool_scope=("workspace.read", "workspace.write"),
                authority_scope=("workspace_read", "workspace_write"),
            )
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

    def test_terminal_authority_depends_on_capability_not_worker_role_name(self) -> None:
        command = "python -V"
        context = ActionAuthorityContext(
            work_thread_id="thread-capability",
            work_item_id="item-capability",
            worker_run_id="worker-capability",
            plan_version=1,
            executor_kind="independent-verifier",
            expected_action="run_python",
            tool_scope=("terminal.test",),
            authority_scope=("terminal_verify",),
            workspace_root=None,
            allowed_command_sha256=ActionAuthorityContext.command_digest(command),
        )
        WorkerActionAuthorityEnforcer.authorize(
            "command",
            {"command": command},
            context,
        )

    def test_stale_plan_context_is_rejected_at_body_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident, event, workspace, context = self._resident_with_context(
                root,
                executor_kind="workspace-writer",
                expected_action="write_file",
                tool_scope=("workspace.write",),
                authority_scope=("workspace_write",),
            )
            target = workspace / "stale.txt"
            try:
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
