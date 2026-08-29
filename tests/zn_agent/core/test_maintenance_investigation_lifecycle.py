from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.health_observation import ResidentHealthJournal
from zn_agent.core.maintenance_investigation import MaintenanceInvestigationLedger


class MaintenanceInvestigationLifecycleTests(unittest.TestCase):
    @staticmethod
    def _store(tmp: str):
        return SimpleNamespace(path=Path(tmp) / "kernel.db")

    @staticmethod
    def _open_task(journal: ResidentHealthJournal, message: str = "broken invariant"):
        health = None
        for _ in range(3):
            health = journal.record_failure("channel:test", AssertionError(message))
        task = journal.maintenance_task("channel:test")
        assert health is not None
        assert task is not None
        return health, task

    def test_separate_health_journal_task_is_reconciled_and_recovery_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            bootstrap = ResidentHealthJournal(store)
            ledger = MaintenanceInvestigationLedger(store)

            # Simulate a channel supervisor that owns a separate health-journal
            # object against the same resident DB. Lifecycle read-through must
            # discover its task without sharing an in-memory callback.
            channel_health = ResidentHealthJournal(store)
            health, task = self._open_task(channel_health)

            investigation = ledger.get(task["task_id"])
            self.assertIsNotNone(investigation)
            self.assertEqual(investigation["status"], "pending")
            self.assertEqual(investigation["source_task_status"], "open")
            self.assertEqual(investigation["authority"], "evidence_only")
            self.assertEqual(investigation["task_fingerprint"], health["last_fingerprint"])
            self.assertEqual(investigation["observed_occurrences"], 3)
            self.assertEqual(ledger.snapshot()["active_count"], 1)

            recovered = channel_health.record_success("channel:test")
            self.assertTrue(recovered["healthy"])
            closed = ledger.get(task["task_id"])
            self.assertEqual(closed["source_task_status"], "closed")
            self.assertEqual(closed["status"], "closed")
            self.assertEqual(closed["close_reason"], "organ_recovered")
            self.assertEqual(ledger.snapshot()["active_count"], 0)
            self.assertIsNotNone(bootstrap)

    def test_lifecycle_requires_baseline_isolated_branch_and_passing_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            journal = ResidentHealthJournal(store)
            ledger = MaintenanceInvestigationLedger(store)
            _, task = self._open_task(journal)
            task_id = task["task_id"]

            with self.assertRaises(RuntimeError):
                ledger.record_attempt(
                    task_id,
                    attempt_key="attempt-0",
                    branch_ref="work/test",
                    regression_passed=True,
                    evidence_ref="ci:0",
                )

            started = ledger.begin(
                task_id,
                baseline_ref="commit:abc123",
                regression_oracle="test:tests/zn_agent/core/test_example.py",
            )
            self.assertEqual(started["status"], "investigating")
            self.assertEqual(started["authority"], "evidence_only")

            with self.assertRaises(ValueError):
                ledger.record_attempt(
                    task_id,
                    attempt_key="attempt-bad-branch",
                    branch_ref="dev/zn-agent",
                    regression_passed=True,
                    evidence_ref="ci:bad",
                )

            first = ledger.record_attempt(
                task_id,
                attempt_key="attempt-1",
                branch_ref="work/self-maintenance-test",
                regression_passed=False,
                evidence_ref="ci:1",
            )
            self.assertEqual(first["attempt_count"], 1)
            with self.assertRaises(RuntimeError):
                ledger.accept(task_id, attempt_key="attempt-1")

            second = ledger.record_attempt(
                task_id,
                attempt_key="attempt-2",
                branch_ref="work/self-maintenance-test",
                regression_passed=True,
                evidence_ref="ci:2",
            )
            duplicate = ledger.record_attempt(
                task_id,
                attempt_key="attempt-2",
                branch_ref="work/self-maintenance-test",
                regression_passed=True,
                evidence_ref="ci:2-duplicate",
            )
            self.assertEqual(second["attempt_count"], 2)
            self.assertEqual(duplicate["attempt_count"], 2)

            accepted = ledger.accept(task_id, attempt_key="attempt-2")
            self.assertEqual(accepted["status"], "accepted")
            self.assertEqual(accepted["acceptance_state"], "accepted")
            self.assertEqual(accepted["accepted_attempt_key"], "attempt-2")
            self.assertEqual(accepted["authority"], "evidence_only")

    def test_changed_incident_resets_attempts_and_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            journal = ResidentHealthJournal(store)
            ledger = MaintenanceInvestigationLedger(store)
            _, first_task = self._open_task(journal, "invariant-a")
            task_id = first_task["task_id"]

            ledger.begin(
                task_id,
                baseline_ref="commit:one",
                regression_oracle="test:oracle-one",
            )
            ledger.record_attempt(
                task_id,
                attempt_key="attempt-a",
                branch_ref="work/incident-a",
                regression_passed=True,
                evidence_ref="ci:a",
            )
            ledger.accept(task_id, attempt_key="attempt-a")

            # One changed fingerprint removes candidate status and closes the
            # source task; repeated new evidence reopens the same per-organ task.
            journal.record_failure("channel:test", AssertionError("invariant-b"))
            journal.record_failure("channel:test", AssertionError("invariant-b"))
            new_health = journal.record_failure("channel:test", AssertionError("invariant-b"))
            reopened_task = journal.maintenance_task("channel:test")
            self.assertEqual(reopened_task["task_id"], task_id)
            self.assertEqual(reopened_task["status"], "open")

            reset = ledger.get(task_id)
            self.assertEqual(reset["status"], "pending")
            self.assertEqual(reset["task_fingerprint"], new_health["last_fingerprint"])
            self.assertEqual(reset["attempt_count"], 0)
            self.assertEqual(reset["acceptance_state"], "unreviewed")
            self.assertIsNone(reset["accepted_attempt_key"])
            self.assertIsNone(reset["baseline_ref"])
            self.assertIsNone(reset["regression_oracle"])

            ledger.begin(
                task_id,
                baseline_ref="commit:two",
                regression_oracle="test:oracle-two",
            )
            replayed_key = ledger.record_attempt(
                task_id,
                attempt_key="attempt-a",
                branch_ref="work/incident-b",
                regression_passed=False,
                evidence_ref="ci:b",
            )
            self.assertEqual(replayed_key["attempt_count"], 1)

    def test_changing_investigation_contract_invalidates_old_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            journal = ResidentHealthJournal(store)
            ledger = MaintenanceInvestigationLedger(store)
            _, task = self._open_task(journal)
            task_id = task["task_id"]

            ledger.begin(
                task_id,
                baseline_ref="commit:one",
                regression_oracle="test:oracle-one",
            )
            ledger.record_attempt(
                task_id,
                attempt_key="attempt-1",
                branch_ref="work/contract-one",
                regression_passed=True,
                evidence_ref="ci:1",
            )

            changed = ledger.begin(
                task_id,
                baseline_ref="commit:one",
                regression_oracle="test:oracle-two",
            )
            self.assertEqual(changed["attempt_count"], 0)
            self.assertEqual(changed["acceptance_state"], "unreviewed")
            again = ledger.record_attempt(
                task_id,
                attempt_key="attempt-1",
                branch_ref="work/contract-two",
                regression_passed=False,
                evidence_ref="ci:2",
            )
            self.assertEqual(again["attempt_count"], 1)

    def test_rejected_evidence_cannot_be_reaccepted_without_fresh_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            journal = ResidentHealthJournal(store)
            ledger = MaintenanceInvestigationLedger(store)
            _, task = self._open_task(journal)
            task_id = task["task_id"]

            ledger.begin(
                task_id,
                baseline_ref="commit:one",
                regression_oracle="test:oracle-one",
            )
            ledger.record_attempt(
                task_id,
                attempt_key="attempt-accepted-before-review",
                branch_ref="work/rejected-evidence",
                regression_passed=True,
                evidence_ref="ci:one",
            )
            rejected = ledger.reject(task_id, reason="diff_review_rejected")
            self.assertEqual(rejected["status"], "rejected")

            restarted = ledger.begin(
                task_id,
                baseline_ref="commit:one",
                regression_oracle="test:oracle-one",
            )
            self.assertEqual(restarted["attempt_count"], 0)
            self.assertEqual(restarted["acceptance_state"], "unreviewed")
            with self.assertRaises(ValueError):
                ledger.accept(task_id, attempt_key="attempt-accepted-before-review")

    def test_closed_task_preserves_attempt_history_until_a_new_incident(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            journal = ResidentHealthJournal(store)
            ledger = MaintenanceInvestigationLedger(store)
            _, task = self._open_task(journal)
            task_id = task["task_id"]

            ledger.begin(
                task_id,
                baseline_ref="commit:one",
                regression_oracle="test:oracle-one",
            )
            ledger.record_attempt(
                task_id,
                attempt_key="attempt-history",
                branch_ref="work/history",
                regression_passed=True,
                evidence_ref="ci:history",
            )
            ledger.accept(task_id, attempt_key="attempt-history")

            journal.record_success("channel:test")
            closed = ledger.get(task_id)
            self.assertEqual(closed["status"], "closed")
            self.assertEqual(closed["attempt_count"], 1)
            self.assertEqual(closed["accepted_attempt_key"], "attempt-history")
            self.assertEqual(closed["acceptance_state"], "accepted")

    def test_damaged_investigation_projection_cannot_block_health_or_task_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            journal = ResidentHealthJournal(store)
            ledger = MaintenanceInvestigationLedger(store)
            _, task = self._open_task(journal)
            self.assertIsNotNone(ledger.get(task["task_id"]))

            # Simulate loss/corruption of the secondary projection. Because the
            # ledger installs no triggers on resident_maintenance_tasks, health
            # truth and task recovery must remain independently writable.
            with closing(sqlite3.connect(store.path)) as conn:
                conn.execute("DROP TABLE resident_maintenance_attempts")
                conn.execute("DROP TABLE resident_maintenance_investigations")
                conn.commit()

            recovered = journal.record_success("channel:test")
            self.assertTrue(recovered["healthy"])
            recovered_task = journal.maintenance_task("channel:test")
            self.assertEqual(recovered_task["status"], "closed")
            self.assertEqual(recovered_task["close_reason"], "organ_recovered")

    def test_restart_reconciles_task_that_predates_lifecycle_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            journal = ResidentHealthJournal(store)
            health, task = self._open_task(journal, "predates-ledger")

            ledger = MaintenanceInvestigationLedger(store)
            restored = ledger.get(task["task_id"])
            self.assertIsNotNone(restored)
            self.assertEqual(restored["status"], "pending")
            self.assertEqual(restored["task_fingerprint"], health["last_fingerprint"])
            self.assertEqual(restored["observed_occurrences"], 3)
            self.assertEqual(restored["authority"], "evidence_only")


if __name__ == "__main__":
    unittest.main()
