from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.adaptive_guidance import (
    active_schema_relations,
    schema_attention_focus,
    schema_reality_score,
)
from zn_agent.core.intention_formation import (
    NativeIntentionCandidate,
    NativeIntentionFormation,
    SituatedIntentionalResidentRuntime,
)
from zn_agent.core.nervous_system import NeuralActivation, NeuralTrace
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class AdaptedSchemaGuidanceTests(unittest.TestCase):
    @staticmethod
    def _profile(*, stabilized: bool) -> dict:
        relations = [
            {
                "family": "workspace",
                "value": "dirty",
                "support_ratio": 0.94,
                "weight": 0.92,
                "channels": ["git"],
                "anchor": False,
                "confidence": 0.18 if stabilized else 0.86,
                "confirmations": 0,
                "conflicts": 3 if stabilized else 0,
                "status": "contested" if stabilized else "expected",
            }
        ]
        if stabilized:
            relations.append(
                {
                    "family": "workspace",
                    "value": "clean",
                    "support_ratio": 0.66,
                    "weight": 0.61,
                    "channels": ["git"],
                    "anchor": False,
                    "confidence": 0.82,
                    "confirmations": 2,
                    "conflicts": 0,
                    "status": "expected",
                    "formed_from_prediction_error": True,
                    "stabilized_from_prediction_error": True,
                    "stabilized_at": "2026-08-21T10:00:00+00:00",
                }
            )
        return {
            "version": 1,
            "anchor_feature": "adapted_guidance_pattern",
            "source_count": 3,
            "features": [],
            "channels": {"world": 1, "vision": 1, "action": 1},
            "relations": relations,
            "alternatives": {"workspace": {"clean": 3}} if stabilized else {},
            "feedback": {
                "supported": 1 if stabilized else 0,
                "refined": 2 if stabilized else 0,
                "contradicted": 0,
            },
            **(
                {"last_stabilized_at": "2026-08-21T10:00:00+00:00"}
                if stabilized
                else {}
            ),
        }

    @classmethod
    def _schema(cls, *, trace_id: str, stabilized: bool) -> NeuralTrace:
        return NeuralTrace(
            trace_id=trace_id,
            fingerprint=f"fp-{trace_id}",
            channel="schema",
            summary="Persistent pattern: adapted_guidance_pattern recurs in lived experience.",
            features=("adapted_guidance_pattern", "consolidated_pattern"),
            strength=0.82,
            salience=0.80,
            arousal=0.35,
            repetitions=4,
            metadata={
                "prediction_profile": cls._profile(stabilized=stabilized),
                "prediction_confidence": 0.84 if stabilized else 0.70,
                "memory_state": "consolidated",
            },
        )

    def test_reality_view_excludes_superseded_relation_and_surfaces_stable_replacement(self):
        schema = self._schema(trace_id="schema-adapted", stabilized=True)

        relations = active_schema_relations(schema)
        labels = [(item["family"], item["value"]) for item in relations]
        focus = schema_attention_focus(schema)

        self.assertEqual(labels[0], ("workspace", "clean"))
        self.assertNotIn(("workspace", "dirty"), labels)
        self.assertIn("reality-updated", focus)
        self.assertIn("workspace:clean", focus)
        self.assertNotIn("workspace:dirty", focus)
        self.assertGreater(schema_reality_score(schema), 0.60)

        schema.metadata["prediction_confidence"] = "not-a-number"
        self.assertGreaterEqual(schema_reality_score(schema), 0.0)

    def test_endogenous_attention_uses_reality_updated_schema_focus_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            schema = resident.nervous.perceive(
                "schema",
                "Persistent pattern: attention_adaptation recurs in lived experience.",
                features=("attention_adaptation", "consolidated_pattern"),
                salience=0.96,
                arousal=0.34,
                metadata={
                    "prediction_profile": self._profile(stabilized=True),
                    "prediction_confidence": 0.88,
                    "memory_state": "consolidated",
                },
            )
            schema.strength = 0.94
            schema.salience = 0.96
            resident.nervous._save_trace(schema)

            candidate = resident._select_endogenous_attention(
                resident.nervous.snapshot()
            )

            self.assertIsNotNone(candidate)
            self.assertEqual(candidate.get("trace_id"), schema.trace_id)
            self.assertEqual(candidate.get("drive"), "integrate")
            self.assertIn("reality-updated", candidate.get("focus") or "")
            self.assertIn("workspace:clean", candidate.get("focus") or "")
            self.assertNotIn("workspace:dirty", candidate.get("focus") or "")
            self.assertIn("reality-updated", candidate.get("action") or "")
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_stabilized_relation_wins_within_one_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            formation = NativeIntentionFormation(resident.nervous, resident=resident)
            profile = {
                "relations": [
                    {
                        "family": "system",
                        "value": "linux",
                        "support_ratio": 0.74,
                        "weight": 0.70,
                        "confidence": 0.78,
                        "status": "expected",
                    },
                    {
                        "family": "architecture",
                        "value": "x86_64",
                        "support_ratio": 0.66,
                        "weight": 0.62,
                        "confidence": 0.76,
                        "status": "expected",
                        "formed_from_prediction_error": True,
                        "stabilized_from_prediction_error": True,
                    },
                ]
            }

            relation = formation._select_relation(
                profile,
                "understand current host adaptation",
                body=None,
            )

            self.assertIsNotNone(relation)
            self.assertEqual(relation.get("family"), "architecture")
            self.assertEqual(relation.get("value"), "x86_64")
            self.assertTrue(relation.get("stabilized_from_prediction_error"))
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_reality_adapted_schema_can_beat_slightly_stronger_stale_activation(self):
        stale = self._schema(trace_id="schema-stale", stabilized=False)
        adapted = self._schema(trace_id="schema-adapted", stabilized=True)
        stale_activation = NeuralActivation(
            trace=stale,
            activation=0.66,
            cue_overlap=0.60,
        )
        adapted_activation = NeuralActivation(
            trace=adapted,
            activation=0.58,
            cue_overlap=0.52,
        )
        stale_candidate = NativeIntentionCandidate(
            kind="situated_schema_probe",
            step="inspect stale workspace",
            reason="older inherited expectation",
            support=(stale.trace_id,),
            payload={
                "schema_expectation": {
                    "family": "workspace",
                    "value": "dirty",
                    "status": "expected",
                    "recheck": False,
                }
            },
            probe_key="git",
            relation_family="workspace",
            relation_value="dirty",
        )
        adapted_candidate = NativeIntentionCandidate(
            kind="situated_schema_probe",
            step="inspect reality-updated workspace",
            reason="relation survived prediction error and reality support",
            support=(adapted.trace_id,),
            payload={
                "schema_expectation": {
                    "family": "workspace",
                    "value": "clean",
                    "status": "expected",
                    "recheck": False,
                }
            },
            probe_key="git",
            relation_family="workspace",
            relation_value="clean",
        )

        stale_score = SituatedIntentionalResidentRuntime._formed_candidate_score(
            stale_activation,
            stale_candidate,
        )
        adapted_score = SituatedIntentionalResidentRuntime._formed_candidate_score(
            adapted_activation,
            adapted_candidate,
        )

        self.assertGreater(adapted_score, stale_score)
        selected = max(
            (
                (stale_activation, stale_candidate),
                (adapted_activation, adapted_candidate),
            ),
            key=lambda item: SituatedIntentionalResidentRuntime._formed_candidate_score(
                item[0], item[1]
            ),
        )
        self.assertEqual(selected[1].relation_value, "clean")


if __name__ == "__main__":
    unittest.main()
