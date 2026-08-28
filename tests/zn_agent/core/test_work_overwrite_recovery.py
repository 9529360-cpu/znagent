from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class OverwriteRecoveryTests(unittest.TestCase):
    @staticmethod
    def _prepare_overwrite(resident, target: Path, content: str):
        event = resident.enqueue(
            "replace the file with the requested exact text",
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
                "content": content,
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
        return event, state

    @staticmethod
    def _attempts(store_path: Path, event_id: str):
        with closing(sqlite3.connect(store_path)) as conn:
            return conn.execute(
                "SELECT attempt_id,status,result_action_id,result_success "
                "FROM resident_side_effect_attempts WHERE event_id=? "
                "ORDER BY started_at ASC",
                (event_id,),
            ).fetchall()

    @staticmethod
    def _crash_after_real_write(resident):
        original = resident.body._write_text

        def write_then_crash(action, started):
            original(action, started)
            raise SystemExit("simulate process death after overwrite reached filesystem")

        resident.body._write_text = write_then_crash

    def test_restart_observes_completed_overwrite_and_never_replays_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old", encoding="utf-8")
            intended = "new exact state"

            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            event, state = self._prepare_overwrite(resident, target, intended)
            self._crash_after_real_write(resident)
            try:
                with self.assertRaises(SystemExit):
                    resident._native_action_step(event, state, readiness=None)
                self.assertEqual(target.read_text(encoding="utf-8"), intended)
                attempts = self._attempts(store_path, event.event_id)
                self.assertEqual(len(attempts), 1)
                self.assertEqual(attempts[0][1], "started")
            finally:
                resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            try:
                restored_event = restored.store.get_event(event.event_id)
                self.assertIsNotNone(restored_event)
                assert restored_event is not None
                restored_state = restored.store.get_working_state()
                self.assertEqual(restored_state.stage, "native_action")

                self.assertIsNone(
                    restored._native_action_step(
                        restored_event,
                        restored_state,
                        readiness=None,
                    )
                )
                recovery_state = restored.store.get_working_state()
                self.assertEqual(recovery_state.stage, "side_effect_recovery")
                recovery = recovery_state.data["side_effect_recovery"]
                self.assertEqual(recovery["recovery_policy"], "overwrite_effect_only")
                self.assertEqual(recovery["decision"], "reverify_effect")
                self.assertTrue(recovery["replay_blocked"])

                result = restored._side_effect_recovery_step(
                    restored_event,
                    recovery_state,
                    readiness=None,
                )
                self.assertIsNotNone(result)
                assert result is not None
                self.assertTrue(result.success)
                self.assertIn("without replaying", result.reason)
                self.assertEqual(target.read_text(encoding="utf-8"), intended)

                attempts = self._attempts(store_path, event.event_id)
                self.assertEqual(len(attempts), 1)
                self.assertEqual(attempts[0][1], "verified_effect")
                writes = [
                    item
                    for item in restored.body.recent_actions(40)
                    if item.event_id == event.event_id and item.kind == "write_text"
                ]
                self.assertEqual(writes, [])
            finally:
                restored.store.close()

    def test_restart_refuses_overwrite_when_current_file_changed_after_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old", encoding="utf-8")
            intended = "resident intended state"
            external = "user changed this after the crash"

            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            event, state = self._prepare_overwrite(resident, target, intended)
            self._crash_after_real_write(resident)
            try:
                with self.assertRaises(SystemExit):
                    resident._native_action_step(event, state, readiness=None)
                self.assertEqual(target.read_text(encoding="utf-8"), intended)
            finally:
                resident.store.close()

            target.write_text(external, encoding="utf-8")

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            try:
                restored_event = restored.store.get_event(event.event_id)
                self.assertIsNotNone(restored_event)
                assert restored_event is not None
                restored_state = restored.store.get_working_state()

                self.assertIsNone(
                    restored._native_action_step(
                        restored_event,
                        restored_state,
                        readiness=None,
                    )
                )
                recovery_state = restored.store.get_working_state()
                self.assertEqual(recovery_state.stage, "side_effect_recovery")

                self.assertIsNone(
                    restored._side_effect_recovery_step(
                        restored_event,
                        recovery_state,
                        readiness=None,
                    )
                )
                held = restored.store.get_working_state()
                self.assertEqual(held.stage, "side_effect_recovery")
                recovery = held.data["side_effect_recovery"]
                self.assertEqual(recovery["decision"], "user_decision_required")
                self.assertTrue(recovery["replay_blocked"])
                self.assertIn("replay is forbidden", recovery["reason"])
                self.assertEqual(target.read_text(encoding="utf-8"), external)
                attempts = self._attempts(store_path, event.event_id)
                self.assertEqual(len(attempts), 1)
                self.assertEqual(attempts[0][1], "started")
                writes = [
                    item
                    for item in restored.body.recent_actions(40)
                    if item.event_id == event.event_id and item.kind == "write_text"
                ]
                self.assertEqual(writes, [])
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main()
