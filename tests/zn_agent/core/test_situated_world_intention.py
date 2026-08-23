from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core import ExecutionPath
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class SituatedWorldIntentionTests(unittest.TestCase):
    @staticmethod
    def _payload() -> str:
        return json.dumps(
            {
                "results": [
                    {
                        "title": "Battery lab note",
                        "snippet": "The tracked source set is unchanged in this observation.",
                        "url": "https://battery.test/lab-note",
                    }
                ]
            }
        )

    @staticmethod
    def _seed_world_schema(resident, focus_id: str):
        for channel, summary in (
            (
                "world",
                "world_pattern repeatedly coincided with a changed outside source set",
            ),
            (
                "action",
                "following world_pattern preserved the expectation of outside source change",
            ),
            (
                "outcome",
                "world_pattern again ended with a changed outside source set",
            ),
        ):
            resident.nervous.perceive(
                channel,
                summary,
                features=("world_pattern", "world_change:changed"),
                source="world_sense",
                salience=0.86,
                arousal=0.56,
                metadata={"focus_id": focus_id},
            )
        resident.nervous.consolidate()
        schemas = [
            trace
            for trace in resident.nervous.recent_traces(120)
            if trace.channel == "schema" and "world_pattern" in trace.features
        ]
        if not schemas:
            raise AssertionError("expected a world relation schema")
        return schemas[0]

    def test_world_schema_becomes_will_probe_and_reconsolidates_from_current_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            focus = resident.follow_world(
                "battery research",
                priority=5,
                interval_seconds=600,
            )
            payload = self._payload()
            baseline = resident.observe_world_once(
                focus.focus_id,
                search_fn=lambda query, limit: payload,
            )
            self.assertTrue(baseline.changed)
            resident.world._search = lambda query, limit: payload

            schema = self._seed_world_schema(resident, focus.focus_id)
            intention = resident.intend(
                "understand battery research world_pattern current behavior",
                priority=5,
            )

            resident.live_once()
            incubating = resident.will.get(intention.intention_id)
            self.assertIsNotNone(incubating)
            self.assertEqual(incubating.candidate_kind, "situated_schema_probe")
            self.assertIn("world_change:changed", incubating.candidate_step)
            self.assertEqual(incubating.candidate_payload.get("native_probe_key"), "world")
            self.assertEqual(
                incubating.candidate_payload.get("schema_probe_observation"),
                "world",
            )
            self.assertEqual(
                incubating.candidate_payload.get("world_focus_id"),
                focus.focus_id,
            )
            expectation = incubating.candidate_payload.get("schema_expectation") or {}
            self.assertEqual(expectation.get("family"), "world_change")
            self.assertEqual(expectation.get("value"), "changed")
            self.assertIn(schema.trace_id, incubating.candidate_support)

            terminal = None
            for _ in range(30):
                terminal = resident.live_once()
                if terminal is not None:
                    break

            self.assertIsNotNone(terminal)
            self.assertTrue(terminal.success)
            self.assertEqual(terminal.execution_path, ExecutionPath.INVESTIGATION)
            self.assertEqual(terminal.model_invocations, 0)
            self.assertEqual(terminal.event.kind, "intention_probe")
            self.assertEqual(terminal.event.payload.get("native_probe_key"), "world")
            self.assertEqual(terminal.event.payload.get("world_focus_id"), focus.focus_id)

            investigation = resident.investigator.current(terminal.event.event_id)
            self.assertIsNotNone(investigation)
            self.assertGreaterEqual(len(investigation.probe_keys), 2)
            self.assertEqual(investigation.probe_keys[0], "experience")
            self.assertIn("world", investigation.probe_keys)
            world_fact = investigation.facts.get("world") or {}
            self.assertTrue(world_fact.get("available"))
            self.assertFalse(world_fact.get("changed"))
            self.assertTrue(world_fact.get("stable_sources"))

            feedback = investigation.facts.get("schema_prediction_feedback") or []
            self.assertTrue(feedback)
            latest = feedback[-1]
            self.assertIn(latest.get("status"), {"refined", "contradicted"})
            self.assertGreater(float(latest.get("prediction_error") or 0.0), 0.0)
            self.assertIn("world", latest.get("observation_channels") or [])
            self.assertTrue(
                any(
                    "world_change:changed->stable" in item
                    for item in (latest.get("contradictions") or [])
                )
            )
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
