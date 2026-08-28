from __future__ import annotations

import os
import sqlite3
import stat
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.staged_text_write import StagedWriteCommitUncertainError


@unittest.skipUnless(os.name == "nt", "Windows staged overwrite semantics")
class WindowsAtomicOverwriteTests(unittest.TestCase):
    @staticmethod
    def _work(resident, target: Path, content: str):
        event = resident.enqueue("replace exact text", payload={"required_capabilities": ["filesystem"]})
        assert resident.store.claim_event(event.event_id) is not None
        intent = NativeActionIntent(
            intent_id=f"intent-{event.event_id}",
            event_id=event.event_id,
            kind="write_text",
            args={"path": str(target), "content": content, "append": False, "create_parents": True},
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
    def _attempt_status(db: Path, event_id: str) -> str:
        with closing(sqlite3.connect(db)) as conn:
            row = conn.execute(
                "SELECT status FROM resident_side_effect_attempts WHERE event_id=? ORDER BY started_at DESC LIMIT 1",
                (event_id,),
            ).fetchone()
        assert row is not None
        return str(row[0])

    @staticmethod
    def _artifacts(root: Path) -> list[Path]:
        return [*root.glob(".zn-write-*.tmp"), *root.glob(".zn-backup-*.tmp")]

    def test_existing_file_replace_preserves_creation_time_and_cleans_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "document.txt"
            target.write_text("old", encoding="utf-8")
            before = target.stat()
            created = int(getattr(before, "st_birthtime_ns", before.st_ctime_ns))
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=root / "kernel.db"
            )
            try:
                result = resident.body.act(
                    "write_text",
                    event_id="evt-existing",
                    path=str(target),
                    content="new complete state",
                    append=False,
                    create_parents=True,
                )
                after = target.stat()
                self.assertTrue(result.success)
                self.assertEqual(result.data["write_strategy"], "replace_file_with_backup")
                self.assertEqual(target.read_text(encoding="utf-8"), "new complete state")
                self.assertEqual(created, int(getattr(after, "st_birthtime_ns", after.st_ctime_ns)))
                self.assertEqual(self._artifacts(root), [])
            finally:
                resident.store.close()

    def test_missing_target_race_never_clobbers_external_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "new.txt"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=root / "kernel.db"
            )
            from zn_agent.core import staged_text_write
            original = staged_text_write._move_new_windows

            def race(staging: Path, destination: Path) -> None:
                destination.write_text("external winner", encoding="utf-8")
                original(staging, destination)

            try:
                with patch("zn_agent.core.staged_text_write._move_new_windows", side_effect=race):
                    result = resident.body.act(
                        "write_text",
                        event_id="evt-create-race",
                        path=str(target),
                        content="resident value",
                        append=False,
                    )
                self.assertFalse(result.success)
                self.assertTrue(result.data["atomic_commit_proven_absent"])
                self.assertEqual(target.read_text(encoding="utf-8"), "external winner")
                self.assertEqual(self._artifacts(root), [])
            finally:
                resident.store.close()

    def test_process_death_after_staging_does_not_truncate_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "document.txt"
            target.write_text("old durable state", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=root / "kernel.db"
            )
            try:
                with patch(
                    "zn_agent.core.staged_text_write._replace_existing_windows",
                    side_effect=SystemExit("process death after staging"),
                ):
                    with self.assertRaises(SystemExit):
                        resident.body.act(
                            "write_text",
                            event_id="evt-crash",
                            path=str(target),
                            content="new complete state",
                            append=False,
                        )
                self.assertEqual(target.read_text(encoding="utf-8"), "old durable state")
                self.assertTrue(any(root.glob(".zn-write-*.tmp")))
            finally:
                resident.store.close()

    def test_precommit_drift_closes_attempt_as_verified_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=db)
            event, state, _ = self._work(resident, target, "resident value")
            from zn_agent.core import staged_text_write
            original = staged_text_write._write_stage

            def drift(path: Path, content: str, encoding: str) -> int:
                written = original(path, content, encoding)
                target.write_text("external edit", encoding="utf-8")
                return written

            try:
                with patch("zn_agent.core.staged_text_write._write_stage", side_effect=drift):
                    self.assertIsNone(resident._native_action_step(event, state, readiness=None))
                current = resident.store.get_working_state()
                self.assertEqual(current.stage, "native_investigation")
                self.assertIn("precommit identity changed", current.data["local_failure"])
                self.assertEqual(self._attempt_status(db, event.event_id), "verified_absent")
                self.assertEqual(target.read_text(encoding="utf-8"), "external edit")
                self.assertEqual(self._artifacts(root), [])
            finally:
                resident.store.close()

    def test_namespace_mutating_replace_failure_enters_recovery_not_failure_learning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=db)
            event, state, _ = self._work(resident, target, "resident value")

            def uncertain(target_path: Path, staging: Path, backup: Path) -> None:
                raise StagedWriteCommitUncertainError(
                    "synthetic ERROR_UNABLE_TO_MOVE_REPLACEMENT_2",
                    staging_path=staging,
                    backup_path=backup,
                    strategy="replace_file_with_backup",
                    error_code=1177,
                )

            try:
                with patch("zn_agent.core.staged_text_write._replace_existing_windows", side_effect=uncertain):
                    self.assertIsNone(resident._native_action_step(event, state, readiness=None))
                current = resident.store.get_working_state()
                self.assertEqual(current.stage, "side_effect_recovery")
                self.assertNotIn("local_failure", current.data)
                self.assertTrue(current.data["side_effect_recovery"]["write_commit_uncertain"])
                self.assertEqual(current.data["side_effect_recovery"]["winerror"], 1177)
                self.assertEqual(self._attempt_status(db, event.event_id), "observed")
                self.assertEqual(target.read_text(encoding="utf-8"), "old")
            finally:
                resident.store.close()

    def test_read_only_target_fails_without_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "readonly.txt"
            target.write_text("old", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=root / "kernel.db"
            )
            os.chmod(target, stat.S_IREAD)
            try:
                result = resident.body.act(
                    "write_text", event_id="evt-readonly", path=str(target), content="new", append=False
                )
                self.assertFalse(result.success)
                self.assertTrue(result.data["atomic_commit_proven_absent"])
                self.assertEqual(target.read_text(encoding="utf-8"), "old")
                self.assertEqual(self._artifacts(root), [])
            finally:
                os.chmod(target, stat.S_IWRITE)
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
