from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.models import EventStatus
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


if __name__ == "__main__":
    unittest.main()
