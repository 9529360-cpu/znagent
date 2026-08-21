from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.kernel.integrated_transfer import IntegratedTransferActivation
from agent.kernel.life import ThoughtFrame
from agent.kernel.models import utc_now
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class TransferAttentionRhythmTests(unittest.TestCase):
    @staticmethod
    def _profile(family: str, value: str, *, stabilized: bool = False) -> dict:
        relation = {
            "family": family,
            "value": value,
            "support_ratio": 0.82,
            "weight": 0.78,
            "confidence": 0.90,
            "confirmations": 3 if stabilized else 1,
            "conflicts": 0,
            "status": "expected",
        }
        if stabilized:
            relation.update(
                {
                    "formed_from_prediction_error": True,
                    "stabilized_from_prediction_error": True,
                    "stabilized_at": "2026-08-21T15:00:00+00:00",
                }
            )
        return {
            "version": 1,
            "anchor_feature": f"{family}_{value}_pattern",
            "source_count": 4,
            "features": [],
            "channels": {"world": 2, "action": 1},
            "relations": [relation],
            "alternatives": {},
            "feedback": {"supported": 3, "refined": 0, "contradicted": 0},
            **(
                {"last_stabilized_at": "2026-08-21T15:00:00+00:00"}
                if stabilized
                else {}
            ),
        }

    @classmethod
    def _schema(
        cls,
        resident,
        name: str,
        family: str,
        value: str,
        *,
        stabilized: bool = False,
    ):
        trace = resident.nervous.perceive(
            "schema",
            f"Persistent pattern: {name}.",
            features=(name, "consolidated_pattern"),
            salience=0.87,
            arousal=0.34,
            metadata={
                "memory_state": "consolidated",
                "prediction_confidence": 0.91 if stabilized else 0.78,
                "prediction_profile": cls._profile(
                    family,
                    value,
                    stabilized=stabilized,
                ),
            },
        )
        trace.strength = 0.92
        trace.salience = 0.87
        resident.nervous._save_trace(trace)
        return trace

    @staticmethod
    def _bridge(resident, name: str):
        return resident.nervous.perceive(
            "world",
            f"lived attention bridge {name}",
            features=(f"attention_bridge_{name}",),
            salience=0.76,
            arousal=0.28,
        )

    @classmethod
    def _contributors(cls, resident, count: int):
        pairs = []
        for index in range(count):
            source = cls._schema(
                resident,
                f"attention_source_{index}",
                "workspace" if index % 2 == 0 else "branch",
                "clean" if index % 2 == 0 else "dev",
                stabilized=True,
            )
            bridge = cls._bridge(resident, str(index))
            pairs.append((source, bridge))
        return tuple(pairs)

    @staticmethod
    def _activation(target, contributors, *, consensus: float, conflicts: int):
        bundle = tuple(
            {
                "source_trace_id": source.trace_id,
                "bridge_trace_id": bridge.trace_id,
                "gain": 0.18 - 0.01 * index,
                "tendency": 1.18,
                "feedback_count": 3,
            }
            for index, (source, bridge) in enumerate(contributors)
        )
        first = bundle[0] if bundle else {}
        return IntegratedTransferActivation(
            trace=target,
            activation=0.34,
            cue_overlap=0.0,
            associative_gain=0.32,
            transfer_gain=0.32,
            transfer_source_trace_id=str(first.get("source_trace_id") or ""),
            transfer_bridge_trace_id=str(first.get("bridge_trace_id") or ""),
            transfer_tendency=1.18,
            transfer_feedback_count=3,
            transfer_contributors=bundle,
            transfer_consensus=consensus,
            transfer_conflict_count=conflicts,
        )

    @staticmethod
    def _thought(sequence: int) -> ThoughtFrame:
        return ThoughtFrame(
            sequence=sequence,
            at=utc_now(),
            focus="transfer attention rhythm",
            reason="test",
            confidence=0.50,
        )

    @staticmethod
    def _prime(resident):
        resident.life.wake()
        resident.life.pulse()
        body = resident.life.snapshot().body
        if body is None:
            raise AssertionError("resident body was not available")
        return body

    def test_coherent_supported_transfer_matures_without_extra_review_delay(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            body = self._prime(resident)
            target = self._schema(
                resident,
                "coherent_attention_target",
                "system",
                str(body.system).lower(),
            )
            contributors = self._contributors(resident, 2)
            activation = self._activation(
                target,
                contributors,
                consensus=0.96,
                conflicts=0,
            )
            intention = resident.intend(
                "reuse coherent transferred runtime evidence",
                priority=7,
            )

            with patch.object(resident.nervous, "activate", return_value=[activation]):
                first_thought = self._thought(100)
                resident._incubate_primary_intention(first_thought)
                first = resident.will.get(intention.intention_id)
                self.assertIsNotNone(first)
                self.assertEqual(first.candidate_repetitions, 1)
                attention = first.candidate_payload.get("transfer_attention")
                self.assertEqual(attention.get("evidence_state"), "coherent")
                self.assertEqual(attention.get("review_period_pulses"), 1)
                self.assertNotEqual(first_thought.action_kind, "incubate")

                second_thought = self._thought(101)
                resident._incubate_primary_intention(second_thought)
                matured = resident.will.get(intention.intention_id)
                self.assertGreaterEqual(matured.candidate_repetitions, 2)
                self.assertGreaterEqual(matured.candidate_maturity, 0.72)
                self.assertEqual(second_thought.action_kind, "incubate")
                self.assertIn(
                    "cross-context recall plus current Situation support",
                    second_thought.reason,
                )

            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_conflict_keeps_attention_open_and_review_rhythm_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            body = self._prime(resident)
            target = self._schema(
                resident,
                "conflicted_attention_target",
                "system",
                str(body.system).lower(),
            )
            contributors = self._contributors(resident, 1)
            activation = self._activation(
                target,
                contributors,
                consensus=0.55,
                conflicts=1,
            )
            intention = resident.intend(
                "hold a conflicted transferred runtime question open",
                priority=7,
            )

            with patch.object(resident.nervous, "activate", return_value=[activation]):
                first_thought = self._thought(200)
                resident._incubate_primary_intention(first_thought)
                first = resident.will.get(intention.intention_id)
                self.assertEqual(first.candidate_repetitions, 1)
                attention = first.candidate_payload.get("transfer_attention")
                self.assertEqual(attention.get("evidence_state"), "conflicted")
                self.assertEqual(attention.get("review_period_pulses"), 3)
                self.assertEqual(attention.get("first_sequence"), 200)
                self.assertEqual(first_thought.action_kind, "observe")
                self.assertTrue(
                    any(
                        "transfer attention remains open across pulses" in item
                        for item in first_thought.known
                    )
                )

            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored_target = restored.nervous._get_trace(target.trace_id)
            self.assertIsNotNone(restored_target)
            restored_pairs = tuple(
                (
                    restored.nervous._get_trace(source.trace_id),
                    restored.nervous._get_trace(bridge.trace_id),
                )
                for source, bridge in contributors
            )
            self.assertTrue(all(source and bridge for source, bridge in restored_pairs))
            restored_activation = self._activation(
                restored_target,
                restored_pairs,
                consensus=0.55,
                conflicts=1,
            )

            with patch.object(
                restored.nervous,
                "activate",
                return_value=[restored_activation],
            ):
                for sequence in (201, 202):
                    held_thought = self._thought(sequence)
                    restored._incubate_primary_intention(held_thought)
                    held = restored.will.get(intention.intention_id)
                    self.assertEqual(held.candidate_repetitions, 1)
                    self.assertEqual(held_thought.action_kind, "observe")
                    self.assertEqual(
                        held.candidate_payload["transfer_attention"]["first_sequence"],
                        200,
                    )

                review_thought = self._thought(203)
                restored._incubate_primary_intention(review_thought)
                reviewed = restored.will.get(intention.intention_id)
                self.assertEqual(reviewed.candidate_repetitions, 2)
                self.assertNotEqual(review_thought.action_kind, "incubate")

                for sequence in (204, 205):
                    held_thought = self._thought(sequence)
                    restored._incubate_primary_intention(held_thought)
                    held = restored.will.get(intention.intention_id)
                    self.assertEqual(held.candidate_repetitions, 2)
                    self.assertEqual(held_thought.action_kind, "observe")

                mature_thought = None
                repetitions = 2
                for sequence in range(206, 214):
                    thought = self._thought(sequence)
                    restored._incubate_primary_intention(thought)
                    current = restored.will.get(intention.intention_id)
                    if sequence in {206, 209, 212}:
                        repetitions += 1
                        self.assertEqual(current.candidate_repetitions, repetitions)
                    else:
                        self.assertEqual(current.candidate_repetitions, repetitions)
                        self.assertEqual(thought.action_kind, "observe")
                    if thought.action_kind == "incubate":
                        mature_thought = thought
                        break

                matured = restored.will.get(intention.intention_id)
                self.assertIsNotNone(mature_thought)
                self.assertGreaterEqual(matured.candidate_maturity, 0.72)
                self.assertEqual(mature_thought.action_kind, "incubate")

            promoted = restored.will.promote_candidate(intention.intention_id)
            self.assertIsNotNone(promoted.next_task)
            self.assertEqual(
                promoted.next_payload["transfer_attention"]["first_sequence"],
                200,
            )
            restored._advance_intention(intention.intention_id)
            engaged = restored.will.get(intention.intention_id)
            event = restored.store.get_event(engaged.related_event_id)
            self.assertIsNotNone(event)
            self.assertEqual(event.kind, "intention_probe")
            self.assertEqual(event.payload.get("model_policy"), "never")
            self.assertEqual(
                event.payload["transfer_attention"]["evidence_state"],
                "conflicted",
            )
            self.assertEqual(restored.store.get_runtime_metrics().model_invocations, 0)
            restored.store.close()


if __name__ == "__main__":
    unittest.main()
