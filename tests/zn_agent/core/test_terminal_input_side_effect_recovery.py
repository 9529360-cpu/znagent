from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.body import BodyAction, BodyActionResult
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.side_effect_body import SideEffectAwareBody
from zn_agent.core.store import KernelStore


class TerminalInputSideEffectRecoveryTests(unittest.TestCase):
    def test_terminal_input_aliases_require_non_replayable_guard(self) -> None:
        for kind in ("terminal_input", "terminal_write", "command_input"):
            with self.subTest(kind=kind):
                self.assertTrue(
                    SideEffectAwareBody._requires_guard(
                        kind,
                        {"session_id": "pty-1", "data": "secret"},
                    )
                )

    def test_started_terminal_input_attempt_enters_recovery_without_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                event = resident.enqueue(
                    "continue the interactive terminal",
                    payload={"required_capabilities": []},
                )
                claimed = resident.store.claim_event(event.event_id)
                self.assertIsNotNone(claimed)
                intent = NativeActionIntent(
                    intent_id=f"intent-{event.event_id}",
                    event_id=event.event_id,
                    kind="terminal_input",
                    args={"session_id": "pty-existing", "data": "yes\n"},
                    source="structured_event",
                )
                state = WorkingState(
                    current_event_id=event.event_id,
                    stage="native_action",
                    next_action="move body: terminal_input",
                    data={"native_action_intent": intent.to_dict()},
                )
                resident.store.save_working_state(state)
                signature = resident.body._signature_hash(intent.kind, dict(intent.args))
                resident.body._start_attempt(
                    attempt_id=f"sidefx-seeded-{event.event_id}",
                    event_id=event.event_id,
                    kind=intent.kind,
                    signature_hash=signature,
                )

                result = resident._native_action_step(
                    event,
                    state,
                    readiness=None,
                )
                self.assertIsNone(result)
                durable = resident.store.get_working_state()
                self.assertEqual(durable.stage, "side_effect_recovery")
                recovery = durable.data["side_effect_recovery"]
                self.assertEqual(recovery["kind"], "terminal_input")
                self.assertEqual(recovery["decision"], "user_decision_required")
                self.assertTrue(recovery["replay_blocked"])
                self.assertNotIn("local_failure", durable.data)
                self.assertEqual(len(resident.body.uncertain_attempts(event.event_id)), 1)
            finally:
                resident.store.close()

    def test_terminal_input_durable_result_drops_echo_and_command_text(self) -> None:
        secret = "typed-private-value"
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            try:
                body = SideEffectAwareBody(store=store)
                action = BodyAction(
                    action_id="body-terminal-input-result-secret",
                    event_id="evt-terminal-input-result-secret",
                    kind="terminal_input",
                    args={"session_id": "pty-1", "data": secret},
                )
                result = BodyActionResult(
                    action_id=action.action_id,
                    event_id=action.event_id,
                    kind=action.kind,
                    success=True,
                    output=f"Password: {secret}",
                    data={
                        "status": "running",
                        "command": "interactive-secret-reader",
                        "output": f"Password: {secret}",
                        "session_id": "pty-1",
                        "pid": 123,
                    },
                )

                body._record(action, result)
                with closing(sqlite3.connect(store.path)) as conn:
                    row = conn.execute(
                        "SELECT action_json,result_json FROM native_body_actions WHERE action_id=?",
                        (action.action_id,),
                    ).fetchone()
                self.assertIsNotNone(row)
                assert row is not None
                serialized = f"{row[0]}\n{row[1]}"
                self.assertNotIn(secret, serialized)
                persisted_action = json.loads(str(row[0]))
                persisted_result = json.loads(str(row[1]))
                self.assertTrue(persisted_action["args"]["input_redacted"])
                self.assertNotIn("data", persisted_action["args"])
                self.assertEqual(persisted_result["output"], "")
                self.assertNotIn("output", persisted_result["data"])
                self.assertNotIn("command", persisted_result["data"])
                self.assertTrue(
                    persisted_result["data"]["terminal_input_output_redacted"]
                )
                self.assertEqual(
                    persisted_result["data"]["terminal_input_output_chars"],
                    len(f"Password: {secret}"),
                )

                # Redaction is durable-history only. The live caller's result
                # still carries the real terminal evidence for the current pulse.
                self.assertEqual(result.output, f"Password: {secret}")
                self.assertEqual(result.data["command"], "interactive-secret-reader")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
