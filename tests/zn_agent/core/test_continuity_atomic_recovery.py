from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.continuity_atomic_recovery import (
    atomic_overwrite_recovery_snapshot,
    compare_atomic_overwrite_recovery,
)


class AtomicOverwriteRecoveryContinuityTests(unittest.TestCase):
    @staticmethod
    def _database(root: str) -> Path:
        path = Path(root) / "kernel.db"
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript(
                """
                CREATE TABLE resident_atomic_overwrite_protocols(
                    event_id TEXT NOT NULL,
                    signature_hash TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    intent_id TEXT NOT NULL,
                    attempt_id TEXT,
                    staging_path TEXT NOT NULL,
                    backup_path TEXT NOT NULL,
                    stage_ready INTEGER NOT NULL DEFAULT 0,
                    stage_identity_json TEXT,
                    namespace_commit_started INTEGER NOT NULL DEFAULT 0,
                    write_strategy TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(event_id, signature_hash)
                );
                CREATE TABLE resident_side_effect_attempts(
                    attempt_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    signature_hash TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    result_action_id TEXT,
                    result_success INTEGER
                );
                CREATE TABLE events(
                    event_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE event_outcomes(
                    event_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE working_state(
                    id INTEGER PRIMARY KEY,
                    current_event_id TEXT,
                    stage TEXT NOT NULL,
                    next_action TEXT,
                    blocked_by TEXT,
                    data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.commit()
        return path

    @staticmethod
    def _protocol(
        database: Path,
        *,
        event_id: str = "event-secret",
        attempt_id: str | None = "attempt-secret",
        stage_ready: bool = True,
        commit_started: bool = False,
        strategy: str | None = None,
        stage_identity: dict | None = None,
    ) -> None:
        identity = stage_identity or {
            "path": "C:/private/zn-stage.tmp",
            "content_sha256": "1" * 64,
            "size_bytes": 12,
        }
        with closing(sqlite3.connect(database)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO resident_atomic_overwrite_protocols VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    "signature-private",
                    1,
                    "intent-private",
                    attempt_id,
                    "C:/private/zn-stage.tmp",
                    "C:/private/zn-backup.tmp",
                    1 if stage_ready else 0,
                    json.dumps(identity) if stage_ready else None,
                    1 if commit_started else 0,
                    strategy,
                    "now",
                ),
            )
            conn.commit()

    @staticmethod
    def _attempt(database: Path, *, status: str, event_id: str = "event-secret") -> None:
        with closing(sqlite3.connect(database)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO resident_side_effect_attempts VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    "attempt-secret",
                    event_id,
                    "signature-private",
                    "write_text",
                    status,
                    "started",
                    "done" if status != "started" else None,
                    None,
                    None,
                ),
            )
            conn.commit()

    @staticmethod
    def _delete_protocol(database: Path) -> None:
        with closing(sqlite3.connect(database)) as conn:
            conn.execute("DELETE FROM resident_atomic_overwrite_protocols")
            conn.commit()

    @staticmethod
    def _native_completion(database: Path, *, attempt_id: str) -> None:
        state = {
            "current_event_id": "event-secret",
            "stage": "native_completion",
            "next_action": "publish terminal EventOutcome",
            "blocked_by": None,
            "data": {
                "native_action_result": {
                    "success": True,
                    "data": {"side_effect_attempt_id": attempt_id},
                },
                "native_completion": {"success": True},
            },
        }
        with closing(sqlite3.connect(database)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO working_state VALUES(?,?,?,?,?,?,?)",
                (
                    1,
                    state["current_event_id"],
                    state["stage"],
                    state["next_action"],
                    state["blocked_by"],
                    json.dumps(state["data"]),
                    "now",
                ),
            )
            conn.commit()

    def test_prepared_only_protocol_is_not_recovery_authority(self):
        with tempfile.TemporaryDirectory() as root:
            database = self._database(root)
            self._protocol(database, attempt_id=None, stage_ready=False)
            snapshot = atomic_overwrite_recovery_snapshot(database)
            self.assertEqual(snapshot["protocol_count"], 0)
            self.assertEqual(snapshot["protocols"], [])

    def test_staged_proof_hides_private_protocol_content(self):
        with tempfile.TemporaryDirectory() as root:
            database = self._database(root)
            self._protocol(database)
            snapshot = atomic_overwrite_recovery_snapshot(database)
            self.assertEqual(snapshot["protocol_count"], 1)
            representation = repr(snapshot)
            for private in (
                "event-secret",
                "attempt-secret",
                "signature-private",
                "intent-private",
                "C:/private/zn-stage.tmp",
                "C:/private/zn-backup.tmp",
            ):
                self.assertNotIn(private, representation)

    def test_staged_protocol_may_advance_to_commit_started(self):
        with tempfile.TemporaryDirectory() as root:
            database = self._database(root)
            self._protocol(database)
            before = atomic_overwrite_recovery_snapshot(database)
            self._protocol(
                database,
                commit_started=True,
                strategy="replace_file_with_backup",
            )
            after = atomic_overwrite_recovery_snapshot(database)
            self.assertEqual(compare_atomic_overwrite_recovery(before, after), [])

    def test_stage_rank_regression_is_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            database = self._database(root)
            self._protocol(
                database,
                commit_started=True,
                strategy="replace_file_with_backup",
            )
            before = atomic_overwrite_recovery_snapshot(database)
            self._protocol(database)
            blockers = compare_atomic_overwrite_recovery(
                before, atomic_overwrite_recovery_snapshot(database)
            )
            self.assertIn(
                "atomic_overwrite_recovery_stage_regressed",
                {item["kind"] for item in blockers},
            )

    def test_stage_identity_rewrite_is_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            database = self._database(root)
            self._protocol(database)
            before = atomic_overwrite_recovery_snapshot(database)
            self._protocol(
                database,
                stage_identity={
                    "path": "C:/private/zn-stage.tmp",
                    "content_sha256": "2" * 64,
                    "size_bytes": 12,
                },
            )
            blockers = compare_atomic_overwrite_recovery(
                before, atomic_overwrite_recovery_snapshot(database)
            )
            self.assertIn(
                "atomic_overwrite_recovery_stage_identity_changed",
                {item["kind"] for item in blockers},
            )

    def test_commit_strategy_rewrite_is_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            database = self._database(root)
            self._protocol(
                database,
                commit_started=True,
                strategy="replace_file_with_backup",
            )
            before = atomic_overwrite_recovery_snapshot(database)
            self._protocol(
                database,
                commit_started=True,
                strategy="move_new_no_replace",
            )
            blockers = compare_atomic_overwrite_recovery(
                before, atomic_overwrite_recovery_snapshot(database)
            )
            self.assertIn(
                "atomic_overwrite_recovery_strategy_changed",
                {item["kind"] for item in blockers},
            )

    def test_active_staged_protocol_cannot_disappear(self):
        with tempfile.TemporaryDirectory() as root:
            database = self._database(root)
            self._protocol(database)
            before = atomic_overwrite_recovery_snapshot(database)
            self._delete_protocol(database)
            blockers = compare_atomic_overwrite_recovery(
                before, atomic_overwrite_recovery_snapshot(database)
            )
            self.assertIn(
                "atomic_overwrite_recovery_protocol_lost",
                {item["kind"] for item in blockers},
            )

    def test_verified_attempt_discharges_protocol(self):
        for status in ("verified_effect", "verified_absent"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as root:
                database = self._database(root)
                self._protocol(database)
                before = atomic_overwrite_recovery_snapshot(database)
                self._attempt(database, status=status)
                self._delete_protocol(database)
                after = atomic_overwrite_recovery_snapshot(database)
                self.assertEqual(compare_atomic_overwrite_recovery(before, after), [])

    def test_exact_native_completion_discharges_protocol(self):
        with tempfile.TemporaryDirectory() as root:
            database = self._database(root)
            self._protocol(database)
            before = atomic_overwrite_recovery_snapshot(database)
            self._native_completion(database, attempt_id="attempt-secret")
            self._delete_protocol(database)
            after = atomic_overwrite_recovery_snapshot(database)
            self.assertEqual(compare_atomic_overwrite_recovery(before, after), [])

    def test_wrong_native_completion_attempt_does_not_discharge_protocol(self):
        with tempfile.TemporaryDirectory() as root:
            database = self._database(root)
            self._protocol(database)
            before = atomic_overwrite_recovery_snapshot(database)
            self._native_completion(database, attempt_id="another-attempt")
            self._delete_protocol(database)
            blockers = compare_atomic_overwrite_recovery(
                before, atomic_overwrite_recovery_snapshot(database)
            )
            self.assertIn(
                "atomic_overwrite_recovery_protocol_lost",
                {item["kind"] for item in blockers},
            )

    def test_terminal_event_outcome_discharges_protocol(self):
        with tempfile.TemporaryDirectory() as root:
            database = self._database(root)
            self._protocol(database)
            before = atomic_overwrite_recovery_snapshot(database)
            with closing(sqlite3.connect(database)) as conn:
                conn.execute(
                    "INSERT INTO events VALUES(?,?,?,?,?)",
                    ("event-secret", "failed", 0, "born", "{}"),
                )
                conn.execute(
                    "INSERT INTO event_outcomes VALUES(?,?,?)",
                    ("event-secret", "done", "{}"),
                )
                conn.commit()
            self._delete_protocol(database)
            after = atomic_overwrite_recovery_snapshot(database)
            self.assertEqual(compare_atomic_overwrite_recovery(before, after), [])

    def test_malformed_candidate_proof_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            database = self._database(root)
            self._protocol(database)
            before = atomic_overwrite_recovery_snapshot(database)
            after = atomic_overwrite_recovery_snapshot(database)
            after["digest"] = "0" * 64
            blockers = compare_atomic_overwrite_recovery(before, after)
            self.assertIn(
                "atomic_overwrite_recovery_continuity_unproven",
                {item["kind"] for item in blockers},
            )

    def test_new_unrelated_protocol_growth_is_allowed(self):
        with tempfile.TemporaryDirectory() as root:
            database = self._database(root)
            self._protocol(database)
            before = atomic_overwrite_recovery_snapshot(database)
            self._protocol(
                database,
                event_id="event-two",
                attempt_id="attempt-two",
            )
            after = atomic_overwrite_recovery_snapshot(database)
            self.assertEqual(compare_atomic_overwrite_recovery(before, after), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
