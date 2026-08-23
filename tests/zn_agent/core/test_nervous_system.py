from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zn_agent.core import (
    CognitiveSituation,
    KernelStore,
    PersistentNervousSystem,
)
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


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

    def test_different_experiences_consolidate_shared_structure_into_schema_not_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            resident.perceive_world(
                "SQLite writer contention appeared in an upstream issue report",
                features=("sqlite_lock", "database", "contention"),
                salience=0.76,
                arousal=0.55,
            )
            resident.perceive_visual(
                "the local database monitor showed a writer lock spike",
                features=("sqlite_lock", "database", "monitor"),
                salience=0.82,
                valence=-0.24,
                arousal=0.63,
            )
            resident.nervous.perceive(
                "action",
                "a local transaction retry resolved one writer lock collision",
                features=("sqlite_lock", "database", "retry"),
                salience=0.80,
                valence=0.30,
                arousal=0.50,
            )

            report = resident.nervous.consolidate()
            schemas = [
                trace
                for trace in resident.nervous.recent_traces(100)
                if trace.channel == "schema"
                and "sqlite_lock" in trace.features
            ]

            self.assertTrue(
                any("sqlite_lock" in summary for summary in report.abstractions)
            )
            self.assertEqual(len(schemas), 1)
            self.assertGreaterEqual(schemas[0].metadata.get("support_count", 0), 3)
            self.assertEqual(resident.capabilities.names(), ())
            activated = resident.nervous.activate("sqlite_lock", limit=8)
            self.assertTrue(
                any(item.trace.trace_id == schemas[0].trace_id for item in activated)
            )
            resident.store.close()

            # The higher-order trace is part of the continuing nervous system,
            # not a transient summary produced by one Python process.
            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            latest = restored.nervous.latest_consolidation()
            self.assertIsNotNone(latest)
            self.assertTrue(
                any(
                    trace.channel == "schema" and "sqlite_lock" in trace.features
                    for trace in restored.nervous.recent_traces(100)
                )
            )
            restored.store.close()

    def test_old_isolated_detail_can_be_forgotten_instead_of_growing_forever(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            nervous = PersistentNervousSystem(store)
            trace = nervous.perceive(
                "world",
                "an unimportant one-off transient detail",
                features=("one_off_detail",),
                salience=0.08,
                arousal=0.05,
            )
            old = datetime.now(timezone.utc) - timedelta(days=180)
            trace.first_seen_at = old.isoformat()
            trace.last_seen_at = old.isoformat()
            trace.last_activated_at = None
            trace.strength = 0.05
            trace.salience = 0.05
            trace.repetitions = 1
            nervous._save_trace(trace)

            report = nervous.consolidate(now=datetime.now(timezone.utc))
            remaining = {item.trace_id for item in nervous.recent_traces(100)}

            self.assertGreaterEqual(report.faded, 1)
            self.assertEqual(report.pruned, 1)
            self.assertNotIn(trace.trace_id, remaining)
            store.close()

    def test_repeated_old_experience_stabilizes_instead_of_being_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            nervous = PersistentNervousSystem(store)
            trace = None
            for _ in range(5):
                trace = nervous.perceive(
                    "world",
                    "a recurring deployment rollback pattern",
                    features=("deployment", "rollback", "recurring"),
                    salience=0.72,
                    valence=-0.36,
                    arousal=0.58,
                )
            self.assertIsNotNone(trace)
            old = datetime.now(timezone.utc) - timedelta(days=180)
            trace.first_seen_at = old.isoformat()
            trace.last_seen_at = old.isoformat()
            trace.last_activated_at = None
            nervous._save_trace(trace)
            before = trace.strength

            report = nervous.consolidate(now=datetime.now(timezone.utc))
            restored = {
                item.trace_id: item for item in nervous.recent_traces(100)
            }[trace.trace_id]

            self.assertEqual(report.pruned, 0)
            self.assertGreaterEqual(restored.strength, before)
            self.assertEqual(restored.metadata.get("memory_state"), "consolidated")
            store.close()


if __name__ == "__main__":
    unittest.main()
