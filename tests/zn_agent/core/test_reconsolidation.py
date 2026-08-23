from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.nervous_system import PersistentNervousSystem
from zn_agent.core.reconsolidation import SchemaReconsolidator
from zn_agent.core.store import KernelStore


class SchemaReconsolidationTests(unittest.TestCase):
    @staticmethod
    def _seed_git_schema(nervous: PersistentNervousSystem):
        sources = [
            nervous.perceive(
                "world",
                "a prior repository observation found a dirty workspace",
                features=("git_pattern", "workspace:dirty", "repository"),
                salience=0.76,
                arousal=0.52,
            ),
            nervous.perceive(
                "vision",
                "the repository status display showed pending local changes",
                features=("git_pattern", "workspace:dirty", "status_panel"),
                salience=0.82,
                arousal=0.58,
            ),
            nervous.perceive(
                "action",
                "a repository inspection encountered uncommitted local changes",
                features=("git_pattern", "workspace:dirty", "inspection"),
                salience=0.80,
                arousal=0.55,
            ),
        ]
        nervous.consolidate()
        schemas = [
            trace
            for trace in nervous.recent_traces(100)
            if trace.channel == "schema" and "git_pattern" in trace.features
        ]
        if not schemas:
            raise AssertionError("expected git_pattern schema to consolidate")
        schema = schemas[0]
        source_ids = set(schema.metadata.get("source_trace_ids") or ())
        if not {trace.trace_id for trace in sources}.issubset(source_ids):
            raise AssertionError("schema did not retain all source traces")
        return schema

    def test_supported_current_evidence_reinforces_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            nervous = PersistentNervousSystem(store)
            schema = self._seed_git_schema(nervous)
            before = schema.strength
            facts = {
                "git": {
                    "available": True,
                    "branch": "dev/zn-agent",
                    "dirty": True,
                    "changed_files": 2,
                }
            }

            feedback = SchemaReconsolidator(nervous).evaluate(
                [{"trace_id": schema.trace_id}],
                facts,
                event_id="evt-supported",
            )
            updated = nervous._get_trace(schema.trace_id)

            self.assertEqual(len(feedback), 1)
            self.assertEqual(feedback[0].status, "supported")
            self.assertEqual(feedback[0].prediction_error, 0.0)
            self.assertIsNotNone(updated)
            self.assertGreater(updated.strength, before)
            self.assertEqual(updated.metadata.get("memory_state"), "consolidated")
            profile = updated.metadata.get("prediction_profile") or {}
            self.assertTrue(
                any(
                    item.get("family") == "workspace"
                    and item.get("value") == "dirty"
                    for item in profile.get("relations") or ()
                )
            )
            store.close()

    def test_contradiction_weakens_schema_and_persists_exception_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            store = KernelStore(db)
            nervous = PersistentNervousSystem(store)
            schema = self._seed_git_schema(nervous)
            before = schema.strength
            facts = {
                "git": {
                    "available": True,
                    "branch": "dev/zn-agent",
                    "dirty": False,
                    "changed_files": 0,
                }
            }

            feedback = SchemaReconsolidator(nervous).evaluate(
                [{"trace_id": schema.trace_id}],
                facts,
                event_id="evt-contradicted",
            )
            updated = nervous._get_trace(schema.trace_id)

            self.assertEqual(feedback[0].status, "contradicted")
            self.assertGreater(feedback[0].prediction_error, 0.0)
            self.assertLess(updated.strength, before)
            self.assertEqual(updated.metadata.get("memory_state"), "labile")
            exception_ids = tuple(updated.metadata.get("exception_trace_ids") or ())
            self.assertTrue(exception_ids)
            exception = nervous._get_trace(exception_ids[-1])
            self.assertIsNotNone(exception)
            self.assertEqual(exception.channel, "outcome")
            self.assertEqual(
                exception.metadata.get("prediction_schema_id"),
                schema.trace_id,
            )
            self.assertEqual(
                exception.metadata.get("prediction_status"),
                "contradicted",
            )
            store.close()

            restored_store = KernelStore(db)
            restored = PersistentNervousSystem(restored_store)
            restored_schema = restored._get_trace(schema.trace_id)
            restored_exception = restored._get_trace(exception_ids[-1])
            self.assertIsNotNone(restored_schema)
            self.assertIsNotNone(restored_exception)
            self.assertEqual(
                (restored_schema.metadata.get("last_prediction_feedback") or {}).get(
                    "status"
                ),
                "contradicted",
            )
            restored_store.close()

    def test_partial_error_refines_relation_and_repeated_reality_restructures_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            nervous = PersistentNervousSystem(store)
            schema = self._seed_git_schema(nervous)
            reconsolidator = SchemaReconsolidator(nervous)

            first_facts = {
                "git": {
                    "available": True,
                    "branch": "dev/zn-agent",
                    "dirty": False,
                    "changed_files": 0,
                },
                "evidence_features": ["git_pattern"],
            }
            first = reconsolidator.evaluate(
                [{"trace_id": schema.trace_id}],
                first_facts,
                event_id="evt-refine-1",
            )
            after_first = nervous._get_trace(schema.trace_id)
            strength_after_first = after_first.strength

            self.assertEqual(first[0].status, "refined")
            self.assertGreater(first[0].prediction_error, 0.0)
            self.assertLess(first[0].prediction_error, 1.0)
            self.assertEqual(
                after_first.metadata.get("memory_state"),
                "reconsolidating",
            )

            duplicate = reconsolidator.evaluate(
                [{"trace_id": schema.trace_id}],
                first_facts,
                event_id="evt-refine-1",
            )
            self.assertEqual(duplicate, [])
            self.assertAlmostEqual(
                nervous._get_trace(schema.trace_id).strength,
                strength_after_first,
                places=8,
            )

            for index in (2, 3):
                later_facts = {
                    "git": {
                        "available": True,
                        "branch": "dev/zn-agent",
                        "dirty": False,
                        "changed_files": 0,
                    },
                    "evidence_features": ["git_pattern"],
                }
                later = reconsolidator.evaluate(
                    [{"trace_id": schema.trace_id}],
                    later_facts,
                    event_id=f"evt-refine-{index}",
                )
                self.assertEqual(later[0].status, "refined")

            restructured = nervous._get_trace(schema.trace_id)
            profile = restructured.metadata.get("prediction_profile") or {}
            relations = profile.get("relations") or ()
            dirty = next(
                item
                for item in relations
                if item.get("family") == "workspace"
                and item.get("value") == "dirty"
            )
            clean = next(
                item
                for item in relations
                if item.get("family") == "workspace"
                and item.get("value") == "clean"
            )
            self.assertEqual(dirty.get("status"), "contested")
            self.assertEqual(clean.get("status"), "emerging")
            self.assertTrue(clean.get("formed_from_prediction_error"))
            self.assertIsNotNone(profile.get("last_restructured_at"))
            alternatives = profile.get("alternatives") or {}
            self.assertGreaterEqual(
                int(alternatives.get("workspace", {}).get("clean", 0)),
                2,
            )
            store.close()


if __name__ == "__main__":
    unittest.main()
