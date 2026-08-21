from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.kernel import CognitiveSituation, EmbodiedResidentRuntime, ExecutionPath
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


if __name__ == "__main__":
    unittest.main()
