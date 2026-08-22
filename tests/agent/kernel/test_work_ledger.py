from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from agent.kernel.daemon import ResidentRpcServer
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack
from agent.kernel.work import ResidentWorkLedger


class ResidentWorkLedgerTests(unittest.TestCase):
    def test_work_history_survives_resident_reconstruction(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = ResidentWorkLedger(resident)
            thread = ledger.create_thread(thread_id="work-persistent")
            snapshot, run = ledger.submit(
                thread.thread_id,
                "unknown task with no external brain",
            )

            self.assertFalse(run.success)
            saved_thread, messages = snapshot
            self.assertEqual(saved_thread.thread_id, "work-persistent")
            self.assertEqual(saved_thread.title, "unknown task with no external brain")
            self.assertEqual([message.role for message in messages], ["user", "zn", "activity"])
            self.assertEqual(messages[-1].detail["event_id"], run.event.event_id)
            self.assertEqual(
                run.event.payload["work_thread_id"],
                "work-persistent",
            )
            self.assertEqual(
                run.event.payload["work_message_id"],
                messages[0].message_id,
            )
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            restored_ledger = ResidentWorkLedger(restored)
            snapshots = restored_ledger.list_snapshots()

            self.assertEqual(len(snapshots), 1)
            restored_thread, restored_messages = snapshots[0]
            self.assertEqual(restored_thread.thread_id, "work-persistent")
            self.assertEqual(
                [message.message_id for message in restored_messages],
                [message.message_id for message in messages],
            )
            restored.store.close()

    def test_work_rpc_is_resident_backed(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            server = ResidentRpcServer(
                resident=resident,
                input_stream=io.StringIO(),
                output_stream=io.StringIO(),
            )

            created = server.handle(
                {
                    "id": "create",
                    "method": "work_create",
                    "params": {"thread_id": "work-rpc"},
                }
            )
            self.assertTrue(created["ok"])
            self.assertEqual(created["result"]["id"], "work-rpc")
            self.assertEqual(created["result"]["messages"], [])

            submitted = server.handle(
                {
                    "id": "submit",
                    "method": "work_submit",
                    "params": {
                        "thread_id": "work-rpc",
                        "task": "unknown task with no external brain",
                    },
                }
            )
            self.assertTrue(submitted["ok"])
            self.assertEqual(submitted["result"]["thread"]["id"], "work-rpc")
            self.assertEqual(
                [message["role"] for message in submitted["result"]["thread"]["messages"]],
                ["user", "zn", "activity"],
            )
            self.assertFalse(submitted["result"]["run"]["success"])

            listed = server.handle(
                {"id": "list", "method": "work_list", "params": {"limit": 24}}
            )
            self.assertTrue(listed["ok"])
            self.assertEqual(len(listed["result"]), 1)
            self.assertEqual(listed["result"][0]["id"], "work-rpc")
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
