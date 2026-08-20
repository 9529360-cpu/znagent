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
            self.assertIn(state.mode, {"observing", "engaged"})
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
            self.assertEqual(state.intention, "remain available and observe")
            self.assertTrue(any("completed" in item for item in state.observations))
            resident.store.close()

    def test_pending_event_enters_attention_on_pulse(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            event = resident.enqueue("finish the unfinished thing")

            resident.pulse()
            state = resident.life.snapshot()

            self.assertEqual(state.mode, "engaged")
            self.assertEqual(state.attention, event.task)
            self.assertIn(event.event_id, state.intention or "")
            resident.store.close()

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
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
