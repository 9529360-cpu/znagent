from __future__ import annotations

import copy
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from agent.kernel.models import ExecutionPath, ResidentRunResult, utc_now
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class ContextualTransferTendencyTests(unittest.TestCase):
    @staticmethod
    def _profile(family: str, value: str, *, stabilized: bool = False) -> dict:
        relation = {
            "family": family,
            "value": value,
            "support_ratio": 0.78,
            "weight": 0.72,
            "confidence": 0.86,
            "confirmations": 3 if stabilized else 1,
            "conflicts": 0,
            "status": "expected",
        }
        if stabilized:
            relation.update(
                {
                    "formed_from_prediction_error": True,
                    "stabilized_from_prediction_error": True,
                    "stabilized_at": "2026-08-21T12:00:00+00:00",
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
                {"last_stabilized_at": "2026-08-21T12:00:00+00:00"}
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
            salience=0.84,
            arousal=0.34,
            metadata={
                "memory_state": "consolidated",
                "prediction_confidence": 0.90 if stabilized else 0.74,
                "prediction_profile": cls._profile(
                    family,
                    value,
                    stabilized=stabilized,
                ),
            },
        )
        trace.strength = 0.90
        trace.salience = 0.84
        resident.nervous._save_trace(trace)
        return trace

    @staticmethod
    def _bridge(resident, name: str):
        return resident.nervous.perceive(
            "world",
            f"lived bridge {name}",
            features=(f"bridge_{name}",),
            salience=0.72,
            arousal=0.28,
        )

    @staticmethod
    def _set_exact_links(resident, pairs, *, strength: float = 0.78) -> None:
        with closing(resident.nervous._connect()) as conn:
            conn.execute("DELETE FROM neural_links")
            for left_id, right_id in pairs:
                left, right = sorted((left_id, right_id))
                conn.execute(
                    "INSERT INTO neural_links"
                    "(left_id,right_id,strength,repetitions,updated_at) VALUES(?,?,?,?,?)",
                    (left, right, strength, 1, utc_now()),
                )
            conn.commit()

    @classmethod
    def _three_context_network(cls, resident):
        source = cls._schema(
            resident,
            "zirconanchor corrected source",
            "workspace",
            "clean",
            stabilized=True,
        )
        target_b = cls._schema(resident, "context beta", "system", "linux")
        target_c = cls._schema(resident, "context cobalt", "system", "linux")
        target_d = cls._schema(resident, "context delta", "system", "linux")
        bridge_b = cls._bridge(resident, "beta")
        bridge_c = cls._bridge(resident, "cobalt")
        bridge_d = cls._bridge(resident, "delta")
        cls._set_exact_links(
            resident,
            (
                (source.trace_id, bridge_b.trace_id),
                (target_b.trace_id, bridge_b.trace_id),
                (source.trace_id, bridge_c.trace_id),
                (target_c.trace_id, bridge_c.trace_id),
                (source.trace_id, bridge_d.trace_id),
                (target_d.trace_id, bridge_d.trace_id),
            ),
        )
        return source, (
            (target_b, bridge_b),
            (target_c, bridge_c),
            (target_d, bridge_d),
        )

    @staticmethod
    def _payload(source, target, bridge, *, gain: float = 0.20) -> dict:
        return {
            "model_policy": "never",
            "incubated_event_kind": "intention_probe",
            "schema_trace_id": target.trace_id,
            "schema_expectation": {
                "family": "system",
                "value": "linux",
                "status": "expected",
                "recheck": False,
                "attempt": 1,
            },
            "transfer_informed": True,
            "transfer_gain": gain,
            "transfer_context_supported": True,
            "transfer_context_basis": "body:system:linux",
            "transfer_source_schema_id": source.trace_id,
            "transfer_bridge_trace_id": bridge.trace_id,
        }

    @staticmethod
    def _bind_feedback(
        resident,
        target,
        event_id: str,
        *,
        support=(),
        contradictions=(),
    ) -> None:
        current = resident.nervous._get_trace(target.trace_id)
        current.metadata["last_prediction_feedback"] = {
            "schema_trace_id": target.trace_id,
            "status": (
                "supported"
                if support and not contradictions
                else "contradicted"
                if contradictions and not support
                else "refined"
            ),
            "prediction_error": 0.0 if support and not contradictions else 1.0,
            "support": list(support),
            "contradictions": list(contradictions),
            "untested": [],
            "observation_channels": ["body"],
            "at": utc_now(),
            "reconsolidation_key": f"feedback-{event_id}",
            "event_id": event_id,
        }
        resident.nervous._save_trace(current)

    @staticmethod
    def _complete(resident, event):
        claimed = resident.store.claim_event(event.event_id)
        if claimed is None:
            raise AssertionError("test event was not claimable")
        return resident._complete_result(
            claimed,
            ResidentRunResult(
                event=claimed,
                execution_path=ExecutionPath.INVESTIGATION,
                success=True,
                response="probe completed",
                model_invocations=0,
            ),
        )

    def test_repeated_bridge_feedback_biases_equal_transfer_paths_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            source, contexts = self._three_context_network(resident)
            (target_b, bridge_b), (target_c, bridge_c), (target_d, bridge_d) = contexts

            for _ in range(4):
                resident.nervous.record_transfer_feedback(
                    source.trace_id,
                    bridge_b.trace_id,
                    target_b.trace_id,
                    status="supported",
                )
                resident.nervous.record_transfer_feedback(
                    source.trace_id,
                    bridge_c.trace_id,
                    target_c.trace_id,
                    status="contradicted",
                )

            activations = resident.nervous.activate(
                "zirconanchor",
                channels=("schema",),
                limit=16,
            )
            by_id = {item.trace.trace_id: item for item in activations}
            beta = by_id[target_b.trace_id]
            cobalt = by_id[target_c.trace_id]
            delta = by_id[target_d.trace_id]

            self.assertGreater(beta.transfer_gain, delta.transfer_gain)
            self.assertGreater(delta.transfer_gain, cobalt.transfer_gain)
            self.assertGreater(beta.transfer_tendency, 1.0)
            self.assertEqual(delta.transfer_tendency, 1.0)
            self.assertLess(cobalt.transfer_tendency, 1.0)
            self.assertEqual(beta.transfer_feedback_count, 4)
            self.assertEqual(cobalt.transfer_feedback_count, 4)
            self.assertEqual(delta.transfer_feedback_count, 0)
            self.assertEqual(beta.transfer_bridge_trace_id, bridge_b.trace_id)
            self.assertEqual(cobalt.transfer_bridge_trace_id, bridge_c.trace_id)
            self.assertEqual(delta.transfer_bridge_trace_id, bridge_d.trace_id)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            beta_tendency, beta_count = restored.nervous.transfer_tendency(
                source.trace_id,
                bridge_b.trace_id,
                target_b.trace_id,
            )
            cobalt_tendency, cobalt_count = restored.nervous.transfer_tendency(
                source.trace_id,
                bridge_c.trace_id,
                target_c.trace_id,
            )
            delta_tendency, delta_count = restored.nervous.transfer_tendency(
                source.trace_id,
                bridge_d.trace_id,
                target_d.trace_id,
            )
            self.assertGreater(beta_tendency, delta_tendency)
            self.assertGreater(delta_tendency, cobalt_tendency)
            self.assertEqual((beta_count, cobalt_count, delta_count), (4, 4, 0))
            self.assertEqual(restored.store.get_runtime_metrics().model_invocations, 0)
            restored.store.close()

    def test_one_feedback_only_nudges_transfer_and_repetition_creates_tendency(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            source, contexts = self._three_context_network(resident)
            target, bridge = contexts[0]

            resident.nervous.record_transfer_feedback(
                source.trace_id,
                bridge.trace_id,
                target.trace_id,
                status="supported",
            )
            first_tendency, first_count = resident.nervous.transfer_tendency(
                source.trace_id,
                bridge.trace_id,
                target.trace_id,
            )
            self.assertEqual(first_count, 1)
            self.assertGreater(first_tendency, 1.0)
            self.assertLess(first_tendency, 1.04)

            for _ in range(3):
                resident.nervous.record_transfer_feedback(
                    source.trace_id,
                    bridge.trace_id,
                    target.trace_id,
                    status="supported",
                )
            repeated_tendency, repeated_count = resident.nervous.transfer_tendency(
                source.trace_id,
                bridge.trace_id,
                target.trace_id,
            )
            self.assertEqual(repeated_count, 4)
            self.assertGreater(repeated_tendency, 1.15)
            self.assertGreater(repeated_tendency, first_tendency)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_relation_outcome_writes_bridge_history_without_rewriting_source_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            source, contexts = self._three_context_network(resident)
            target, bridge = contexts[0]
            source_profile_before = copy.deepcopy(source.metadata["prediction_profile"])
            event = resident.enqueue(
                "test one transferred context against current reality",
                kind="intention_probe",
                payload=self._payload(source, target, bridge, gain=0.24),
            )
            self._bind_feedback(
                resident,
                target,
                event.event_id,
                support=("system:linux",),
            )

            completed = self._complete(resident, event)

            self.assertTrue(completed.success)
            tendency, count = resident.nervous.transfer_tendency(
                source.trace_id,
                bridge.trace_id,
                target.trace_id,
            )
            self.assertEqual(count, 1)
            self.assertGreater(tendency, 1.0)
            learned_source = resident.nervous._get_trace(source.trace_id)
            self.assertEqual(
                learned_source.metadata["prediction_profile"],
                source_profile_before,
            )
            learned_bridge = resident.nervous._get_trace(bridge.trace_id)
            history = learned_bridge.metadata.get("reality_transfer_history")
            self.assertIsInstance(history, list)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0].get("supported"), 1)
            self.assertEqual(history[0].get("contradicted"), 0)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
