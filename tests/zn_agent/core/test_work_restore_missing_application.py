from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


@unittest.skipUnless(os.name == "nt", "missing-file restore application is Windows-only")
class WorkRestoreMissingApplicationTests(unittest.TestCase):
    @staticmethod
    def _capture_restore_point(resident, ledger, target: Path):
        thread = ledger.create_thread(thread_id=f"restore-missing-{target.parent.name}")
        _, event = ledger.start(
            thread.thread_id,
            "prepare exact overwrite so the old file can be retained",
            payload={"required_capabilities": ["filesystem"]},
        )
        claimed = resident.store.claim_event(event.event_id)
        assert claimed is not None
        intent = NativeActionIntent(
            intent_id=f"intent-{event.event_id}",
            event_id=event.event_id,
            kind="write_text",
            args={
                "path": str(target),
                "content": "new state",
                "append": False,
                "create_parents": True,
            },
            source="native_deliberation",
        )
        state = WorkingState(
            current_event_id=event.event_id,
            stage="native_action",
            next_action="move body: write_text",
            data={"native_action_intent": intent.to_dict()},
        )
        resident.store.save_working_state(state)

        original_act = resident.body.act

        def stop_before_dispatch(kind: str, *, event_id=None, **args):
            if str(kind).lower() in {"write_text", "write_file"}:
                raise SystemExit("restore point captured before mutation")
            return original_act(kind, event_id=event_id, **args)

        resident.body.act = stop_before_dispatch
        try:
            with unittest.TestCase().assertRaisesRegex(
                SystemExit, "restore point captured before mutation"
            ):
                resident._native_action_step(event, state, readiness=None)
        finally:
            resident.body.act = original_act

        points = resident.retained_work_restore_points(event.event_id)
        assert len(points) == 1
        return thread.thread_id, points[0]["restore_point_id"]

    def test_rpc_explicit_approval_restores_exact_binary_bytes_to_missing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "document.bin"
            old_bytes = b"\xff\x00old-private-bytes\r\n"
            target.write_bytes(old_bytes)
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=root / "kernel.db"
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            thread_id, restore_point_id = self._capture_restore_point(
                resident, ledger, target
            )
            server = ResidentRpcServer(resident=resident)
            try:
                self.assertIsInstance(server.work_control, RestoreAwareWorkControl)
                target.unlink()
                thread, _ = server.work_control.get_snapshot(thread_id)
                proposal = thread.metadata["restore_points"][0]["restore_proposal"]
                self.assertEqual(proposal["status"], "missing_target_review_required")
                self.assertTrue(proposal["application_available"])
                self.assertEqual(proposal["application_scope"], "missing_target_no_replace")
                self.assertTrue(proposal["requires_user_approval"])

                prepare_response = server.handle(
                    {
                        "id": "restore-prepare",
                        "method": "work_restore_prepare",
                        "params": {
                            "thread_id": thread_id,
                            "restore_point_id": restore_point_id,
                        },
                    }
                )
                self.assertTrue(prepare_response["ok"])
                prepared = prepare_response["result"]
                self.assertEqual(prepared["status"], "approval_required")
                self.assertTrue(prepared["requires_user_approval"])
                self.assertFalse(target.exists())
                self.assertNotIn("content_sha256", prepared)

                approve_response = server.handle(
                    {
                        "id": "restore-approve",
                        "method": "work_restore_approve",
                        "params": {
                            "thread_id": thread_id,
                            "application_id": prepared["application_id"],
                        },
                    }
                )
                self.assertTrue(approve_response["ok"])
                completed = approve_response["result"]
                self.assertEqual(completed["status"], "completed")
                self.assertFalse(completed["requires_user_approval"])
                self.assertEqual(target.read_bytes(), old_bytes)
            finally:
                resident.store.close()

    def test_target_that_reappears_after_preparation_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "document.txt"
            target.write_bytes(b"retained old state")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=root / "kernel.db"
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            thread_id, restore_point_id = self._capture_restore_point(
                resident, ledger, target
            )
            control = RestoreAwareWorkControl(ledger)
            try:
                target.unlink()
                prepared = control.prepare_missing_restore(thread_id, restore_point_id)
                target.write_bytes(b"external winner")

                with self.assertRaisesRegex(RuntimeError, "no longer missing"):
                    control.approve_missing_restore(
                        thread_id, prepared["application_id"]
                    )

                self.assertEqual(target.read_bytes(), b"external winner")
                inspected = control.restore_application(prepared["application_id"])
                self.assertEqual(inspected["status"], "blocked")
                self.assertFalse(inspected["requires_user_approval"])
            finally:
                resident.store.close()

    def test_missing_parent_is_not_recreated_by_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            target = workspace / "document.txt"
            target.write_bytes(b"retained old state")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=root / "kernel.db"
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            thread_id, restore_point_id = self._capture_restore_point(
                resident, ledger, target
            )
            control = RestoreAwareWorkControl(ledger)
            try:
                target.unlink()
                prepared = control.prepare_missing_restore(thread_id, restore_point_id)
                workspace.rmdir()

                with self.assertRaisesRegex(RuntimeError, "parent directory changed"):
                    control.approve_missing_restore(
                        thread_id, prepared["application_id"]
                    )

                self.assertFalse(workspace.exists())
                inspected = control.restore_application(prepared["application_id"])
                self.assertEqual(inspected["status"], "blocked")
            finally:
                resident.store.close()

    def test_restart_recovers_move_that_completed_before_final_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.bin"
            old_bytes = b"\x00\xfecrash-safe-old-state\n"
            target.write_bytes(old_bytes)
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            thread_id, restore_point_id = self._capture_restore_point(
                resident, ledger, target
            )
            control = RestoreAwareWorkControl(ledger)
            target.unlink()
            prepared = control.prepare_missing_restore(thread_id, restore_point_id)
            application_id = prepared["application_id"]

            try:
                with patch.object(
                    resident,
                    "_verify_restored_target",
                    side_effect=SystemExit("crash after namespace move"),
                ):
                    with self.assertRaisesRegex(SystemExit, "crash after namespace move"):
                        control.approve_missing_restore(thread_id, application_id)
                self.assertEqual(target.read_bytes(), old_bytes)
                interrupted = control.restore_application(application_id)
                self.assertEqual(interrupted["status"], "commit_started")
            finally:
                resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            try:
                restored_control = RestoreAwareWorkControl(
                    RecoveryBoundedWorkLedger(restored)
                )
                recovered = restored_control.restore_application(application_id)
                self.assertEqual(recovered["status"], "completed")
                self.assertEqual(target.read_bytes(), old_bytes)
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main()
