from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core import CognitiveSituation, EmbodiedResidentRuntime, ExecutionPath
from zn_agent.core.action import derive_native_action_intent
from zn_agent.core.models import AgentEvent
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class NativeActionTests(unittest.TestCase):
    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 12) -> None:
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
    def _run_to_terminal(resident, limit: int = 20):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach a terminal result")

    def test_native_evidence_becomes_body_intent_then_verified_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "notes" / "self.txt"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            self.assertIsInstance(resident, EmbodiedResidentRuntime)

            event = resident.enqueue(
                f"ensure {target} contains the requested content",
                payload={
                    "path": str(target),
                    "content": "ZN moved its own body",
                },
            )
            self._advance_until_stage(resident, "native_action")

            state = resident.store.get_working_state()
            raw_intent = state.data.get("native_action_intent")
            self.assertIsInstance(raw_intent, dict)
            self.assertEqual(raw_intent["kind"], "write_text")
            self.assertEqual(raw_intent["event_id"], event.event_id)
            self.assertIn("target is missing", raw_intent["reason"])

            pulse = resident.pulse()
            situation = resident.life.snapshot().current_situation
            self.assertIsInstance(situation, CognitiveSituation)
            self.assertEqual(situation.working_stage, "native_action")
            self.assertEqual(situation.native_action_kind, "write_text")
            self.assertEqual(pulse.thought.action_kind, "body_action")
            self.assertEqual(pulse.thought.action_target, event.event_id)

            # A successful write is not a terminal task result. It persists an
            # explicit postcondition and waits for a later resident observation.
            self.assertIsNone(resident.live_once())
            verification_state = resident.store.get_working_state()
            self.assertEqual(verification_state.stage, "native_verification")
            self.assertEqual(
                verification_state.data["native_verification"]["kind"],
                "text_equals",
            )
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "ZN moved its own body",
            )

            verification_pulse = resident.pulse()
            self.assertEqual(verification_pulse.thought.action_kind, "verify_action")
            self.assertEqual(verification_pulse.thought.action_target, event.event_id)

            result = resident.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.BODY)
            self.assertEqual(result.model_invocations, 0)
            self.assertIn("independently verifying", result.reason)
            self.assertEqual(resident.capabilities.names(), ())

            movements = [
                item.kind
                for item in reversed(resident.body.recent_actions(20))
                if item.event_id == event.event_id
            ]
            self.assertIn("inspect_path", movements)
            self.assertIn("write_text", movements)
            self.assertIn("read_text", movements)
            self.assertLess(movements.index("inspect_path"), movements.index("write_text"))
            self.assertLess(movements.index("write_text"), movements.index("read_text"))
            resident.store.close()

    def test_already_satisfied_text_state_completes_from_evidence_without_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "already.txt"
            target.write_text("already here", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            event = resident.enqueue(
                f"ensure {target} contains the requested content",
                payload={
                    "path": str(target),
                    "content": "already here",
                    "model_policy": "never",
                },
            )

            result = self._run_to_terminal(resident)

            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.INVESTIGATION)
            self.assertEqual(result.model_invocations, 0)
            self.assertIn("requested text state is already satisfied", result.response)
            self.assertEqual(target.read_text(encoding="utf-8"), "already here")

            movements = [
                item.kind
                for item in resident.body.recent_actions(20)
                if item.event_id == event.event_id
            ]
            self.assertIn("inspect_path", movements)
            self.assertIn("read_text", movements)
            self.assertNotIn("write_text", movements)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_observed_git_root_anchors_native_command_intent(self):
        event = AgentEvent(
            event_id="evt-observed-root",
            task="run tests in the current repository",
            payload={"command": "python -m unittest"},
        )

        intent = derive_native_action_intent(
            event,
            facts={
                "git": {
                    "available": True,
                    "root": "/observed/repository",
                    "branch": "dev/zn-agent",
                }
            },
        )

        self.assertIsNotNone(intent)
        self.assertEqual(intent.kind, "command")
        self.assertEqual(intent.args.get("workdir"), "/observed/repository")
        self.assertEqual(intent.source, "native_deliberation")
        self.assertIn("observed the repository root", intent.reason)

    def test_observed_directory_prevents_blind_file_write_intent(self):
        target = "/observed/target"
        event = AgentEvent(
            event_id="evt-incompatible-target",
            task=f"ensure {target} contains the requested content",
            payload={"path": target, "content": "text"},
        )

        intent = derive_native_action_intent(
            event,
            facts={
                "paths": [
                    {
                        "path": target,
                        "exists": True,
                        "type": "directory",
                    }
                ]
            },
        )

        self.assertIsNone(intent)

    def test_native_action_intent_survives_restart_and_continues_same_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "resume" / "action.txt"

            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            event = first.enqueue(
                f"ensure {target} contains the requested content",
                payload={"path": str(target), "content": "resume body action"},
            )
            self._advance_until_stage(first, "native_action")
            before = first.store.get_working_state()
            intent_id = before.data["native_action_intent"]["intent_id"]
            self.assertFalse(target.exists())
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            pulse = second.pulse()
            situation = second.life.snapshot().current_situation

            self.assertEqual(situation.active_event_id, event.event_id)
            self.assertEqual(situation.working_stage, "native_action")
            self.assertEqual(situation.native_action_intent_id, intent_id)
            self.assertEqual(pulse.thought.action_kind, "body_action")

            self.assertIsNone(second.live_once())
            self.assertEqual(second.store.get_working_state().stage, "native_verification")
            result = second.live_once()
            self.assertIsNotNone(result)
            self.assertEqual(result.event.event_id, event.event_id)
            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.BODY)
            self.assertEqual(target.read_text(encoding="utf-8"), "resume body action")
            self.assertEqual(result.model_invocations, 0)
            second.store.close()

    def test_postcondition_verification_survives_restart_without_repeating_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "resume" / "verify.txt"

            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            event = first.enqueue(
                f"ensure {target} contains the requested content",
                payload={
                    "path": str(target),
                    "content": "verify after restart",
                    "model_policy": "never",
                },
            )
            self._advance_until_stage(first, "native_action")
            self.assertIsNone(first.live_once())
            before = first.store.get_working_state()
            self.assertEqual(before.stage, "native_verification")
            self.assertEqual(target.read_text(encoding="utf-8"), "verify after restart")
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
            self.assertEqual(pulse.thought.action_target, event.event_id)

            result = second.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(result.event.event_id, event.event_id)
            self.assertIn("independently verifying", result.reason)

            movements = [
                item.kind
                for item in second.body.recent_actions(30)
                if item.event_id == event.event_id
            ]
            self.assertEqual(movements.count("write_text"), 1)
            self.assertGreaterEqual(movements.count("read_text"), 1)
            second.store.close()

    def test_contradicted_postcondition_returns_to_investigation_without_blind_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "contradicted.txt"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            event = resident.enqueue(
                f"ensure {target} contains the requested content",
                payload={
                    "path": str(target),
                    "content": "intended state",
                    "model_policy": "never",
                },
            )
            self._advance_until_stage(resident, "native_action")
            self.assertIsNone(resident.live_once())
            self.assertEqual(resident.store.get_working_state().stage, "native_verification")

            # Reality changes between movement and verification. The successful
            # write call therefore cannot be treated as proof of task completion.
            target.write_text("contradicted by current reality", encoding="utf-8")
            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertIn("postcondition verification failed", state.data["local_failure"])
            failures = state.data["native_action_failure_records"]
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["source"], "verification")
            self.assertEqual(
                state.data["execution_context"]["failed_actions"]["current_evidence_count"],
                1,
            )
            self.assertFalse(state.data["native_verification_result"]["verified"])

            terminal = self._run_to_terminal(resident)
            self.assertFalse(terminal.success)
            self.assertEqual(target.read_text(encoding="utf-8"), "contradicted by current reality")
            movements = [
                item.kind
                for item in resident.body.recent_actions(40)
                if item.event_id == event.event_id
            ]
            self.assertEqual(movements.count("write_text"), 1)
            self.assertGreaterEqual(movements.count("read_text"), 1)
            resident.store.close()

    def test_failed_body_action_becomes_next_thought_evidence_not_a_retry_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            event = resident.enqueue(
                "perform the requested local body movement",
                payload={"body_action": {"kind": "movement_that_does_not_exist"}},
            )
            self._advance_until_stage(resident, "native_action")

            # Execute the selected movement. Failure is not terminal here: it
            # becomes fresh evidence and sends cognition back to investigation.
            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertIn("unknown body action kind", state.data["local_failure"])

            pulse = resident.pulse()
            situation = resident.life.snapshot().current_situation
            self.assertEqual(situation.last_body_action_kind, "movement_that_does_not_exist")
            self.assertFalse(situation.last_body_action_success)
            self.assertIn("unknown body action kind", situation.last_body_action_error)
            self.assertTrue(
                any("unknown body action kind" in item for item in pulse.thought.unknown)
            )

            terminal = None
            for _ in range(12):
                terminal = resident.live_once()
                if terminal is not None:
                    break
            self.assertIsNotNone(terminal)
            self.assertFalse(terminal.success)

            repeated = [
                item
                for item in resident.body.recent_actions(20)
                if item.event_id == event.event_id
                and item.kind == "movement_that_does_not_exist"
            ]
            self.assertEqual(len(repeated), 1)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
