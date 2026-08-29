from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.continuity_atomic_recovery import atomic_overwrite_recovery_snapshot


class AtomicOverwriteRecoveryContinuityBoundsTests(unittest.TestCase):
    def test_discharge_witnesses_remain_bounded_over_long_resident_history(self):
        with tempfile.TemporaryDirectory() as root:
            database = Path(root) / "kernel.db"
            with closing(sqlite3.connect(database)) as conn:
                conn.executescript(
                    """
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
                    """
                )
                history_size = 4100
                conn.executemany(
                    "INSERT INTO resident_side_effect_attempts VALUES(?,?,?,?,?,?,?,?,?)",
                    [
                        (
                            f"attempt-{index}",
                            f"event-{index}",
                            "signature",
                            "write_text",
                            "verified_effect",
                            f"{index:08d}",
                            f"{index:08d}",
                            None,
                            1,
                        )
                        for index in range(history_size)
                    ],
                )
                conn.executemany(
                    "INSERT INTO events VALUES(?,?,?,?,?)",
                    [
                        (f"event-{index}", "completed", 0, f"{index:08d}", "{}")
                        for index in range(history_size)
                    ],
                )
                conn.executemany(
                    "INSERT INTO event_outcomes VALUES(?,?,?)",
                    [
                        (f"event-{index}", f"{index:08d}", "{}")
                        for index in range(history_size)
                    ],
                )
                conn.commit()

            snapshot = atomic_overwrite_recovery_snapshot(database)

            self.assertEqual(len(snapshot["verified_attempt_hashes"]), 4096)
            self.assertEqual(len(snapshot["terminal_event_hashes"]), 4096)
            self.assertTrue(all(len(value) == 64 for value in snapshot["verified_attempt_hashes"]))
            self.assertTrue(all(len(value) == 64 for value in snapshot["terminal_event_hashes"]))
            self.assertNotIn("attempt-", repr(snapshot))
            self.assertNotIn("event-", repr(snapshot))


if __name__ == "__main__":
    unittest.main(verbosity=2)
