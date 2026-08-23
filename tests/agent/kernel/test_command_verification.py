from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent.kernel import ExecutionPath
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class CommandPostconditionTests(unittest.TestCase):
    @staticmethod
    def _python_command(code: str) -> str:
        return subprocess.list2cmdline([sys.executable, "-c", code])

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

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_verification")
            self.assertEqual(state.data["native_verification"]["kind"], "command")
            self.assertEqual(target.read_text(encoding="utf-8"), "ready")

            pulse = resident.pulse()
            self.assertEqual(pulse.thought.action_kind, "verify_action")
            self.assertEqual(pulse.thought.action_target, event.event_id)

            result = resident.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.BODY)
            self.assertEqual(result.model_invocations, 0)
            self.assertIn("independently verifying", result.reason)
            self.assertIn("ready", result.response)

            verification = resident.store.get_working_state().data.get(
                "native_verification_result"
            )
            self.assertIsInstance(verification, dict)
            self.assertTrue(verification["verified"])
            self.assertEqual(verification["observed_exit_code"], 0)
            self.assertEqual(verification["missing_output_contains"], [])

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
            self.assertEqual(first.store.get_working_state().stage, "native_verification")
            self.assertEqual(target.read_text(encoding="utf-8"), "persisted")
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored = second.store.get_working_state()
            self.assertEqual(restored.current_event_id, event.event_id)
            self.assertEqual(restored.stage, "native_verification")
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
            self.assertTrue(state.data.get("native_action_failure_signature"))
            verification = state.data["native_verification_result"]
            self.assertFalse(verification["verified"])
            self.assertEqual(verification["observed_exit_code"], 9)
            self.assertIn(
                "expected-success-marker",
                verification["missing_output_contains"],
            )

            # The contradiction becomes part of the next resident Situation and
            # Thought immediately. Cognition does not spend another pulse acting
            # as though the successful primary process proved the goal.
            pulse = resident.pulse()
            situation = resident.life.snapshot().current_situation
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


if __name__ == "__main__":
    unittest.main()
