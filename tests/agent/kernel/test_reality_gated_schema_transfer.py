from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class RealityGatedSchemaTransferTests(unittest.TestCase):
    @staticmethod
    def _profile(
        family: str,
        value: str,
        *,
        stabilized: bool = False,
        confidence: float = 0.82,
        support: float = 0.72,
    ) -> dict:
        relation = {
            "family": family,
            "value": value,
            "support_ratio": support,
            "weight": 0.68,
            "confidence": confidence,
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
    ):
        trace = resident.nervous.perceive(
            "schema",
            f"Persistent pattern: {name}.",
            features=(name, "consolidated_pattern"),
            salience=0.86,
            arousal=0.35,
            metadata={
                "memory_state": "consolidated",
                "prediction_confidence": 0.88 if stabilized else 0.70,
                "prediction_profile": cls._profile(
                    family,
                    value,
                    stabilized=stabilized,
                ),
            },
        )
        trace.strength = 0.90
        trace.salience = 0.86
        resident.nervous._save_trace(trace)
        return trace

    @staticmethod
    def _activation(resident, cue: str, trace_id: str):
        return next(
            (
                item
                for item in resident.nervous.activate(
                    cue,
                    channels=("schema",),
                    limit=16,
                )
                if item.trace.trace_id == trace_id
            ),
            None,
        )

    def test_stabilized_schema_transfers_activation_through_shared_lived_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            source = self._schema(
                resident,
                "clean_workspace_anchor",
                "workspace",
                "clean",
                stabilized=True,
            )
            target = self._schema(
                resident,
                "runtime_architecture_pattern",
                "architecture",
                "x86_64",
            )
            bridge = resident.nervous.perceive(
                "world",
                "the same repository session connected workspace state and runtime body",
                features=("shared_session_evidence",),
                salience=0.75,
            )
            resident.nervous._strengthen_link(source.trace_id, bridge.trace_id, amount=0.95)
            resident.nervous._strengthen_link(target.trace_id, bridge.trace_id, amount=0.95)

            target_activation = self._activation(
                resident,
                "clean_workspace_anchor",
                target.trace_id,
            )

            self.assertIsNotNone(target_activation)
            self.assertEqual(target_activation.cue_overlap, 0.0)
            self.assertGreaterEqual(target_activation.associative_gain, 0.04)
            self.assertGreater(target_activation.activation, 0.04)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_transfer_is_blocked_by_current_relation_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            source = self._schema(
                resident,
                "clean_workspace_anchor",
                "workspace",
                "clean",
                stabilized=True,
            )
            conflicting = self._schema(
                resident,
                "dirty_neighbor_pattern",
                "workspace",
                "dirty",
            )
            bridge = resident.nervous.perceive(
                "action",
                "one lived action linked both workspace schemas",
                features=("shared_workspace_evidence",),
                salience=0.82,
            )
            resident.nervous._strengthen_link(source.trace_id, bridge.trace_id, amount=0.95)
            resident.nervous._strengthen_link(conflicting.trace_id, bridge.trace_id, amount=0.95)

            blocked = self._activation(
                resident,
                "clean_workspace_anchor",
                conflicting.trace_id,
            )

            self.assertIsNone(blocked)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_unstabilized_schema_does_not_gain_cross_context_transfer_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            ordinary = self._schema(
                resident,
                "ordinary_workspace_anchor",
                "workspace",
                "clean",
                stabilized=False,
            )
            target = self._schema(
                resident,
                "neighbor_body_pattern",
                "system",
                "linux",
            )
            bridge = resident.nervous.perceive(
                "world",
                "shared but not yet reality-corrected lived evidence",
                features=("ordinary_shared_evidence",),
                salience=0.80,
            )
            resident.nervous._strengthen_link(ordinary.trace_id, bridge.trace_id, amount=0.95)
            resident.nervous._strengthen_link(target.trace_id, bridge.trace_id, amount=0.95)

            transferred = self._activation(
                resident,
                "ordinary_workspace_anchor",
                target.trace_id,
            )

            self.assertIsNone(transferred)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_reality_gated_transfer_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            source = self._schema(
                resident,
                "clean_workspace_anchor",
                "workspace",
                "clean",
                stabilized=True,
            )
            target = self._schema(
                resident,
                "restart_neighbor_pattern",
                "presence",
                "exists",
            )
            bridge = resident.nervous.perceive(
                "world",
                "durable shared evidence between corrected and neighboring structure",
                features=("durable_shared_evidence",),
                salience=0.82,
            )
            resident.nervous._strengthen_link(source.trace_id, bridge.trace_id, amount=0.95)
            resident.nervous._strengthen_link(target.trace_id, bridge.trace_id, amount=0.95)
            target_id = target.trace_id
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            activation = self._activation(
                restored,
                "clean_workspace_anchor",
                target_id,
            )

            self.assertIsNotNone(activation)
            self.assertEqual(activation.cue_overlap, 0.0)
            self.assertGreaterEqual(activation.associative_gain, 0.04)
            self.assertEqual(restored.store.get_runtime_metrics().model_invocations, 0)
            restored.store.close()


if __name__ == "__main__":
    unittest.main()
