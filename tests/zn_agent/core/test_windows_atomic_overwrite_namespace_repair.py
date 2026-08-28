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


@unittest.skipUnless(os.name == "nt", "Windows retained namespace repair semantics")
class WindowsAtomicOverwriteNamespaceRepairTests(unittest.TestCase):
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
    def _split_1177(target_path: Path, staging: Path, backup: Path) -> None:
        target_path.replace(backup)
        raise StagedWriteCommitUncertainError(
            "synthetic documented ERROR_UNABLE_TO_MOVE_REPLACEMENT_2",
            staging_path=staging,
            backup_path=backup,
            strategy="replace_file_with_backup",
            error_code=1177,
        )

    def _make_split(self, root: Path):
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
        try:
            with patch(
                "zn_agent.core.staged_text_write._replace_existing_windows",
                side_effect=self._split_1177,
            ):
                self.assertIsNone(resident._native_action_step(event, state, readiness=None))
        finally:
            resident.store.close()
        self.assertFalse(target.exists())
        self.assertEqual(staging_path.read_text(encoding="utf-8"), "new complete state")
        self.assertEqual(backup_path.read_text(encoding="utf-8"), "old durable state")
        self.assertEqual(self._attempt_statuses(db, event.event_id), ["observed"])
        return db, target, event, intent, staging_path, backup_path

    def _checkpoint_repair(self, db: Path, event, intent):
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}}, store_path=db
        )
        try:
            current = resident.store.get_working_state()
            self.assertIsNone(
                resident._side_effect_recovery_step(event, current, readiness=None)
            )
            classified = resident.store.get_working_state()
            self.assertEqual(
                classified.data["side_effect_recovery"]["decision"],
                "repair_retained_atomic_namespace_required",
            )
            self.assertIsNone(
                resident._side_effect_recovery_step(event, classified, readiness=None)
            )
            checkpoint = resident.store.get_working_state()
            recovery = checkpoint.data["side_effect_recovery"]
            self.assertEqual(recovery["decision"], "repair_retained_atomic_namespace")
            self.assertEqual(recovery["status"], "namespace_repair_pending")
            self.assertTrue(recovery["replay_blocked"])
            repair = recovery["atomic_namespace_repair"]
            self.assertEqual(repair["attempt_id"], self._protocol(db, event.event_id)["attempt_id"])
            self.assertEqual(repair["intent_id"], intent.intent_id)
        finally:
            resident.store.close()

    def test_repair_checkpoint_survives_process_death_before_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, target, event, intent, staging_path, backup_path = self._make_split(root)
            self._checkpoint_repair(db, event, intent)

            # Process death here leaves only durable repair authority and the
            # unchanged proven split. A new resident may execute the new repair,
            # but must never replay the stale overwrite attempt.
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
                self.assertEqual(target.read_text(encoding="utf-8"), "new complete state")
                self.assertFalse(staging_path.exists())
                self.assertFalse(backup_path.exists())
                self.assertEqual(
                    self._attempt_statuses(db, event.event_id), ["verified_effect"]
                )
                self.assertIsNone(self._protocol(db, event.event_id))
            finally:
                resumed.store.close()

    def test_restart_reconciles_process_death_after_repair_move_without_second_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, target, event, intent, staging_path, backup_path = self._make_split(root)
            self._checkpoint_repair(db, event, intent)

            from zn_agent.core import staged_text_write

            original = staged_text_write.repair_staged_to_missing_target_windows

            def move_then_crash(staging: Path, target_path: Path) -> None:
                original(staging, target_path)
                raise SystemExit("process death after retained-stage repair move")

            repairing = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=db
            )
            try:
                checkpoint = repairing.store.get_working_state()
                with patch(
                    "zn_agent.core.staged_text_write.repair_staged_to_missing_target_windows",
                    side_effect=move_then_crash,
                ):
                    with self.assertRaises(SystemExit):
                        repairing._side_effect_recovery_step(
                            event, checkpoint, readiness=None
                        )
                self.assertEqual(target.read_text(encoding="utf-8"), "new complete state")
                self.assertFalse(staging_path.exists())
                self.assertTrue(backup_path.exists())
                self.assertEqual(self._attempt_statuses(db, event.event_id), ["observed"])
                self.assertIsNotNone(self._protocol(db, event.event_id))
            finally:
                repairing.store.close()

            resumed = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=db
            )
            try:
                checkpoint = resumed.store.get_working_state()
                with patch(
                    "zn_agent.core.staged_text_write.repair_staged_to_missing_target_windows",
                    side_effect=AssertionError("repair move must not replay after observed effect"),
                ):
                    result = resumed._side_effect_recovery_step(
                        event, checkpoint, readiness=None
                    )
                self.assertIsNotNone(result)
                self.assertTrue(result.success)
                completed = resumed.store.get_working_state()
                self.assertEqual(completed.stage, "complete")
                self.assertEqual(target.read_text(encoding="utf-8"), "new complete state")
                self.assertFalse(backup_path.exists())
                self.assertEqual(
                    self._attempt_statuses(db, event.event_id), ["verified_effect"]
                )
                self.assertIsNone(self._protocol(db, event.event_id))
            finally:
                resumed.store.close()

    def test_external_target_winner_after_repair_checkpoint_is_never_clobbered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, target, event, intent, staging_path, backup_path = self._make_split(root)
            self._checkpoint_repair(db, event, intent)
            target.write_text("external winner", encoding="utf-8")

            resumed = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=db
            )
            try:
                checkpoint = resumed.store.get_working_state()
                with patch(
                    "zn_agent.core.staged_text_write.repair_staged_to_missing_target_windows",
                    side_effect=AssertionError("no-replace repair must not run after target appears"),
                ):
                    self.assertIsNone(
                        resumed._side_effect_recovery_step(
                            event, checkpoint, readiness=None
                        )
                    )
                held = resumed.store.get_working_state()
                recovery = held.data["side_effect_recovery"]
                self.assertEqual(recovery["decision"], "user_decision_required")
                self.assertEqual(recovery["status"], "namespace_repair_blocked")
                self.assertTrue(recovery["replay_blocked"])
                self.assertEqual(target.read_text(encoding="utf-8"), "external winner")
                self.assertEqual(staging_path.read_text(encoding="utf-8"), "new complete state")
                self.assertEqual(backup_path.read_text(encoding="utf-8"), "old durable state")
                self.assertEqual(self._attempt_statuses(db, event.event_id), ["observed"])
                self.assertIsNotNone(self._protocol(db, event.event_id))
            finally:
                resumed.store.close()


if __name__ == "__main__":
    unittest.main()
