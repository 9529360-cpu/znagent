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

            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            first_state = first.life.snapshot()
            first.pulse()
            born_at = first_state.born_at
            wake_count = first.life.snapshot().wake_count
            pulse_count = first.life.snapshot().pulse_count
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            second_state = second.life.snapshot()

            self.assertEqual(second_state.born_at, born_at)
            self.assertGreater(second_state.wake_count, wake_count)
            self.assertEqual(second_state.pulse_count, pulse_count)
            self.assertEqual(second_state.name, first_state.name)
            second.store.close()

    def test_pulse_senses_body_without_any_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )

            pulse = resident.pulse()
            state = resident.life.snapshot()

            self.assertGreaterEqual(pulse.sequence, 1)
            self.assertIsNotNone(state.body)
            self.assertTrue(state.body.hostname)
            self.assertGreater(state.body.pid, 0)
            self.assertGreaterEqual(state.body.process_uptime_seconds, 0.0)
            self.assertEqual(state.external_brains, ())
            self.assertIn(state.mode, {"observing", "engaged", "recovering"})
            resident.store.close()

    def test_idle_pulse_forms_native_thought_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )

            pulse = resident.pulse()
            thought = pulse.thought

            self.assertIsNotNone(thought)
            self.assertEqual(thought.focus, "environment")
            self.assertEqual(thought.chosen_action, "observe for meaningful change")
            self.assertTrue(any("I am " in item for item in thought.known))
            self.assertEqual(resident.life.snapshot().current_thought.sequence, thought.sequence)
            self.assertEqual(len(resident.life.recent_thoughts(1)), 1)
            resident.store.close()

    def test_action_becomes_part_of_self_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            resident.capabilities.register(
                ExactTaskCapability(
                    name="local-wave",
                    triggers=("wave",),
                    handler=lambda event, state: CapabilityResult(
                        success=True,
                        response="hello",
                    ),
                )
            )

            result = resident.submit("wave")
            state = resident.life.snapshot()

            self.assertTrue(result.success)
            self.assertEqual(state.last_event_id, result.event.event_id)
            self.assertIn("success via capability", state.last_action_summary or "")
            self.assertEqual(state.intention, "observe for the next meaningful change")
            self.assertTrue(any("completed" in item for item in state.observations))
            resident.store.close()

    def test_pending_event_enters_attention_and_thought_on_pulse(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            event = resident.enqueue("finish the unfinished thing")

            pulse = resident.pulse()
            state = resident.life.snapshot()

            self.assertEqual(state.mode, "engaged")
            self.assertEqual(state.attention, event.task)
            self.assertIn(event.event_id, state.intention or "")
            self.assertIsNotNone(pulse.thought)
            self.assertEqual(pulse.thought.focus, event.task)
            self.assertIn(event.event_id, pulse.thought.chosen_action)
            self.assertIn("make progress on unfinished work", state.drives)
            resident.store.close()

    def test_unresolved_question_survives_restart_and_reenters_thought(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            first.life.set_open_questions(("what changed in the workspace",))
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            pulse = second.pulse()

            self.assertEqual(pulse.thought.focus, "what changed in the workspace")
            self.assertIn("what changed in the workspace", pulse.thought.unknown)
            self.assertEqual(pulse.thought.chosen_action, "inspect unresolved question")
            self.assertIn("reduce unresolved uncertainty", second.life.snapshot().drives)
            second.store.close()

    def test_recent_pulses_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            resident.pulse()
            resident.pulse()

            pulses = resident.life.recent_pulses(2)

            self.assertEqual(len(pulses), 2)
            self.assertGreater(pulses[0].sequence, pulses[1].sequence)
            self.assertIsNotNone(pulses[0].thought)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
