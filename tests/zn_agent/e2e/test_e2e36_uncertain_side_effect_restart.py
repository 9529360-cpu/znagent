from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.recovery_control import ResidentRecoveryRequired
from zn_agent.core.work import ResidentWorkLedger
from zn_agent.core.work_control import ResidentWorkControl


class E2E36UncertainSideEffectRestartTests(unittest.TestCase):
    @staticmethod
    def _attempt_rows(database: Path, event_id: str) -> list[tuple[str, str]]:
        with closing(sqlite3.connect(database)) as conn:
            return [
                (str(row[0]), str(row[1]))
                for row in conn.execute(
                    "SELECT attempt_id,status FROM resident_side_effect_attempts "
                    "WHERE event_id=? ORDER BY started_at ASC",
                    (event_id,),
                ).fetchall()
            ]

    @staticmethod
    def _new_runtime(database: Path):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=database,
        )

    def _start_work_at_native_action(
        self,
        resident,
        *,
        thread_id: str,
        target: Path,
        marker: str,
    ):
        ledger = ResidentWorkLedger(resident)
        ledger.create_thread(thread_id=thread_id)
        _, event = ledger.start(
            thread_id,
            f"append {marker} exactly once",
            payload={"required_capabilities": ["filesystem"]},
        )
        claimed = resident.store.claim_event(event.event_id)
        self.assertIsNotNone(claimed)
        intent = NativeActionIntent(
            intent_id=f"intent-{event.event_id}",
            event_id=event.event_id,
            kind="write_text",
            args={"path": str(target), "content": marker, "append": True},
            source="structured_event",
        )
        state = WorkingState(
            current_event_id=event.event_id,
            stage="native_action",
            next_action="move body: write_text",
            data={"native_action_intent": intent.to_dict()},
        )
        resident.store.save_working_state(state)
        return ledger, event, state, intent

    def test_effect_happened_survives_restart_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "kernel.db"
            target = root / "effect.txt"
            target.write_text("", encoding="utf-8")
            marker = "effect-happened\n"

            first = self._new_runtime(database)
            ledger, event, state, _ = self._start_work_at_native_action(
                first,
                thread_id="e2e36-effect",
                target=target,
                marker=marker,
            )
            original_finish = first.body._finish_attempt

            def crash_after_mutation(*args, **kwargs):
                raise SystemExit("E2E-36 crash after outside-world mutation")

            try:
                with patch.object(first.body, "_finish_attempt", side_effect=crash_after_mutation):
                    with self.assertRaises(SystemExit):
                        first._native_action_step(event, state, readiness=None)
                self.assertEqual(target.read_text(encoding="utf-8"), marker)
                attempts_after_crash = self._attempt_rows(database, event.event_id)
                self.assertEqual(len(attempts_after_crash), 1)
                first_attempt = attempts_after_crash[0][0]
                self.assertEqual(attempts_after_crash[0][1], "started")
            finally:
                first.body._finish_attempt = original_finish
                first.store.close()

            restored = self._new_runtime(database)
            control = ResidentWorkControl(ResidentWorkLedger(restored))
            try:
                with self.assertRaises(ResidentRecoveryRequired):
                    restored.run_once(target_event_id=event.event_id)
                self.assertEqual(target.read_text(encoding="utf-8"), marker)
                progress = control.progress("e2e36-effect", event.event_id)
                self.assertEqual(progress["stage"], "side_effect_recovery")
                self.assertEqual(progress["blocked_by"], "outside_world_effect_uncertain")
                self.assertEqual(progress["recovery"]["decision"], "user_decision_required")
                self.assertTrue(progress["recovery"]["replay_blocked"])
                self.assertNotIn(marker.strip(), str(progress))

                control.resolve_uncertain(
                    "e2e36-effect",
                    event.event_id,
                    attempt_id=first_attempt,
                    decision="effect_happened",
                )
                self.assertEqual(target.read_text(encoding="utf-8"), marker)
                rows = self._attempt_rows(database, event.event_id)
                self.assertEqual(rows, [(first_attempt, "user_confirmed_effect")])

                terminal = restored.run_once(target_event_id=event.event_id)
                self.assertIsNotNone(terminal)
                self.assertTrue(terminal.success)
                self.assertEqual(target.read_text(encoding="utf-8"), marker)
            finally:
                restored.store.close()

            again = self._new_runtime(database)
            try:
                self.assertEqual(target.read_text(encoding="utf-8"), marker)
                self.assertEqual(
                    self._attempt_rows(database, event.event_id),
                    [(first_attempt, "user_confirmed_effect")],
                )
                outcome = again.store.get_event_outcome(event.event_id)
                self.assertIsNotNone(outcome)
                self.assertTrue(outcome.success)
            finally:
                again.store.close()

    def test_retry_authorized_creates_one_new_attempt_and_one_real_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "kernel.db"
            target = root / "retry.txt"
            target.write_text("", encoding="utf-8")
            marker = "retry-once\n"

            first = self._new_runtime(database)
            _, event, state, _ = self._start_work_at_native_action(
                first,
                thread_id="e2e36-retry",
                target=target,
                marker=marker,
            )
            try:
                with patch.object(
                    first.body,
                    "_dispatch",
                    side_effect=SystemExit("E2E-36 crash before external mutation"),
                ):
                    with self.assertRaises(SystemExit):
                        first._native_action_step(event, state, readiness=None)
                self.assertEqual(target.read_text(encoding="utf-8"), "")
                rows = self._attempt_rows(database, event.event_id)
                self.assertEqual(len(rows), 1)
                first_attempt = rows[0][0]
                self.assertEqual(rows[0][1], "started")
            finally:
                first.store.close()

            restored = self._new_runtime(database)
            control = ResidentWorkControl(ResidentWorkLedger(restored))
            try:
                with self.assertRaises(ResidentRecoveryRequired):
                    restored.run_once(target_event_id=event.event_id)
                self.assertEqual(target.read_text(encoding="utf-8"), "")
                recovery = control.progress("e2e36-retry", event.event_id)["recovery"]
                self.assertEqual(recovery["attempt_id"], first_attempt)
                self.assertEqual(recovery["decision"], "user_decision_required")

                progress = control.resolve_uncertain(
                    "e2e36-retry",
                    event.event_id,
                    attempt_id=first_attempt,
                    decision="retry_authorized",
                )
                self.assertEqual(progress["stage"], "native_action")
                self.assertEqual(target.read_text(encoding="utf-8"), "")
                self.assertEqual(
                    self._attempt_rows(database, event.event_id),
                    [(first_attempt, "user_authorized_retry")],
                )

                terminal = restored.run_once(target_event_id=event.event_id)
                self.assertIsNotNone(terminal)
                self.assertTrue(terminal.success)
                self.assertEqual(target.read_text(encoding="utf-8"), marker)
                rows = self._attempt_rows(database, event.event_id)
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[0], (first_attempt, "user_authorized_retry"))
                self.assertNotEqual(rows[1][0], first_attempt)
                self.assertEqual(rows[1][1], "observed")
            finally:
                restored.store.close()

    def test_retry_authority_does_not_carry_to_a_second_uncertain_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "kernel.db"
            target = root / "retry-crash.txt"
            target.write_text("", encoding="utf-8")
            marker = "second-window\n"

            first = self._new_runtime(database)
            _, event, state, _ = self._start_work_at_native_action(
                first,
                thread_id="e2e36-retry-crash",
                target=target,
                marker=marker,
            )
            try:
                with patch.object(
                    first.body,
                    "_dispatch",
                    side_effect=SystemExit("first uncertain dispatch"),
                ):
                    with self.assertRaises(SystemExit):
                        first._native_action_step(event, state, readiness=None)
                first_attempt = self._attempt_rows(database, event.event_id)[0][0]
            finally:
                first.store.close()

            second = self._new_runtime(database)
            control = ResidentWorkControl(ResidentWorkLedger(second))
            try:
                with self.assertRaises(ResidentRecoveryRequired):
                    second.run_once(target_event_id=event.event_id)
                control.resolve_uncertain(
                    "e2e36-retry-crash",
                    event.event_id,
                    attempt_id=first_attempt,
                    decision="retry_authorized",
                )
                retry_state = second.store.get_working_state()
                with patch.object(
                    second.body,
                    "_finish_attempt",
                    side_effect=SystemExit("second uncertain dispatch after real mutation"),
                ):
                    with self.assertRaises(SystemExit):
                        second._native_action_step(event, retry_state, readiness=None)
                self.assertEqual(target.read_text(encoding="utf-8"), marker)
                rows = self._attempt_rows(database, event.event_id)
                self.assertEqual(len(rows), 2)
                second_attempt = rows[1][0]
                self.assertEqual(rows[0], (first_attempt, "user_authorized_retry"))
                self.assertEqual(rows[1][1], "started")
            finally:
                second.store.close()

            third = self._new_runtime(database)
            control = ResidentWorkControl(ResidentWorkLedger(third))
            try:
                with self.assertRaises(ResidentRecoveryRequired):
                    third.run_once(target_event_id=event.event_id)
                progress = control.progress("e2e36-retry-crash", event.event_id)
                self.assertEqual(progress["stage"], "side_effect_recovery")
                self.assertEqual(progress["recovery"]["attempt_id"], second_attempt)
                self.assertEqual(progress["recovery"]["decision"], "user_decision_required")
                self.assertTrue(progress["recovery"]["replay_blocked"])
                self.assertEqual(target.read_text(encoding="utf-8"), marker)
                with self.assertRaises(RuntimeError):
                    control.resolve_uncertain(
                        "e2e36-retry-crash",
                        event.event_id,
                        attempt_id=first_attempt,
                        decision="retry_authorized",
                    )
                self.assertEqual(target.read_text(encoding="utf-8"), marker)
            finally:
                third.store.close()


if __name__ == "__main__":
    unittest.main()
