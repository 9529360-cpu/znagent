from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger


class WorkRestorePointActiveRunTests(unittest.TestCase):
    def test_finalized_work_run_cannot_authorize_new_restore_capture_or_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            thread = ledger.create_thread(thread_id="restore-finalized-run")
            _, event = ledger.start(
                thread.thread_id,
                "replace file from an active Work run only",
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
                    "content": "new",
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
            with sqlite3.connect(store_path) as conn:
                conn.execute(
                    "UPDATE work_runs SET ledger_state='finalized', finalized_at=? WHERE event_id=?",
                    ("2026-08-28T00:00:00+00:00", event.event_id),
                )
                conn.commit()
            try:
                with self.assertRaisesRegex(
                    RuntimeError,
                    "conflicts with active durable Work linkage",
                ):
                    resident._native_action_step(event, state, readiness=None)
                self.assertEqual(target.read_text(encoding="utf-8"), "old")
                self.assertEqual(
                    resident.retained_work_restore_points(event.event_id), []
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
