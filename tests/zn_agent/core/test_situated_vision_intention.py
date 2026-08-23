from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core import ExecutionPath
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.visual_sense import NativeVisualSense, VisualFrame


class SituatedVisionIntentionTests(unittest.TestCase):
    @staticmethod
    def _frame(token: str, regions: tuple[str, ...]) -> VisualFrame:
        return VisualFrame(
            frame_hash=(token * 64)[:64],
            width=320,
            height=180,
            source="test-situated-retina",
            region_signatures=regions,
            grid_columns=4,
            grid_rows=3,
            mean_luminance=0.45,
        )

    @staticmethod
    def _seed_visual_schema(resident):
        resident.perceive_world(
            "screen_pattern repeatedly coincided with a local visual change",
            features=("screen_pattern", "visual_change:local"),
            salience=0.84,
            arousal=0.55,
        )
        resident.perceive_visual(
            "screen_pattern appeared again with a local visual change",
            features=("screen_pattern", "visual_change:local"),
            salience=0.86,
            arousal=0.58,
        )
        resident.nervous.perceive(
            "action",
            "a screen response preserved the same local visual change pattern",
            features=("screen_pattern", "visual_change:local"),
            salience=0.82,
            arousal=0.52,
        )
        resident.nervous.consolidate()
        schemas = [
            trace
            for trace in resident.nervous.recent_traces(100)
            if trace.channel == "schema" and "screen_pattern" in trace.features
        ]
        if not schemas:
            raise AssertionError("expected a visual screen schema")
        return schemas[0]

    def test_visual_schema_becomes_will_probe_and_reconsolidates_from_current_retina(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            regions = tuple(f"stable-{index}" for index in range(12))
            retina = NativeVisualSense(
                resident,
                capture_fn=lambda: self._frame("a", regions),
                interval_seconds=0.1,
            )
            resident.vision = retina
            initial = retina.sample()
            self.assertIsNotNone(initial)
            self.assertTrue(initial.changed)

            schema = self._seed_visual_schema(resident)
            intention = resident.intend(
                "understand screen_pattern current behavior",
                priority=5,
            )

            resident.live_once()
            incubating = resident.will.get(intention.intention_id)
            self.assertIsNotNone(incubating)
            self.assertEqual(incubating.candidate_kind, "situated_schema_probe")
            self.assertIn("current resident vision relation visual_change:local", incubating.candidate_step)
            self.assertEqual(incubating.candidate_payload.get("native_probe_key"), "vision")
            self.assertEqual(
                incubating.candidate_payload.get("schema_probe_observation"),
                "vision",
            )
            expectation = incubating.candidate_payload.get("schema_expectation") or {}
            self.assertEqual(expectation.get("family"), "visual_change")
            self.assertEqual(expectation.get("value"), "local")
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
            self.assertEqual(terminal.event.payload.get("native_probe_key"), "vision")

            investigation = resident.investigator.current(terminal.event.event_id)
            self.assertIsNotNone(investigation)
            self.assertGreaterEqual(len(investigation.probe_keys), 2)
            self.assertEqual(investigation.probe_keys[0], "experience")
            self.assertIn("vision", investigation.probe_keys)
            visual_fact = investigation.facts.get("vision") or {}
            self.assertTrue(visual_fact.get("available"))
            self.assertFalse(visual_fact.get("changed"))
            self.assertEqual(visual_fact.get("change_scale"), "none")

            feedback = investigation.facts.get("schema_prediction_feedback") or []
            self.assertTrue(feedback)
            latest = feedback[-1]
            self.assertIn(latest.get("status"), {"refined", "contradicted"})
            self.assertGreater(float(latest.get("prediction_error") or 0.0), 0.0)
            self.assertIn("vision", latest.get("observation_channels") or [])
            self.assertTrue(
                any(
                    "visual_change:local->none" in item
                    for item in (latest.get("contradictions") or [])
                )
            )
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
