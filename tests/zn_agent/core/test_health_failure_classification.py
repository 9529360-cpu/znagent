from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.health_observation import ResidentHealthJournal


class ResidentHealthFailureClassificationTests(unittest.TestCase):
    def test_repeated_probable_defect_becomes_candidate_and_durable_task_without_raw_message(self):
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

            task = journal.maintenance_task("channel:test")
            self.assertIsNotNone(task)
            self.assertEqual(task["status"], "open")
            self.assertEqual(task["failure_class"], "probable_zn_defect")
            self.assertEqual(task["fingerprint"], third["last_fingerprint"])
            self.assertEqual(task["exception_type"], "AssertionError")
            self.assertEqual(task["occurrences"], 3)
            self.assertTrue(task["task_id"].startswith("maintenance-"))
            self.assertNotIn(secret, repr(journal.snapshot()))
            self.assertNotIn(secret, repr(journal.maintenance_tasks()))
            self.assertNotIn(secret.encode("utf-8"), db.read_bytes())

    def test_maintenance_task_is_one_per_organ_reopens_with_new_defect_and_closes_on_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            journal = ResidentHealthJournal(SimpleNamespace(path=db))

            for _ in range(3):
                first_health = journal.record_failure("channel:test", AssertionError("invariant-a"))
            first_task = journal.maintenance_task("channel:test")
            self.assertIsNotNone(first_task)
            self.assertEqual(journal.maintenance_tasks()["task_count"], 1)
            self.assertEqual(journal.maintenance_tasks()["open_count"], 1)
            self.assertEqual(first_task["occurrences"], 3)

            fourth = journal.record_failure("channel:test", AssertionError("invariant-a"))
            same_task = journal.maintenance_task("channel:test")
            self.assertEqual(same_task["task_id"], first_task["task_id"])
            self.assertEqual(same_task["fingerprint"], first_health["last_fingerprint"])
            self.assertEqual(same_task["occurrences"], 4)
            self.assertEqual(fourth["repeat_fingerprint_failures"], 4)
            self.assertEqual(journal.maintenance_tasks()["task_count"], 1)

            recovered = journal.record_success("channel:test")
            self.assertIsNotNone(recovered)
            closed = journal.maintenance_task("channel:test")
            self.assertEqual(closed["status"], "closed")
            self.assertEqual(closed["close_reason"], "organ_recovered")
            self.assertIsNotNone(closed["closed_at"])
            self.assertEqual(journal.maintenance_tasks()["open_count"], 0)

            for _ in range(3):
                second_health = journal.record_failure("channel:test", NotImplementedError("invariant-b"))
            reopened = journal.maintenance_task("channel:test")
            self.assertEqual(reopened["task_id"], first_task["task_id"])
            self.assertEqual(reopened["status"], "open")
            self.assertEqual(reopened["fingerprint"], second_health["last_fingerprint"])
            self.assertNotEqual(reopened["fingerprint"], first_task["fingerprint"])
            self.assertEqual(reopened["exception_type"], "NotImplementedError")
            self.assertEqual(reopened["occurrences"], 3)
            self.assertIsNone(reopened["closed_at"])
            self.assertIsNone(reopened["close_reason"])
            self.assertEqual(journal.maintenance_tasks()["task_count"], 1)
            self.assertEqual(journal.maintenance_tasks()["open_count"], 1)

    def test_open_task_closes_when_current_failure_evidence_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = ResidentHealthJournal(SimpleNamespace(path=Path(tmp) / "kernel.db"))
            for _ in range(3):
                first = journal.record_failure("channel:test", AssertionError("invariant-a"))
            opened = journal.maintenance_task("channel:test")
            self.assertEqual(opened["status"], "open")
            self.assertEqual(opened["fingerprint"], first["last_fingerprint"])

            changed = journal.record_failure("channel:test", AssertionError("invariant-b"))
            self.assertFalse(changed["maintenance_candidate"])
            stale_closed = journal.maintenance_task("channel:test")
            self.assertEqual(stale_closed["status"], "closed")
            self.assertEqual(stale_closed["close_reason"], "evidence_changed")

            journal.record_failure("channel:test", AssertionError("invariant-b"))
            current = journal.record_failure("channel:test", AssertionError("invariant-b"))
            reopened = journal.maintenance_task("channel:test")
            self.assertTrue(current["maintenance_candidate"])
            self.assertEqual(reopened["status"], "open")
            self.assertEqual(reopened["fingerprint"], current["last_fingerprint"])
            self.assertEqual(reopened["occurrences"], 3)

    def test_task_projection_failure_does_not_rollback_health_and_restart_repairs_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            journal = ResidentHealthJournal(SimpleNamespace(path=db))
            conn = sqlite3.connect(db)
            try:
                conn.execute(
                    """
                    CREATE TRIGGER block_maintenance_insert
                    BEFORE INSERT ON resident_maintenance_tasks
                    BEGIN SELECT RAISE(ABORT, 'task projection blocked'); END
                    """
                )
                conn.commit()
            finally:
                conn.close()

            for _ in range(3):
                health = journal.record_failure("channel:test", AssertionError("durable-health"))

            self.assertTrue(health["maintenance_candidate"])
            self.assertEqual(health["consecutive_failures"], 3)
            self.assertIsNone(journal.maintenance_task("channel:test"))

            conn = sqlite3.connect(db)
            try:
                conn.execute("DROP TRIGGER block_maintenance_insert")
                conn.commit()
            finally:
                conn.close()

            repaired = ResidentHealthJournal(SimpleNamespace(path=db))
            durable = repaired.get("channel:test")
            task = repaired.maintenance_task("channel:test")
            self.assertTrue(durable["maintenance_candidate"])
            self.assertIsNotNone(task)
            self.assertEqual(task["status"], "open")
            self.assertEqual(task["fingerprint"], durable["last_fingerprint"])

    def test_task_close_failure_does_not_rollback_recovery_and_restart_repairs_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            journal = ResidentHealthJournal(SimpleNamespace(path=db))
            for _ in range(3):
                journal.record_failure("channel:test", AssertionError("durable-health"))
            self.assertEqual(journal.maintenance_task("channel:test")["status"], "open")

            conn = sqlite3.connect(db)
            try:
                conn.execute(
                    """
                    CREATE TRIGGER block_maintenance_update
                    BEFORE UPDATE ON resident_maintenance_tasks
                    BEGIN SELECT RAISE(ABORT, 'task close blocked'); END
                    """
                )
                conn.commit()
            finally:
                conn.close()

            recovered = journal.record_success("channel:test")
            self.assertTrue(recovered["healthy"])
            self.assertEqual(recovered["consecutive_failures"], 0)
            self.assertEqual(journal.maintenance_task("channel:test")["status"], "open")

            conn = sqlite3.connect(db)
            try:
                conn.execute("DROP TRIGGER block_maintenance_update")
                conn.commit()
            finally:
                conn.close()

            repaired = ResidentHealthJournal(SimpleNamespace(path=db))
            self.assertTrue(repaired.get("channel:test")["healthy"])
            task = repaired.maintenance_task("channel:test")
            self.assertEqual(task["status"], "closed")
            self.assertEqual(task["close_reason"], "organ_recovered")

    def test_ambiguous_programming_or_payload_failure_stays_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = ResidentHealthJournal(SimpleNamespace(path=Path(tmp) / "kernel.db"))
            for _ in range(4):
                state = journal.record_failure("channel:test", TypeError("unexpected payload shape"))

            self.assertEqual(state["last_failure_class"], "programming_or_data_contract")
            self.assertEqual(state["repeat_fingerprint_failures"], 4)
            self.assertFalse(state["maintenance_candidate"])
            self.assertEqual(journal.snapshot()["maintenance_candidate_count"], 0)
            self.assertIsNone(journal.maintenance_task("channel:test"))

    def test_external_failure_never_becomes_source_maintenance_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = ResidentHealthJournal(SimpleNamespace(path=Path(tmp) / "kernel.db"))
            for _ in range(4):
                state = journal.record_failure("channel:test", TimeoutError("upstream timed out"))

            self.assertEqual(state["last_failure_class"], "network_or_service")
            self.assertEqual(state["repeat_fingerprint_failures"], 4)
            self.assertFalse(state["maintenance_candidate"])
            self.assertEqual(journal.snapshot()["maintenance_candidate_count"], 0)
            self.assertIsNone(journal.maintenance_task("channel:test"))

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
            self.assertIsNone(journal.maintenance_task("channel:test"))

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
            self.assertEqual(journal.maintenance_tasks()["task_count"], 0)

            updated = journal.record_failure("channel:test", TypeError("new-shape"))
            self.assertEqual(updated["total_failures"], 3)
            self.assertEqual(updated["consecutive_failures"], 3)
            self.assertEqual(updated["repeat_fingerprint_failures"], 1)
            self.assertEqual(updated["last_failure_class"], "programming_or_data_contract")
            self.assertFalse(updated["maintenance_candidate"])
            self.assertIsNone(journal.maintenance_task("channel:test"))


if __name__ == "__main__":
    unittest.main()
