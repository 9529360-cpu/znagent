from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.kernel import (
    CognitiveSituation,
    KernelStore,
    PersistentNervousSystem,
)
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class PersistentNervousSystemTests(unittest.TestCase):
    def test_repeated_experience_strengthens_one_trace_instead_of_appending_memories(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            nervous = PersistentNervousSystem(store)

            first = nervous.perceive(
                "vision",
                "a red warning mark appeared on the resident dashboard",
                features=("dashboard", "warning"),
                salience=0.75,
                valence=-0.45,
                arousal=0.70,
            )
            second = nervous.perceive(
                "vision",
                "a red warning mark appeared on the resident dashboard",
                features=("dashboard", "warning"),
                salience=0.75,
                valence=-0.45,
                arousal=0.70,
            )

            self.assertEqual(first.trace_id, second.trace_id)
            self.assertEqual(second.repetitions, 2)
            self.assertGreater(second.strength, first.strength)
            visual = [item for item in nervous.recent_traces(20) if item.channel == "vision"]
            self.assertEqual(len(visual), 1)
            store.close()

    def test_coactive_experience_builds_association_that_can_spread_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            nervous = PersistentNervousSystem(store)

            # Repeated co-activation strengthens the connection between two
            # otherwise unrelated percepts. The second trace can then become
            # active when only the first trace's cue is present.
            for _ in range(12):
                nervous.perceive(
                    "vision",
                    "a red lighthouse flashed over the harbor",
                    features=("lighthouse", "harbor"),
                    salience=0.72,
                    arousal=0.48,
                )
                nervous.perceive(
                    "sound",
                    "a quiet brass bell sounded once",
                    features=("bell", "signal"),
                    salience=0.72,
                    arousal=0.48,
                )

            activations = nervous.activate("lighthouse", limit=8)
            by_summary = {item.trace.summary: item for item in activations}

            self.assertIn("a red lighthouse flashed over the harbor", by_summary)
            self.assertIn("a quiet brass bell sounded once", by_summary)
            self.assertGreater(
                by_summary["a quiet brass bell sounded once"].associative_gain,
                0.0,
            )
            store.close()

    def test_visual_world_memory_and_affect_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first_store = KernelStore(db)
            first = PersistentNervousSystem(first_store)
            visual = first.remember_visual(
                "a blue status panel showed a failed deployment",
                features=("deployment", "panel", "failure"),
                salience=0.88,
                valence=-0.72,
                arousal=0.86,
            )
            world = first.remember_world(
                "a new solar storage technology was reported by a research lab",
                features=("solar", "storage", "research"),
                salience=0.70,
                valence=0.38,
                arousal=0.52,
            )
            before = first.snapshot()
            first_store.close()

            second_store = KernelStore(db)
            second = PersistentNervousSystem(second_store)
            after = second.snapshot()
            traces = {item.trace_id: item for item in second.recent_traces(20)}
            recalled = second.activate("solar storage research", limit=5)

            self.assertIn(visual.trace_id, traces)
            self.assertIn(world.trace_id, traces)
            self.assertEqual(after.heartbeat_count, before.heartbeat_count)
            self.assertAlmostEqual(after.tension, before.tension, places=6)
            self.assertAlmostEqual(after.valence, before.valence, places=6)
            self.assertTrue(any(item.trace.trace_id == world.trace_id for item in recalled))
            second_store.close()

    def test_lived_trace_enters_situation_and_thought_without_model_context_dump(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            remembered = resident.perceive_world(
                "SQLite writer lock contention appeared during a resident transaction",
                features=("sqlite", "writer", "lock", "transaction"),
                salience=0.82,
                valence=-0.35,
                arousal=0.68,
            )
            event = resident.enqueue(
                "investigate the sqlite writer lock contention",
                payload={"model_policy": "never"},
            )

            pulse = resident.pulse()
            situation = resident.life.snapshot().current_situation

            self.assertIsInstance(situation, CognitiveSituation)
            self.assertEqual(situation.active_event_id, event.event_id)
            self.assertIn(remembered.summary, situation.activated_neural_traces)
            self.assertTrue(
                any("associated lived trace became active" in item for item in pulse.thought.known)
            )
            self.assertIsNotNone(situation.nervous_tone)
            self.assertGreater(resident.status()["nervous_system"]["recent_trace_count"], 0)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
