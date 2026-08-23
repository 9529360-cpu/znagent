from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.adaptive_nervous_system import RealityAwareNervousSystem
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class RealityAwareRecallTests(unittest.TestCase):
    @staticmethod
    def _seed_reconsolidated_schema(resident):
        schema = resident.nervous.perceive(
            "schema",
            "Persistent pattern: carryover workspace dirty state recurs in lived work.",
            features=(
                "carryover_pattern",
                "workspace:dirty",
                "dirty",
                "repository",
                "consolidated_pattern",
            ),
            salience=0.88,
            arousal=0.42,
            metadata={
                "memory_state": "consolidated",
                "prediction_confidence": 0.86,
                "prediction_profile": {
                    "version": 1,
                    "anchor_feature": "carryover_pattern",
                    "source_count": 4,
                    "features": [],
                    "channels": {"world": 1, "vision": 1, "action": 1},
                    "relations": [
                        {
                            "family": "workspace",
                            "value": "dirty",
                            "support_ratio": 0.94,
                            "weight": 0.91,
                            "confidence": 0.17,
                            "confirmations": 0,
                            "conflicts": 3,
                            "status": "contested",
                            "leading_alternative": "clean",
                        },
                        {
                            "family": "workspace",
                            "value": "clean",
                            "support_ratio": 0.68,
                            "weight": 0.62,
                            "confidence": 0.84,
                            "confirmations": 2,
                            "conflicts": 0,
                            "status": "expected",
                            "formed_from_prediction_error": True,
                            "stabilized_from_prediction_error": True,
                            "stabilized_at": "2026-08-21T10:00:00+00:00",
                        },
                    ],
                    "alternatives": {"workspace": {"clean": 3}},
                    "feedback": {"supported": 1, "refined": 2, "contradicted": 0},
                    "last_stabilized_at": "2026-08-21T10:00:00+00:00",
                },
            },
        )
        schema.strength = 0.90
        schema.salience = 0.88
        resident.nervous._save_trace(schema)
        return schema

    @staticmethod
    def _schema_activation(resident, cue: str, trace_id: str):
        return next(
            (
                item
                for item in resident.nervous.activate(
                    cue,
                    channels=("schema",),
                    limit=12,
                )
                if item.trace.trace_id == trace_id
            ),
            None,
        )

    def test_product_resident_uses_reality_aware_nervous_system(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            self.assertIsInstance(resident.nervous, RealityAwareNervousSystem)
            self.assertIs(resident.intention_formation.nervous, resident.nervous)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_reconsolidated_relation_changes_recall_without_rewriting_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            schema = self._seed_reconsolidated_schema(resident)

            clean = self._schema_activation(
                resident,
                "clean workspace repository",
                schema.trace_id,
            )
            dirty = self._schema_activation(
                resident,
                "dirty workspace repository",
                schema.trace_id,
            )

            self.assertIsNotNone(clean)
            self.assertIsNotNone(dirty)
            self.assertGreater(clean.cue_overlap, dirty.cue_overlap)
            self.assertGreater(clean.activation, dirty.activation)

            stored = resident.nervous._get_trace(schema.trace_id)
            self.assertIsNotNone(stored)
            self.assertIn("dirty", stored.summary)
            self.assertIn("workspace:dirty", stored.features)
            profile = stored.metadata.get("prediction_profile") or {}
            old = next(
                item
                for item in profile.get("relations") or ()
                if item.get("family") == "workspace"
                and item.get("value") == "dirty"
            )
            current = next(
                item
                for item in profile.get("relations") or ()
                if item.get("family") == "workspace"
                and item.get("value") == "clean"
            )
            self.assertEqual(old.get("status"), "contested")
            self.assertTrue(current.get("stabilized_from_prediction_error"))
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_reality_aware_recall_survives_restart_and_guides_will(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            schema = self._seed_reconsolidated_schema(resident)
            trace_id = schema.trace_id
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            self.assertIsInstance(restored.nervous, RealityAwareNervousSystem)
            activation = self._schema_activation(
                restored,
                "understand clean workspace repository state",
                trace_id,
            )
            self.assertIsNotNone(activation)

            intention = restored.intend(
                "understand clean workspace repository state",
                priority=6,
            )
            candidate = restored.intention_formation.form(
                intention,
                activation,
                situation=restored.life.snapshot().current_situation,
                body=restored.life.snapshot().body,
            )

            self.assertIsNotNone(candidate)
            self.assertEqual(candidate.kind, "situated_schema_probe")
            self.assertEqual(candidate.probe_key, "git")
            self.assertEqual(candidate.relation_family, "workspace")
            self.assertEqual(candidate.relation_value, "clean")
            expectation = candidate.payload.get("schema_expectation") or {}
            self.assertEqual(expectation.get("value"), "clean")
            self.assertEqual(expectation.get("status"), "expected")
            self.assertFalse(bool(expectation.get("recheck")))
            self.assertEqual(restored.store.get_runtime_metrics().model_invocations, 0)
            restored.store.close()


if __name__ == "__main__":
    unittest.main()
