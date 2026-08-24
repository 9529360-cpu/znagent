from __future__ import annotations

import shlex
import sys
import tempfile
import unittest
from pathlib import Path

from zn_agent.core import ExecutionPath, NativeActionIntent, WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class CommandPostconditionTests(unittest.TestCase):
    @staticmethod
    def _python_command(code: str) -> str:
        args = [sys.executable, "-c", code]
        return shlex.join(args)

    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 16) -> None:
        for _ in range(limit):
            if resident.store.get_working_state().stage == stage:
                return
            result = resident.live_once()
            if result is not None:
                raise AssertionError(
                    f"event reached terminal result before stage {stage}: {result}"
                )
        raise AssertionError(
            f"resident did not reach stage {stage}; current="
            f"{resident.store.get_working_state().stage}"
        )

    @staticmethod
    def _run_to_terminal(resident, limit: int = 24):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach a terminal result")

    def test_command_success_waits_for_independent_expected_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "marker.txt"
            primary = self._python_command(
                "from pathlib import Path; "
                f"Path({str(target)!r}).write_text('ready', encoding='utf-8')"
            )
            verify = self._python_command(
                "from pathlib import Path; "
                f"p=Path({str(target)!r}); "
                "text=p.read_text(encoding='utf-8') if p.exists() else ''; "
                "print(text); raise SystemExit(0 if text == 'ready' else 7)"
            )
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / ".zn" / "kernel.db",
            )
            event = resident.enqueue(
                "run the command and verify the resulting marker",
                payload={
                    "command": primary,
                    "workdir": str(root),
                    "model_policy": "never",
                    "expected_outcome": {
                        "kind": "command",
                        "command": verify,
                        "workdir": str(root),
                        "exit_code": 0,
                        "output_contains": "ready",
                    },
                },
            )
            self._advance_until_stage(resident, "native_action")

            before = resident.store.get_working_state()
            context = before.data["execution_context"]
            self.assertEqual(context["goal"], event.task)
            self.assertEqual(context["stage"], "native_action")
            self.assertEqual(context["current_action"]["kind"], "command")
            self.assertEqual(context["expected_outcome"]["kind"], "command")
            self.assertEqual(context["verification_history"], [])

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_verification")
            self.assertEqual(state.data["native_verification"]["kind"], "command")
            self.assertEqual(state.data["execution_context"]["stage"], "native_verification")
            self.assertEqual(target.read_text(encoding="utf-8"), "ready")

            pulse = resident.pulse()
            situation = resident.life.snapshot().current_situation
            self.assertEqual(pulse.thought.action_kind, "verify_action")
            self.assertEqual(pulse.thought.action_target, event.event_id)
            self.assertEqual(situation.task_goal, event.task)
            self.assertEqual(situation.task_expected_outcome_kind, "command")
            self.assertTrue(
                any("my active task goal remains" in item for item in pulse.thought.known)
            )
            self.assertTrue(
                any("completion criterion" in item for item in pulse.thought.known)
            )

            result = resident.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.BODY)
            self.assertEqual(result.model_invocations, 0)
            self.assertIn("independently verifying", result.reason)
            self.assertIn("ready", result.response)

            actions = [
                item
                for item in resident.body.recent_actions(30)
                if item.event_id == event.event_id and item.kind == "command"
            ]
            self.assertEqual(len(actions), 2)
            self.assertEqual(
                sum(1 for item in actions if item.data.get("command") == primary),
                1,
            )
            self.assertEqual(
                sum(1 for item in actions if item.data.get("command") == verify),
                1,
            )
            verification_action = next(
                item for item in actions if item.data.get("command") == verify
            )
            self.assertEqual(verification_action.data.get("exit_code"), 0)
            self.assertIn("ready", verification_action.output)
            resident.store.close()

    def test_command_postcondition_survives_restart_without_repeating_primary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / ".zn" / "kernel.db"
            target = root / "restart-marker.txt"
            primary = self._python_command(
                "from pathlib import Path; "
                f"Path({str(target)!r}).write_text('persisted', encoding='utf-8')"
            )
            verify = self._python_command(
                "from pathlib import Path; "
                f"p=Path({str(target)!r}); "
                "raise SystemExit(0 if p.exists() and "
                "p.read_text(encoding='utf-8') == 'persisted' else 8)"
            )
            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            event = first.enqueue(
                "run the command and verify its durable result",
                payload={
                    "command": primary,
                    "workdir": str(root),
                    "model_policy": "never",
                    "expected_outcome": {
                        "kind": "command",
                        "command": verify,
                        "workdir": str(root),
                    },
                },
            )
            self._advance_until_stage(first, "native_action")
            self.assertIsNone(first.live_once())
            first_state = first.store.get_working_state()
            self.assertEqual(first_state.stage, "native_verification")
            self.assertEqual(first_state.data["execution_context"]["goal"], event.task)
            self.assertEqual(
                first_state.data["execution_context"]["expected_outcome"]["kind"],
                "command",
            )
            self.assertEqual(target.read_text(encoding="utf-8"), "persisted")
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored = second.store.get_working_state()
            self.assertEqual(restored.current_event_id, event.event_id)
            self.assertEqual(restored.stage, "native_verification")
            self.assertEqual(restored.data["execution_context"]["goal"], event.task)
            self.assertEqual(restored.data["execution_context"]["stage"], "native_verification")
            pulse = second.pulse()
            self.assertEqual(pulse.thought.action_kind, "verify_action")

            result = second.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(result.event.event_id, event.event_id)

            actions = [
                item
                for item in second.body.recent_actions(30)
                if item.event_id == event.event_id and item.kind == "command"
            ]
            self.assertEqual(
                sum(1 for item in actions if item.data.get("command") == primary),
                1,
            )
            self.assertEqual(
                sum(1 for item in actions if item.data.get("command") == verify),
                1,
            )
            second.store.close()

    def test_failed_command_postcondition_returns_to_investigation_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = self._python_command("print('primary-ok')")
            verify = self._python_command(
                "print('verification says no'); raise SystemExit(9)"
            )
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / ".zn" / "kernel.db",
            )
            event = resident.enqueue(
                "run the command and verify the requested outcome",
                payload={
                    "command": primary,
                    "workdir": str(root),
                    "model_policy": "never",
                    "expected_outcome": {
                        "kind": "command",
                        "command": verify,
                        "workdir": str(root),
                        "exit_code": 0,
                        "output_contains": "expected-success-marker",
                    },
                },
            )
            self._advance_until_stage(resident, "native_action")
            self.assertIsNone(resident.live_once())
            self.assertEqual(resident.store.get_working_state().stage, "native_verification")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertIn("postcondition command verification failed", state.data["local_failure"])
            failures = state.data["native_action_failure_records"]
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["source"], "verification")
            verification = state.data["native_verification_result"]
            self.assertFalse(verification["verified"])
            self.assertEqual(verification["observed_exit_code"], 9)
            self.assertIn(
                "expected-success-marker",
                verification["missing_output_contains"],
            )
            context = state.data["execution_context"]
            self.assertEqual(context["goal"], event.task)
            self.assertEqual(context["stage"], "native_investigation")
            self.assertIn("postcondition command verification failed", context["current_gap"])
            self.assertFalse(context["latest_verification"]["verified"])
            self.assertEqual(context["latest_verification"]["observed_exit_code"], 9)
            self.assertEqual(context["failed_actions"]["current_evidence_count"], 1)

            pulse = resident.pulse()
            situation = resident.life.snapshot().current_situation
            self.assertEqual(situation.task_goal, event.task)
            self.assertIn("postcondition command verification failed", situation.task_current_gap)
            self.assertEqual(situation.task_expected_outcome_kind, "command")
            self.assertEqual(situation.last_verification_kind, "command")
            self.assertFalse(situation.last_verification_verified)
            self.assertIn(
                "postcondition command verification failed",
                situation.last_verification_error,
            )
            self.assertTrue(
                any(
                    "postcondition command verification failed" in item
                    for item in pulse.thought.unknown
                )
            )
            self.assertTrue(
                any(
                    "verification was contradicted by current reality" in item
                    for item in pulse.thought.known
                )
            )

            terminal = self._run_to_terminal(resident)
            self.assertFalse(terminal.success)
            self.assertEqual(terminal.model_invocations, 0)

            actions = [
                item
                for item in resident.body.recent_actions(40)
                if item.event_id == event.event_id and item.kind == "command"
            ]
            self.assertEqual(
                sum(1 for item in actions if item.data.get("command") == primary),
                1,
            )
            self.assertEqual(
                sum(1 for item in actions if item.data.get("command") == verify),
                1,
            )
            resident.store.close()

    def test_new_action_cycle_archives_old_verdict_without_current_pollution(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            event = resident.enqueue(
                "pursue the same goal with a revised action",
                payload={
                    "expected_outcome": {
                        "kind": "command",
                        "command": "verify revised state",
                    }
                },
            )
            state = WorkingState(
                current_event_id=event.event_id,
                stage="native_deliberation",
                data={
                    "local_failure": "old postcondition was contradicted",
                    "native_verification": {"kind": "command"},
                    "native_verification_result": {
                        "kind": "command",
                        "verified": False,
                        "expected_exit_code": 0,
                        "observed_exit_code": 9,
                    },
                    "native_action_result": {"kind": "command", "success": True},
                    "execution_context": {"verification_history": []},
                },
            )
            intent = NativeActionIntent(
                intent_id="act-revised",
                event_id=event.event_id,
                kind="command",
                args={"command": "revised action"},
                reason="new evidence supports a different movement",
            )

            resident._begin_native_action_cycle(event, state, intent)

            self.assertEqual(state.stage, "native_action")
            self.assertNotIn("native_verification", state.data)
            self.assertNotIn("native_verification_result", state.data)
            self.assertNotIn("native_action_result", state.data)
            self.assertNotIn("local_failure", state.data)
            context = state.data["execution_context"]
            self.assertEqual(context["goal"], event.task)
            self.assertIsNone(context["current_gap"])
            self.assertIsNone(context["latest_verification"])
            self.assertEqual(context["current_action"]["intent_id"], "act-revised")
            self.assertEqual(len(context["verification_history"]), 1)
            archived = context["verification_history"][0]
            self.assertFalse(archived["verified"])
            self.assertEqual(archived["observed_exit_code"], 9)
            self.assertIn("old postcondition", archived["error"])
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
