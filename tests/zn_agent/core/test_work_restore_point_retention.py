from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger


class WorkRestorePointRetentionTests(unittest.TestCase):
    def test_capacity_blocks_new_overwrite_without_deleting_retained_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old current value", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            thread = ledger.create_thread(thread_id="restore-capacity-work")
            _, event = ledger.start(
                thread.thread_id,
                "replace exact file only if rollback retention is safe",
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
                    "content": "new value",
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
            with closing(sqlite3.connect(store_path)) as conn:
                conn.execute(
                    """
                    INSERT INTO work_restore_points(
                        restore_point_id,version,event_id,thread_id,message_id,intent_id,
                        action_signature,target_path,pre_identity_json,content,content_sha256,
                        size_bytes,status,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        "restore-retained-only-copy",
                        1,
                        "older-event",
                        "older-thread",
                        "older-message",
                        "older-intent",
                        "older-signature",
                        str(root / "older.txt"),
                        "{}",
                        sqlite3.Binary(b"x"),
                        "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881",
                        1,
                        "retained",
                        "2026-08-28T00:00:00+00:00",
                        "2026-08-28T00:00:00+00:00",
                    ),
                )
                conn.commit()
            try:
                with patch(
                    "zn_agent.core.work_restore_point_resident._MAX_TOTAL_POINTS",
                    1,
                ):
                    result = resident._native_action_step(event, state, readiness=None)
                self.assertIsNone(result)
                held = resident.store.get_working_state()
                self.assertEqual(held.stage, "native_investigation")
                self.assertEqual(
                    held.data["work_restore_point_capture"]["status"],
                    "capacity_blocked",
                )
                self.assertEqual(
                    target.read_text(encoding="utf-8"),
                    "old current value",
                )
                with closing(sqlite3.connect(store_path)) as conn:
                    rows = conn.execute(
                        "SELECT restore_point_id FROM work_restore_points ORDER BY restore_point_id"
                    ).fetchall()
                self.assertEqual(rows, [("restore-retained-only-copy",)])
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
