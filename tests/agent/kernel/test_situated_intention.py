from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.kernel import ExecutionPath
from agent.kernel.intention_formation import SituatedIntentionalResidentRuntime
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class SituatedIntentionFormationTests(unittest.TestCase):
    @staticmethod
    def _seed_workspace_schema(resident):
        resident.perceive_world(
            "repository work repeatedly appeared with local workspace changes",
            features=("repo_pattern", "workspace:dirty", "repository"),
            salience=0.84,
            arousal=0.55,
        )
        resident.perceive_visual(
            "the same repository pattern appeared with a dirty workspace",
            features=("repo_pattern", "workspace:dirty", "repository"),
            salience=0.82,
            arousal=0.52,
        )
        resident.nervous.perceive(
            "action",
            "repository inspection observed the workspace pattern again",
            features=("repo_pattern", "workspace:dirty", "repository"),
            salience=0.80,
            arousal=0.50,
        )
        resident.nervous.consolidate()
        schemas = [
            trace
            for trace in resident.nervous.recent_traces(100)
            if trace.channel == "schema" and "repo_pattern" in trace.features
        ]
        if not schemas:
            raise AssertionError("expected a repository schema")
        return schemas[0]

    def test_provider_builds_resident_with_situated_intention_formation(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            self.assertIsInstance(resident, SituatedIntentionalResidentRuntime)
            schema = self._seed_workspace_schema(resident)
            intention = resident.intend(
                "understand repo_pattern current behavior",
                priority=4,
            )

            resident.live_once()
            current = resident.will.get(intention.intention_id)
            payload = current.candidate_payload
            context = payload.get("native_situation_context") or {}
            expectation = payload.get("schema_expectation") or {}

            self.assertEqual(current.candidate_kind, "situated_schema_probe")
            self.assertIn(
                "current git workspace relation workspace",
                current.candidate_step,
            )
            self.assertIn(schema.trace_id, current.candidate_support)
            self.assertEqual(payload.get("native_probe_key"), "git")
            self.assertEqual(
                payload.get("workspace_path"),
                resident.life.snapshot().body.cwd,
            )
            self.assertEqual(expectation.get("family"), "workspace")
            self.assertEqual(expectation.get("value"), "dirty")
            self.assertEqual(context.get("body_cwd"), resident.life.snapshot().body.cwd)
            self.assertGreaterEqual(int(context.get("sequence") or 0), 1)
            self.assertEqual(resident.store.list_events(), [])
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_situated_candidate_reaches_reconsolidation_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            schema = self._seed_workspace_schema(resident)
            intention = resident.intend(
                "understand repo_pattern current behavior",
                priority=5,
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
            self.assertEqual(
                terminal.event.payload.get("schema_trace_id"),
                schema.trace_id,
            )
            self.assertEqual(terminal.event.payload.get("native_probe_key"), "git")

            investigation = resident.investigator.current(terminal.event.event_id)
            self.assertIsNotNone(investigation)
            self.assertGreaterEqual(len(investigation.probe_keys), 2)
            self.assertEqual(investigation.probe_keys[0], "git")
            self.assertIn("experience", investigation.probe_keys)

            predictions = investigation.facts.get("schema_predictions") or []
            feedback = investigation.facts.get("schema_prediction_feedback") or []
            self.assertTrue(predictions)
            self.assertEqual(predictions[0].get("trace_id"), schema.trace_id)
            self.assertTrue(feedback)
            self.assertIn(
                feedback[-1].get("status"),
                {"supported", "refined", "contradicted"},
            )
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
