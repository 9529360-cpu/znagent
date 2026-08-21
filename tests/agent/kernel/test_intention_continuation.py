from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from agent.kernel import ExecutionPath
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class IntentionContinuationTests(unittest.TestCase):
    @staticmethod
    def _run_to_terminal(resident, *, limit: int = 36):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach a terminal intention probe")

    @staticmethod
    def _wait_for_candidate(resident, intention_id: str, *, limit: int = 12):
        for _ in range(limit):
            resident.live_once()
            current = resident.will.get(intention_id)
            if current is not None and current.candidate_step:
                return current
        raise AssertionError("resident did not form a follow-up intention candidate")

    @staticmethod
    def _seed_wrong_workspace_schema(resident):
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        actual = "dirty" if proc.stdout.strip() else "clean"
        predicted = "clean" if actual == "dirty" else "dirty"
        relation = f"workspace:{predicted}"

        resident.perceive_world(
            "continuation_pattern repeatedly appeared with a repository workspace state",
            features=("continuation_pattern", relation, "repository"),
            salience=0.86,
            arousal=0.56,
        )
        resident.perceive_visual(
            "the same continuation pattern appeared with the same workspace state",
            features=("continuation_pattern", relation, "repository"),
            salience=0.84,
            arousal=0.54,
        )
        resident.nervous.perceive(
            "action",
            "repository inspection observed continuation_pattern again",
            features=("continuation_pattern", relation, "repository"),
            salience=0.82,
            arousal=0.52,
        )
        resident.nervous.consolidate()
        schemas = [
            trace
            for trace in resident.nervous.recent_traces(100)
            if trace.channel == "schema" and "continuation_pattern" in trace.features
        ]
        if not schemas:
            raise AssertionError("expected a continuation workspace schema")
        return schemas[0], actual, predicted

    def test_prediction_error_forms_one_recheck_then_emerging_relation(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            schema, actual, predicted = self._seed_wrong_workspace_schema(resident)
            intention = resident.intend(
                "understand continuation_pattern current repository behavior",
                priority=6,
            )

            first = self._run_to_terminal(resident)
            self.assertTrue(first.success)
            self.assertEqual(first.execution_path, ExecutionPath.INVESTIGATION)
            self.assertEqual(first.model_invocations, 0)
            self.assertEqual(first.event.kind, "intention_probe")
            first_expectation = first.event.payload.get("schema_expectation") or {}
            self.assertEqual(first_expectation.get("family"), "workspace")
            self.assertEqual(first_expectation.get("value"), predicted)
            self.assertFalse(bool(first_expectation.get("recheck")))

            first_inv = resident.investigator.current(first.event.event_id)
            self.assertIsNotNone(first_inv)
            first_feedback = first_inv.facts.get("schema_prediction_feedback") or []
            self.assertTrue(first_feedback)
            self.assertIn(first_feedback[-1].get("status"), {"refined", "contradicted"})

            recheck = self._wait_for_candidate(resident, intention.intention_id)
            recheck_expectation = recheck.candidate_payload.get("schema_expectation") or {}
            self.assertEqual(recheck.candidate_kind, "situated_schema_probe")
            self.assertEqual(recheck_expectation.get("family"), "workspace")
            self.assertEqual(recheck_expectation.get("value"), predicted)
            self.assertTrue(recheck_expectation.get("recheck"))
            self.assertEqual(recheck_expectation.get("attempt"), 2)
            self.assertIn("recheck 2 current git workspace", recheck.candidate_step)
            self.assertNotEqual(recheck.candidate_step, recheck.current_step)

            second = self._run_to_terminal(resident)
            self.assertTrue(second.success)
            self.assertEqual(second.execution_path, ExecutionPath.INVESTIGATION)
            self.assertEqual(second.model_invocations, 0)
            second_inv = resident.investigator.current(second.event.event_id)
            self.assertIsNotNone(second_inv)
            second_feedback = second_inv.facts.get("schema_prediction_feedback") or []
            self.assertTrue(second_feedback)
            self.assertIn(second_feedback[-1].get("status"), {"refined", "contradicted"})

            emerging = self._wait_for_candidate(resident, intention.intention_id)
            emerging_expectation = emerging.candidate_payload.get("schema_expectation") or {}
            self.assertEqual(emerging.candidate_kind, "situated_schema_probe")
            self.assertEqual(emerging_expectation.get("family"), "workspace")
            self.assertEqual(emerging_expectation.get("value"), actual)
            self.assertEqual(emerging_expectation.get("status"), "emerging")
            self.assertFalse(bool(emerging_expectation.get("recheck")))
            self.assertNotEqual(
                emerging_expectation.get("signature"),
                first_expectation.get("signature"),
            )
            self.assertNotEqual(emerging.candidate_step, emerging.current_step)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
