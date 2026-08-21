from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.kernel import CognitiveSituation, EmbodiedResidentRuntime, ExecutionPath
from agent.kernel.action import derive_native_action_intent
from agent.kernel.models import AgentEvent
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


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

    def test_native_evidence_becomes_body_intent_then_outcome(self):
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

            result = resident.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.BODY)
            self.assertEqual(result.model_invocations, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "ZN moved its own body")
            self.assertEqual(resident.capabilities.names(), ())

            movements = [
                item.kind
                for item in reversed(resident.body.recent_actions(20))
                if item.event_id == event.event_id
            ]
            self.assertIn("inspect_path", movements)
            self.assertIn("write_text", movements)
            self.assertLess(movements.index("inspect_path"), movements.index("write_text"))
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

            result = second.live_once()
            self.assertIsNotNone(result)
            self.assertEqual(result.event.event_id, event.event_id)
            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.BODY)
            self.assertEqual(target.read_text(encoding="utf-8"), "resume body action")
            self.assertEqual(result.model_invocations, 0)
            second.store.close()

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
