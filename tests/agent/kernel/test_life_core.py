from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.kernel import CapabilityResult, ExactTaskCapability
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class LifeCoreTests(unittest.TestCase):
    def test_living_self_survives_process_style_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=db)
            first_state = first.life.snapshot()
            first.pulse()
            born_at = first_state.born_at
            wake_count = first.life.snapshot().wake_count
            pulse_count = first.life.snapshot().pulse_count
            first.store.close()

            second = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=db)
            second_state = second.life.snapshot()
            self.assertEqual(second_state.born_at, born_at)
            self.assertGreater(second_state.wake_count, wake_count)
            self.assertEqual(second_state.pulse_count, pulse_count)
            self.assertEqual(second_state.name, first_state.name)
            second.store.close()

    def test_pulse_senses_body_and_builds_situation_without_any_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=Path(tmp) / "kernel.db")
            pulse = resident.pulse()
            state = resident.life.snapshot()
            self.assertGreaterEqual(pulse.sequence, 1)
            self.assertIsNotNone(state.body)
            self.assertTrue(state.body.hostname)
            self.assertGreater(state.body.pid, 0)
            self.assertEqual(state.external_brains, ())
            self.assertIsNotNone(state.current_situation)
            self.assertEqual(state.current_situation.external_brains, ())
            self.assertEqual(state.current_situation.body_health, "nominal")
            self.assertEqual(len(resident.life.recent_situations(1)), 1)
            resident.store.close()

    def test_idle_pulse_forms_native_thought_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=Path(tmp) / "kernel.db")
            thought = resident.pulse().thought
            self.assertIsNotNone(thought)
            self.assertEqual(thought.focus, "environment")
            self.assertEqual(thought.action_kind, "observe")
            self.assertIsNone(thought.action_target)
            resident.store.close()

    def test_action_becomes_part_of_self_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=Path(tmp) / "kernel.db")
            resident.capabilities.register(ExactTaskCapability(name="local-wave", triggers=("wave",), handler=lambda event, state: CapabilityResult(success=True, response="hello")))
            result = resident.submit("wave")
            state = resident.life.snapshot()
            self.assertTrue(result.success)
            self.assertEqual(state.last_event_id, result.event.event_id)
            self.assertIn("success via capability", state.last_action_summary or "")
            resident.store.close()

    def test_pending_event_enters_situation_attention_and_thought(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=Path(tmp) / "kernel.db")
            event = resident.enqueue("finish the unfinished thing")
            pulse = resident.pulse()
            state = resident.life.snapshot()
            self.assertEqual(state.current_situation.active_event_id, event.event_id)
            self.assertEqual(state.current_situation.active_task, event.task)
            self.assertEqual(pulse.thought.action_kind, "event")
            self.assertEqual(pulse.thought.action_target, event.event_id)
            self.assertEqual(pulse.thought.focus, event.task)
            resident.store.close()

    def test_live_once_executes_exact_event_selected_by_thought(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=Path(tmp) / "kernel.db")
            resident.capabilities.register(ExactTaskCapability(name="local", triggers=("low", "high"), handler=lambda event, state: CapabilityResult(success=True, response=event.task)))
            low = resident.enqueue("low", priority=1)
            high = resident.enqueue("high", priority=9)
            result = resident.live_once()
            thought = resident.life.recent_thoughts(1)[0]
            self.assertEqual(thought.action_target, high.event_id)
            self.assertEqual(result.event.event_id, high.event_id)
            self.assertEqual(result.response, "high")
            self.assertEqual(resident.store.get_event(low.event_id).status.value, "pending")
            resident.store.close()

    def test_unresolved_question_survives_restart_and_reenters_thought(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=db)
            first.life.set_open_questions(("what changed in the workspace",))
            first.store.close()
            second = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=db)
            thought = second.pulse().thought
            self.assertEqual(thought.focus, "what changed in the workspace")
            self.assertEqual(thought.action_kind, "reflect")
            self.assertEqual(thought.action_target, "what changed in the workspace")
            second.store.close()

    def test_impasse_survives_restart_and_reenters_situation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=db)
            result = first.submit("something I cannot yet do")
            self.assertFalse(result.success)
            impasse_id = first.life.snapshot().current_impasse.impasse_id
            first.store.close()

            second = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=db)
            pulse = second.pulse()
            state = second.life.snapshot()
            self.assertIsNotNone(state.current_impasse)
            self.assertEqual(state.current_impasse.impasse_id, impasse_id)
            self.assertEqual(state.current_situation.active_impasse_id, impasse_id)
            self.assertEqual(pulse.thought.action_kind, "impasse")
            self.assertEqual(pulse.thought.action_target, impasse_id)
            second.store.close()

    def test_recent_pulses_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(config={"model": {}}, store_path=Path(tmp) / "kernel.db")
            resident.pulse()
            resident.pulse()
            pulses = resident.life.recent_pulses(2)
            self.assertEqual(len(pulses), 2)
            self.assertGreater(pulses[0].sequence, pulses[1].sequence)
            self.assertIsNotNone(pulses[0].thought)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()