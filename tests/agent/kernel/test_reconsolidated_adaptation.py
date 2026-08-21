from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.kernel import ExecutionPath
from agent.kernel.nervous_system import PersistentNervousSystem
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack
from agent.kernel.reconsolidation import SchemaReconsolidator
from agent.kernel.schema_structure import SchemaStructurePlasticity
from agent.kernel.store import KernelStore
from agent.kernel.visual_sense import NativeVisualSense, VisualFrame


class ReconsolidatedAdaptationTests(unittest.TestCase):
    @staticmethod
    def _seed_workspace_schema(nervous: PersistentNervousSystem):
        for channel, suffix in (
            ("world", "world"),
            ("vision", "visual context"),
            ("action", "body inspection"),
        ):
            nervous.perceive(
                channel,
                f"adaptation_pattern appeared in {suffix} with a dirty workspace",
                features=("adaptation_pattern", "workspace:dirty", "repository"),
                salience=0.84,
                arousal=0.54,
            )
        nervous.consolidate()
        schemas = [
            trace
            for trace in nervous.recent_traces(100)
            if trace.channel == "schema" and "adaptation_pattern" in trace.features
        ]
        if not schemas:
            raise AssertionError("expected adaptation schema")
        return schemas[0]

    @staticmethod
    def _frame(token: str, regions: tuple[str, ...]) -> VisualFrame:
        return VisualFrame(
            frame_hash=(token * 64)[:64],
            width=320,
            height=180,
            source="test-adaptation-retina",
            region_signatures=regions,
            grid_columns=4,
            grid_rows=3,
            mean_luminance=0.45,
        )

    @staticmethod
    def _seed_visual_schema(resident):
        for channel, summary in (
            ("world", "screen_adaptation_pattern coincided with a local visual change"),
            ("vision", "screen_adaptation_pattern repeated with a local visual change"),
            ("action", "screen response retained the same local visual change pattern"),
        ):
            resident.nervous.perceive(
                channel,
                summary,
                features=("screen_adaptation_pattern", "visual_change:local"),
                salience=0.86,
                arousal=0.56,
            )
        resident.nervous.consolidate()
        schemas = [
            trace
            for trace in resident.nervous.recent_traces(100)
            if trace.channel == "schema"
            and "screen_adaptation_pattern" in trace.features
        ]
        if not schemas:
            raise AssertionError("expected visual adaptation schema")
        return schemas[0]

    @staticmethod
    def _run_to_terminal(resident, *, limit: int = 36):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach a terminal intention probe")

    @staticmethod
    def _wait_for_candidate(resident, intention_id: str, *, limit: int = 16):
        for _ in range(limit):
            resident.live_once()
            current = resident.will.get(intention_id)
            if current is not None and current.candidate_step:
                return current
        raise AssertionError("resident did not form the next adaptation candidate")

    def test_supported_emerging_relation_stabilizes_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            store = KernelStore(db)
            nervous = PersistentNervousSystem(store)
            schema = self._seed_workspace_schema(nervous)
            reconsolidator = SchemaReconsolidator(nervous)

            for index in range(3):
                feedback = reconsolidator.evaluate(
                    [{"trace_id": schema.trace_id}],
                    {
                        "git": {
                            "available": True,
                            "branch": "dev/zn-agent",
                            "dirty": False,
                            "changed_files": 0,
                        },
                        "evidence_features": ["adaptation_pattern"],
                    },
                    event_id=f"evt-adapt-{index}",
                )
                self.assertTrue(feedback)
                self.assertIn(feedback[-1].status, {"refined", "contradicted"})

            revised = nervous._get_trace(schema.trace_id)
            profile = revised.metadata.get("prediction_profile") or {}
            clean = next(
                item
                for item in profile.get("relations") or ()
                if item.get("family") == "workspace"
                and item.get("value") == "clean"
            )
            self.assertEqual(clean.get("status"), "emerging")
            self.assertTrue(clean.get("formed_from_prediction_error"))

            supported = reconsolidator.evaluate(
                [{"trace_id": schema.trace_id}],
                {
                    "git": {
                        "available": True,
                        "branch": "dev/zn-agent",
                        "dirty": False,
                        "changed_files": 0,
                    },
                    "evidence_features": ["adaptation_pattern"],
                },
                event_id="evt-adapt-stabilize",
            )
            self.assertEqual(supported[-1].status, "supported")

            stabilized = nervous._get_trace(schema.trace_id)
            profile = stabilized.metadata.get("prediction_profile") or {}
            clean = next(
                item
                for item in profile.get("relations") or ()
                if item.get("family") == "workspace"
                and item.get("value") == "clean"
            )
            dirty = next(
                item
                for item in profile.get("relations") or ()
                if item.get("family") == "workspace"
                and item.get("value") == "dirty"
            )
            self.assertEqual(dirty.get("status"), "contested")
            self.assertEqual(clean.get("status"), "expected")
            self.assertGreaterEqual(int(clean.get("confirmations") or 0), 1)
            self.assertTrue(clean.get("stabilized_from_prediction_error"))
            self.assertTrue(clean.get("stabilized_at"))
            self.assertEqual(profile.get("last_stabilized_at"), clean.get("stabilized_at"))
            self.assertEqual(stabilized.metadata.get("memory_state"), "consolidated")
            store.close()

            restored_store = KernelStore(db)
            restored = PersistentNervousSystem(restored_store)
            restored_schema = restored._get_trace(schema.trace_id)
            restored_profile = restored_schema.metadata.get("prediction_profile") or {}
            restored_clean = next(
                item
                for item in restored_profile.get("relations") or ()
                if item.get("family") == "workspace"
                and item.get("value") == "clean"
            )
            self.assertEqual(restored_clean.get("status"), "expected")
            self.assertTrue(restored_clean.get("stabilized_from_prediction_error"))
            self.assertTrue(restored_profile.get("last_stabilized_at"))
            restored_store.close()

    def test_schema_profile_merge_does_not_downgrade_stabilized_relation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            nervous = PersistentNervousSystem(store)
            plasticity = SchemaStructurePlasticity(nervous)
            base = {
                "version": 1,
                "anchor_feature": "adaptation_pattern",
                "source_count": 3,
                "features": [],
                "channels": {"world": 1},
                "alternatives": {"workspace": {"clean": 2}},
                "feedback": {"supported": 0, "refined": 2, "contradicted": 0},
            }
            stabilized = {
                **base,
                "last_stabilized_at": "2026-08-21T10:00:00+00:00",
                "relations": [
                    {
                        "family": "workspace",
                        "value": "clean",
                        "support_ratio": 0.64,
                        "weight": 0.60,
                        "channels": ["git"],
                        "anchor": False,
                        "confidence": 0.78,
                        "confirmations": 1,
                        "conflicts": 0,
                        "status": "expected",
                        "formed_from_prediction_error": True,
                        "stabilized_from_prediction_error": True,
                        "stabilized_at": "2026-08-21T10:00:00+00:00",
                    }
                ],
            }
            emerging = {
                **base,
                "relations": [
                    {
                        "family": "workspace",
                        "value": "clean",
                        "support_ratio": 0.55,
                        "weight": 0.50,
                        "channels": ["git"],
                        "anchor": False,
                        "confidence": 0.62,
                        "confirmations": 0,
                        "conflicts": 0,
                        "status": "emerging",
                        "formed_from_prediction_error": True,
                    }
                ],
            }

            merged = plasticity._merge_profiles(
                stabilized,
                emerging,
                canonical_count=3,
                absorbed_count=3,
                source_count=3,
            )
            relation = merged["relations"][0]
            self.assertEqual(relation.get("status"), "expected")
            self.assertTrue(relation.get("stabilized_from_prediction_error"))
            self.assertEqual(
                relation.get("stabilized_at"),
                "2026-08-21T10:00:00+00:00",
            )
            self.assertEqual(
                merged.get("last_stabilized_at"),
                "2026-08-21T10:00:00+00:00",
            )
            store.close()

    def test_visual_prediction_error_rechecks_adapts_stabilizes_and_stays_learned(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            regions = tuple(f"stable-{index}" for index in range(12))
            retina = NativeVisualSense(
                resident,
                capture_fn=lambda: self._frame("a", regions),
                interval_seconds=0.1,
            )
            resident.vision = retina
            self.assertIsNotNone(retina.sample())
            schema = self._seed_visual_schema(resident)
            intention = resident.intend(
                "understand screen_adaptation_pattern current behavior",
                priority=7,
            )

            first = self._run_to_terminal(resident)
            self.assertTrue(first.success)
            self.assertEqual(first.execution_path, ExecutionPath.INVESTIGATION)
            self.assertEqual(first.model_invocations, 0)
            first_expectation = first.event.payload.get("schema_expectation") or {}
            self.assertEqual(first_expectation.get("family"), "visual_change")
            self.assertEqual(first_expectation.get("value"), "local")
            self.assertFalse(bool(first_expectation.get("recheck")))

            recheck = self._wait_for_candidate(resident, intention.intention_id)
            recheck_expectation = recheck.candidate_payload.get("schema_expectation") or {}
            self.assertEqual(recheck_expectation.get("value"), "local")
            self.assertTrue(recheck_expectation.get("recheck"))
            self.assertEqual(recheck_expectation.get("attempt"), 2)

            second = self._run_to_terminal(resident)
            self.assertTrue(second.success)
            self.assertEqual(second.execution_path, ExecutionPath.INVESTIGATION)
            self.assertEqual(second.model_invocations, 0)

            emerging = self._wait_for_candidate(resident, intention.intention_id)
            emerging_expectation = emerging.candidate_payload.get("schema_expectation") or {}
            self.assertEqual(emerging_expectation.get("family"), "visual_change")
            self.assertEqual(emerging_expectation.get("value"), "none")
            self.assertEqual(emerging_expectation.get("status"), "emerging")
            self.assertFalse(bool(emerging_expectation.get("recheck")))

            third = self._run_to_terminal(resident)
            self.assertTrue(third.success)
            self.assertEqual(third.execution_path, ExecutionPath.INVESTIGATION)
            self.assertEqual(third.model_invocations, 0)
            third_inv = resident.investigator.current(third.event.event_id)
            self.assertIsNotNone(third_inv)
            feedback = third_inv.facts.get("schema_prediction_feedback") or []
            self.assertTrue(feedback)
            self.assertEqual(feedback[-1].get("status"), "supported")
            self.assertIn("visual_change:none", feedback[-1].get("support") or [])

            resolved = SchemaStructurePlasticity(resident.nervous).resolve_schema(
                schema.trace_id
            )
            self.assertIsNotNone(resolved)
            profile = resolved.metadata.get("prediction_profile") or {}
            none_relation = next(
                item
                for item in profile.get("relations") or ()
                if item.get("family") == "visual_change"
                and item.get("value") == "none"
            )
            local_relation = next(
                item
                for item in profile.get("relations") or ()
                if item.get("family") == "visual_change"
                and item.get("value") == "local"
            )
            self.assertEqual(local_relation.get("status"), "contested")
            self.assertEqual(none_relation.get("status"), "expected")
            self.assertTrue(none_relation.get("stabilized_from_prediction_error"))
            self.assertTrue(profile.get("last_stabilized_at"))
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)

            probe_events_before = [
                event
                for event in resident.store.list_events(limit=200)
                if event.kind == "intention_probe"
                and event.payload.get("intention_id") == intention.intention_id
            ]
            self.assertEqual(len(probe_events_before), 3)
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored_retina = NativeVisualSense(
                restored,
                capture_fn=lambda: self._frame("a", regions),
                interval_seconds=0.1,
            )
            restored.vision = restored_retina
            self.assertIsNotNone(restored_retina.sample())
            lived = restored.will.get(intention.intention_id)
            self.assertIsNotNone(lived)
            restored_schema = SchemaStructurePlasticity(restored.nervous).resolve_schema(
                schema.trace_id
            )
            self.assertIsNotNone(restored_schema)
            restored_profile = restored_schema.metadata.get("prediction_profile") or {}
            restored_none = next(
                item
                for item in restored_profile.get("relations") or ()
                if item.get("family") == "visual_change"
                and item.get("value") == "none"
            )
            self.assertEqual(restored_none.get("status"), "expected")
            self.assertTrue(restored_none.get("stabilized_from_prediction_error"))

            activation = next(
                item
                for item in restored.nervous.activate(
                    lived.description,
                    channels=restored._INCUBATION_CHANNELS,
                    limit=12,
                )
                if item.trace.trace_id == restored_schema.trace_id
            )
            follow_up = restored.intention_formation.form(
                lived,
                activation,
                situation=restored.life.snapshot().current_situation,
                body=restored.life.snapshot().body,
            )
            self.assertIsNone(follow_up)

            for _ in range(8):
                restored.live_once()
            probe_events_after = [
                event
                for event in restored.store.list_events(limit=200)
                if event.kind == "intention_probe"
                and event.payload.get("intention_id") == intention.intention_id
            ]
            self.assertEqual(len(probe_events_after), 3)
            self.assertEqual(restored.store.get_runtime_metrics().model_invocations, 0)
            restored.store.close()


if __name__ == "__main__":
    unittest.main()
