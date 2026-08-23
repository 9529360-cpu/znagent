from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.work import ResidentWorkLedger


class ResidentWorkProgressTests(unittest.TestCase):
    def test_started_work_is_durable_before_completion_and_progress_finalizes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            resident.memory.remember("progress task", "remembered result")
            ledger = ResidentWorkLedger(resident)

            snapshot, event = ledger.start("work-progress", "progress task")
            self.assertEqual([message.role for message in snapshot[1]], ["user"])
            self.assertEqual(event.payload["work_thread_id"], "work-progress")
            self.assertEqual(event.payload["work_message_id"], snapshot[1][0].message_id)

            pending = ledger.progress("work-progress", event.event_id)
            self.assertEqual(pending["status"], "pending")
            self.assertEqual(pending["stage"], "queued")
            self.assertFalse(pending["terminal"])
            self.assertFalse(pending["finalized"])

            body = getattr(resident, "body", None)
            self.assertIsNotNone(body)
            body.act("inspect_path", event_id=event.event_id, path=str(root))
            with_body = ledger.progress("work-progress", event.event_id)
            self.assertTrue(
                any(item["kind"] == "inspect_path" for item in with_body["body_actions"])
            )

            resident.live_once()
            self.assertIsNotNone(resident.result_for(event.event_id))

            completed = ledger.progress("work-progress", event.event_id)
            self.assertTrue(completed["terminal"])
            self.assertTrue(completed["finalized"])
            self.assertEqual(completed["stage"], "complete")
            final_thread, messages = ledger.get_snapshot("work-progress")
            self.assertEqual(final_thread.thread_id, "work-progress")
            self.assertEqual([message.role for message in messages], ["user", "zn", "activity"])
            self.assertEqual(messages[-1].detail["event_id"], event.event_id)

            again = ledger.progress("work-progress", event.event_id)
            self.assertTrue(again["finalized"])
            _, messages_again = ledger.get_snapshot("work-progress")
            self.assertEqual(
                [message.message_id for message in messages_again],
                [message.message_id for message in messages],
            )
            resident.store.close()

    def test_completed_background_work_is_finalized_after_resident_reconstruction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            resident.memory.remember("detached work", "finished while desktop was away")
            ledger = ResidentWorkLedger(resident)
            _, event = ledger.start("work-detached", "detached work")
            resident.live_once()
            self.assertIsNotNone(resident.result_for(event.event_id))
            self.assertEqual(
                [message.role for message in ledger.list_messages("work-detached")],
                ["user"],
            )
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            restored_ledger = ResidentWorkLedger(restored)
            _, messages = restored_ledger.get_snapshot("work-detached")
            self.assertEqual([message.role for message in messages], ["user", "zn", "activity"])
            self.assertEqual(messages[1].text, "finished while desktop was away")
            run = restored_ledger.get_run(event.event_id)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run.ledger_state, "finalized")
            restored.store.close()

    def test_thread_rejects_parallel_active_resident_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            ledger = ResidentWorkLedger(resident)
            ledger.start("work-serial", "first pending task")
            with self.assertRaisesRegex(ValueError, "already has an active"):
                ledger.start("work-serial", "second pending task")
            resident.store.close()

    def test_work_start_and_progress_rpc_use_background_event_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            resident.memory.remember("rpc progress", "rpc completed")
            server = ResidentRpcServer(
                resident=resident,
                input_stream=io.StringIO(),
                output_stream=io.StringIO(),
            )

            started = server.handle(
                {
                    "id": "start",
                    "method": "work_start",
                    "params": {"thread_id": "work-rpc-progress", "task": "rpc progress"},
                }
            )
            self.assertTrue(started["ok"])
            self.assertEqual(started["result"]["thread"]["id"], "work-rpc-progress")
            self.assertEqual(
                [item["role"] for item in started["result"]["thread"]["messages"]],
                ["user"],
            )
            progress = started["result"]["progress"]
            self.assertFalse(progress["terminal"])
            event_id = progress["event_id"]

            resident.live_once()
            polled = server.handle(
                {
                    "id": "progress",
                    "method": "work_progress",
                    "params": {
                        "thread_id": "work-rpc-progress",
                        "event_id": event_id,
                    },
                }
            )
            self.assertTrue(polled["ok"])
            self.assertTrue(polled["result"]["progress"]["terminal"])
            self.assertTrue(polled["result"]["progress"]["finalized"])
            self.assertEqual(
                [item["role"] for item in polled["result"]["thread"]["messages"]],
                ["user", "zn", "activity"],
            )
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
