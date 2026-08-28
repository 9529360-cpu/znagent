from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.file_identity import observe_file_identity as real_observe_file_identity
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger


class WorkRestorePointGuardTests(unittest.TestCase):
    @staticmethod
    def _intent(event_id: str, target: Path, content: str = "new state") -> NativeActionIntent:
        return NativeActionIntent(
            intent_id=f"intent-{event_id}",
            event_id=event_id,
            kind="write_text",
            args={
                "path": str(target),
                "content": content,
                "append": False,
                "create_parents": True,
            },
            source="native_deliberation",
        )

    @staticmethod
    def _state(event_id: str, intent: NativeActionIntent) -> WorkingState:
        return WorkingState(
            current_event_id=event_id,
            stage="native_action",
            next_action="move body: write_text",
            data={"native_action_intent": intent.to_dict()},
        )

    def test_capture_identity_drift_withdraws_mutation_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old stable state", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            thread = ledger.create_thread(thread_id="restore-capture-drift")
            _, event = ledger.start(
                thread.thread_id,
                "replace exact file only from stable current reality",
                payload={"required_capabilities": ["filesystem"]},
            )
            claimed = resident.store.claim_event(event.event_id)
            assert claimed is not None
            intent = self._intent(event.event_id, target)
            state = self._state(event.event_id, intent)
            resident.store.save_working_state(state)

            changed = False

            def drift_then_observe(value, *, max_hash_bytes):
                nonlocal changed
                if not changed:
                    target.write_text("external winner", encoding="utf-8")
                    changed = True
                return real_observe_file_identity(value, max_hash_bytes=max_hash_bytes)

            try:
                with patch(
                    "zn_agent.core.work_restore_point_resident.observe_file_identity",
                    side_effect=drift_then_observe,
                ):
                    result = resident._native_action_step(event, state, readiness=None)
                self.assertIsNone(result)
                held = resident.store.get_working_state()
                self.assertEqual(held.stage, "native_investigation")
                self.assertEqual(
                    held.data["work_restore_point_capture"]["status"],
                    "identity_changed",
                )
                self.assertEqual(
                    target.read_text(encoding="utf-8"),
                    "external winner",
                )
                self.assertEqual(
                    resident.retained_work_restore_points(event.event_id), []
                )
                writes = [
                    item
                    for item in resident.body.recent_actions(40)
                    if item.event_id == event.event_id
                    and item.kind in {"write_text", "write_file"}
                ]
                self.assertEqual(writes, [])
            finally:
                resident.store.close()

    def test_forged_work_payload_without_durable_run_cannot_create_restore_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            RecoveryBoundedWorkLedger(resident)
            event = resident.enqueue(
                "forged Work linkage must not own restore bytes",
                payload={
                    "required_capabilities": ["filesystem"],
                    "work_thread_id": "thread-forged",
                    "work_message_id": "msg-forged",
                },
            )
            claimed = resident.store.claim_event(event.event_id)
            assert claimed is not None
            intent = self._intent(event.event_id, target)
            state = self._state(event.event_id, intent)
            resident.store.save_working_state(state)
            try:
                with self.assertRaisesRegex(
                    RuntimeError,
                    "cannot find its durable Work run",
                ):
                    resident._native_action_step(event, state, readiness=None)
                self.assertEqual(
                    resident.retained_work_restore_points(event.event_id), []
                )
                self.assertEqual(target.read_text(encoding="utf-8"), "old")
                writes = [
                    item
                    for item in resident.body.recent_actions(40)
                    if item.event_id == event.event_id
                    and item.kind in {"write_text", "write_file"}
                ]
                self.assertEqual(writes, [])
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
