from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.work import ResidentWorkLedger
from zn_agent.core.work_control import ResidentWorkControl


class WorkUncertainResolutionAtomicityTests(unittest.TestCase):
    @staticmethod
    def _attempt_status(database: Path, attempt_id: str) -> str:
        with closing(sqlite3.connect(database)) as conn:
            row = conn.execute(
                "SELECT status FROM resident_side_effect_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
        if row is None:
            raise AssertionError("missing side-effect attempt")
        return str(row[0])

    def _prepare(self, database: Path):
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}}, store_path=database
        )
        ledger = ResidentWorkLedger(resident)
        ledger.create_thread(thread_id="atomic-resolution")
        _, event = ledger.start("atomic-resolution", "run one guarded command")
        self.assertIsNotNone(resident.store.claim_event(event.event_id))

        intent = NativeActionIntent(
            intent_id=f"intent-{event.event_id}",
            event_id=event.event_id,
            kind="command",
            args={"command": "SECRET_COMMAND_MUST_NOT_APPEAR"},
            source="structured_event",
        )
        attempt_id = f"attempt-{event.event_id}"
        signature = resident.body._signature_hash("command", intent.args)
        resident.body._start_attempt(
            attempt_id=attempt_id,
            event_id=event.event_id,
            kind="command",
            signature_hash=signature,
        )
        resident.store.save_working_state(
            WorkingState(
                current_event_id=event.event_id,
                stage="side_effect_recovery",
                next_action="await explicit recovery decision",
                blocked_by="outside_world_effect_uncertain",
                data={
                    "native_action_intent": intent.to_dict(),
                    "side_effect_recovery": {
                        "status": "decision_required",
                        "kind": "command",
                        "intent_id": intent.intent_id,
                        "attempt_id": attempt_id,
                        "signature": signature[:16],
                        "replay_blocked": True,
                        "decision": "user_decision_required",
                        "user_resolution_supported": True,
                    },
                },
            )
        )
        return resident, ledger, event, attempt_id

    def test_attempt_and_checkpoint_roll_back_together_if_checkpoint_write_crashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "kernel.db"
            resident, ledger, event, attempt_id = self._prepare(database)
            control = ResidentWorkControl(ledger)
            try:
                original_dump = resident.store._dump

                def fail_only_resolved_checkpoint(data):
                    recovery = (
                        data.get("data", {}).get("side_effect_recovery")
                        if isinstance(data, dict)
                        else None
                    )
                    if isinstance(recovery, dict) and recovery.get("resolution_source") == "user":
                        raise RuntimeError("injected checkpoint serialization crash")
                    return original_dump(data)

                with patch.object(resident.store, "_dump", side_effect=fail_only_resolved_checkpoint):
                    with self.assertRaises(RuntimeError):
                        control.resolve_uncertain(
                            "atomic-resolution",
                            event.event_id,
                            attempt_id=attempt_id,
                            decision="retry_authorized",
                        )

                self.assertEqual(self._attempt_status(database, attempt_id), "started")
                state = resident.store.get_working_state()
                recovery = state.data["side_effect_recovery"]
                self.assertEqual(state.stage, "side_effect_recovery")
                self.assertEqual(state.blocked_by, "outside_world_effect_uncertain")
                self.assertEqual(recovery["decision"], "user_decision_required")
                self.assertTrue(recovery["replay_blocked"])
            finally:
                resident.store.close()

    def test_public_progress_and_rpc_expose_only_bounded_resolution_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "kernel.db"
            resident, ledger, event, attempt_id = self._prepare(database)
            control = ResidentWorkControl(ledger)
            try:
                progress = control.progress("atomic-resolution", event.event_id)
                self.assertEqual(
                    progress["recovery"]["allowed_actions"],
                    ["effect_happened", "retry_authorized", "cancel"],
                )
                serialized = str(progress)
                self.assertNotIn("SECRET_COMMAND_MUST_NOT_APPEAR", serialized)

                server = ResidentRpcServer(resident=resident)
                response = server.handle(
                    {
                        "id": "resolve-1",
                        "method": "work_resolve_uncertain",
                        "params": {
                            "thread_id": "atomic-resolution",
                            "event_id": event.event_id,
                            "attempt_id": attempt_id,
                            "decision": "retry_authorized",
                        },
                    }
                )
                self.assertTrue(response["ok"])
                self.assertEqual(response["result"]["progress"]["stage"], "native_action")
                self.assertEqual(self._attempt_status(database, attempt_id), "user_authorized_retry")
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
