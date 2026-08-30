from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.body import BodyAction, BodyActionResult
from zn_agent.core.side_effect_body import SideEffectAwareBody
from zn_agent.core.store import KernelStore


class TerminalBodyActionRedactionTests(unittest.TestCase):
    @staticmethod
    def _persisted_action(store: KernelStore, action_id: str) -> dict:
        with closing(sqlite3.connect(store.path)) as conn:
            row = conn.execute(
                "SELECT action_json FROM native_body_actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()
        if row is None:
            raise AssertionError(f"missing body action row: {action_id}")
        return json.loads(str(row[0]))

    def test_command_explicit_environment_values_are_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            try:
                body = SideEffectAwareBody(store=store)
                action = BodyAction(
                    action_id="body-command-secret",
                    event_id="evt-command-secret",
                    kind="command",
                    args={
                        "command": "tool --read-env",
                        "env": {
                            "API_TOKEN": "super-secret-token",
                            "CLIENT_SECRET": "another-private-value",
                        },
                        "timeout": 5,
                    },
                )
                result = BodyActionResult(
                    action_id=action.action_id,
                    event_id=action.event_id,
                    kind=action.kind,
                    success=True,
                    output="ok",
                )

                body._record(action, result)
                persisted = self._persisted_action(store, action.action_id)
                serialized = json.dumps(persisted, ensure_ascii=False)

                self.assertNotIn("super-secret-token", serialized)
                self.assertNotIn("another-private-value", serialized)
                self.assertNotIn("env", persisted["args"])
                self.assertTrue(persisted["args"]["env_redacted"])
                self.assertEqual(
                    persisted["args"]["env_keys"],
                    ["API_TOKEN", "CLIENT_SECRET"],
                )
                self.assertEqual(persisted["args"]["env_count"], 2)
                self.assertEqual(persisted["args"]["command"], "tool --read-env")
                self.assertEqual(persisted["args"]["timeout"], 5)
            finally:
                store.close()

    def test_terminal_input_payload_is_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            try:
                body = SideEffectAwareBody(store=store)
                action = BodyAction(
                    action_id="body-terminal-input-secret",
                    event_id="evt-terminal-input-secret",
                    kind="terminal_input",
                    args={
                        "session_id": "terminal-session",
                        "data": "typed-private-value",
                    },
                )
                result = BodyActionResult(
                    action_id=action.action_id,
                    event_id=action.event_id,
                    kind=action.kind,
                    success=True,
                )

                body._record(action, result)
                persisted = self._persisted_action(store, action.action_id)
                serialized = json.dumps(persisted, ensure_ascii=False)

                self.assertNotIn("typed-private-value", serialized)
                self.assertNotIn("data", persisted["args"])
                self.assertNotIn("input", persisted["args"])
                self.assertTrue(persisted["args"]["input_redacted"])
                self.assertEqual(persisted["args"]["input_source"], "data")
                self.assertEqual(persisted["args"]["input_chars"], 19)
                self.assertEqual(
                    persisted["args"]["session_id"],
                    "terminal-session",
                )
            finally:
                store.close()

    def test_redaction_does_not_change_pre_dispatch_replay_identity(self) -> None:
        first = SideEffectAwareBody._signature_hash(
            "command",
            {"command": "tool --read-env", "env": {"API_TOKEN": "first"}},
        )
        second = SideEffectAwareBody._signature_hash(
            "command",
            {"command": "tool --read-env", "env": {"API_TOKEN": "second"}},
        )

        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
