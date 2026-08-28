from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


@unittest.skipUnless(os.name == "nt", "missing-file restore application is Windows-only")
class WorkRestorePrepareContinuityTests(unittest.TestCase):
    @staticmethod
    def _capture_restore_point(resident, ledger, target: Path):
        thread = ledger.create_thread(thread_id="restore-prepare-continuity")
        _, event = ledger.start(
            thread.thread_id,
            "retain the exact old file before overwrite",
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

    def test_prepare_after_restart_reuses_same_pending_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.bin"
            target.write_bytes(b"\x00retained-before-restart\xff")

            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            thread_id, restore_point_id = self._capture_restore_point(
                resident, ledger, target
            )
            control = RestoreAwareWorkControl(ledger)
            target.unlink()
            first = control.prepare_missing_restore(thread_id, restore_point_id)
            self.assertEqual(first["status"], "approval_required")
            first_id = first["application_id"]
            resident.store.close()

            restarted = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            try:
                restarted_control = RestoreAwareWorkControl(
                    RecoveryBoundedWorkLedger(restarted)
                )
                resumed = restarted_control.prepare_missing_restore(
                    thread_id, restore_point_id
                )
                self.assertEqual(resumed["application_id"], first_id)
                self.assertEqual(resumed["status"], "approval_required")
                self.assertTrue(resumed["requires_user_approval"])
                self.assertFalse(target.exists())

                completed = restarted_control.approve_missing_restore(
                    thread_id, resumed["application_id"]
                )
                self.assertEqual(completed["status"], "completed")
                self.assertEqual(target.read_bytes(), b"\x00retained-before-restart\xff")
            finally:
                restarted.store.close()


if __name__ == "__main__":
    unittest.main()
