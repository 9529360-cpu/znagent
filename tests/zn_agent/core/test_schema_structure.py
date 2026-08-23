from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.nervous_system import PersistentNervousSystem
from zn_agent.core.reconsolidation import SchemaReconsolidator
from zn_agent.core.schema_structure import SchemaStructurePlasticity
from zn_agent.core.store import KernelStore


class SchemaStructuralCompactionTests(unittest.TestCase):
    @staticmethod
    def _seed_redundant_schemas(nervous: PersistentNervousSystem):
        sources = [
            nervous.perceive(
                "world",
                "a repository deployment pattern appeared with local changes",
                features=("deployment_pattern", "workspace:dirty", "repository"),
                salience=0.78,
                arousal=0.52,
            ),
            nervous.perceive(
                "vision",
                "the deployment dashboard showed the same repository pattern",
                features=("deployment_pattern", "workspace:dirty", "repository"),
                salience=0.82,
                arousal=0.58,
            ),
            nervous.perceive(
                "action",
                "repository inspection observed the deployment pattern again",
                features=("deployment_pattern", "workspace:dirty", "repository"),
                salience=0.80,
                arousal=0.55,
            ),
        ]
        nervous.consolidate()
        source_ids = {trace.trace_id for trace in sources}
        schemas = [
            trace
            for trace in nervous.recent_traces(100)
            if trace.channel == "schema"
            and source_ids.issubset(set(trace.metadata.get("source_trace_ids") or ()))
        ]
        if len(schemas) < 2:
            raise AssertionError("expected redundant one-feature schemas before compaction")
        schemas.sort(
            key=lambda trace: (
                "deployment_pattern" not in trace.features,
                trace.trace_id,
            )
        )
        return sources, schemas

    def test_structural_compaction_collapses_redundant_schemas_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            store = KernelStore(db)
            nervous = PersistentNervousSystem(store)
            sources, schemas = self._seed_redundant_schemas(nervous)
            canonical = schemas[0]
            absorbed_ids = {trace.trace_id for trace in schemas[1:]}

            merges = SchemaStructurePlasticity(nervous).compact(
                seed_ids=[canonical.trace_id]
            )
            active = [
                trace
                for trace in nervous.recent_traces(100)
                if trace.channel == "schema"
            ]
            updated = nervous._get_trace(canonical.trace_id)

            self.assertEqual(len(active), 1)
            self.assertEqual(active[0].trace_id, canonical.trace_id)
            self.assertEqual(len(merges), len(absorbed_ids))
            self.assertTrue(
                absorbed_ids.issubset(
                    set(updated.metadata.get("merged_schema_ids") or ())
                )
            )
            self.assertTrue(
                {"deployment_pattern", "workspace:dirty", "repository"}.issubset(
                    set(updated.features)
                )
            )
            for source in sources:
                restored_source = nervous._get_trace(source.trace_id)
                schema_ids = set(restored_source.metadata.get("schema_trace_ids") or ())
                self.assertEqual(schema_ids, {canonical.trace_id})
            for trace_id in absorbed_ids:
                tombstone = nervous._get_trace(trace_id)
                self.assertEqual(tombstone.channel, "schema_merged")
                self.assertEqual(
                    tombstone.metadata.get("merged_into_schema_id"),
                    canonical.trace_id,
                )
            store.close()

            restored_store = KernelStore(db)
            restored = PersistentNervousSystem(restored_store)
            resolver = SchemaStructurePlasticity(restored)
            for trace_id in absorbed_ids:
                self.assertEqual(
                    resolver.resolve_schema(trace_id).trace_id,
                    canonical.trace_id,
                )
            self.assertEqual(
                len(
                    [
                        trace
                        for trace in restored.recent_traces(100)
                        if trace.channel == "schema"
                    ]
                ),
                1,
            )
            restored_store.close()

    def test_conflicting_structured_predictions_are_not_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            nervous = PersistentNervousSystem(store)
            _, schemas = self._seed_redundant_schemas(nervous)
            dirty = schemas[0]
            clean = schemas[1]
            reconsolidator = SchemaReconsolidator(nervous)
            reconsolidator._profile(dirty)
            clean_profile = reconsolidator._profile(clean)
            workspace = next(
                item
                for item in clean_profile.get("relations") or ()
                if item.get("family") == "workspace"
            )
            workspace["value"] = "clean"
            workspace["confidence"] = 0.95
            clean.metadata["prediction_profile"] = clean_profile
            nervous._save_trace(clean)

            SchemaStructurePlasticity(nervous).compact(seed_ids=[dirty.trace_id])
            active_ids = {
                trace.trace_id
                for trace in nervous.recent_traces(100)
                if trace.channel == "schema"
            }

            self.assertIn(dirty.trace_id, active_ids)
            self.assertIn(clean.trace_id, active_ids)
            self.assertGreaterEqual(len(active_ids), 2)
            store.close()

    def test_merge_preserves_prediction_history_and_repoints_exceptions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            nervous = PersistentNervousSystem(store)
            _, schemas = self._seed_redundant_schemas(nervous)
            canonical = schemas[0]
            absorbed = schemas[1]
            reconsolidator = SchemaReconsolidator(nervous)
            canonical_profile = reconsolidator._profile(canonical)
            absorbed_profile = reconsolidator._profile(absorbed)
            canonical_profile["feedback"]["supported"] = 2
            absorbed_profile["feedback"]["refined"] = 3
            absorbed_profile["alternatives"] = {"workspace": {"clean": 2}}
            canonical.metadata["prediction_profile"] = canonical_profile
            absorbed.metadata["prediction_profile"] = absorbed_profile

            exception = nervous.perceive(
                "outcome",
                "a clean workspace contradicted an older dirty-workspace expectation",
                features=("workspace:clean", "clean"),
                source="reconsolidation",
                salience=0.74,
                arousal=0.60,
                metadata={
                    "prediction_schema_id": absorbed.trace_id,
                    "prediction_status": "refined",
                },
            )
            absorbed.metadata["exception_trace_ids"] = [exception.trace_id]
            nervous._save_trace(canonical)
            nervous._save_trace(absorbed)

            SchemaStructurePlasticity(nervous).compact(seed_ids=[canonical.trace_id])
            updated = nervous._get_trace(canonical.trace_id)
            profile = updated.metadata.get("prediction_profile") or {}
            feedback = profile.get("feedback") or {}
            alternatives = profile.get("alternatives") or {}
            updated_exception = nervous._get_trace(exception.trace_id)

            self.assertGreaterEqual(int(feedback.get("supported") or 0), 2)
            self.assertGreaterEqual(int(feedback.get("refined") or 0), 3)
            self.assertGreaterEqual(
                int(alternatives.get("workspace", {}).get("clean", 0)),
                2,
            )
            self.assertIn(
                exception.trace_id,
                updated.metadata.get("exception_trace_ids") or (),
            )
            self.assertEqual(
                updated_exception.metadata.get("prediction_schema_id"),
                canonical.trace_id,
            )
            self.assertEqual(
                updated_exception.metadata.get("prediction_schema_merged_from"),
                absorbed.trace_id,
            )
            store.close()


if __name__ == "__main__":
    unittest.main()
