from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.models import ExecutionPath, ResidentRunResult
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class TransferOutcomePlasticityTests(unittest.TestCase):
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
            "feedback": {"supported": 1, "refined": 0, "contradicted": 0},
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
            salience=0.84,
            arousal=0.34,
            metadata={
                "memory_state": "consolidated",
                "prediction_confidence": 0.88 if stabilized else 0.72,
                "prediction_profile": cls._profile(
                    family,
                    value,
                    stabilized=stabilized,
                ),
            },
        )
        trace.strength = 0.88
        trace.salience = 0.84
        resident.nervous._save_trace(trace)
        return trace

    @classmethod
    def _seed_path(cls, resident):
        source = cls._schema(
            resident,
            "learned_clean_workspace",
            "workspace",
            "clean",
            stabilized=True,
        )
        target = cls._schema(
            resident,
            "related_linux_runtime",
            "system",
            "linux",
        )
        bridge = resident.nervous.perceive(
            "world",
            "one lived session connected the clean workspace to this runtime context",
            features=("shared_transfer_session",),
            salience=0.78,
        )
        resident.nervous._strengthen_link(source.trace_id, bridge.trace_id, amount=0.55)
        resident.nervous._strengthen_link(target.trace_id, bridge.trace_id, amount=0.55)
        return source, target, bridge

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
    def _bind_feedback(resident, target, event_id: str, *, support=(), contradictions=()):
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
            "at": "2026-08-21T10:30:00+00:00",
            "reconsolidation_key": f"feedback-{event_id}",
            "event_id": event_id,
        }
        resident.nervous._save_trace(current)

    @staticmethod
    def _complete(resident, event, *, success: bool = True):
        claimed = resident.store.claim_event(event.event_id)
        if claimed is None:
            raise AssertionError("test event was not claimable")
        result = ResidentRunResult(
            event=claimed,
            execution_path=ExecutionPath.INVESTIGATION,
            success=success,
            response="probe completed" if success else "",
            reason="" if success else "probe execution failed",
            model_invocations=0,
        )
        return resident._complete_result(claimed, result)

    def test_relation_support_reinforces_exact_transfer_path_without_rewriting_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            source, target, bridge = self._seed_path(resident)
            source_profile_before = copy.deepcopy(source.metadata["prediction_profile"])
            source_edge_before = resident.nervous.link_strength(
                source.trace_id,
                bridge.trace_id,
            )
            target_edge_before = resident.nervous.link_strength(
                target.trace_id,
                bridge.trace_id,
            )
            event = resident.enqueue(
                "test the transferred runtime expectation",
                kind="intention_probe",
                payload=self._payload(source, target, bridge, gain=0.24),
            )
            self._bind_feedback(
                resident,
                target,
                event.event_id,
                support=("system:linux",),
            )

            completed = self._complete(resident, event, success=True)

            self.assertTrue(completed.success)
            source_edge_after = resident.nervous.link_strength(
                source.trace_id,
                bridge.trace_id,
            )
            target_edge_after = resident.nervous.link_strength(
                target.trace_id,
                bridge.trace_id,
            )
            self.assertGreater(source_edge_after, source_edge_before)
            self.assertGreater(target_edge_after, target_edge_before)
            learned_source = resident.nervous._get_trace(source.trace_id)
            self.assertEqual(
                learned_source.metadata["prediction_profile"],
                source_profile_before,
            )
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            self.assertAlmostEqual(
                restored.nervous.link_strength(source.trace_id, bridge.trace_id),
                source_edge_after,
            )
            self.assertAlmostEqual(
                restored.nervous.link_strength(target.trace_id, bridge.trace_id),
                target_edge_after,
            )
            restored.store.close()

    def test_relation_contradiction_weakens_only_target_side_even_when_probe_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            source, target, bridge = self._seed_path(resident)
            source_profile_before = copy.deepcopy(source.metadata["prediction_profile"])
            source_edge_before = resident.nervous.link_strength(
                source.trace_id,
                bridge.trace_id,
            )
            target_edge_before = resident.nervous.link_strength(
                target.trace_id,
                bridge.trace_id,
            )
            event = resident.enqueue(
                "observe B even if the transferred expectation is wrong",
                kind="intention_probe",
                payload=self._payload(source, target, bridge, gain=0.26),
            )
            self._bind_feedback(
                resident,
                target,
                event.event_id,
                contradictions=("system:linux->windows",),
            )

            completed = self._complete(resident, event, success=True)

            self.assertTrue(completed.success)
            self.assertAlmostEqual(
                resident.nervous.link_strength(source.trace_id, bridge.trace_id),
                source_edge_before,
            )
            self.assertLess(
                resident.nervous.link_strength(target.trace_id, bridge.trace_id),
                target_edge_before,
            )
            learned_source = resident.nervous._get_trace(source.trace_id)
            self.assertEqual(
                learned_source.metadata["prediction_profile"],
                source_profile_before,
            )
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_execution_failure_without_relation_feedback_does_not_punish_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            source, target, bridge = self._seed_path(resident)
            source_edge_before = resident.nervous.link_strength(
                source.trace_id,
                bridge.trace_id,
            )
            target_edge_before = resident.nervous.link_strength(
                target.trace_id,
                bridge.trace_id,
            )
            event = resident.enqueue(
                "an execution failure is not evidence that transfer was false",
                kind="intention_probe",
                payload=self._payload(source, target, bridge, gain=0.30),
            )

            completed = self._complete(resident, event, success=False)

            self.assertFalse(completed.success)
            self.assertAlmostEqual(
                resident.nervous.link_strength(source.trace_id, bridge.trace_id),
                source_edge_before,
            )
            self.assertAlmostEqual(
                resident.nervous.link_strength(target.trace_id, bridge.trace_id),
                target_edge_before,
            )
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_feedback_for_another_relation_does_not_reshape_this_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            source, target, bridge = self._seed_path(resident)
            source_edge_before = resident.nervous.link_strength(
                source.trace_id,
                bridge.trace_id,
            )
            target_edge_before = resident.nervous.link_strength(
                target.trace_id,
                bridge.trace_id,
            )
            event = resident.enqueue(
                "feedback about another relation must stay local",
                kind="intention_probe",
                payload=self._payload(source, target, bridge, gain=0.22),
            )
            self._bind_feedback(
                resident,
                target,
                event.event_id,
                support=("architecture:x86_64",),
            )

            self._complete(resident, event, success=True)

            self.assertAlmostEqual(
                resident.nervous.link_strength(source.trace_id, bridge.trace_id),
                source_edge_before,
            )
            self.assertAlmostEqual(
                resident.nervous.link_strength(target.trace_id, bridge.trace_id),
                target_edge_before,
            )
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
