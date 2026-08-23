from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class EndogenousAttentionTests(unittest.TestCase):
    @staticmethod
    def _resident(tmp: str):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )

    def test_high_tension_pulls_attention_toward_salient_risk_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            for _ in range(6):
                resident.nervous.perceive(
                    "outcome",
                    "database corruption risk remains unresolved after a failed write",
                    features=("database", "corruption", "risk", "write"),
                    salience=0.96,
                    valence=-0.95,
                    arousal=0.92,
                )

            affect = resident.nervous.snapshot()
            self.assertGreaterEqual(affect.tension, 0.75)
            self.assertLess(
                resident._reflection_period_for(affect),
                resident._REFLECTION_PERIOD_PULSES,
            )

            pulse = resident.pulse()
            thought = pulse.thought
            self.assertIsNotNone(thought)
            self.assertIn("database corruption risk", thought.focus)
            self.assertIn("risk", thought.chosen_action)
            self.assertIn("protect", thought.reason)
            self.assertEqual(thought.action_kind, "observe")
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_due_world_focus_can_pull_idle_attention_without_becoming_a_model_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            focus = resident.follow_world(
                "distributed resident agent research",
                priority=4,
                interval_seconds=3600,
            )

            pulse = resident.pulse()
            thought = pulse.thought
            self.assertIsNotNone(thought)
            self.assertEqual(thought.focus, focus.topic)
            self.assertIn("world focus", thought.chosen_action)
            self.assertIn("curiosity", thought.reason)
            self.assertEqual(thought.action_kind, "observe")
            self.assertEqual(resident.store.list_events(), [])
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_fatigue_suppresses_exploration_and_prefers_internal_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            resident.follow_world("open ended machine intelligence", interval_seconds=3600)
            for index in range(26):
                resident.nervous.perceive(
                    "thought",
                    f"sustained internal cognition cycle {index}",
                    features=("sustained", "cognition"),
                    salience=0.30,
                    valence=0.0,
                    arousal=1.0,
                )

            affect = resident.nervous.snapshot()
            self.assertGreaterEqual(affect.fatigue, 0.75)
            self.assertGreaterEqual(
                resident._reflection_period_for(affect),
                resident._REFLECTION_PERIOD_PULSES * 2,
            )

            pulse = resident.pulse()
            thought = pulse.thought
            self.assertIsNotNone(thought)
            self.assertEqual(thought.focus, "internal recovery and continuity")
            self.assertIn("reduce active exploration", thought.chosen_action)
            self.assertIn("recovery", thought.reason)
            self.assertEqual(thought.action_kind, "observe")
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
