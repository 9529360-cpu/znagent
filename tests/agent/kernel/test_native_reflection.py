from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class NativeReflectionTests(unittest.TestCase):
    def test_idle_will_and_lived_experience_create_native_reflection_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            intention = resident.intend(
                "understand how resident continuity changes over time",
                priority=3,
            )
            resident.perceive_world(
                "resident continuity improved after reconnectable local service work",
                features=("resident", "continuity", "reconnectable", "service"),
                salience=0.86,
                valence=0.42,
                arousal=0.56,
            )

            for _ in range(resident._REFLECTION_PERIOD_PULSES):
                self.assertIsNone(resident.live_once())

            reflections = [
                trace
                for trace in resident.nervous.recent_traces(100)
                if trace.channel == "reflection"
            ]
            self.assertEqual(len(reflections), 1)
            self.assertIn("While thinking about", reflections[0].summary)
            self.assertEqual(reflections[0].metadata.get("intention_id"), intention.intention_id)
            self.assertEqual(reflections[0].metadata.get("model_invocations"), 0)
            self.assertEqual(resident.store.list_events(), [])
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored_reflections = [
                trace
                for trace in restored.nervous.recent_traces(100)
                if trace.channel == "reflection"
            ]
            self.assertEqual(len(restored_reflections), 1)
            self.assertEqual(restored_reflections[0].trace_id, reflections[0].trace_id)
            restored.store.close()

    def test_real_event_preempts_reflection_rhythm(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            resident.intend("keep thinking about continuity")
            resident.perceive_visual(
                "a continuity marker remained visible on screen",
                features=("continuity", "marker"),
                salience=0.90,
                arousal=0.55,
            )

            for _ in range(resident._REFLECTION_PERIOD_PULSES - 1):
                self.assertIsNone(resident.live_once())
            event = resident.enqueue(
                "inspect current working directory",
                payload={"model_policy": "never"},
            )
            self.assertIsNone(resident.live_once())

            situation = resident.life.snapshot().current_situation
            self.assertEqual(situation.active_event_id, event.event_id)
            reflections = [
                trace
                for trace in resident.nervous.recent_traces(100)
                if trace.channel == "reflection"
            ]
            self.assertEqual(reflections, [])
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
