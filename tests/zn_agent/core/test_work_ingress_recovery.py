from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import EventStatus
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.work import ResidentWorkLedger, WorkMessage


class ResidentWorkIngressRecoveryTests(unittest.TestCase):
    def test_restart_repairs_enqueued_event_missing_work_run_without_executing_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = ResidentWorkLedger(resident)
            thread = ledger.create_thread(thread_id="work-ingress-gap")
            message = WorkMessage(
                message_id="msg-ingress-gap",
                thread_id=thread.thread_id,
                role="user",
                text="recover the Work ingress linkage",
            )
            ledger._append(thread, message)

            event = resident.enqueue(
                message.text,
                kind="desktop_user_event",
                payload={
                    "work_thread_id": thread.thread_id,
                    "work_message_id": message.message_id,
                },
            )
            before = resident.store.get_event(event.event_id)
            self.assertIsNotNone(before)
            assert before is not None
            self.assertEqual(before.status, EventStatus.PENDING)
            self.assertEqual(before.attempts, 0)
            self.assertIsNone(ledger.get_run(event.event_id))
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            server = ResidentRpcServer(
                resident=restored,
                input_stream=io.StringIO(),
                output_stream=io.StringIO(),
            )
            try:
                repaired = server.work.get_run(event.event_id)
                self.assertIsNotNone(repaired)
                assert repaired is not None
                self.assertEqual(repaired.thread_id, thread.thread_id)
                self.assertEqual(repaired.message_id, message.message_id)
                self.assertEqual(repaired.task, message.text)
                self.assertEqual(repaired.ledger_state, "active")

                unchanged = restored.store.get_event(event.event_id)
                self.assertIsNotNone(unchanged)
                assert unchanged is not None
                self.assertEqual(unchanged.status, EventStatus.PENDING)
                self.assertEqual(unchanged.attempts, 0)
                checkpoint = restored.store.get_working_state()
                self.assertEqual(checkpoint.stage, "idle")
                self.assertIsNone(checkpoint.current_event_id)

                progress = server.work_control.progress(
                    thread.thread_id,
                    event.event_id,
                )
                self.assertEqual(progress["status"], "pending")
                self.assertEqual(progress["stage"], "queued")
                self.assertFalse(progress["terminal"])
                self.assertFalse(progress["finalized"])

                with self.assertRaisesRegex(ValueError, "already has an active"):
                    server.work_control.start(
                        thread.thread_id,
                        "must not create duplicate Work while repaired event is active",
                    )
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main()
