from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action_authority import (
    ActionAuthorityContext,
    bind_worker_authority_arg,
)
from zn_agent.core.provider_bridge import build_resident_runtime


class DelegatedSideEffectRestartRecoveryTests(unittest.TestCase):
    def test_scope_admitted_worker_cannot_blindly_replay_uncertain_command_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            workspace = root_dir / "workspace"
            workspace.mkdir()
            db = root_dir / "kernel.db"
            command = 'python -c "print(\'once\')"'
            action_args = {
                "command": command,
                "workdir": str(workspace),
            }

            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="delegated-sidefx", title="Delegated side effect")
                ledger.attach_workspace("delegated-sidefx", workspace, name="Workspace")
                _, event = ledger.start(
                    "delegated-sidefx",
                    "Implement and run the bounded workspace change once.",
                    acceptance_criteria=["command result independently verified"],
                )
                root = ledger.work_item_for_event(event.event_id)
                assert root is not None
                child = ledger.create_child_item(
                    root_work_item_id=root.work_item_id,
                    objective="Run the admitted Python verification once",
                    acceptance_criteria=["delegated_worker_evidence: coding/run_python"],
                )
                worker = ledger.start_worker_run(
                    work_item_id=child.work_item_id,
                    executor_kind="coding",
                    tool_scope=("workspace.read", "terminal.python"),
                    authority_scope=("workspace_read", "terminal_execute"),
                )
                worker = ledger.complete_worker_run(
                    worker.worker_run_id,
                    result_summary="scope-admitted command proposal",
                    claimed_completion=False,
                    verification_status="scope_admitted",
                )
                self.assertEqual(worker.state, "completed")
                self.assertEqual(worker.verification_status, "scope_admitted")

                signature = resident.body._signature_hash("command", action_args)
                attempt_id = f"sidefx-delegated-{worker.worker_run_id}"
                resident.body._start_attempt(
                    attempt_id=attempt_id,
                    event_id=event.event_id,
                    kind="command",
                    signature_hash=signature,
                )
                self.assertEqual(len(resident.body.uncertain_attempts(event.event_id)), 1)
                event_id = event.event_id
                worker_id = worker.worker_run_id
                child_id = child.work_item_id
                plan_version = worker.plan_version
            finally:
                resident.store.close()

            restored = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                persisted = restored.work_ledger.worker_run(worker_id)
                self.assertIsNotNone(persisted)
                assert persisted is not None
                self.assertEqual(persisted.state, "completed")
                self.assertEqual(persisted.verification_status, "scope_admitted")

                authority = ActionAuthorityContext(
                    work_thread_id="delegated-sidefx",
                    work_item_id=child_id,
                    worker_run_id=worker_id,
                    plan_version=plan_version,
                    executor_kind="coding",
                    expected_action="run_python",
                    tool_scope=tuple(persisted.tool_scope),
                    authority_scope=tuple(persisted.authority_scope),
                    workspace_root=str(workspace),
                    allowed_command_sha256=ActionAuthorityContext.command_digest(command),
                )
                blocked = restored.body.act(
                    "command",
                    event_id=event_id,
                    **bind_worker_authority_arg(action_args, authority),
                )
                self.assertFalse(blocked.success)
                self.assertTrue(blocked.data.get("side_effect_uncertain"))
                self.assertTrue(blocked.data.get("replay_blocked"))
                self.assertIn("refusing blind replay", blocked.error or "")

                after = restored.work_ledger.worker_run(worker_id)
                self.assertIsNotNone(after)
                assert after is not None
                self.assertEqual(after.state, "completed")
                self.assertEqual(after.verification_status, "scope_admitted")
                child_after = restored.work_ledger._work_item_by_id(child_id)
                self.assertIsNotNone(child_after)
                assert child_after is not None
                self.assertEqual(child_after.status, "running")
                self.assertEqual(len(restored.body.uncertain_attempts(event_id)), 1)
                self.assertEqual(
                    len(restored.work_ledger.list_worker_runs(thread_id="delegated-sidefx")),
                    1,
                )
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
