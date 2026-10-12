from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.body import BodyAction, BodyActionResult, NativeBody
from zn_agent.core.store import KernelStore


class AuditRedactionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "kernel.db")
        self.addCleanup(self.store.close)
        self.body = NativeBody(store=self.store)

    def _record(self, kind, args):
        action = BodyAction(
            action_id="a1", kind=kind, args=args, event_id="e1",
        )
        result = BodyActionResult(
            action_id="a1", kind=kind, success=True, event_id="e1",
            started_at="t0", completed_at="t1",
        )
        self.body._record(action, result)
        with closing(sqlite3.connect(self.store.path)) as conn:
            row = conn.execute(
                "SELECT action_json FROM native_body_actions WHERE action_id='a1'"
            ).fetchone()
        return json.loads(row[0])

    def test_command_arg_redacted(self):
        secret = "curl -H 'Authorization: Bearer super-secret-token' https://x"
        record = self._record("command", {"command": secret, "timeout": 60.0})
        command = record["args"]["command"]
        self.assertTrue(command["redacted"])
        self.assertEqual(command["chars"], len(secret))
        self.assertNotIn("super-secret-token", json.dumps(record))
        # Non-sensitive args stay visible for debugging.
        self.assertEqual(record["args"]["timeout"], 60.0)

    def test_terminal_input_redacted(self):
        record = self._record(
            "terminal_input", {"session_id": "s1", "input": "hunter2\n"}
        )
        self.assertTrue(record["args"]["input"]["redacted"])
        self.assertNotIn("hunter2", json.dumps(record))
        self.assertEqual(record["args"]["session_id"], "s1")

    def test_non_command_kinds_untouched(self):
        record = self._record("list_directory", {"path": "/tmp"})
        self.assertEqual(record["args"], {"path": "/tmp"})


if __name__ == "__main__":
    unittest.main()
