from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.kernel import ExecutionPath
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class SituatedBodyIntentionTests(unittest.TestCase):
    @staticmethod
    def _seed_body_schema(resident):
        body = resident.life.snapshot().body
        if body is None:
            raise AssertionError("resident body should be available")
        system = str(body.system or "").strip().lower()
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
            context = payload.get("native_situation_context") or {}

            self.assertEqual(current.candidate_kind, "situated_schema_probe")
            self.assertIn("current body relation system", current.candidate_step)
            self.assertIn(schema.trace_id, current.candidate_support)
            self.assertEqual(payload.get("native_probe_key"), "body")
            self.assertEqual(payload.get("schema_probe_observation"), "body")
            self.assertEqual(expectation.get("family"), "system")
            self.assertEqual(expectation.get("value"), system)
            self.assertEqual(context.get("body_system"), body.system)
            self.assertEqual(context.get("body_architecture"), body.architecture)
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


if __name__ == "__main__":
    unittest.main()
