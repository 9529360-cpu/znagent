from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core import IntentionalResidentRuntime
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class NativeWorldSenseTests(unittest.TestCase):
    def test_followed_world_focus_observes_without_model_and_enters_neural_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            capabilities_before = resident.capabilities.names()
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
            self.assertEqual(observation.source_count, 1)
            self.assertEqual(observation.new_sources, ("Solid-state battery result",))
            self.assertEqual(calls, [("battery storage research", 3)])
            traces = resident.nervous.activate("solid-state battery cycle life", limit=8)
            self.assertTrue(any(item.trace.channel == "world" for item in traces))
            self.assertEqual(resident.capabilities.names(), capabilities_before)

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
            self.assertEqual(second.stable_sources, ("Fab capacity update",))
            self.assertEqual(len(world_traces), 1)
            self.assertEqual(world_traces[0].trace_id, before.trace_id)
            self.assertGreater(world_traces[0].repetitions, before.repetitions)
            self.assertGreater(world_traces[0].strength, before.strength)
            resident.store.close()

    def test_result_order_and_tracking_noise_do_not_look_like_world_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            focus = resident.follow_world("grid research", interval_seconds=60)
            first_payload = json.dumps(
                {
                    "results": [
                        {
                            "title": "Alpha grid update",
                            "snippet": "Storage deployment remained at 12 GWh.",
                            "url": "https://alpha.test/report?utm_source=feed",
                        },
                        {
                            "title": "Beta grid update",
                            "snippet": "Transmission work entered phase two.",
                            "url": "https://beta.test/news#latest",
                        },
                    ]
                }
            )
            second_payload = json.dumps(
                {
                    "results": [
                        {
                            "title": "Beta grid update",
                            "snippet": "Transmission work entered phase two.",
                            "url": "https://beta.test/news",
                        },
                        {
                            "title": "Alpha grid update",
                            "snippet": "Storage deployment remained at 12 GWh.",
                            "url": "https://alpha.test/report?utm_source=other",
                        },
                    ]
                }
            )

            first = resident.observe_world_once(
                focus.focus_id,
                search_fn=lambda query, limit: first_payload,
            )
            second = resident.observe_world_once(
                focus.focus_id,
                search_fn=lambda query, limit: second_payload,
            )

            self.assertTrue(first.changed)
            self.assertFalse(second.changed)
            self.assertEqual(first.result_hash, second.result_hash)
            self.assertEqual(
                set(second.stable_sources),
                {"Alpha grid update", "Beta grid update"},
            )
            world_changes = [
                trace
                for trace in resident.nervous.recent_traces(80)
                if trace.channel == "world" and trace.metadata.get("world_change")
            ]
            self.assertEqual(world_changes, [])
            resident.store.close()

    def test_structured_source_delta_survives_restart_and_enters_neural_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            focus = first.follow_world("robotics supply", interval_seconds=60)
            baseline = json.dumps(
                {
                    "results": [
                        {
                            "title": "Actuator supplier note",
                            "snippet": "Lead time is twelve weeks.",
                            "url": "https://actuator.test/note",
                        },
                        {
                            "title": "Sensor supplier note",
                            "snippet": "A tactile sensor line is shipping normally.",
                            "url": "https://sensor.test/note",
                        },
                    ]
                }
            )
            changed_payload = json.dumps(
                {
                    "results": [
                        {
                            "title": "Actuator supplier note",
                            "snippet": "Lead time increased to sixteen weeks.",
                            "url": "https://actuator.test/note",
                        },
                        {
                            "title": "Controller supplier note",
                            "snippet": "A new controller revision entered production.",
                            "url": "https://controller.test/note",
                        },
                    ]
                }
            )

            first.observe_world_once(
                focus.focus_id,
                search_fn=lambda query, limit: baseline,
            )
            changed = first.observe_world_once(
                focus.focus_id,
                search_fn=lambda query, limit: changed_payload,
            )

            self.assertTrue(changed.changed)
            self.assertEqual(changed.source_count, 2)
            self.assertEqual(changed.new_sources, ("Controller supplier note",))
            self.assertEqual(changed.updated_sources, ("Actuator supplier note",))
            self.assertEqual(changed.removed_sources, ("Sensor supplier note",))
            delta_traces = [
                trace
                for trace in first.nervous.recent_traces(80)
                if trace.channel == "world" and trace.metadata.get("world_change")
            ]
            self.assertTrue(delta_traces)
            delta = delta_traces[0]
            self.assertIn("world_delta", delta.features)
            self.assertIn("new_source", delta.features)
            self.assertIn("updated_source", delta.features)
            self.assertIn("removed_source", delta.features)
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored = second.world.focuses(enabled_only=True, limit=10)
            self.assertEqual(len(restored), 1)
            self.assertEqual(restored[0].focus_id, focus.focus_id)
            self.assertEqual(len(restored[0].last_source_state), 2)

            stable = second.observe_world_once(
                focus.focus_id,
                search_fn=lambda query, limit: changed_payload,
            )
            self.assertFalse(stable.changed)
            self.assertEqual(
                set(stable.stable_sources),
                {"Actuator supplier note", "Controller supplier note"},
            )
            second.store.close()

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
            self.assertEqual(len(restored[0].last_source_state), 1)
            recalled = second.nervous.activate("tactile robotics control", limit=8)
            self.assertTrue(any(item.trace.channel == "world" for item in recalled))
            self.assertIn("world_sense", second.status())
            second.store.close()


if __name__ == "__main__":
    unittest.main()
