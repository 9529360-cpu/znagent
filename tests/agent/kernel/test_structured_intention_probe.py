from __future__ import annotations

import platform
import tempfile
import unittest
from pathlib import Path

from agent.kernel import ExecutionPath
from agent.kernel.nervous_system import PersistentNervousSystem
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack
from agent.kernel.reconsolidation import SchemaReconsolidator
from agent.kernel.store import KernelStore
from agent.kernel.will import NativeWill


class StructuredIntentionProbeTests(unittest.TestCase):
    @staticmethod
    def _seed_schema(
        nervous: PersistentNervousSystem,
        *,
        anchor: str,
        relation: str,
    ):
        nervous.perceive(
            "world",
            f"world experience carried {anchor} with {relation}",
            features=(anchor, relation, "resident_pattern"),
            salience=0.80,
            arousal=0.52,
        )
        nervous.perceive(
            "vision",
            f"visual experience carried {anchor} with {relation}",
            features=(anchor, relation, "resident_pattern"),
            salience=0.84,
            arousal=0.56,
        )
        nervous.perceive(
            "action",
            f"body experience carried {anchor} with {relation}",
            features=(anchor, relation, "resident_pattern"),
            salience=0.82,
            arousal=0.54,
        )
        nervous.consolidate()
        schemas = [
            trace
            for trace in nervous.recent_traces(100)
            if trace.channel == "schema" and anchor in trace.features
        ]
        if not schemas:
            raise AssertionError(f"expected schema for {anchor}")
        return schemas[0]

    def test_will_prefers_reconsolidated_relation_over_stale_source_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            nervous = PersistentNervousSystem(store)
            schema = self._seed_schema(
                nervous,
                anchor="repo_health_pattern",
                relation="workspace:dirty",
            )
            reconsolidator = SchemaReconsolidator(nervous)
            profile = reconsolidator._profile(schema)
            dirty = next(
                item
                for item in profile.get("relations") or ()
                if item.get("family") == "workspace"
                and item.get("value") == "dirty"
            )
            dirty["status"] = "contested"
            dirty["confidence"] = 0.18
            profile.setdefault("relations", []).append(
                {
                    "family": "workspace",
                    "value": "clean",
                    "support_ratio": 0.58,
                    "weight": 0.56,
                    "channels": ["git"],
                    "anchor": False,
                    "confidence": 0.76,
                    "confirmations": 2,
                    "conflicts": 0,
                    "status": "emerging",
                    "formed_from_prediction_error": True,
                }
            )
            schema.metadata["prediction_profile"] = profile
            nervous._save_trace(schema)

            will = NativeWill(store)
            intention = will.intend("understand repo_health_pattern current behavior")
            candidate = will.incubate_candidate(
                intention.intention_id,
                kind="schema_probe",
                step=(
                    "test whether this consolidated pattern applies to my current "
                    f"intention: {schema.summary}"
                ),
                reason="a lived pattern repeatedly activated",
                confidence=0.82,
                support=(schema.trace_id,),
                payload={
                    "model_policy": "never",
                    "incubated_event_kind": "intention_probe",
                    "schema_trace_id": schema.trace_id,
                    "schema_summary": schema.summary,
                },
            )

            relation = candidate.candidate_payload.get("schema_probe_relation") or {}
            self.assertEqual(candidate.candidate_kind, "schema_probe")
            self.assertIn("current git repository state", candidate.candidate_step)
            self.assertIn("workspace:clean", candidate.candidate_step)
            self.assertNotIn("workspace:dirty", candidate.candidate_step)
            self.assertEqual(candidate.candidate_payload.get("schema_probe_observation"), "git")
            self.assertEqual(relation.get("family"), "workspace")
            self.assertEqual(relation.get("value"), "clean")
            self.assertEqual(relation.get("status"), "emerging")
            store.close()

    def test_structured_body_relation_drives_zero_model_reality_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            relation = f"system:{platform.system().lower()}"
            schema = self._seed_schema(
                resident.nervous,
                anchor="host_identity_pattern",
                relation=relation,
            )
            intention = resident.intend(
                "understand host_identity_pattern current behavior",
                priority=5,
            )

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
            self.assertEqual(
                terminal.event.payload.get("schema_probe_observation"),
                "body",
            )
            expected = terminal.event.payload.get("schema_probe_relation") or {}
            self.assertEqual(expected.get("family"), "system")
            self.assertEqual(expected.get("value"), platform.system().lower())
            self.assertIn("Reality feedback supported", terminal.response)

            lived = resident.will.get(intention.intention_id)
            self.assertIn("current body state", lived.current_step)
            self.assertIn(relation, lived.current_step)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)

            # A completed structured reality check is not immediately repeated.
            for _ in range(8):
                self.assertIsNone(resident.live_once())
            probe_events = [
                event
                for event in resident.store.list_events(limit=100)
                if event.kind == "intention_probe"
                and event.payload.get("intention_id") == intention.intention_id
            ]
            self.assertEqual(len(probe_events), 1)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
