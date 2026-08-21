from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.kernel import IntentionalResidentRuntime
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class NativeWorldSenseTests(unittest.TestCase):
    def test_followed_world_focus_observes_without_model_and_enters_neural_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            self.assertIsInstance(resident, IntentionalResidentRuntime)
            focus = resident.follow_world(
                "battery storage research",
                priority=4,
                interval_seconds=60,
            )
            calls: list[tuple[str, int]] = []

            def fake_search(query: str, limit: int) -> str:
                calls.append((query, limit))
                return json.dumps(
                    {
                        "results": [
                            {
                                "title": "Solid-state battery result",
                                "url": "https://example.test/battery",
                                "snippet": "A lab reported improved cycle life in a new cell.",
                            }
                        ]
                    }
                )

            observation = resident.world.maybe_observe(search_fn=fake_search, limit=3)

            self.assertIsNotNone(observation)
            self.assertEqual(observation.focus_id, focus.focus_id)
            self.assertTrue(observation.changed)
            self.assertEqual(calls, [("battery storage research", 3)])
            traces = resident.nervous.activate("solid-state battery cycle life", limit=8)
            self.assertTrue(any(item.trace.channel == "world" for item in traces))
            self.assertEqual(resident.capabilities.names(), ())

            # The same focus is not due again immediately. Background life may
            # call maybe_observe every few seconds without repeatedly hitting
            # the network.
            self.assertIsNone(resident.world.maybe_observe(search_fn=fake_search, limit=3))
            self.assertEqual(len(calls), 1)
            resident.store.close()

    def test_same_world_observation_strengthens_existing_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            focus = resident.follow_world("semiconductor supply", interval_seconds=60)
            payload = json.dumps(
                {
                    "results": [
                        {
                            "title": "Fab capacity update",
                            "snippet": "Capacity remained stable this week.",
                            "url": "https://example.test/fab",
                        }
                    ]
                }
            )

            first = resident.observe_world_once(
                focus.focus_id,
                search_fn=lambda query, limit: payload,
            )
            world_traces = [
                trace for trace in resident.nervous.recent_traces(50) if trace.channel == "world"
            ]
            self.assertEqual(len(world_traces), 1)
            before = world_traces[0]

            # Explicit observation may be requested even before the autonomous
            # interval expires. Identical input should reinforce the same trace.
            second = resident.observe_world_once(
                focus.focus_id,
                search_fn=lambda query, limit: payload,
            )
            world_traces = [
                trace for trace in resident.nervous.recent_traces(50) if trace.channel == "world"
            ]
            self.assertFalse(second.changed)
            self.assertEqual(first.result_hash, second.result_hash)
            self.assertEqual(len(world_traces), 1)
            self.assertEqual(world_traces[0].trace_id, before.trace_id)
            self.assertGreater(world_traces[0].repetitions, before.repetitions)
            self.assertGreater(world_traces[0].strength, before.strength)
            resident.store.close()

    def test_world_focus_and_observation_survive_resident_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            focus = first.follow_world("robotics research", priority=2, interval_seconds=60)
            observed = first.observe_world_once(
                focus.focus_id,
                search_fn=lambda query, limit: json.dumps(
                    {
                        "results": [
                            {
                                "title": "Robotics lab update",
                                "snippet": "A new tactile control method was demonstrated.",
                                "url": "https://example.test/robotics",
                            }
                        ]
                    }
                ),
            )
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored = second.world.focuses(enabled_only=True, limit=10)

            self.assertEqual(len(restored), 1)
            self.assertEqual(restored[0].focus_id, focus.focus_id)
            self.assertEqual(restored[0].topic, "robotics research")
            self.assertEqual(restored[0].last_observation_hash, observed.result_hash)
            recalled = second.nervous.activate("tactile robotics control", limit=8)
            self.assertTrue(any(item.trace.channel == "world" for item in recalled))
            self.assertIn("world_sense", second.status())
            second.store.close()


if __name__ == "__main__":
    unittest.main()
