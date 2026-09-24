from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core import ExecutionPath
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class IntentionIncubationTests(unittest.TestCase):
    @staticmethod
    def _seed_writer_schema(resident):
        resident.perceive_world(
            "writer lock contention appeared in an upstream report",
            features=("writer_lock_pattern", "database", "contention"),
            salience=0.80,
            arousal=0.56,
        )
        resident.perceive_visual(
            "a local monitor showed another writer lock collision",
            features=("writer_lock_pattern", "database", "monitor"),
            salience=0.84,
            valence=-0.22,
            arousal=0.64,
        )
        resident.nervous.perceive(
            "action",
            "a retry cleared one writer lock collision",
            features=("writer_lock_pattern", "database", "retry"),
            salience=0.82,
            valence=0.32,
            arousal=0.52,
        )
        report = resident.nervous.consolidate()
        self_schemas = [
            trace
            for trace in resident.nervous.recent_traces(100)
            if trace.channel == "schema"
            and "writer_lock_pattern" in trace.features
        ]
        if not self_schemas:
            raise AssertionError(f"expected writer schema, got {report}")
        return self_schemas[0]

    def test_candidate_step_matures_in_one_durable_will_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            schema = self._seed_writer_schema(resident)
            intention = resident.intend(
                "understand writer_lock_pattern current behavior",
                priority=4,
            )

            resident.live_once()
            first = resident.will.get(intention.intention_id)
            self.assertIsNotNone(first.candidate_step)
            self.assertEqual(first.candidate_kind, "schema_probe")
            self.assertEqual(first.candidate_repetitions, 1)
            first_step = first.candidate_step
            first_maturity = first.candidate_maturity
            self.assertIn(schema.trace_id, first.candidate_support)
            self.assertEqual(resident.store.list_events(), [])

            # Same lived pattern is not appended as another plan. It strengthens
            # the one candidate already incubating inside this intention.
            resident.live_once()
            second = resident.will.get(intention.intention_id)
            self.assertEqual(second.candidate_step, first_step)
            self.assertEqual(second.candidate_repetitions, 2)
            self.assertGreater(second.candidate_maturity, first_maturity)
            self.assertEqual(resident.store.list_events(), [])
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            after_restart = restored.will.get(intention.intention_id)
            self.assertEqual(after_restart.candidate_step, first_step)
            self.assertEqual(after_restart.candidate_repetitions, 2)
            self.assertGreater(after_restart.incubation_count, 0)
            self.assertEqual(restored.store.get_runtime_metrics().model_invocations, 0)
            restored.store.close()

    def test_mature_candidate_becomes_one_self_initiated_native_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            capabilities_before = resident.capabilities.names()
            self._seed_writer_schema(resident)
            intention = resident.intend(
                "understand writer_lock_pattern current behavior",
                priority=5,
            )

            terminal = None
            for _ in range(20):
                terminal = resident.live_once()
                if terminal is not None:
                    break

            self.assertIsNotNone(terminal)
            self.assertTrue(terminal.success)
            self.assertEqual(terminal.execution_path, ExecutionPath.INVESTIGATION)
            self.assertEqual(terminal.model_invocations, 0)
            self.assertEqual(terminal.event.kind, "intention_probe")
            self.assertIn("Native intention probe completed", terminal.response)
            self.assertIn("remains a hypothesis", terminal.response)

            lived = resident.will.get(intention.intention_id)
            self.assertEqual(lived.status, "active")
            self.assertIsNone(lived.related_event_id)
            self.assertIsNone(lived.next_task)
            self.assertIsNone(lived.candidate_step)
            self.assertIsNotNone(lived.current_step)
            self.assertIn("Native intention probe completed", lived.last_outcome)
            self.assertEqual(resident.capabilities.names(), capabilities_before)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)

            probe_events = [
                event
                for event in resident.store.list_events(limit=100)
                if event.kind == "intention_probe"
                and event.payload.get("intention_id") == intention.intention_id
            ]
            self.assertEqual(len(probe_events), 1)

            # The same schema cannot immediately trigger the exact same probe
            # again after it already produced a lived outcome.
            for _ in range(6):
                self.assertIsNone(resident.live_once())
            probe_events_after = [
                event
                for event in resident.store.list_events(limit=100)
                if event.kind == "intention_probe"
                and event.payload.get("intention_id") == intention.intention_id
            ]
            self.assertEqual(len(probe_events_after), 1)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
