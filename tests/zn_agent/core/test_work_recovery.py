from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.models import (
    EventOutcome,
    EventStatus,
    ExecutionPath,
    WorkingState,
)
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.work import ResidentWorkLedger


class ResidentWorkRecoveryTests(unittest.TestCase):
    def test_active_work_resumes_from_persisted_stage_after_resident_reconstruction(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = ResidentWorkLedger(resident)
            snapshot, event = ledger.start(
                "work-restart",
                "investigate an unknown local problem without external cognition",
                payload={"allow_memory": False},
            )
            self.assertEqual([message.role for message in snapshot[1]], ["user"])

            first = resident.live_once()
            self.assertIsNone(first)
            active_event = resident.store.get_event(event.event_id)
            self.assertIsNotNone(active_event)
            assert active_event is not None
            self.assertEqual(active_event.status, EventStatus.PROCESSING)
            before = resident.store.get_working_state()
            self.assertEqual(before.current_event_id, event.event_id)
            self.assertNotIn(before.stage, {"idle", "complete", "failed"})
            self.assertNotEqual(before.stage, "orient")
            checkpoint_stage = before.stage
            checkpoint_next = before.next_action
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            restored_ledger = ResidentWorkLedger(restored)
            try:
                recovered_event = restored.store.get_event(event.event_id)
                self.assertIsNotNone(recovered_event)
                assert recovered_event is not None
                self.assertEqual(recovered_event.status, EventStatus.PENDING)
                self.assertIn("runtime restarted", recovered_event.last_error or "")

                recovered = restored.store.get_working_state()
                self.assertEqual(recovered.current_event_id, event.event_id)
                self.assertEqual(recovered.stage, checkpoint_stage)
                self.assertEqual(recovered.next_action, checkpoint_next)

                progress = restored_ledger.progress("work-restart", event.event_id)
                self.assertFalse(progress["terminal"])
                self.assertFalse(progress["finalized"])
                self.assertEqual(progress["stage"], checkpoint_stage)
                self.assertEqual(progress["next_action"], checkpoint_next)

                result = None
                for _ in range(24):
                    result = restored.live_once()
                    completed = restored.result_for(event.event_id)
                    if completed is not None:
                        result = completed
                        break
                self.assertIsNotNone(result, "recovered work did not reach a durable outcome")

                final = restored_ledger.progress("work-restart", event.event_id)
                self.assertTrue(final["terminal"])
                self.assertTrue(final["finalized"])
                _, messages = restored_ledger.get_snapshot("work-restart")
                self.assertEqual([message.role for message in messages], ["user", "zn", "activity"])
                self.assertEqual(messages[-1].detail["event_id"], event.event_id)
                self.assertEqual(
                    len([message for message in messages if message.role == "user"]),
                    1,
                )
            finally:
                restored.store.close()

    def test_resolved_investigation_completion_survives_restart_without_reprobe(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = ResidentWorkLedger(first)
            _, event = ledger.start(
                "work-investigation-terminal",
                "what is my current working directory?",
                payload={"allow_memory": False},
            )

            self.assertIsNone(first.live_once())
            state = first.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            claimed = first.store.claim_event(event.event_id)
            self.assertIsNotNone(claimed)
            readiness = first.kernel.self_model.assess_task(
                claimed.task,
                first._required_capabilities(claimed),
            )
            result = first._investigation_step(
                claimed,
                state,
                readiness=readiness,
                learning_evidence=[],
            )
            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.INVESTIGATION)
            self.assertEqual(result.response, str(Path.cwd()))
            checkpoint = first.store.get_working_state()
            self.assertEqual(checkpoint.stage, "investigation_completion")
            self.assertEqual(
                checkpoint.data["investigation_completion"]["response"],
                str(Path.cwd()),
            )
            self.assertIsNone(first.store.get_event_outcome(event.event_id))
            tasks_before = first.store.get_runtime_metrics().tasks_total
            rounds_before = first.investigator.current(event.event_id).rounds
            first.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            restored_ledger = ResidentWorkLedger(restored)
            try:
                recovered = restored.store.get_working_state()
                self.assertEqual(recovered.current_event_id, event.event_id)
                self.assertEqual(recovered.stage, "investigation_completion")
                self.assertEqual(restored.store.get_event(event.event_id).status, EventStatus.PENDING)

                with patch.object(
                    restored.investigator,
                    "investigate",
                    side_effect=AssertionError("resolved investigation must not probe again"),
                ):
                    terminal = restored.run_once(target_event_id=event.event_id)

                self.assertIsNotNone(terminal)
                assert terminal is not None
                self.assertTrue(terminal.success)
                self.assertEqual(terminal.execution_path, ExecutionPath.INVESTIGATION)
                self.assertEqual(terminal.response, str(Path.cwd()))
                self.assertEqual(restored.store.get_runtime_metrics().tasks_total, tasks_before)
                self.assertEqual(
                    restored.investigator.current(event.event_id).rounds,
                    rounds_before,
                )
                outcome = restored.store.get_event_outcome(event.event_id)
                self.assertIsNotNone(outcome)
                assert outcome is not None
                self.assertTrue(outcome.success)
                self.assertEqual(outcome.execution_path, ExecutionPath.INVESTIGATION)
                idle = restored.store.get_working_state()
                self.assertEqual(idle.stage, "idle")
                self.assertIsNone(idle.current_event_id)
                progress = restored_ledger.progress(
                    "work-investigation-terminal",
                    event.event_id,
                )
                self.assertTrue(progress["terminal"])
                self.assertTrue(progress["finalized"])
            finally:
                restored.store.close()

    def test_reconstruction_does_not_allow_second_work_item_to_replace_active_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = ResidentWorkLedger(resident)
            _, event = ledger.start(
                "work-restart-serial",
                "investigate another unknown local problem",
                payload={"allow_memory": False},
            )
            resident.live_once()
            checkpoint = resident.store.get_working_state()
            self.assertEqual(checkpoint.current_event_id, event.event_id)
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            restored_ledger = ResidentWorkLedger(restored)
            try:
                with self.assertRaisesRegex(ValueError, "already has an active"):
                    restored_ledger.start(
                        "work-restart-serial",
                        "replacement task must not steal the active work thread",
                    )
                after = restored.store.get_working_state()
                self.assertEqual(after.current_event_id, event.event_id)
                self.assertEqual(after.stage, checkpoint.stage)
                messages = restored_ledger.list_messages("work-restart-serial")
                self.assertEqual([message.role for message in messages], ["user"])
            finally:
                restored.store.close()

    def test_terminal_completion_is_durable_with_outcome_and_idle_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = ResidentWorkLedger(resident)
            resident.memory.remember("atomic terminal work", "durable atomic result")
            _, event = ledger.start("work-atomic-terminal", "atomic terminal work")

            result = resident.live_once()
            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.success)

            terminal = resident.store.get_event(event.event_id)
            outcome = resident.store.get_event_outcome(event.event_id)
            idle = resident.store.get_working_state()
            self.assertIsNotNone(terminal)
            self.assertIsNotNone(outcome)
            assert terminal is not None
            assert outcome is not None
            self.assertEqual(terminal.status, EventStatus.COMPLETED)
            self.assertTrue(outcome.success)
            self.assertEqual(outcome.response, "durable atomic result")
            self.assertEqual(idle.stage, "idle")
            self.assertIsNone(idle.current_event_id)
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            restored_ledger = ResidentWorkLedger(restored)
            try:
                reconstructed = restored.result_for(event.event_id)
                self.assertIsNotNone(reconstructed)
                assert reconstructed is not None
                self.assertTrue(reconstructed.success)
                self.assertEqual(reconstructed.response, "durable atomic result")
                persisted = restored.store.get_event(event.event_id)
                self.assertIsNotNone(persisted)
                assert persisted is not None
                self.assertEqual(persisted.status, EventStatus.COMPLETED)
                self.assertEqual(restored.store.get_working_state().stage, "idle")

                progress = restored_ledger.progress("work-atomic-terminal", event.event_id)
                self.assertTrue(progress["terminal"])
                self.assertTrue(progress["finalized"])
            finally:
                restored.store.close()

    def test_atomic_terminal_transition_allows_claimed_event_without_owned_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                event = resident.enqueue("complete directly from a claimed resident event")
                claimed = resident.store.claim_event(event.event_id)
                self.assertIsNotNone(claimed)
                idle_before = resident.store.get_working_state()
                self.assertEqual(idle_before.stage, "idle")
                self.assertIsNone(idle_before.current_event_id)

                completed = resident.store.complete_event(
                    EventOutcome(
                        event_id=event.event_id,
                        success=True,
                        execution_path=ExecutionPath.INVESTIGATION,
                        response="claimed completion",
                    )
                )

                self.assertEqual(completed.status, EventStatus.COMPLETED)
                self.assertIsNotNone(resident.store.get_event_outcome(event.event_id))
                idle_after = resident.store.get_working_state()
                self.assertEqual(idle_after.stage, "idle")
                self.assertIsNone(idle_after.current_event_id)
            finally:
                resident.store.close()

    def test_atomic_terminal_transition_refuses_foreign_active_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                event = resident.enqueue("must not erase foreign checkpoint")
                claimed = resident.store.claim_event(event.event_id)
                self.assertIsNotNone(claimed)
                resident.store.save_working_state(
                    WorkingState(
                        current_event_id="evt-foreign-active",
                        stage="native_action",
                        next_action="preserve foreign work",
                        data={"sentinel": "foreign"},
                    )
                )

                with self.assertRaisesRegex(RuntimeError, "another event checkpoint"):
                    resident.store.complete_event(
                        EventOutcome(
                            event_id=event.event_id,
                            success=True,
                            execution_path=ExecutionPath.INVESTIGATION,
                            response="must not commit",
                        )
                    )

                persisted = resident.store.get_event(event.event_id)
                self.assertIsNotNone(persisted)
                assert persisted is not None
                self.assertEqual(persisted.status, EventStatus.PROCESSING)
                self.assertIsNone(resident.store.get_event_outcome(event.event_id))
                foreign = resident.store.get_working_state()
                self.assertEqual(foreign.current_event_id, "evt-foreign-active")
                self.assertEqual(foreign.data, {"sentinel": "foreign"})
            finally:
                resident.store.close()

    def test_atomic_terminal_transition_rolls_back_all_three_records_on_outcome_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                event = resident.enqueue("force atomic completion rollback")
                claimed = resident.store.claim_event(event.event_id)
                self.assertIsNotNone(claimed)
                resident.store.save_working_state(
                    WorkingState(
                        current_event_id=event.event_id,
                        stage="native_memory",
                        next_action="complete",
                        data={"sentinel": "keep-checkpoint"},
                    )
                )
                before = resident.store.get_working_state()

                with resident.store._lock, resident.store._conn:
                    resident.store._conn.execute(
                        """
                        CREATE TRIGGER fail_atomic_outcome_insert
                        BEFORE INSERT ON event_outcomes
                        BEGIN
                            SELECT RAISE(ABORT, 'forced outcome insert failure');
                        END
                        """
                    )

                with self.assertRaises(sqlite3.IntegrityError):
                    resident.store.complete_event(
                        EventOutcome(
                            event_id=event.event_id,
                            success=True,
                            execution_path=ExecutionPath.MEMORY,
                            response="must roll back",
                        )
                    )

                persisted = resident.store.get_event(event.event_id)
                self.assertIsNotNone(persisted)
                assert persisted is not None
                self.assertEqual(persisted.status, EventStatus.PROCESSING)
                self.assertIsNone(resident.store.get_event_outcome(event.event_id))
                after = resident.store.get_working_state()
                self.assertEqual(after.current_event_id, before.current_event_id)
                self.assertEqual(after.stage, before.stage)
                self.assertEqual(after.next_action, before.next_action)
                self.assertEqual(after.data, before.data)
            finally:
                try:
                    with resident.store._lock, resident.store._conn:
                        resident.store._conn.execute(
                            "DROP TRIGGER IF EXISTS fail_atomic_outcome_insert"
                        )
                finally:
                    resident.store.close()


if __name__ == "__main__":
    unittest.main()
