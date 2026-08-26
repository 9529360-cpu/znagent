from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.body import BodyAction, BodyActionResult
from zn_agent.core.keyboard_text_body import KeyboardTextBody
from zn_agent.core.models import WorkingState, utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.side_effect_body import SideEffectAwareBody
from zn_agent.core.store import KernelStore


class _FakeSideEffectBody(SideEffectAwareBody):
    def __init__(self, *, store, on_dispatch=None):
        self.on_dispatch = on_dispatch
        self.calls: list[tuple[str, str | None, dict]] = []
        super().__init__(store=store)

    def _dispatch(self, action: BodyAction, started: str) -> BodyActionResult:
        self.calls.append((action.kind, action.event_id, dict(action.args)))
        if self.on_dispatch is not None:
            self.on_dispatch(action)
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output="ok",
            data={"fake": True},
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )


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

                def crash_after_start(_action):
                    assert guard is not None
                    attempts = guard.uncertain_attempts(event_id)
                    self.assertEqual(len(attempts), 1)
                    self.assertEqual(attempts[0]["status"], "started")
                    self.assertEqual(attempts[0]["kind"], kind)
                    raise SystemExit("simulate process interruption after durable start")

                guard = _FakeSideEffectBody(store=store, on_dispatch=crash_after_start)
                with self.assertRaises(SystemExit):
                    guard.act(kind, event_id=event_id, **args)
                self.assertEqual(len(guard.calls), 1)
                self.assertEqual(len(guard.uncertain_attempts(event_id)), 1)
                store.close()

                restored_store = KernelStore(store_path)
                restored_guard = _FakeSideEffectBody(store=restored_store)
                try:
                    blocked = restored_guard.act(kind, event_id=event_id, **args)
                    self.assertFalse(blocked.success)
                    self.assertTrue(blocked.data["side_effect_uncertain"])
                    self.assertTrue(blocked.data["replay_blocked"])
                    self.assertIn("refusing blind replay", blocked.error or "")
                    self.assertEqual(restored_guard.calls, [])
                    self.assertEqual(len(restored_guard.uncertain_attempts(event_id)), 1)
                finally:
                    restored_store.close()

    def test_observed_nonreplayable_dispatch_closes_attempt_and_links_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            guard = _FakeSideEffectBody(store=store)
            try:
                result = guard.act(
                    "command",
                    event_id="evt-observed",
                    command="echo observed",
                )
                self.assertTrue(result.success)
                self.assertEqual(len(guard.calls), 1)
                self.assertTrue(result.data["side_effect_dispatch_observed"])
                attempt_id = result.data["side_effect_attempt_id"]
                self.assertEqual(guard.uncertain_attempts("evt-observed"), [])
                with closing(sqlite3.connect(store.path)) as conn:
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

    def test_recovery_resolution_closes_only_matching_started_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            guard = _FakeSideEffectBody(store=store)
            try:
                args = {"command": "echo guarded"}
                signature = guard._signature_hash("command", args)
                guard._start_attempt(
                    attempt_id="sidefx-resolution",
                    event_id="evt-resolution",
                    kind="command",
                    signature_hash=signature,
                )
                self.assertFalse(
                    guard.resolve_uncertain_attempt(
                        "sidefx-resolution",
                        event_id="evt-other",
                        status="verified_effect",
                    )
                )
                self.assertEqual(len(guard.uncertain_attempts("evt-resolution")), 1)
                self.assertTrue(
                    guard.resolve_uncertain_attempt(
                        "sidefx-resolution",
                        event_id="evt-resolution",
                        status="verified_effect",
                        evidence_action_id="observe-1",
                    )
                )
                self.assertEqual(guard.uncertain_attempts("evt-resolution"), [])
                with closing(sqlite3.connect(store.path)) as conn:
                    row = conn.execute(
                        "SELECT status,result_action_id,result_success "
                        "FROM resident_side_effect_attempts WHERE attempt_id=?",
                        ("sidefx-resolution",),
                    ).fetchone()
                self.assertEqual(row, ("verified_effect", "observe-1", None))
            finally:
                store.close()

    def test_exact_text_replace_is_not_broadened_into_nonreplayable_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            guard = _FakeSideEffectBody(store=store)
            try:
                result = guard.act(
                    "write_text",
                    event_id="evt-replace",
                    path="C:/tmp/example.txt",
                    content="final state",
                    append=False,
                )
                self.assertTrue(result.success)
                self.assertEqual(len(guard.calls), 1)
                self.assertNotIn("side_effect_attempt_id", result.data)
                self.assertEqual(guard.uncertain_attempts("evt-replace"), [])
            finally:
                store.close()

    def test_active_product_resident_preserves_keyboard_body_type_and_side_effect_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertIsInstance(resident.body, SideEffectAwareBody)
                self.assertIsInstance(resident.body, KeyboardTextBody)
                self.assertTrue(callable(resident.body.sense))
                self.assertTrue(callable(resident.body.recent_actions))
            finally:
                resident.store.close()

    @staticmethod
    def _prepare_uncertain_action(resident, *, task, kind, args, expected_outcome=None, source="native_deliberation"):
        event = resident.enqueue(task, payload={"required_capabilities": ["filesystem"]})
        claimed = resident.store.claim_event(event.event_id)
        assert claimed is not None
        intent = NativeActionIntent(
            intent_id=f"intent-{event.event_id}",
            event_id=event.event_id,
            kind=kind,
            args=dict(args),
            expected_outcome=(
                dict(expected_outcome) if isinstance(expected_outcome, dict) else None
            ),
            source=source,
        )
        state = WorkingState(
            current_event_id=event.event_id,
            stage="native_action",
            next_action=f"move body: {kind}",
            data={"native_action_intent": intent.to_dict()},
        )
        resident.store.save_working_state(state)
        signature = resident.body._signature_hash(kind, dict(args))
        attempt_id = f"sidefx-seeded-{event.event_id}"
        resident.body._start_attempt(
            attempt_id=attempt_id,
            event_id=event.event_id,
            kind=kind,
            signature_hash=signature,
        )
        return event, intent, state, attempt_id

    @staticmethod
    def _attempt_row(resident, attempt_id):
        with closing(sqlite3.connect(resident.store.path)) as conn:
            return conn.execute(
                "SELECT status,result_action_id FROM resident_side_effect_attempts "
                "WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()

    def test_interrupted_append_completes_from_verified_effect_without_replay_or_failure_learning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "effect-present.txt"
            target.write_text("prefix-suffix", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            args = {"path": str(target), "content": "suffix", "append": True}
            expected = {
                "kind": "text_equals",
                "path": str(target),
                "expected_text": "prefix-suffix",
            }
            try:
                event, _, state, attempt_id = self._prepare_uncertain_action(
                    resident,
                    task="append suffix to the current file",
                    kind="write_text",
                    args=args,
                    expected_outcome=expected,
                    source="resident_choice",
                )
                self.assertIsNone(
                    resident._native_action_step(event, state, readiness=None)
                )
                recovery_state = resident.store.get_working_state()
                self.assertEqual(recovery_state.stage, "side_effect_recovery")
                self.assertEqual(
                    recovery_state.data["side_effect_recovery"]["decision"],
                    "reverify_effect",
                )
                self.assertNotIn("local_failure", recovery_state.data)

                result = resident._side_effect_recovery_step(
                    event,
                    recovery_state,
                    readiness=None,
                )
                self.assertIsNotNone(result)
                assert result is not None
                self.assertTrue(result.success)
                self.assertIn("without replay", result.reason)
                self.assertEqual(target.read_text(encoding="utf-8"), "prefix-suffix")
                self.assertEqual(self._attempt_row(resident, attempt_id)[0], "verified_effect")
                writes = [
                    item
                    for item in resident.body.recent_actions(40)
                    if item.event_id == event.event_id and item.kind == "write_text"
                ]
                self.assertEqual(writes, [])
                final_state = resident.store.get_working_state()
                self.assertEqual(final_state.stage, "complete")
                self.assertNotIn("latest_verified_experience", final_state.data)
            finally:
                resident.store.close()

    def test_interrupted_derived_append_retries_only_after_exact_baseline_is_reobserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "effect-absent.txt"
            target.write_text("prefix-", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            args = {"path": str(target), "content": "suffix", "append": True}
            expected = {
                "kind": "text_equals",
                "path": str(target),
                "expected_text": "prefix-suffix",
            }
            try:
                event, _, state, attempt_id = self._prepare_uncertain_action(
                    resident,
                    task="append suffix to the current file",
                    kind="write_text",
                    args=args,
                    expected_outcome=expected,
                    source="resident_choice",
                )
                resident._native_action_step(event, state, readiness=None)
                recovery_state = resident.store.get_working_state()

                self.assertIsNone(
                    resident._side_effect_recovery_step(
                        event,
                        recovery_state,
                        readiness=None,
                    )
                )
                retry_state = resident.store.get_working_state()
                self.assertEqual(retry_state.stage, "native_action")
                self.assertEqual(
                    retry_state.data["side_effect_recovery"]["status"],
                    "verified_absent",
                )
                self.assertEqual(self._attempt_row(resident, attempt_id)[0], "verified_absent")
                reads_before_retry = [
                    item
                    for item in resident.body.recent_actions(40)
                    if item.event_id == event.event_id and item.kind == "read_text"
                ]
                self.assertGreaterEqual(len(reads_before_retry), 1)

                self.assertIsNone(
                    resident._native_action_step(event, retry_state, readiness=None)
                )
                verification_state = resident.store.get_working_state()
                self.assertEqual(verification_state.stage, "native_verification")
                result = resident._native_verification_step(
                    event,
                    verification_state,
                    readiness=None,
                )
                self.assertIsNotNone(result)
                assert result is not None
                self.assertTrue(result.success)
                self.assertEqual(target.read_text(encoding="utf-8"), "prefix-suffix")
                writes = [
                    item
                    for item in resident.body.recent_actions(60)
                    if item.event_id == event.event_id and item.kind == "write_text"
                ]
                self.assertEqual(len(writes), 1)
                self.assertEqual(resident.body.uncertain_attempts(event.event_id), [])
            finally:
                resident.store.close()

    def test_interrupted_generic_command_enters_blocked_recovery_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            args = {"command": "echo must-not-replay"}
            try:
                event, _, state, attempt_id = self._prepare_uncertain_action(
                    resident,
                    task="run the requested command once",
                    kind="command",
                    args=args,
                )
                self.assertIsNone(
                    resident._native_action_step(event, state, readiness=None)
                )
                recovery_state = resident.store.get_working_state()
                self.assertEqual(recovery_state.stage, "side_effect_recovery")
                recovery = recovery_state.data["side_effect_recovery"]
                self.assertEqual(recovery["decision"], "user_decision_required")
                self.assertTrue(recovery["replay_blocked"])
                self.assertNotIn("local_failure", recovery_state.data)
                self.assertEqual(len(resident.body.uncertain_attempts(event.event_id)), 1)

                self.assertIsNone(
                    resident._side_effect_recovery_step(
                        event,
                        recovery_state,
                        readiness=None,
                    )
                )
                after = resident.store.get_working_state()
                self.assertEqual(after.stage, "side_effect_recovery")
                self.assertIn("do not replay", after.next_action or "")
                self.assertEqual(self._attempt_row(resident, attempt_id)[0], "started")
                commands = [
                    item
                    for item in resident.body.recent_actions(40)
                    if item.event_id == event.event_id and item.kind == "command"
                ]
                self.assertEqual(commands, [])
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
