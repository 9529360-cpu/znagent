from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class NeuralPredictionTests(unittest.TestCase):
    def test_consolidated_schema_becomes_native_prediction_before_body_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            resident.perceive_world(
                "writer lock contention appeared in an upstream report",
                features=("writer_lock_pattern", "database", "contention"),
                salience=0.78,
                arousal=0.55,
            )
            resident.perceive_visual(
                "a local monitor showed another writer lock collision",
                features=("writer_lock_pattern", "database", "monitor"),
                salience=0.82,
                valence=-0.20,
                arousal=0.62,
            )
            resident.nervous.perceive(
                "action",
                "a retry cleared one writer lock collision",
                features=("writer_lock_pattern", "database", "retry"),
                salience=0.80,
                valence=0.30,
                arousal=0.50,
            )
            resident.nervous.consolidate()

            event = resident.enqueue(
                "understand writer_lock_pattern current behavior",
                payload={"model_policy": "never"},
            )
            required = resident._required_capabilities(event)
            readiness = resident.kernel.self_model.assess_task(event.task, required)
            learning = resident._related_learning_evidence(event, readiness, limit=5)
            self.assertTrue(any(item.get("consolidated") for item in learning))

            first = resident.investigator.investigate(
                event,
                readiness,
                learning_evidence=learning,
            )

            self.assertEqual(first.performed_probe, "experience")
            self.assertIn("schema_predictions", first.state.facts)
            self.assertTrue(first.state.facts["schema_predictions"])
            self.assertTrue(
                any(
                    "consolidated lived pattern predicts" in hypothesis
                    for hypothesis in first.state.hypotheses
                )
            )
            self.assertTrue(
                any(
                    "consolidated schema prediction activated" in evidence
                    for evidence in first.state.evidence
                )
            )
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)

            # A later investigation pulse acquires body evidence. The old
            # schema remains a prediction to compare against reality, not a
            # conclusion that bypasses observation.
            second = resident.investigator.investigate(
                event,
                readiness,
                learning_evidence=learning,
            )
            self.assertEqual(second.performed_probe, "body")
            self.assertIn("body", second.state.facts)
            self.assertTrue(
                any(
                    "confirm, refine, or contradict" in hypothesis
                    for hypothesis in second.state.hypotheses
                )
            )
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            self.assertEqual(resident.capabilities.names(), ())
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
