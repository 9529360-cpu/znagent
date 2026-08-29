from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.continuity_reference_proof import resident_state_proof


class CompletionObservationContinuityTests(unittest.TestCase):
    @staticmethod
    def _database(root: str) -> Path:
        path = Path(root) / "kernel.db"
        with closing(sqlite3.connect(path)) as conn:
            conn.execute(
                """
                CREATE TABLE resident_completion_observations(
                    event_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(event_id, stage)
                )
                """
            )
            conn.commit()
        return path

    @staticmethod
    def _insert(database: Path, *, status: str = "pending", attempts: int = 1) -> None:
        with closing(sqlite3.connect(database)) as conn:
            conn.execute(
                "INSERT INTO resident_completion_observations VALUES(?,?,?,?,?,?)",
                (
                    "event-private",
                    "life",
                    status,
                    attempts,
                    "private repair error" if status == "pending" else None,
                    "now",
                ),
            )
            conn.commit()

    def test_status_progress_does_not_change_observation_identity(self):
        with tempfile.TemporaryDirectory() as root:
            database = self._database(root)
            self._insert(database)
            before = resident_state_proof(database)
            self.assertEqual(before["section_counts"]["completion_observations"], 1)

            with closing(sqlite3.connect(database)) as conn:
                conn.execute(
                    "UPDATE resident_completion_observations "
                    "SET status='running',attempts=2,last_error=NULL,updated_at='later'"
                )
                conn.commit()
            running = resident_state_proof(database)
            self.assertEqual(before["reference_hashes"], running["reference_hashes"])

            with closing(sqlite3.connect(database)) as conn:
                conn.execute(
                    "UPDATE resident_completion_observations "
                    "SET status='completed',attempts=2,last_error=NULL,updated_at='done'"
                )
                conn.commit()
            completed = resident_state_proof(database)
            self.assertEqual(before["reference_hashes"], completed["reference_hashes"])

    def test_observation_row_loss_breaks_resident_continuity_reference(self):
        with tempfile.TemporaryDirectory() as root:
            database = self._database(root)
            self._insert(database)
            before = resident_state_proof(database)
            with closing(sqlite3.connect(database)) as conn:
                conn.execute("DELETE FROM resident_completion_observations")
                conn.commit()
            after = resident_state_proof(database)
            self.assertFalse(
                set(before["reference_hashes"]).issubset(after["reference_hashes"])
            )

    def test_observation_proof_does_not_expose_event_or_error_plaintext(self):
        with tempfile.TemporaryDirectory() as root:
            database = self._database(root)
            self._insert(database)
            proof = resident_state_proof(database)
            rendered = repr(proof)
            self.assertNotIn("event-private", rendered)
            self.assertNotIn("private repair error", rendered)
            self.assertNotIn("pending", rendered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
