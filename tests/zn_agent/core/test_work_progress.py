from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import WorkingState
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
            self.assertIsNone(pending["recovery"])

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
            self.assertIsNone(completed["recovery"])
            final_thread, messages = ledger.get_snapshot("work-progress")
            self.assertEqual(final_thread.thread_id, "work-progress")
            self.assertEqual([message.role for message in messages], ["user", "zn", "activity"])
            self.assertEqual(messages[-1].detail["event_id"], event.event_id)

            again = ledger.progress("work-progress", event.event_id)
            self.assertTrue(again["finalized"])
            self.assertIsNone(again["recovery"])
            _, messages_again = ledger.get_snapshot("work-progress")
            self.assertEqual(
                [message.message_id for message in messages_again],
                [message.message_id for message in messages],
            )
            resident.store.close()

    def test_user_presence_blocker_projects_waiting_for_user_without_terminalizing_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            ledger = ResidentWorkLedger(resident)
            _, event = ledger.start("work-user-presence", "finish browser task")
            self.assertIsNotNone(resident.store.claim_event(event.event_id))
            next_action = (
                "请在当前已授权浏览器标签页完成一次性验证码/多因素验证。"
                "ZN 不会读取或输入验证码；完成后会重新读取页面并继续当前任务。"
            )
            resident.store.save_working_state(
                WorkingState(
                    current_event_id=event.event_id,
                    stage="native_investigation",
                    next_action=next_action,
                    blocked_by="user_presence_required",
                    data={},
                )
            )

            progress = ledger.progress("work-user-presence", event.event_id)

            self.assertEqual(progress["status"], "processing")
            self.assertEqual(progress["stage"], "waiting_for_user")
            self.assertEqual(progress["blocked_by"], "user_presence_required")
            self.assertEqual(progress["next_action"], next_action)
            self.assertFalse(progress["terminal"])
            self.assertFalse(progress["finalized"])
            resident.store.close()

    def test_active_side_effect_recovery_is_sanitized_and_survives_reconstruction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = ResidentWorkLedger(resident)
            _, event = ledger.start("work-recovery-projection", "uncertain command")
            self.assertIsNotNone(resident.store.claim_event(event.event_id))
            resident.store.save_working_state(
                WorkingState(
                    current_event_id=event.event_id,
                    stage="side_effect_recovery",
                    next_action="await explicit recovery decision",
                    blocked_by="outside_world_effect_uncertain",
                    data={
                        "side_effect_recovery": {
                            "status": "uncertain",
                            "kind": "command",
                            "intent_id": "intent-private",
                            "attempt_id": "sidefx-public-attempt",
                            "replay_blocked": True,
                            "signature": "0123456789abcdef",
                            "verification_kind": None,
                            "decision": "user_decision_required",
                            "reason": "current reality cannot prove whether the command effect happened",
                            "command": "secret-command --token raw-secret",
                            "content": "private appended content",
                            "env": {"API_KEY": "raw-secret"},
                            "verification": {
                                "action_id": "read-public-evidence",
                                "success": True,
                                "truncated": False,
                                "observed_chars": 17,
                                "path": "C:/private/path.txt",
                                "output": "private current text",
                            },
                        }
                    },
                )
            )

            progress = ledger.progress("work-recovery-projection", event.event_id)
            self.assertEqual(progress["stage"], "side_effect_recovery")
            self.assertEqual(
                progress["recovery"],
                {
                    "status": "uncertain",
                    "kind": "command",
                    "attempt_id": "sidefx-public-attempt",
                    "replay_blocked": True,
                    "verification_kind": None,
                    "decision": "user_decision_required",
                    "reason": "current reality cannot prove whether the command effect happened",
                    "verification": {
                        "action_id": "read-public-evidence",
                        "success": True,
                        "truncated": False,
                        "observed_chars": 17,
                    },
                },
            )
            encoded = json.dumps(progress["recovery"], sort_keys=True)
            for private_value in (
                "intent-private",
                "0123456789abcdef",
                "secret-command",
                "raw-secret",
                "private appended content",
                "C:/private/path.txt",
                "private current text",
            ):
                self.assertNotIn(private_value, encoded)
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            restored_ledger = ResidentWorkLedger(restored)
            restored_progress = restored_ledger.progress(
                "work-recovery-projection", event.event_id
            )
            self.assertEqual(restored_progress["stage"], "side_effect_recovery")
            self.assertEqual(restored_progress["recovery"], progress["recovery"])
            restored.store.close()

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
            self.assertIsNone(progress["recovery"])
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
            self.assertIsNone(polled["result"]["progress"]["recovery"])
            self.assertEqual(
                [item["role"] for item in polled["result"]["thread"]["messages"]],
                ["user", "zn", "activity"],
            )
            resident.store.close()

    def test_work_progress_rpc_passes_through_sanitized_recovery(self):
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
            started = server.handle(
                {
                    "id": "start-recovery",
                    "method": "work_start",
                    "params": {
                        "thread_id": "work-rpc-recovery",
                        "task": "recover uncertain side effect",
                    },
                }
            )
            event_id = started["result"]["progress"]["event_id"]
            self.assertIsNotNone(resident.store.claim_event(event_id))
            resident.store.save_working_state(
                WorkingState(
                    current_event_id=event_id,
                    stage="side_effect_recovery",
                    next_action="await explicit recovery decision",
                    blocked_by="outside_world_effect_uncertain",
                    data={
                        "side_effect_recovery": {
                            "status": "uncertain",
                            "kind": "command",
                            "attempt_id": "sidefx-rpc",
                            "replay_blocked": True,
                            "signature": "private-signature",
                            "decision": "user_decision_required",
                            "command": "private command",
                        }
                    },
                )
            )

            polled = server.handle(
                {
                    "id": "poll-recovery",
                    "method": "work_progress",
                    "params": {
                        "thread_id": "work-rpc-recovery",
                        "event_id": event_id,
                    },
                }
            )
            self.assertTrue(polled["ok"])
            recovery = polled["result"]["progress"]["recovery"]
            self.assertEqual(recovery["attempt_id"], "sidefx-rpc")
            self.assertTrue(recovery["replay_blocked"])
            self.assertEqual(recovery["decision"], "user_decision_required")
            self.assertNotIn("private-signature", json.dumps(recovery))
            self.assertNotIn("private command", json.dumps(recovery))
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
