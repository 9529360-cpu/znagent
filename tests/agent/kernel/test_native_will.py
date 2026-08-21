from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.kernel import (
    CognitiveSituation,
    EventOutcome,
    EventStatus,
    ExecutionPath,
    IntentionalResidentRuntime,
)
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class NativeWillTests(unittest.TestCase):
    def test_intention_exists_in_situation_without_inventing_a_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            self.assertIsInstance(resident, IntentionalResidentRuntime)

            intention = resident.intend("maintain a long-lived resident objective")
            pulse = resident.pulse()
            situation = resident.life.snapshot().current_situation

            self.assertIsInstance(situation, CognitiveSituation)
            self.assertIsNone(situation.active_event_id)
            self.assertEqual(situation.active_intention_id, intention.intention_id)
            self.assertEqual(
                situation.active_intention_description,
                "maintain a long-lived resident objective",
            )
            self.assertEqual(pulse.thought.focus, intention.description)
            self.assertEqual(pulse.thought.action_kind, "observe")
            self.assertIn("no new concrete step", pulse.thought.reason)
            self.assertIsNone(resident.live_once())
            self.assertEqual(resident.store.list_events(), [])
            resident.store.close()

            # Will belongs to the durable resident, not the current Python
            # process or conversation.
            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            pulse = restored.pulse()
            situation = restored.life.snapshot().current_situation
            self.assertEqual(situation.active_intention_id, intention.intention_id)
            self.assertEqual(pulse.thought.focus, intention.description)
            restored.store.close()

    def test_concrete_intention_step_runs_through_normal_body_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "will" / "result.txt"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            intention = resident.intend(
                "leave a durable result in my environment",
                priority=5,
                next_task=f"ensure {target} contains the requested content",
                next_payload={
                    "path": str(target),
                    "content": "completed by resident will",
                },
                complete_on_step_success=True,
            )

            pulse = resident.pulse()
            self.assertEqual(pulse.thought.action_kind, "intention")
            self.assertEqual(pulse.thought.action_target, intention.intention_id)

            # Advancing Will creates an internal event; it does not call a model
            # and it does not register a new skill.
            self.assertIsNone(resident.live_once())
            engaged = resident.will.get(intention.intention_id)
            self.assertEqual(engaged.status, "engaged")
            self.assertIsNotNone(engaged.related_event_id)
            self.assertIsNone(engaged.next_task)
            self.assertEqual(resident.capabilities.names(), ())

            terminal = None
            for _ in range(20):
                terminal = resident.live_once()
                if terminal is not None:
                    break

            self.assertIsNotNone(terminal)
            self.assertTrue(terminal.success)
            self.assertEqual(terminal.execution_path, ExecutionPath.BODY)
            self.assertEqual(terminal.model_invocations, 0)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "completed by resident will",
            )

            completed = resident.will.get(intention.intention_id)
            self.assertEqual(completed.status, "completed")
            self.assertIsNone(completed.related_event_id)
            self.assertIn(str(target), completed.last_outcome)
            self.assertEqual(resident.will.active(), [])
            resident.store.close()

    def test_engaged_intention_resumes_same_internal_event_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "resume" / "will.txt"

            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            intention = first.intend(
                "finish the same step after a resident restart",
                priority=3,
                next_task=f"ensure {target} contains the requested content",
                next_payload={"path": str(target), "content": "same intention"},
                complete_on_step_success=True,
            )
            self.assertIsNone(first.live_once())
            engaged = first.will.get(intention.intention_id)
            event_id = engaged.related_event_id
            self.assertIsNotNone(event_id)
            self.assertFalse(target.exists())
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            pulse = second.pulse()
            situation = second.life.snapshot().current_situation

            self.assertEqual(situation.active_event_id, event_id)
            self.assertEqual(situation.active_intention_id, intention.intention_id)
            self.assertEqual(situation.active_intention_status, "engaged")
            self.assertEqual(situation.active_intention_related_event_id, event_id)
            self.assertEqual(pulse.thought.action_target, event_id)

            terminal = None
            for _ in range(20):
                terminal = second.live_once()
                if terminal is not None:
                    break

            self.assertIsNotNone(terminal)
            self.assertTrue(terminal.success)
            self.assertEqual(terminal.event.event_id, event_id)
            self.assertEqual(terminal.model_invocations, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "same intention")

            restored_intention = second.will.get(intention.intention_id)
            self.assertEqual(restored_intention.status, "completed")
            intention_events = [
                event
                for event in second.store.list_events(limit=100)
                if event.payload.get("intention_id") == intention.intention_id
            ]
            self.assertEqual(len(intention_events), 1)
            second.store.close()

    def test_will_reconciles_if_process_dies_after_outcome_before_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            intention = first.intend(
                "survive the event-to-will handoff crash window",
                next_task="perform one durable step",
                complete_on_step_success=True,
            )
            self.assertIsNone(first.live_once())
            engaged = first.will.get(intention.intention_id)
            event_id = engaged.related_event_id
            self.assertIsNotNone(event_id)

            # Simulate the exact crash window: event and outcome are durable,
            # but Will has not yet received the outcome callback.
            first.store.finish_event(event_id, success=True)
            first.store.save_event_outcome(
                EventOutcome(
                    event_id=event_id,
                    success=True,
                    execution_path=ExecutionPath.BODY,
                    response="durable step already finished",
                    model_invocations=0,
                    reason="simulated crash after outcome persistence",
                )
            )
            self.assertEqual(first.will.get(intention.intention_id).status, "engaged")
            self.assertEqual(first.store.get_event(event_id).status, EventStatus.COMPLETED)
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            repaired = second.will.get(intention.intention_id)

            self.assertEqual(repaired.status, "completed")
            self.assertIsNone(repaired.related_event_id)
            self.assertIn("durable step already finished", repaired.last_outcome)
            self.assertEqual(second.will.active(), [])
            second.store.close()


if __name__ == "__main__":
    unittest.main()
