from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.continuity_atomic_recovery import atomic_overwrite_recovery_snapshot


class AtomicOverwriteRecoveryMalformedStateTests(unittest.TestCase):
    def test_commit_started_without_durable_stage_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            database = Path(root) / "kernel.db"
            with closing(sqlite3.connect(database)) as conn:
                conn.execute(
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
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO resident_atomic_overwrite_protocols VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "event-private",
                        "signature-private",
                        1,
                        "intent-private",
                        "attempt-private",
                        "C:/private/stage.tmp",
                        "C:/private/backup.tmp",
                        0,
                        None,
                        1,
                        "replace_file_with_backup",
                        "now",
                    ),
                )
                conn.commit()
            with self.assertRaisesRegex(RuntimeError, "mutated prepared-only protocol"):
                atomic_overwrite_recovery_snapshot(database)


if __name__ == "__main__":
    unittest.main(verbosity=2)
