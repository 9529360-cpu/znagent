from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_control import ResidentWorkControl


class WorkRestoreProposalTests(unittest.TestCase):
    @staticmethod
    def _capture_restore_point(resident, ledger, target: Path):
        thread = ledger.create_thread(thread_id="restore-proposal-work")
        _, event = ledger.start(
            thread.thread_id,
            "prepare one exact file overwrite",
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
                raise SystemExit("captured restore point")
            return original_act(kind, event_id=event_id, **args)

        resident.body.act = stop_before_dispatch
        try:
            with unittest.TestCase().assertRaisesRegex(SystemExit, "captured restore point"):
                resident._native_action_step(event, state, readiness=None)
        finally:
            resident.body.act = original_act
        return thread.thread_id, event.event_id

    @staticmethod
    def _proposal(control: ResidentWorkControl, thread_id: str):
        thread, _ = control.get_snapshot(thread_id)
        points = thread.metadata["restore_points"]
        assert len(points) == 1
        return points[0], points[0]["restore_proposal"]

    def test_restore_proposal_tracks_reality_without_granting_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "document.txt"
            target.write_text("old private bytes", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            thread_id, event_id = self._capture_restore_point(resident, ledger, target)
            control = ResidentWorkControl(ledger)
            try:
                point, proposal = self._proposal(control, thread_id)
                self.assertEqual(point["event_id"], event_id)
                self.assertEqual(point["current_status"], "unchanged")
                self.assertEqual(proposal["kind"], "restore_exact_file")
                self.assertEqual(proposal["status"], "candidate")
                self.assertTrue(proposal["destructive"])
                self.assertTrue(proposal["requires_user_approval"])
                self.assertTrue(proposal["requires_fresh_revalidation"])
                self.assertFalse(proposal["application_available"])
                self.assertFalse(proposal["automatic_authority"])
                self.assertFalse(point["restore_application_available"])
                self.assertFalse(point["automatic_restore_authority"])

                target.write_text("external changed reality", encoding="utf-8")
                _, changed = self._proposal(control, thread_id)
                self.assertEqual(changed["status"], "conflict_review_required")
                self.assertFalse(changed["application_available"])

                target.unlink()
                _, missing = self._proposal(control, thread_id)
                self.assertEqual(missing["status"], "missing_target_review_required")
                self.assertFalse(missing["application_available"])

                target.mkdir()
                point, blocked = self._proposal(control, thread_id)
                self.assertEqual(point["current_status"], "unsupported")
                self.assertEqual(blocked["status"], "blocked")
                self.assertFalse(blocked["application_available"])

                encoded = json.dumps(point, sort_keys=True)
                for private_name in (
                    "content",
                    "content_sha256",
                    "action_signature",
                    "intent_id",
                    "message_id",
                    "pre_identity_json",
                ):
                    self.assertNotIn(private_name, encoded)
                self.assertNotIn("old private bytes", encoded)
                self.assertTrue(target.is_dir())
            finally:
                resident.store.close()

    def test_restore_proposal_is_rederived_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old state", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            thread_id, _ = self._capture_restore_point(resident, ledger, target)
            resident.store.close()

            target.write_text("changed after restart", encoding="utf-8")
            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            try:
                control = ResidentWorkControl(RecoveryBoundedWorkLedger(restored))
                point, proposal = self._proposal(control, thread_id)
                self.assertEqual(point["current_status"], "changed")
                self.assertEqual(proposal["status"], "conflict_review_required")
                self.assertTrue(proposal["requires_user_approval"])
                self.assertTrue(proposal["requires_fresh_revalidation"])
                self.assertFalse(proposal["application_available"])
                self.assertEqual(target.read_text(encoding="utf-8"), "changed after restart")
            finally:
                restored.store.close()

    def test_restore_proposal_rejects_forged_work_ownership(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old state", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            thread_id, event_id = self._capture_restore_point(resident, ledger, target)
            control = ResidentWorkControl(ledger)
            try:
                with sqlite3.connect(store_path) as conn:
                    conn.execute(
                        "UPDATE work_restore_points SET message_id=? WHERE event_id=?",
                        ("forged-message", event_id),
                    )
                    conn.commit()
                with self.assertRaisesRegex(RuntimeError, "conflicts with its Work ownership"):
                    control.get_snapshot(thread_id)
                self.assertEqual(target.read_text(encoding="utf-8"), "old state")
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
