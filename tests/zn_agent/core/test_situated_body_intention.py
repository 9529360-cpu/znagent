from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core import ExecutionPath
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.schema_structure import SchemaStructurePlasticity


class SituatedBodyIntentionTests(unittest.TestCase):
    @staticmethod
    def _seed_body_schema(resident):
        body = resident.body.sense()
        system = str(body.get("system") or "").strip().lower()
        if not system:
            raise AssertionError("resident system should be observable")
        features = ("body_pattern", f"system:{system}", "resident_host")
        resident.perceive_world(
            "the same resident host pattern appeared in the world stream",
            features=features,
            salience=0.84,
            arousal=0.52,
        )
        resident.perceive_visual(
            "the resident host pattern appeared again in visual context",
            features=features,
            salience=0.82,
            arousal=0.50,
        )
        resident.nervous.perceive(
            "action",
            "a body observation encountered the same resident host pattern",
            features=features,
            salience=0.80,
            arousal=0.48,
        )
        resident.nervous.consolidate()
        schemas = [
            trace
            for trace in resident.nervous.recent_traces(100)
            if trace.channel == "schema" and "body_pattern" in trace.features
        ]
        if not schemas:
            raise AssertionError("expected a body schema")
        return schemas[0], body, system

    @staticmethod
    def _seed_body_snapshot_schema(resident):
        body = resident.body.sense()
        system = str(body.get("system") or "").strip().lower()
        architecture = str(body.get("architecture") or "").strip().lower()
        total = max(1, int(body.get("disk_total_bytes") or 1))
        free = max(0, int(body.get("disk_free_bytes") or 0))
        ratio = free / total
        disk_state = (
            "low"
            if ratio < 0.10
            else "constrained"
            if ratio < 0.20
            else "healthy"
        )
        if not system or not architecture:
            raise AssertionError("resident body identity should be observable")
        relations = (
            f"system:{system}",
            f"architecture:{architecture}",
            f"disk_state:{disk_state}",
        )
        features = ("body_snapshot_pattern", *relations)
        resident.perceive_world(
            "body_snapshot_pattern carried the same host snapshot relations",
            features=features,
            salience=0.86,
            arousal=0.54,
        )
        resident.perceive_visual(
            "the body snapshot pattern repeated across current visual context",
            features=features,
            salience=0.84,
            arousal=0.52,
        )
        resident.nervous.perceive(
            "action",
            "body sensing encountered body_snapshot_pattern again",
            features=features,
            salience=0.82,
            arousal=0.50,
        )
        resident.nervous.consolidate()
        schemas = [
            trace
            for trace in resident.nervous.recent_traces(100)
            if trace.channel == "schema"
            and "body_snapshot_pattern" in trace.features
        ]
        if not schemas:
            raise AssertionError("expected a body snapshot schema")
        return schemas[0], relations

    def test_body_relation_forms_through_situated_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            schema, body, system = self._seed_body_schema(resident)
            intention = resident.intend(
                "understand body_pattern current host behavior",
                priority=5,
            )

            resident.live_once()
            current = resident.will.get(intention.intention_id)
            self.assertIsNotNone(current)
            payload = current.candidate_payload
            expectation = payload.get("schema_expectation") or {}
            relation = payload.get("schema_probe_relation") or {}
            context = payload.get("native_situation_context") or {}

            self.assertEqual(current.candidate_kind, "situated_schema_probe")
            self.assertIn("current body state relation system:", current.candidate_step)
            self.assertIn(schema.trace_id, current.candidate_support)
            self.assertEqual(payload.get("native_probe_key"), "body")
            self.assertEqual(payload.get("schema_probe_observation"), "body")
            self.assertEqual(expectation.get("family"), "system")
            self.assertEqual(expectation.get("value"), system)
            self.assertEqual(relation.get("family"), "system")
            self.assertEqual(relation.get("value"), system)
            self.assertEqual(context.get("body_system"), body.get("system"))
            self.assertEqual(context.get("body_architecture"), body.get("architecture"))
            self.assertIn("body_disk_free_ratio", context)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_structured_body_probe_activates_prediction_before_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            schema, _body, system = self._seed_body_schema(resident)
            resident.intend(
                "understand body_pattern current host behavior",
                priority=6,
            )

            terminal = None
            for _ in range(24):
                terminal = resident.live_once()
                if terminal is not None:
                    break

            self.assertIsNotNone(terminal)
            self.assertTrue(terminal.success)
            self.assertEqual(terminal.execution_path, ExecutionPath.INVESTIGATION)
            self.assertEqual(terminal.model_invocations, 0)
            self.assertEqual(terminal.event.kind, "intention_probe")
            self.assertEqual(terminal.event.payload.get("native_probe_key"), "body")
            self.assertEqual(
                terminal.event.payload.get("schema_probe_observation"),
                "body",
            )

            investigation = resident.investigator.current(terminal.event.event_id)
            self.assertIsNotNone(investigation)
            self.assertGreaterEqual(len(investigation.probe_keys), 2)
            self.assertEqual(tuple(investigation.probe_keys[:2]), ("experience", "body"))

            predictions = investigation.facts.get("schema_predictions") or []
            feedback = investigation.facts.get("schema_prediction_feedback") or []
            self.assertTrue(predictions)
            self.assertEqual(predictions[0].get("trace_id"), schema.trace_id)
            self.assertTrue(feedback)
            self.assertEqual(feedback[-1].get("status"), "supported")
            support = set(feedback[-1].get("support") or ())
            self.assertIn(f"system:{system}", support)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_one_body_snapshot_covers_all_relations_for_next_formation(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            schema, relations = self._seed_body_snapshot_schema(resident)
            intention = resident.intend(
                "understand body_snapshot_pattern current host behavior",
                priority=7,
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
            investigation = resident.investigator.current(terminal.event.event_id)
            self.assertIsNotNone(investigation)
            feedback = investigation.facts.get("schema_prediction_feedback") or []
            current_feedback = next(
                item
                for item in feedback
                if item.get("schema_trace_id") == schema.trace_id
            )
            support = set(current_feedback.get("support") or ())
            for relation in relations:
                self.assertIn(relation, support)

            resolved = SchemaStructurePlasticity(resident.nervous).resolve_schema(
                schema.trace_id
            )
            self.assertIsNotNone(resolved)
            persisted_feedback = (
                resolved.metadata.get("last_prediction_feedback") or {}
            )
            self.assertEqual(
                persisted_feedback.get("event_id"),
                terminal.event.event_id,
            )

            lived = resident.will.get(intention.intention_id)
            self.assertIsNotNone(lived)
            targeted = resident.intention_formation._targeted_expectation_signatures(
                lived
            )
            tested = resident.intention_formation._tested_expectation_signatures(
                lived,
                resolved.metadata,
            )
            expected_signatures = {
                resident.intention_formation._expectation_signature(
                    *relation.split(":", 1)
                )
                for relation in relations
            }
            self.assertTrue(targeted)
            self.assertTrue(targeted.issubset(tested))
            self.assertTrue(expected_signatures.issubset(tested))

            activation = next(
                item
                for item in resident.nervous.activate(
                    intention.description,
                    channels=resident._INCUBATION_CHANNELS,
                    limit=12,
                )
                if item.trace.trace_id == resolved.trace_id
            )
            follow_up = resident.intention_formation.form(
                lived,
                activation,
                situation=resident.life.snapshot().current_situation,
                body=resident.life.snapshot().body,
            )
            self.assertIsNone(follow_up)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
