from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.recurring_will_rpc import RecurringWillResidentRpcServer


class RecurringWillRpcTests(unittest.TestCase):
    @staticmethod
    def _server(db: Path) -> RecurringWillResidentRpcServer:
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=db,
        )
        return RecurringWillResidentRpcServer(resident=resident)

    def test_schedule_list_disable_stays_on_existing_resident_control_plane(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = self._server(Path(tmp) / "kernel.db")
            try:
                due = datetime.now(timezone.utc) + timedelta(minutes=5)
                scheduled = server.handle(
                    {
                        "id": "schedule",
                        "method": "recurring_schedule",
                        "params": {
                            "description": "keep project status current",
                            "task": "review the current project status from fresh evidence",
                            "interval_seconds": 300,
                            "priority": 6,
                            "source": "user",
                            "first_due_at": due.isoformat(),
                            # Arbitrary future execution arguments are deliberately
                            # not part of this RPC contract.
                            "payload": {"command": "must-not-be-persisted"},
                        },
                    }
                )
                self.assertTrue(scheduled["ok"])
                item = scheduled["result"]
                intention_id = item["intention_id"]
                self.assertEqual(item["priority"], 6)
                self.assertEqual(item["source"], "user")
                self.assertFalse(item["execution_authority"])
                self.assertTrue(item["fresh_revalidation_required"])
                self.assertTrue(item["trigger"]["enabled"])
                self.assertEqual(item["trigger"]["interval_seconds"], 300)
                self.assertNotIn("payload", item["trigger"])
                self.assertNotIn("command", repr(item))

                listed = server.handle(
                    {
                        "id": "list",
                        "method": "recurring_list",
                        "params": {"enabled_only": True, "limit": 20},
                    }
                )
                self.assertTrue(listed["ok"])
                self.assertEqual(len(listed["result"]), 1)
                self.assertEqual(listed["result"][0]["intention_id"], intention_id)

                disabled = server.handle(
                    {
                        "id": "disable",
                        "method": "recurring_disable",
                        "params": {"intention_id": intention_id},
                    }
                )
                self.assertTrue(disabled["ok"])
                self.assertFalse(disabled["result"]["trigger"]["enabled"])

                enabled = server.handle(
                    {
                        "id": "enabled",
                        "method": "recurring_list",
                        "params": {"enabled_only": True},
                    }
                )
                self.assertEqual(enabled["result"], [])

                all_items = server.handle(
                    {
                        "id": "all",
                        "method": "recurring_list",
                        "params": {"enabled_only": False},
                    }
                )
                self.assertEqual(len(all_items["result"]), 1)
                self.assertFalse(all_items["result"][0]["trigger"]["enabled"])
            finally:
                server.resident.store.close()

    def test_schedule_validation_reuses_resident_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = self._server(Path(tmp) / "kernel.db")
            try:
                with self.assertRaisesRegex(ValueError, "requires description"):
                    server.handle(
                        {
                            "id": "missing-description",
                            "method": "recurring_schedule",
                            "params": {
                                "task": "inspect current state",
                                "interval_seconds": 60,
                            },
                        }
                    )
                with self.assertRaisesRegex(ValueError, "at least 60 seconds"):
                    server.handle(
                        {
                            "id": "tight-loop",
                            "method": "recurring_schedule",
                            "params": {
                                "description": "too frequent",
                                "task": "inspect current state",
                                "interval_seconds": 1,
                            },
                        }
                    )
                with self.assertRaisesRegex(ValueError, "integer interval_seconds"):
                    server.handle(
                        {
                            "id": "bad-interval",
                            "method": "recurring_schedule",
                            "params": {
                                "description": "bad interval",
                                "task": "inspect current state",
                                "interval_seconds": "often",
                            },
                        }
                    )
            finally:
                server.resident.store.close()

    def test_existing_formal_rpc_superclass_contract_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = self._server(Path(tmp) / "kernel.db")
            try:
                response = server.handle(
                    {"id": "status", "method": "status", "params": {}}
                )
                self.assertTrue(response["ok"])
                self.assertEqual(
                    response["result"]["resident_surface"],
                    {"name": "zn-formal-resident", "schema": 2},
                )
                self.assertIn("recurring_will", response["result"])
            finally:
                server.resident.store.close()

    def test_disable_unknown_recurring_intention_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = self._server(Path(tmp) / "kernel.db")
            try:
                with self.assertRaisesRegex(ValueError, "unknown recurring intention"):
                    server.handle(
                        {
                            "id": "disable-missing",
                            "method": "recurring_disable",
                            "params": {"intention_id": "intent-missing"},
                        }
                    )
            finally:
                server.resident.store.close()


if __name__ == "__main__":
    unittest.main()
