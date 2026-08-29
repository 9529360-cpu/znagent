from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.continuity_reference_proof import resident_state_proof


class ContinuitySideEffectRetentionTests(unittest.TestCase):
    @staticmethod
    def _database(root: str) -> Path:
        path = Path(root) / "kernel.db"
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript(
                """
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
                """
            )
            conn.commit()
        return path

    @staticmethod
    def _insert_event(
        database: Path,
        *,
        event_id: str,
        event_status: str,
        attempt_status: str,
        terminal_outcome: bool,
    ) -> None:
        with closing(sqlite3.connect(database)) as conn:
            conn.execute(
                "INSERT INTO events VALUES(?,?,?,?,?)",
                (event_id, event_status, 0, "born", "{}"),
            )
            if terminal_outcome:
                conn.execute(
                    "INSERT INTO event_outcomes VALUES(?,?,?)",
                    (event_id, "done", "{}"),
                )
            conn.execute(
                "INSERT INTO resident_side_effect_attempts VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    f"attempt-{event_id}",
                    event_id,
                    f"signature-{event_id}",
                    "command",
                    attempt_status,
                    "started",
                    "completed" if attempt_status != "started" else None,
                    None,
                    None,
                ),
            )
            conn.commit()

    @staticmethod
    def _delete_attempt(database: Path, event_id: str) -> None:
        with closing(sqlite3.connect(database)) as conn:
            conn.execute(
                "DELETE FROM resident_side_effect_attempts WHERE event_id=?",
                (event_id,),
            )
            conn.commit()

    def test_nonterminal_observed_attempt_cannot_disappear_from_continuity(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = self._database(temporary)
            self._insert_event(
                database,
                event_id="active",
                event_status="running",
                attempt_status="observed",
                terminal_outcome=False,
            )
            before = resident_state_proof(database)
            self.assertEqual(before["section_counts"]["side_effect_attempts"], 1)

            self._delete_attempt(database, "active")
            after = resident_state_proof(database)

            self.assertFalse(
                set(before["reference_hashes"]).issubset(after["reference_hashes"])
            )

    def test_terminal_nonstarted_attempt_may_leave_proof_after_durable_outcome(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = self._database(temporary)
            self._insert_event(
                database,
                event_id="terminal",
                event_status="completed",
                attempt_status="verified_effect",
                terminal_outcome=True,
            )
            before = resident_state_proof(database)
            self.assertEqual(before["section_counts"]["side_effect_attempts"], 0)

            self._delete_attempt(database, "terminal")
            after = resident_state_proof(database)

            self.assertEqual(before["reference_hashes"], after["reference_hashes"])
            self.assertEqual(before["digest"], after["digest"])

    def test_started_attempt_remains_protected_even_if_owner_is_terminal(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = self._database(temporary)
            self._insert_event(
                database,
                event_id="terminal-started",
                event_status="failed",
                attempt_status="started",
                terminal_outcome=True,
            )
            before = resident_state_proof(database)
            self.assertEqual(before["section_counts"]["side_effect_attempts"], 1)

            self._delete_attempt(database, "terminal-started")
            after = resident_state_proof(database)

            self.assertFalse(
                set(before["reference_hashes"]).issubset(after["reference_hashes"])
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
