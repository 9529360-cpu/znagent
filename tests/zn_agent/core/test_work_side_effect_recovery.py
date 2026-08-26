from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.body import BodyActionResult
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.side_effect_body import SideEffectAwareBody
from zn_agent.core.store import KernelStore


class _FakeBody:
    def __init__(self, *, on_act=None):
        self.on_act = on_act
        self.calls: list[tuple[str, str | None, dict]] = []

    def act(self, kind: str, *, event_id: str | None = None, **args):
        self.calls.append((kind, event_id, dict(args)))
        if self.on_act is not None:
            self.on_act(kind, event_id, dict(args))
        return BodyActionResult(
            action_id=f"fake-{len(self.calls)}",
            kind=str(kind),
            success=True,
            output="ok",
            data={"fake": True},
            event_id=event_id,
        )

    def sense(self):
        return {"fake": True}

    def recent_actions(self, limit: int = 20):
        return []


class SideEffectAwareBodyTests(unittest.TestCase):
    def test_nonreplayable_command_and_append_persist_started_before_dispatch_and_block_after_reopen(self):
        cases = (
            ("command", {"command": "echo once"}),
            (
                "write_text",
                {"path": "C:/tmp/example.txt", "content": "once", "append": True},
            ),
        )
        for kind, args in cases:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                store_path = Path(tmp) / "kernel.db"
                store = KernelStore(store_path)
                event_id = f"evt-{kind}"
                guard = None

                def crash_after_start(_kind, _event_id, _args):
                    assert guard is not None
                    attempts = guard.uncertain_attempts(event_id)
                    self.assertEqual(len(attempts), 1)
                    self.assertEqual(attempts[0]["status"], "started")
                    self.assertEqual(attempts[0]["kind"], kind)
                    raise SystemExit("simulate process interruption after durable start")

                first_body = _FakeBody(on_act=crash_after_start)
                guard = SideEffectAwareBody(first_body, store=store)
                with self.assertRaises(SystemExit):
                    guard.act(kind, event_id=event_id, **args)
                self.assertEqual(len(first_body.calls), 1)
                self.assertEqual(len(guard.uncertain_attempts(event_id)), 1)
                store.close()

                restored_store = KernelStore(store_path)
                second_body = _FakeBody()
                restored_guard = SideEffectAwareBody(second_body, store=restored_store)
                try:
                    blocked = restored_guard.act(kind, event_id=event_id, **args)
                    self.assertFalse(blocked.success)
                    self.assertTrue(blocked.data["side_effect_uncertain"])
                    self.assertTrue(blocked.data["replay_blocked"])
                    self.assertIn("refusing blind replay", blocked.error or "")
                    self.assertEqual(second_body.calls, [])
                    self.assertEqual(len(restored_guard.uncertain_attempts(event_id)), 1)
                finally:
                    restored_store.close()

    def test_observed_nonreplayable_dispatch_closes_attempt_and_links_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            body = _FakeBody()
            guard = SideEffectAwareBody(body, store=store)
            try:
                result = guard.act(
                    "command",
                    event_id="evt-observed",
                    command="echo observed",
                )
                self.assertTrue(result.success)
                self.assertEqual(len(body.calls), 1)
                self.assertTrue(result.data["side_effect_dispatch_observed"])
                attempt_id = result.data["side_effect_attempt_id"]
                self.assertEqual(guard.uncertain_attempts("evt-observed"), [])
                with sqlite3.connect(store.path) as conn:
                    row = conn.execute(
                        "SELECT status,result_action_id,result_success "
                        "FROM resident_side_effect_attempts WHERE attempt_id=?",
                        (attempt_id,),
                    ).fetchone()
                self.assertIsNotNone(row)
                assert row is not None
                self.assertEqual(row[0], "observed")
                self.assertEqual(row[1], result.action_id)
                self.assertEqual(row[2], 1)
            finally:
                store.close()

    def test_exact_text_replace_is_not_broadened_into_nonreplayable_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            body = _FakeBody()
            guard = SideEffectAwareBody(body, store=store)
            try:
                result = guard.act(
                    "write_text",
                    event_id="evt-replace",
                    path="C:/tmp/example.txt",
                    content="final state",
                    append=False,
                )
                self.assertTrue(result.success)
                self.assertEqual(len(body.calls), 1)
                self.assertNotIn("side_effect_attempt_id", result.data)
                self.assertEqual(guard.uncertain_attempts("evt-replace"), [])
            finally:
                store.close()

    def test_active_product_resident_wraps_final_body_with_side_effect_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertIsInstance(resident.body, SideEffectAwareBody)
                self.assertTrue(callable(resident.body.sense))
                self.assertTrue(callable(resident.body.recent_actions))
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
