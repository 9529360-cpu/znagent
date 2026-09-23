from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import EventStatus, WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime


class WorkReconnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "kernel.db"
        self.resident = build_resident_runtime(config={"model": {}}, store_path=self.path)
        self.server = ResidentRpcServer(self.resident)
        self.addCleanup(lambda: self.resident.store.close())

    def rpc(self, method, **params):
        return self.server.handle({"id": "reconnect", "method": method, "params": params})["result"]

    def restart(self):
        self.resident.store.close()
        self.resident = build_resident_runtime(config={"model": {}}, store_path=self.path)
        self.server = ResidentRpcServer(self.resident)

    def test_pending_work_is_discoverable_after_restart_without_resubmission(self):
        started = self.rpc("work_start", thread_id="reconnect-a", task="pending reconnection task")
        event_id = started["progress"]["event_id"]
        expected = {"thread_id": "reconnect-a", "event_id": event_id}
        self.assertEqual(started["thread"]["active_run"], expected)
        message_ids = [m["id"] for m in started["thread"]["messages"]]
        identity = self.resident.kernel.identity
        self.restart()
        self.assertEqual(self.resident.kernel.identity, identity)

        for _ in range(3):
            snapshot = self.rpc("work_get", thread_id="reconnect-a")
            self.assertEqual(snapshot["active_run"], expected)
            self.assertEqual([m["id"] for m in snapshot["messages"]], message_ids)
            listed = self.rpc("work_list")
            self.assertEqual(next(t for t in listed if t["id"] == "reconnect-a")["active_run"], expected)
            progress = self.rpc("work_progress", thread_id="reconnect-a", event_id=event_id)["progress"]
            self.assertFalse(progress["terminal"])
        self.assertEqual(self.resident.store.get_event(event_id).status, EventStatus.PENDING)
        self.assertIsNone(self.resident.result_for(event_id))

    def test_projection_does_not_accept_metadata_identity_or_cross_threads(self):
        empty = self.rpc("work_create", thread_id="empty", metadata={
            "active_run": {"thread_id": "other", "event_id": "forged-event"},
        })
        self.assertIsNone(empty["active_run"])
        first = self.rpc("work_start", thread_id="first", task="first pending request")
        second = self.rpc("work_start", thread_id="second", task="second pending request")
        self.assertNotEqual(first["progress"]["event_id"], second["progress"]["event_id"])
        listed = {thread["id"]: thread for thread in self.rpc("work_list")}
        for name, started in (("first", first), ("second", second)):
            self.assertEqual(listed[name]["active_run"], {
                "thread_id": name, "event_id": started["progress"]["event_id"],
            })
        self.assertIsNone(listed["empty"]["active_run"])

    def test_completed_work_reconnects_to_one_durable_reply_not_an_active_run(self):
        self.resident.memory.remember("reconnect stored fact", "durable remembered answer")
        started = self.rpc("work_start", thread_id="completed", task="reconnect stored fact")
        event_id = started["progress"]["event_id"]
        for _ in range(32):
            self.resident.live_once()
            if self.resident.result_for(event_id) is not None:
                break
        self.assertIsNotNone(self.resident.result_for(event_id))
        self.restart()
        snapshot = self.rpc("work_get", thread_id="completed")
        self.assertIsNone(snapshot["active_run"])
        self.assertEqual([m["text"] for m in snapshot["messages"] if m["role"] == "zn"], ["durable remembered answer"])
        again = self.rpc("work_get", thread_id="completed")
        self.assertEqual([m["id"] for m in again["messages"]], [m["id"] for m in snapshot["messages"]])
        self.assertTrue(self.rpc("work_progress", thread_id="completed", event_id=event_id)["progress"]["finalized"])

    def test_recovery_work_is_discoverable_without_exporting_or_replaying_action(self):
        started = self.rpc("work_start", thread_id="blocked", task="uncertain prior effect")
        event_id = started["progress"]["event_id"]
        self.assertIsNotNone(self.resident.store.claim_event(event_id))
        self.resident.store.save_working_state(WorkingState(
            current_event_id=event_id,
            stage="side_effect_recovery",
            next_action="await explicit recovery decision",
            blocked_by="outside_world_effect_uncertain",
            data={"side_effect_recovery": {
                "status": "uncertain", "kind": "command",
                "attempt_id": "effect-attempt", "replay_blocked": True,
                "decision": "user_decision_required", "reason": "outcome remains unproven",
                "command": "private-command --token private-value",
            }},
        ))
        self.restart()
        before = self.resident.store.get_working_state()
        snapshot = self.rpc("work_get", thread_id="blocked")
        self.assertEqual(snapshot["active_run"], {"thread_id": "blocked", "event_id": event_id})
        progress = self.rpc("work_progress", thread_id="blocked", event_id=event_id)["progress"]
        self.assertEqual(progress["stage"], "side_effect_recovery")
        self.assertTrue(progress["recovery"]["replay_blocked"])
        self.assertNotIn("command", progress["recovery"])
        self.assertFalse(progress["terminal"])
        after = self.resident.store.get_working_state()
        self.assertEqual(after.stage, before.stage)
        self.assertEqual(after.data, before.data)
        self.assertIsNone(self.resident.result_for(event_id))


if __name__ == "__main__":
    unittest.main()
