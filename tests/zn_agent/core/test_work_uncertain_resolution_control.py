from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.work import ResidentWorkLedger
from zn_agent.core.work_control import ResidentWorkControl


class ResidentWorkUncertainResolutionControlTests(unittest.TestCase):
    @staticmethod
    def _attempts(database: Path, event_id: str) -> list[tuple[str, str]]:
        with closing(sqlite3.connect(database)) as conn:
            return [
                (str(row[0]), str(row[1]))
                for row in conn.execute(
                    "SELECT attempt_id,status FROM resident_side_effect_attempts "
                    "WHERE event_id=? ORDER BY started_at ASC",
                    (event_id,),
                ).fetchall()
            ]

    def _prepare(
        self,
        resident,
        ledger: ResidentWorkLedger,
        *,
        thread_id: str,
        path: Path,
        suffix: str,
    ):
        ledger.create_thread(thread_id=thread_id)
        _, event = ledger.start(thread_id, f"append durable marker {suffix}")
        claimed = resident.store.claim_event(event.event_id)
        self.assertIsNotNone(claimed)

        args = {"path": str(path), "content": f"{suffix}\n", "append": True}
        intent = NativeActionIntent(
            intent_id=f"intent-{suffix}",
            event_id=event.event_id,
            kind="write_text",
            args=args,
            source="structured_event",
        )
        attempt_id = f"attempt-{suffix}"
        signature = resident.body._signature_hash("write_text", args)
        resident.body._start_attempt(
            attempt_id=attempt_id,
            event_id=event.event_id,
            kind="write_text",
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
                        "kind": "write_text",
                        "intent_id": intent.intent_id,
                        "attempt_id": attempt_id,
                        "replay_blocked": True,
                        "signature": signature[:16],
                        "verification_kind": None,
                        "decision": "user_decision_required",
                        "user_resolution_supported": True,
                    },
                },
            )
        )
        return event, attempt_id, args

    def test_effect_happened_is_user_evidence_and_conflicting_retry_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "kernel.db"
            target = Path(tmp) / "effect.txt"
            target.write_text("already happened\n", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=database
            )
            ledger = ResidentWorkLedger(resident)
            control = ResidentWorkControl(ledger)
            try:
                event, attempt_id, _ = self._prepare(
                    resident,
                    ledger,
                    thread_id="user-effect",
                    path=target,
                    suffix="effect",
                )
                before = target.read_text(encoding="utf-8")
                control.resolve_uncertain(
                    "user-effect",
                    event.event_id,
                    attempt_id=attempt_id,
                    decision="effect_happened",
                )
                self.assertEqual(target.read_text(encoding="utf-8"), before)
                self.assertEqual(
                    self._attempts(database, event.event_id),
                    [(attempt_id, "user_confirmed_effect")],
                )
                state = resident.store.get_working_state()
                recovery = state.data["side_effect_recovery"]
                self.assertEqual(recovery["status"], "user_confirmed_effect")
                self.assertEqual(recovery["resolution_source"], "user")
                self.assertFalse(recovery["replay_blocked"])
                self.assertNotEqual(recovery["status"], "verified_effect")

                with self.assertRaises(RuntimeError):
                    control.resolve_uncertain(
                        "user-effect",
                        event.event_id,
                        attempt_id=attempt_id,
                        decision="retry_authorized",
                    )
                self.assertEqual(target.read_text(encoding="utf-8"), before)
            finally:
                resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=database
            )
            try:
                recovery = restored.store.get_working_state().data["side_effect_recovery"]
                self.assertEqual(recovery["status"], "user_confirmed_effect")
                self.assertEqual(
                    self._attempts(database, event.event_id),
                    [(attempt_id, "user_confirmed_effect")],
                )
            finally:
                restored.store.close()

    def test_retry_authorized_retires_only_old_attempt_and_next_body_call_is_new_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "kernel.db"
            target = Path(tmp) / "retry.txt"
            target.write_text("", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=database
            )
            ledger = ResidentWorkLedger(resident)
            control = ResidentWorkControl(ledger)
            try:
                event, attempt_id, args = self._prepare(
                    resident,
                    ledger,
                    thread_id="user-retry",
                    path=target,
                    suffix="retry",
                )
                progress = control.resolve_uncertain(
                    "user-retry",
                    event.event_id,
                    attempt_id=attempt_id,
                    decision="retry_authorized",
                )
                self.assertEqual(progress["stage"], "native_action")
                self.assertEqual(
                    self._attempts(database, event.event_id),
                    [(attempt_id, "user_authorized_retry")],
                )
                with self.assertRaises(RuntimeError):
                    control.resolve_uncertain(
                        "user-retry",
                        event.event_id,
                        attempt_id=attempt_id,
                        decision="retry_authorized",
                    )

                result = resident.body.act(
                    "write_text", event_id=event.event_id, **args
                )
                self.assertTrue(result.success)
                attempts = self._attempts(database, event.event_id)
                self.assertEqual(len(attempts), 2)
                self.assertEqual(attempts[0], (attempt_id, "user_authorized_retry"))
                self.assertNotEqual(attempts[1][0], attempt_id)
                self.assertEqual(attempts[1][1], "observed")
                self.assertEqual(target.read_text(encoding="utf-8"), "retry\n")
            finally:
                resident.store.close()

    def test_stale_attempt_cross_thread_and_non_recovery_requests_have_zero_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "kernel.db"
            target = Path(tmp) / "guard.txt"
            target.write_text("", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=database
            )
            ledger = ResidentWorkLedger(resident)
            control = ResidentWorkControl(ledger)
            try:
                event, attempt_id, _ = self._prepare(
                    resident,
                    ledger,
                    thread_id="thread-a",
                    path=target,
                    suffix="guard",
                )
                ledger.create_thread(thread_id="thread-b")
                with self.assertRaises(ValueError):
                    control.resolve_uncertain(
                        "thread-b",
                        event.event_id,
                        attempt_id=attempt_id,
                        decision="retry_authorized",
                    )
                with self.assertRaises(RuntimeError):
                    control.resolve_uncertain(
                        "thread-a",
                        event.event_id,
                        attempt_id="stale-attempt-id",
                        decision="retry_authorized",
                    )
                self.assertEqual(
                    self._attempts(database, event.event_id), [(attempt_id, "started")]
                )
                self.assertEqual(target.read_text(encoding="utf-8"), "")

                state = resident.store.get_working_state()
                state.stage = "native_action"
                state.blocked_by = None
                resident.store.save_working_state(state)
                with self.assertRaises(RuntimeError):
                    control.resolve_uncertain(
                        "thread-a",
                        event.event_id,
                        attempt_id=attempt_id,
                        decision="effect_happened",
                    )
                self.assertEqual(
                    self._attempts(database, event.event_id), [(attempt_id, "started")]
                )
                self.assertEqual(target.read_text(encoding="utf-8"), "")
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
