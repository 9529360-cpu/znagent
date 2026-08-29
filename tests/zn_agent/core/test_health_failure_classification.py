from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.health_observation import ResidentHealthJournal


class ResidentHealthFailureClassificationTests(unittest.TestCase):
    def test_repeated_probable_defect_becomes_candidate_without_persisting_raw_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            journal = ResidentHealthJournal(SimpleNamespace(path=db))
            secret = "secret-token-123"

            first = journal.record_failure("channel:test", AssertionError(f"broken invariant {secret}"))
            second = journal.record_failure("channel:test", AssertionError(f"broken invariant {secret}"))
            third = journal.record_failure("channel:test", AssertionError(f"broken invariant {secret}"))

            self.assertEqual(first["last_failure_class"], "probable_zn_defect")
            self.assertFalse(first["maintenance_candidate"])
            self.assertEqual(second["repeat_fingerprint_failures"], 2)
            self.assertEqual(third["consecutive_failures"], 3)
            self.assertEqual(third["repeat_fingerprint_failures"], 3)
            self.assertTrue(third["maintenance_candidate"])
            self.assertEqual(len(third["last_fingerprint"]), 64)
            self.assertNotIn(secret, repr(journal.snapshot()))
            self.assertNotIn(secret.encode("utf-8"), db.read_bytes())

    def test_ambiguous_programming_or_payload_failure_stays_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = ResidentHealthJournal(SimpleNamespace(path=Path(tmp) / "kernel.db"))
            for _ in range(4):
                state = journal.record_failure("channel:test", TypeError("unexpected payload shape"))

            self.assertEqual(state["last_failure_class"], "programming_or_data_contract")
            self.assertEqual(state["repeat_fingerprint_failures"], 4)
            self.assertFalse(state["maintenance_candidate"])
            self.assertEqual(journal.snapshot()["maintenance_candidate_count"], 0)

    def test_external_failure_never_becomes_source_maintenance_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = ResidentHealthJournal(SimpleNamespace(path=Path(tmp) / "kernel.db"))
            for _ in range(4):
                state = journal.record_failure("channel:test", TimeoutError("upstream timed out"))

            self.assertEqual(state["last_failure_class"], "network_or_service")
            self.assertEqual(state["repeat_fingerprint_failures"], 4)
            self.assertFalse(state["maintenance_candidate"])
            self.assertEqual(journal.snapshot()["maintenance_candidate_count"], 0)

    def test_new_fingerprint_and_recovery_reset_repeat_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = ResidentHealthJournal(SimpleNamespace(path=Path(tmp) / "kernel.db"))
            journal.record_failure("channel:test", AssertionError("invariant-a"))
            repeated = journal.record_failure("channel:test", AssertionError("invariant-a"))
            changed = journal.record_failure("channel:test", AssertionError("invariant-b"))

            self.assertEqual(repeated["repeat_fingerprint_failures"], 2)
            self.assertEqual(changed["consecutive_failures"], 3)
            self.assertEqual(changed["repeat_fingerprint_failures"], 1)
            self.assertFalse(changed["maintenance_candidate"])

            recovered = journal.record_success("channel:test")
            self.assertIsNotNone(recovered)
            self.assertTrue(recovered["healthy"])
            self.assertEqual(recovered["consecutive_failures"], 0)
            self.assertEqual(recovered["repeat_fingerprint_failures"], 0)
            self.assertEqual(recovered["total_failures"], 3)

    def test_existing_health_table_is_migrated_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            conn = sqlite3.connect(db)
            try:
                conn.executescript(
                    """
                    CREATE TABLE resident_health_observations(
                        organ TEXT PRIMARY KEY,
                        total_failures INTEGER NOT NULL DEFAULT 0,
                        consecutive_failures INTEGER NOT NULL DEFAULT 0,
                        first_failure_at TEXT NOT NULL,
                        last_failure_at TEXT NOT NULL,
                        last_success_at TEXT,
                        last_exception_type TEXT,
                        last_fingerprint TEXT
                    );
                    INSERT INTO resident_health_observations(
                        organ,total_failures,consecutive_failures,first_failure_at,
                        last_failure_at,last_success_at,last_exception_type,last_fingerprint
                    ) VALUES('channel:test',2,2,'t1','t2',NULL,'TypeError','old-fingerprint');
                    """
                )
                conn.commit()
            finally:
                conn.close()

            journal = ResidentHealthJournal(SimpleNamespace(path=db))
            migrated = journal.get("channel:test")
            self.assertIsNotNone(migrated)
            self.assertEqual(migrated["repeat_fingerprint_failures"], 0)
            self.assertEqual(migrated["last_failure_class"], "unknown")

            updated = journal.record_failure("channel:test", TypeError("new-shape"))
            self.assertEqual(updated["total_failures"], 3)
            self.assertEqual(updated["consecutive_failures"], 3)
            self.assertEqual(updated["repeat_fingerprint_failures"], 1)
            self.assertEqual(updated["last_failure_class"], "programming_or_data_contract")
            self.assertFalse(updated["maintenance_candidate"])


if __name__ == "__main__":
    unittest.main()
