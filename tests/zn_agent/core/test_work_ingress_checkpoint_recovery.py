from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.models import EventStatus
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_control import ResidentWorkControl


class WorkIngressCheckpointRecoveryTests(unittest.TestCase):
    def test_restart_restores_message_accepted_before_resident_event_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            thread = ledger.create_thread(thread_id="work-pre-event-crash")

            original_enqueue = resident.store.enqueue_event

            def crash_before_event_persistence(event):
                raise SystemExit("simulated hard exit after Work message persistence")

            resident.store.enqueue_event = crash_before_event_persistence
            with self.assertRaisesRegex(SystemExit, "simulated hard exit"):
                ledger.start(
                    thread.thread_id,
                    "restore accepted Work without inventing replay authority",
                )
            resident.store.enqueue_event = original_enqueue

            messages = ledger.list_messages(thread.thread_id)
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0].role, "user")
            self.assertEqual(
                messages[0].text,
                "restore accepted Work without inventing replay authority",
            )
            self.assertEqual(resident.store.list_events(limit=10), [])
            self.assertIsNone(ledger._active_run_for_thread(thread.thread_id))
            with ledger._lock, closing(ledger._connect()) as conn:
                checkpoint = conn.execute(
                    f"SELECT * FROM {ledger._INGRESS_TABLE} WHERE thread_id=?",
                    (thread.thread_id,),
                ).fetchone()
            self.assertIsNotNone(checkpoint)
            assert checkpoint is not None
            expected_event_id = str(checkpoint["event_id"])
            expected_message_id = str(checkpoint["message_id"])
            self.assertEqual(expected_message_id, messages[0].message_id)
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            restored_ledger = RecoveryBoundedWorkLedger(restored)
            control = ResidentWorkControl(restored_ledger)
            try:
                event = restored.store.get_event(expected_event_id)
                self.assertIsNotNone(event)
                assert event is not None
                self.assertEqual(event.status, EventStatus.PENDING)
                self.assertEqual(event.attempts, 0)
                self.assertEqual(event.payload["work_thread_id"], thread.thread_id)
                self.assertEqual(event.payload["work_message_id"], expected_message_id)

                run = restored_ledger.get_run(expected_event_id)
                self.assertIsNotNone(run)
                assert run is not None
                self.assertEqual(run.thread_id, thread.thread_id)
                self.assertEqual(run.message_id, expected_message_id)
                self.assertEqual(run.ledger_state, "active")

                restored_messages = restored_ledger.list_messages(thread.thread_id)
                self.assertEqual(len(restored_messages), 1)
                self.assertEqual(restored_messages[0].message_id, expected_message_id)

                with restored_ledger._lock, closing(restored_ledger._connect()) as conn:
                    remaining = conn.execute(
                        f"SELECT COUNT(*) AS n FROM {restored_ledger._INGRESS_TABLE}"
                    ).fetchone()
                self.assertEqual(int(remaining["n"]), 0)

                progress = control.progress(thread.thread_id, expected_event_id)
                self.assertEqual(progress["status"], "pending")
                self.assertEqual(progress["stage"], "queued")
                self.assertFalse(progress["terminal"])
                self.assertFalse(progress["finalized"])

                with self.assertRaisesRegex(ValueError, "already has an active"):
                    control.start(
                        thread.thread_id,
                        "must not duplicate the recovered accepted Work",
                    )
            finally:
                restored.store.close()

    def test_restart_with_existing_event_repairs_linkage_without_duplicate_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            thread = ledger.create_thread(thread_id="work-post-event-crash")

            original_save_run = ledger._save_run

            def crash_before_work_run(run):
                raise SystemExit("simulated hard exit after resident event persistence")

            ledger._save_run = crash_before_work_run
            with self.assertRaisesRegex(SystemExit, "simulated hard exit"):
                ledger.start(
                    thread.thread_id,
                    "repair linkage without duplicating the durable resident event",
                )
            ledger._save_run = original_save_run

            events = resident.store.list_events(limit=10)
            self.assertEqual(len(events), 1)
            expected_event_id = events[0].event_id
            self.assertEqual(events[0].status, EventStatus.PENDING)
            self.assertEqual(events[0].attempts, 0)
            self.assertIsNone(ledger.get_run(expected_event_id))
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            restored_ledger = RecoveryBoundedWorkLedger(restored)
            try:
                events_after = restored.store.list_events(limit=10)
                self.assertEqual(len(events_after), 1)
                self.assertEqual(events_after[0].event_id, expected_event_id)
                self.assertEqual(events_after[0].status, EventStatus.PENDING)
                self.assertEqual(events_after[0].attempts, 0)

                run = restored_ledger.get_run(expected_event_id)
                self.assertIsNotNone(run)
                assert run is not None
                self.assertEqual(run.thread_id, thread.thread_id)
                self.assertEqual(run.message_id, events_after[0].payload["work_message_id"])

                with restored_ledger._lock, closing(restored_ledger._connect()) as conn:
                    remaining = conn.execute(
                        f"SELECT COUNT(*) AS n FROM {restored_ledger._INGRESS_TABLE}"
                    ).fetchone()
                self.assertEqual(int(remaining["n"]), 0)
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main()
