from __future__ import annotations

import ctypes
import os
import sqlite3
import stat
import tempfile
import unittest
from contextlib import closing, contextmanager
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
    def _attempt_statuses(db: Path, event_id: str) -> list[str]:
        with closing(sqlite3.connect(db)) as conn:
            rows = conn.execute(
                "SELECT status FROM resident_side_effect_attempts WHERE event_id=? ORDER BY started_at",
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
    def _artifacts(root: Path) -> list[Path]:
        return [*root.glob(".zn-write-*.tmp"), *root.glob(".zn-backup-*.tmp")]

    @staticmethod
    @contextmanager
    def _deny_delete_share(path: Path):
        generic_read = 0x80000000
        share_read = 0x00000001
        share_write = 0x00000002
        open_existing = 3
        file_attribute_normal = 0x00000080
        invalid_handle = ctypes.c_void_p(-1).value
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        create_file.restype = ctypes.c_void_p
        handle = create_file(
            str(path),
            generic_read,
            share_read | share_write,
            None,
            open_existing,
            file_attribute_normal,
            None,
        )
        if handle == invalid_handle:
            raise OSError(ctypes.get_last_error(), "CreateFileW test lock failed", str(path))
        try:
            yield
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))

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
                self.assertIsNone(self._protocol(db, event.event_id))
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
                self.assertTrue(current.data["side_effect_recovery"]["atomic_namespace_commit_started"])
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

    def test_restart_reconciles_exact_stage_when_namespace_commit_never_started(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old durable state", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=db)
            event, state, intent = self._work(resident, target, "new complete state")
            staging_path, _ = resident.body.atomic_artifact_paths(
                event_id=event.event_id, kind=intent.kind, args=dict(intent.args)
            )
            try:
                with patch.object(
                    resident.body,
                    "_precommit",
                    side_effect=SystemExit("process death after durable stage identity"),
                ):
                    with self.assertRaises(SystemExit):
                        resident._native_action_step(event, state, readiness=None)
                protocol = self._protocol(db, event.event_id)
                self.assertIsNotNone(protocol)
                self.assertEqual(protocol["stage_ready"], 1)
                self.assertEqual(protocol["namespace_commit_started"], 0)
                self.assertTrue(staging_path.exists())
                self.assertEqual(target.read_text(encoding="utf-8"), "old durable state")
            finally:
                resident.store.close()

            restarted = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=db)
            try:
                current = restarted.store.get_working_state()
                self.assertIsNone(restarted._native_action_step(event, current, readiness=None))
                current = restarted.store.get_working_state()
                self.assertEqual(current.stage, "side_effect_recovery")
                self.assertIsNone(restarted._side_effect_recovery_step(event, current, readiness=None))
                current = restarted.store.get_working_state()
                self.assertEqual(current.stage, "native_action")
                self.assertEqual(self._attempt_status(db, event.event_id), "verified_absent")
                self.assertFalse(staging_path.exists())
                self.assertIsNone(self._protocol(db, event.event_id))
                self.assertEqual(target.read_text(encoding="utf-8"), "old durable state")

                self.assertIsNone(restarted._native_action_step(event, current, readiness=None))
                current = restarted.store.get_working_state()
                self.assertEqual(current.stage, "native_verification")
                completed = restarted._native_verification_step(event, current, readiness=None)
                self.assertIsNotNone(completed)
                self.assertTrue(completed.success)
                self.assertEqual(target.read_text(encoding="utf-8"), "new complete state")
                self.assertEqual(self._attempt_statuses(db, event.event_id), ["verified_absent", "observed"])
                self.assertEqual(self._artifacts(root), [])
                self.assertIsNone(self._protocol(db, event.event_id))
            finally:
                restarted.store.close()

    def test_restart_never_replays_after_durable_namespace_commit_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old durable state", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=db)
            event, state, _ = self._work(resident, target, "new complete state")
            try:
                with patch(
                    "zn_agent.core.staged_text_write._replace_existing_windows",
                    side_effect=SystemExit("process death after durable commit marker"),
                ):
                    with self.assertRaises(SystemExit):
                        resident._native_action_step(event, state, readiness=None)
                protocol = self._protocol(db, event.event_id)
                self.assertIsNotNone(protocol)
                self.assertEqual(protocol["namespace_commit_started"], 1)
                self.assertEqual(target.read_text(encoding="utf-8"), "old durable state")
            finally:
                resident.store.close()

            restarted = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=db)
            try:
                current = restarted.store.get_working_state()
                self.assertIsNone(restarted._native_action_step(event, current, readiness=None))
                current = restarted.store.get_working_state()
                self.assertIsNone(restarted._side_effect_recovery_step(event, current, readiness=None))
                held = restarted.store.get_working_state()
                self.assertEqual(held.stage, "side_effect_recovery")
                self.assertEqual(held.blocked_by, "outside_world_effect_uncertain")
                self.assertEqual(self._attempt_status(db, event.event_id), "started")
                self.assertTrue(any(root.glob(".zn-write-*.tmp")))
                self.assertEqual(target.read_text(encoding="utf-8"), "old durable state")
            finally:
                restarted.store.close()

    def test_restart_preserves_tampered_stage_instead_of_granting_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=db)
            event, state, intent = self._work(resident, target, "resident value")
            staging_path, _ = resident.body.atomic_artifact_paths(
                event_id=event.event_id, kind=intent.kind, args=dict(intent.args)
            )
            try:
                with patch.object(resident.body, "_precommit", side_effect=SystemExit("crash")):
                    with self.assertRaises(SystemExit):
                        resident._native_action_step(event, state, readiness=None)
                staging_path.write_text("tampered external stage", encoding="utf-8")
            finally:
                resident.store.close()

            restarted = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=db)
            try:
                current = restarted.store.get_working_state()
                self.assertIsNone(restarted._native_action_step(event, current, readiness=None))
                current = restarted.store.get_working_state()
                self.assertIsNone(restarted._side_effect_recovery_step(event, current, readiness=None))
                held = restarted.store.get_working_state()
                evidence = held.data["side_effect_recovery"]["atomic_precommit_reconciliation"]
                self.assertFalse(evidence["stage_exact"])
                self.assertEqual(held.stage, "side_effect_recovery")
                self.assertEqual(self._attempt_status(db, event.event_id), "started")
                self.assertEqual(staging_path.read_text(encoding="utf-8"), "tampered external stage")
                self.assertEqual(target.read_text(encoding="utf-8"), "old")
            finally:
                restarted.store.close()

    def test_restart_never_deletes_unexpected_backup_before_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=db)
            event, state, intent = self._work(resident, target, "resident value")
            _, backup_path = resident.body.atomic_artifact_paths(
                event_id=event.event_id, kind=intent.kind, args=dict(intent.args)
            )
            try:
                with patch.object(resident.body, "_precommit", side_effect=SystemExit("crash")):
                    with self.assertRaises(SystemExit):
                        resident._native_action_step(event, state, readiness=None)
                backup_path.write_text("unique retained pre-state evidence", encoding="utf-8")
            finally:
                resident.store.close()

            restarted = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=db)
            try:
                current = restarted.store.get_working_state()
                self.assertIsNone(restarted._native_action_step(event, current, readiness=None))
                current = restarted.store.get_working_state()
                self.assertIsNone(restarted._side_effect_recovery_step(event, current, readiness=None))
                held = restarted.store.get_working_state()
                evidence = held.data["side_effect_recovery"]["atomic_precommit_reconciliation"]
                self.assertFalse(evidence["backup_absent"])
                self.assertTrue(backup_path.exists())
                self.assertEqual(
                    backup_path.read_text(encoding="utf-8"),
                    "unique retained pre-state evidence",
                )
                self.assertEqual(self._attempt_status(db, event.event_id), "started")
            finally:
                restarted.store.close()

    def test_backup_cleanup_failure_is_retried_after_verified_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=db)
            event, state, intent = self._work(resident, target, "new")
            _, backup_path = resident.body.atomic_artifact_paths(
                event_id=event.event_id, kind=intent.kind, args=dict(intent.args)
            )
            original_unlink = Path.unlink

            def fail_backup_once(path: Path, *args, **kwargs):
                if path == backup_path:
                    raise PermissionError("synthetic backup cleanup lock")
                return original_unlink(path, *args, **kwargs)

            try:
                with patch("pathlib.Path.unlink", new=fail_backup_once):
                    self.assertIsNone(resident._native_action_step(event, state, readiness=None))
                current = resident.store.get_working_state()
                self.assertEqual(current.stage, "native_verification")
                self.assertTrue(backup_path.exists())
                self.assertIsNotNone(self._protocol(db, event.event_id))

                completed = resident._native_verification_step(event, current, readiness=None)
                self.assertIsNotNone(completed)
                self.assertTrue(completed.success)
                self.assertEqual(target.read_text(encoding="utf-8"), "new")
                self.assertFalse(backup_path.exists())
                self.assertIsNone(self._protocol(db, event.event_id))
            finally:
                resident.store.close()

    def test_windows_sharing_lock_fails_without_target_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "locked.txt"
            target.write_text("old locked value", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=root / "kernel.db"
            )
            try:
                with self._deny_delete_share(target):
                    result = resident.body.act(
                        "write_text",
                        event_id="evt-sharing-lock",
                        path=str(target),
                        content="new value",
                        append=False,
                    )
                self.assertFalse(result.success)
                self.assertTrue(result.data["atomic_commit_proven_absent"])
                self.assertEqual(target.read_text(encoding="utf-8"), "old locked value")
                self.assertEqual(self._artifacts(root), [])
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
