from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.kernel.adaptive_nervous_system import RealityAwareActivation
from agent.kernel.life import ThoughtFrame
from agent.kernel.models import utc_now
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack
from agent.kernel.transfer_incubation import TransferAwareSituatedResidentRuntime


class TransferInformedIncubationTests(unittest.TestCase):
    @staticmethod
    def _profile(family: str, value: str, *, stabilized: bool = False) -> dict:
        relation = {
            "family": family,
            "value": value,
            "support_ratio": 0.76,
            "weight": 0.70,
            "confidence": 0.84,
            "confirmations": 2 if stabilized else 1,
            "conflicts": 0,
            "status": "expected",
        }
        if stabilized:
            relation.update(
                {
                    "formed_from_prediction_error": True,
                    "stabilized_from_prediction_error": True,
                    "stabilized_at": "2026-08-21T10:00:00+00:00",
                }
            )
        return {
            "version": 1,
            "anchor_feature": f"{family}_{value}_pattern",
            "source_count": 3,
            "features": [],
            "channels": {"world": 1, "action": 1},
            "relations": [relation],
            "alternatives": {},
            "feedback": {"supported": 2, "refined": 0, "contradicted": 0},
            **(
                {"last_stabilized_at": "2026-08-21T10:00:00+00:00"}
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
        source_trace_ids=(),
    ):
        trace = resident.nervous.perceive(
            "schema",
            f"Persistent pattern: {name}.",
            features=(name, "consolidated_pattern"),
            salience=0.86,
            arousal=0.34,
            metadata={
                "memory_state": "consolidated",
                "prediction_confidence": 0.88 if stabilized else 0.72,
                "prediction_profile": cls._profile(
                    family,
                    value,
                    stabilized=stabilized,
                ),
                "source_trace_ids": list(source_trace_ids),
            },
        )
        trace.strength = 0.90
        trace.salience = 0.86
        resident.nervous._save_trace(trace)
        return trace

    @staticmethod
    def _thought() -> ThoughtFrame:
        return ThoughtFrame(
            sequence=999,
            at=utc_now(),
            focus="test transfer-informed incubation",
            reason="test",
            confidence=0.50,
        )

    @staticmethod
    def _prime_life(resident) -> None:
        resident.life.wake()
        resident.life.pulse()

    def test_product_runtime_uses_transfer_aware_resident(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            self.assertIsInstance(resident, TransferAwareSituatedResidentRuntime)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_two_hop_schema_activation_exposes_transfer_gain(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            body = resident.body.sense()
            source = self._schema(
                resident,
                "source_transfer_anchor",
                "workspace",
                "clean",
                stabilized=True,
            )
            target = self._schema(
                resident,
                "neighbor_body_pattern",
                "system",
                str(body.system).lower(),
            )
            bridge = resident.nervous.perceive(
                "world",
                "shared lived session bridge",
                features=("shared_transfer_session",),
                salience=0.80,
            )
            resident.nervous._strengthen_link(source.trace_id, bridge.trace_id, amount=0.95)
            resident.nervous._strengthen_link(target.trace_id, bridge.trace_id, amount=0.95)

            target_activation = next(
                item
                for item in resident.nervous.activate(
                    "source_transfer_anchor",
                    channels=("schema",),
                    limit=16,
                )
                if item.trace.trace_id == target.trace_id
            )

            self.assertIsInstance(target_activation, RealityAwareActivation)
            self.assertEqual(target_activation.cue_overlap, 0.0)
            self.assertGreaterEqual(target_activation.transfer_gain, 0.04)
            self.assertEqual(
                target_activation.transfer_gain,
                target_activation.associative_gain,
            )
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_transfer_candidate_freezes_until_current_situation_supports_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            self._prime_life(resident)
            body = resident.life.snapshot().body
            self.assertIsNotNone(body)

            lived = [
                resident.nervous.perceive(
                    "world",
                    f"supporting lived trace {index}",
                    features=(f"support_trace_{index}",),
                    salience=0.55,
                )
                for index in range(4)
            ]
            target = self._schema(
                resident,
                "transferred_system_pattern",
                "system",
                str(body.system).lower(),
                source_trace_ids=[item.trace_id for item in lived],
            )
            activation = RealityAwareActivation(
                trace=target,
                activation=0.16,
                cue_overlap=0.0,
                associative_gain=0.16,
                transfer_gain=0.16,
            )
            intention = resident.intend(
                "consider a related runtime situation",
                priority=6,
            )

            with patch.object(resident.nervous, "activate", return_value=[activation]), patch.object(
                resident,
                "_transfer_context_support",
                return_value=(False, "current Situation does not yet support system"),
            ):
                resident._incubate_primary_intention(self._thought())
                seeded = resident.will.get(intention.intention_id)
                self.assertIsNotNone(seeded)
                self.assertEqual(seeded.candidate_repetitions, 1)
                self.assertTrue(seeded.candidate_payload.get("transfer_informed"))
                self.assertFalse(seeded.candidate_payload.get("transfer_context_supported"))

                resident._incubate_primary_intention(self._thought())
                frozen = resident.will.get(intention.intention_id)
                self.assertEqual(frozen.candidate_repetitions, 1)

            with patch.object(resident.nervous, "activate", return_value=[activation]), patch.object(
                resident,
                "_transfer_context_support",
                return_value=(True, f"body:system:{str(body.system).lower()}"),
            ):
                resident._incubate_primary_intention(self._thought())
                supported = resident.will.get(intention.intention_id)
                self.assertEqual(supported.candidate_repetitions, 2)
                self.assertTrue(supported.candidate_payload.get("transfer_context_supported"))
                self.assertGreater(len(supported.candidate_support), len(seeded.candidate_support))

            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_supported_transfer_can_mature_but_never_in_one_pulse(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            self._prime_life(resident)
            body = resident.life.snapshot().body
            lived = [
                resident.nervous.perceive(
                    "action",
                    f"maturity support {index}",
                    features=(f"maturity_support_{index}",),
                    salience=0.60,
                )
                for index in range(4)
            ]
            target = self._schema(
                resident,
                "transfer_maturity_pattern",
                "system",
                str(body.system).lower(),
                source_trace_ids=[item.trace_id for item in lived],
            )
            activation = RealityAwareActivation(
                trace=target,
                activation=0.28,
                cue_overlap=0.0,
                associative_gain=0.28,
                transfer_gain=0.28,
            )
            intention = resident.intend("reuse related lived structure", priority=6)
            basis = f"body:system:{str(body.system).lower()}"

            with patch.object(resident.nervous, "activate", return_value=[activation]), patch.object(
                resident,
                "_transfer_context_support",
                return_value=(True, basis),
            ):
                first_thought = self._thought()
                resident._incubate_primary_intention(first_thought)
                first = resident.will.get(intention.intention_id)
                self.assertEqual(first.candidate_repetitions, 1)
                self.assertNotEqual(first_thought.action_kind, "incubate")

                matured_thought = None
                for _ in range(5):
                    thought = self._thought()
                    resident._incubate_primary_intention(thought)
                    if thought.action_kind == "incubate":
                        matured_thought = thought
                        break

                matured = resident.will.get(intention.intention_id)
                self.assertGreaterEqual(matured.candidate_repetitions, 2)
                self.assertGreaterEqual(matured.candidate_maturity, 0.72)
                self.assertIsNotNone(matured_thought)
                self.assertIn("cross-context recall plus current Situation support", matured_thought.reason)

            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
