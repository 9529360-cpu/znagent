from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.staged_text_write import StagedWriteCommitUncertainError


@unittest.skipUnless(os.name == "nt", "Windows atomic overwrite namespace recovery semantics")
class WindowsAtomicOverwriteNamespaceRecoveryTests(unittest.TestCase):
    @staticmethod
    def _work(resident, target: Path, content: str):
        event = resident.enqueue(
            "replace exact text",
            payload={"required_capabilities": ["filesystem"]},
        )
        assert resident.store.claim_event(event.event_id) is not None
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
        return event, state, intent

    @staticmethod
    def _attempt_statuses(db: Path, event_id: str) -> list[str]:
        with closing(sqlite3.connect(db)) as conn:
            rows = conn.execute(
                "SELECT status FROM resident_side_effect_attempts "
                "WHERE event_id=? ORDER BY started_at",
                (event_id,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    @staticmethod
    def _protocol(db: Path, event_id: str) -> dict[str, object] | None:
        with closing(sqlite3.connect(db)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM resident_atomic_overwrite_protocols WHERE event_id=?",
                (event_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def _crash_after_successful_namespace_commit(resident, event, state) -> None:
        from zn_agent.core import staged_text_write

        original = staged_text_write._replace_existing_windows

        def commit_then_crash(target_path: Path, staging: Path, backup: Path) -> None:
            original(target_path, staging, backup)
            raise SystemExit("process death after successful ReplaceFileW")

        with patch(
            "zn_agent.core.staged_text_write._replace_existing_windows",
            side_effect=commit_then_crash,
        ):
            with unittest.TestCase().assertRaises(SystemExit):
                resident._native_action_step(event, state, readiness=None)

    def test_restart_classifies_documented_1177_split_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old durable state", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=db
            )
            event, state, intent = self._work(resident, target, "new complete state")
            staging_path, backup_path = resident.body.atomic_artifact_paths(
                event_id=event.event_id,
                kind=intent.kind,
                args=dict(intent.args),
            )

            def split_1177(target_path: Path, staging: Path, backup: Path) -> None:
                target_path.replace(backup)
                raise StagedWriteCommitUncertainError(
                    "synthetic documented ERROR_UNABLE_TO_MOVE_REPLACEMENT_2",
                    staging_path=staging,
                    backup_path=backup,
                    strategy="replace_file_with_backup",
                    error_code=1177,
                )

            try:
                with patch(
                    "zn_agent.core.staged_text_write._replace_existing_windows",
                    side_effect=split_1177,
                ):
                    self.assertIsNone(
                        resident._native_action_step(event, state, readiness=None)
                    )
                current = resident.store.get_working_state()
                self.assertEqual(current.stage, "side_effect_recovery")
                self.assertFalse(target.exists())
                self.assertEqual(
                    staging_path.read_text(encoding="utf-8"), "new complete state"
                )
                self.assertEqual(
                    backup_path.read_text(encoding="utf-8"), "old durable state"
                )
                self.assertEqual(self._attempt_statuses(db, event.event_id), ["observed"])
                protocol = self._protocol(db, event.event_id)
                self.assertIsNotNone(protocol)
                self.assertEqual(protocol["namespace_commit_started"], 1)
            finally:
                resident.store.close()

            restarted = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=db
            )
            try:
                current = restarted.store.get_working_state()
                self.assertIsNone(
                    restarted._side_effect_recovery_step(
                        event, current, readiness=None
                    )
                )
                held = restarted.store.get_working_state()
                recovery = held.data["side_effect_recovery"]
                evidence = recovery["atomic_commit_namespace"]
                self.assertEqual(
                    evidence["classification"], "replacefile_1177_split_retained"
                )
                self.assertEqual(
                    recovery["decision"], "repair_retained_atomic_namespace_required"
                )
                self.assertTrue(recovery["replay_blocked"])
                self.assertEqual(held.stage, "side_effect_recovery")
                self.assertEqual(held.blocked_by, "outside_world_effect_uncertain")
                self.assertFalse(target.exists())
                self.assertEqual(
                    staging_path.read_text(encoding="utf-8"), "new complete state"
                )
                self.assertEqual(
                    backup_path.read_text(encoding="utf-8"), "old durable state"
                )
                self.assertEqual(self._attempt_statuses(db, event.event_id), ["observed"])
                self.assertIsNotNone(self._protocol(db, event.event_id))
            finally:
                restarted.store.close()

    def test_verified_effect_cleanup_checkpoint_survives_process_death(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old durable state", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=db
            )
            event, state, intent = self._work(resident, target, "new complete state")
            _, backup_path = resident.body.atomic_artifact_paths(
                event_id=event.event_id,
                kind=intent.kind,
                args=dict(intent.args),
            )
            try:
                self._crash_after_successful_namespace_commit(resident, event, state)
                self.assertEqual(
                    target.read_text(encoding="utf-8"), "new complete state"
                )
                self.assertTrue(backup_path.exists())
                self.assertEqual(self._attempt_statuses(db, event.event_id), ["started"])
            finally:
                resident.store.close()

            restarted = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=db
            )
            try:
                current = restarted.store.get_working_state()
                self.assertIsNone(
                    restarted._native_action_step(event, current, readiness=None)
                )
                current = restarted.store.get_working_state()

                original_unlink = Path.unlink

                def crash_before_backup_delete(path: Path, *args, **kwargs):
                    if path == backup_path:
                        raise SystemExit("process death after durable cleanup checkpoint")
                    return original_unlink(path, *args, **kwargs)

                with patch("pathlib.Path.unlink", new=crash_before_backup_delete):
                    with self.assertRaises(SystemExit):
                        restarted._side_effect_recovery_step(
                            event, current, readiness=None
                        )

                checkpoint = restarted.store.get_working_state()
                recovery = checkpoint.data["side_effect_recovery"]
                self.assertEqual(
                    recovery["decision"],
                    "cleanup_verified_atomic_overwrite_artifacts",
                )
                self.assertTrue(recovery["replay_blocked"])
                self.assertEqual(checkpoint.stage, "side_effect_recovery")
                self.assertTrue(backup_path.exists())
                self.assertEqual(
                    self._attempt_statuses(db, event.event_id), ["verified_effect"]
                )
                self.assertIsNotNone(self._protocol(db, event.event_id))
            finally:
                restarted.store.close()

            resumed = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=db
            )
            try:
                checkpoint = resumed.store.get_working_state()
                result = resumed._side_effect_recovery_step(
                    event, checkpoint, readiness=None
                )
                self.assertIsNotNone(result)
                self.assertTrue(result.success)
                completed = resumed.store.get_working_state()
                self.assertEqual(completed.stage, "complete")
                self.assertFalse(backup_path.exists())
                self.assertIsNone(self._protocol(db, event.event_id))
                self.assertEqual(
                    self._attempt_statuses(db, event.event_id), ["verified_effect"]
                )
                self.assertEqual(
                    target.read_text(encoding="utf-8"), "new complete state"
                )
            finally:
                resumed.store.close()

    def test_cleanup_checkpoint_preserves_backup_if_identity_drifts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old durable state", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=db
            )
            event, state, intent = self._work(resident, target, "new complete state")
            _, backup_path = resident.body.atomic_artifact_paths(
                event_id=event.event_id,
                kind=intent.kind,
                args=dict(intent.args),
            )
            try:
                self._crash_after_successful_namespace_commit(resident, event, state)
            finally:
                resident.store.close()

            restarted = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=db
            )
            try:
                current = restarted.store.get_working_state()
                self.assertIsNone(
                    restarted._native_action_step(event, current, readiness=None)
                )
                current = restarted.store.get_working_state()

                original_unlink = Path.unlink

                def crash_before_backup_delete(path: Path, *args, **kwargs):
                    if path == backup_path:
                        raise SystemExit("process death after durable cleanup checkpoint")
                    return original_unlink(path, *args, **kwargs)

                with patch("pathlib.Path.unlink", new=crash_before_backup_delete):
                    with self.assertRaises(SystemExit):
                        restarted._side_effect_recovery_step(
                            event, current, readiness=None
                        )
            finally:
                restarted.store.close()

            backup_path.write_text("external replacement artifact", encoding="utf-8")

            resumed = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=db
            )
            try:
                checkpoint = resumed.store.get_working_state()
                self.assertIsNone(
                    resumed._side_effect_recovery_step(
                        event, checkpoint, readiness=None
                    )
                )
                held = resumed.store.get_working_state()
                recovery = held.data["side_effect_recovery"]
                self.assertEqual(recovery["decision"], "user_decision_required")
                self.assertTrue(recovery["atomic_cleanup_drift"])
                self.assertTrue(backup_path.exists())
                self.assertEqual(
                    backup_path.read_text(encoding="utf-8"),
                    "external replacement artifact",
                )
                self.assertEqual(
                    self._attempt_statuses(db, event.event_id), ["verified_effect"]
                )
                self.assertEqual(
                    target.read_text(encoding="utf-8"), "new complete state"
                )
            finally:
                resumed.store.close()


if __name__ == "__main__":
    unittest.main()
