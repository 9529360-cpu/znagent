from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from agent.kernel.integrated_transfer import IntegratedTransferActivation
from agent.kernel.life import ThoughtFrame
from agent.kernel.models import ExecutionPath, ResidentRunResult, utc_now
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack
from agent.kernel.schema_structure import SchemaStructurePlasticity


class IntegratedTransferEvidenceTests(unittest.TestCase):
    @staticmethod
    def _profile(family: str, value: str, *, stabilized: bool = False) -> dict:
        relation = {
            "family": family,
            "value": value,
            "support_ratio": 0.80,
            "weight": 0.74,
            "confidence": 0.88,
            "confirmations": 3 if stabilized else 1,
            "conflicts": 0,
            "status": "expected",
        }
        if stabilized:
            relation.update(
                {
                    "formed_from_prediction_error": True,
                    "stabilized_from_prediction_error": True,
                    "stabilized_at": "2026-08-21T13:00:00+00:00",
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
                {"last_stabilized_at": "2026-08-21T13:00:00+00:00"}
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
                "prediction_confidence": 0.90 if stabilized else 0.76,
                "prediction_profile": cls._profile(
                    family,
                    value,
                    stabilized=stabilized,
                ),
                "source_trace_ids": list(source_trace_ids),
            },
        )
        trace.strength = 0.91
        trace.salience = 0.86
        resident.nervous._save_trace(trace)
        return trace

    @staticmethod
    def _bridge(resident, name: str):
        return resident.nervous.perceive(
            "world",
            f"lived context bridge {name}",
            features=(f"bridge_{name}",),
            salience=0.74,
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

    @staticmethod
    def _thought() -> ThoughtFrame:
        return ThoughtFrame(
            sequence=1200,
            at=utc_now(),
            focus="integrate transferred lived evidence",
            reason="test",
            confidence=0.50,
        )

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

    def test_compatible_sources_corroborate_target_instead_of_one_path_monopoly(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            source_a = self._schema(
                resident,
                "amber_source_anchor",
                "workspace",
                "clean",
                stabilized=True,
            )
            source_b = self._schema(
                resident,
                "beryl_source_anchor",
                "branch",
                "dev",
                stabilized=True,
            )
            target = self._schema(
                resident,
                "shared_future_context",
                "system",
                "linux",
            )
            bridge_a = self._bridge(resident, "amber")
            bridge_b = self._bridge(resident, "beryl")
            self._set_exact_links(
                resident,
                (
                    (source_a.trace_id, bridge_a.trace_id),
                    (target.trace_id, bridge_a.trace_id),
                    (source_b.trace_id, bridge_b.trace_id),
                    (target.trace_id, bridge_b.trace_id),
                ),
            )

            target_activation = next(
                item
                for item in resident.nervous.activate(
                    "amber_source_anchor beryl_source_anchor",
                    channels=("schema",),
                    limit=16,
                )
                if item.trace.trace_id == target.trace_id
            )

            self.assertIsInstance(target_activation, IntegratedTransferActivation)
            contributors = target_activation.transfer_contributors
            self.assertEqual(len(contributors), 2)
            self.assertEqual(target_activation.transfer_conflict_count, 0)
            self.assertAlmostEqual(target_activation.transfer_consensus, 1.0)
            self.assertGreater(
                target_activation.transfer_gain,
                max(float(item["gain"]) for item in contributors),
            )
            self.assertEqual(
                {str(item["source_trace_id"]) for item in contributors},
                {source_a.trace_id, source_b.trace_id},
            )
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_conflicting_sources_create_pressure_and_do_not_join_same_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            source_clean = self._schema(
                resident,
                "clean_source_anchor",
                "workspace",
                "clean",
                stabilized=True,
            )
            source_dirty = self._schema(
                resident,
                "dirty_source_anchor",
                "workspace",
                "dirty",
                stabilized=True,
            )
            target = self._schema(
                resident,
                "conflicted_future_context",
                "system",
                "linux",
            )
            bridge_clean = self._bridge(resident, "clean")
            bridge_dirty = self._bridge(resident, "dirty")
            self._set_exact_links(
                resident,
                (
                    (source_clean.trace_id, bridge_clean.trace_id),
                    (target.trace_id, bridge_clean.trace_id),
                    (source_dirty.trace_id, bridge_dirty.trace_id),
                    (target.trace_id, bridge_dirty.trace_id),
                ),
            )

            target_activation = next(
                item
                for item in resident.nervous.activate(
                    "clean_source_anchor dirty_source_anchor",
                    channels=("schema",),
                    limit=16,
                )
                if item.trace.trace_id == target.trace_id
            )

            self.assertIsInstance(target_activation, IntegratedTransferActivation)
            self.assertEqual(len(target_activation.transfer_contributors), 1)
            self.assertEqual(target_activation.transfer_conflict_count, 1)
            self.assertLess(target_activation.transfer_consensus, 1.0)
            self.assertLess(
                target_activation.transfer_gain,
                float(target_activation.transfer_contributors[0]["gain"]),
            )
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_will_carries_bundle_into_event_and_outcome_shapes_every_contributor(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            resident.life.wake()
            resident.life.pulse()
            body = resident.life.snapshot().body
            self.assertIsNotNone(body)
            system = str(body.system).lower()

            source_a = self._schema(
                resident,
                "will_source_alpha",
                "workspace",
                "clean",
                stabilized=True,
            )
            source_b = self._schema(
                resident,
                "will_source_beta",
                "branch",
                "dev",
                stabilized=True,
            )
            target = self._schema(
                resident,
                "will_target_runtime",
                "system",
                system,
            )
            bridge_a = self._bridge(resident, "will_alpha")
            bridge_b = self._bridge(resident, "will_beta")
            self._set_exact_links(
                resident,
                (
                    (source_a.trace_id, bridge_a.trace_id),
                    (target.trace_id, bridge_a.trace_id),
                    (source_b.trace_id, bridge_b.trace_id),
                    (target.trace_id, bridge_b.trace_id),
                ),
            )
            contributors = (
                {
                    "source_trace_id": source_a.trace_id,
                    "bridge_trace_id": bridge_a.trace_id,
                    "gain": 0.17,
                    "tendency": 1.0,
                    "feedback_count": 0,
                },
                {
                    "source_trace_id": source_b.trace_id,
                    "bridge_trace_id": bridge_b.trace_id,
                    "gain": 0.16,
                    "tendency": 1.0,
                    "feedback_count": 0,
                },
            )
            activation = IntegratedTransferActivation(
                trace=target,
                activation=0.31,
                cue_overlap=0.0,
                associative_gain=0.31,
                transfer_gain=0.31,
                transfer_source_trace_id=source_a.trace_id,
                transfer_bridge_trace_id=bridge_a.trace_id,
                transfer_tendency=1.0,
                transfer_feedback_count=0,
                transfer_contributors=contributors,
                transfer_consensus=1.0,
                transfer_conflict_count=0,
            )
            intention = resident.intend(
                "reuse corroborated runtime structure",
                priority=7,
            )

            matured = False
            with patch.object(resident.nervous, "activate", return_value=[activation]):
                for _ in range(6):
                    thought = self._thought()
                    resident._incubate_primary_intention(thought)
                    current = resident.will.get(intention.intention_id)
                    if current and current.candidate_repetitions >= 2:
                        payload = current.candidate_payload
                        self.assertEqual(len(payload.get("transfer_contributors") or ()), 2)
                        self.assertEqual(payload.get("transfer_conflict_count"), 0)
                    if thought.action_kind == "incubate":
                        matured = True
                        break
            self.assertTrue(matured)

            promoted = resident.will.promote_candidate(intention.intention_id)
            self.assertIsNotNone(promoted.next_task)
            self.assertEqual(len(promoted.next_payload.get("transfer_contributors") or ()), 2)
            resident._advance_intention(intention.intention_id)
            engaged = resident.will.get(intention.intention_id)
            self.assertIsNotNone(engaged.related_event_id)
            event = resident.store.get_event(engaged.related_event_id)
            self.assertEqual(len(event.payload.get("transfer_contributors") or ()), 2)

            source_a_edge = resident.nervous.link_strength(
                source_a.trace_id, bridge_a.trace_id
            )
            source_b_edge = resident.nervous.link_strength(
                source_b.trace_id, bridge_b.trace_id
            )
            target_a_edge = resident.nervous.link_strength(
                target.trace_id, bridge_a.trace_id
            )
            target_b_edge = resident.nervous.link_strength(
                target.trace_id, bridge_b.trace_id
            )
            self._bind_feedback(
                resident,
                target,
                event.event_id,
                support=(f"system:{system}",),
            )
            completed = self._complete(resident, event)

            self.assertTrue(completed.success)
            self.assertGreater(
                resident.nervous.link_strength(source_a.trace_id, bridge_a.trace_id),
                source_a_edge,
            )
            self.assertGreater(
                resident.nervous.link_strength(source_b.trace_id, bridge_b.trace_id),
                source_b_edge,
            )
            self.assertGreater(
                resident.nervous.link_strength(target.trace_id, bridge_a.trace_id),
                target_a_edge,
            )
            self.assertGreater(
                resident.nervous.link_strength(target.trace_id, bridge_b.trace_id),
                target_b_edge,
            )
            tendency_a, count_a = resident.nervous.transfer_tendency(
                source_a.trace_id, bridge_a.trace_id, target.trace_id
            )
            tendency_b, count_b = resident.nervous.transfer_tendency(
                source_b.trace_id, bridge_b.trace_id, target.trace_id
            )
            self.assertEqual((count_a, count_b), (1, 1))
            self.assertGreater(tendency_a, 1.0)
            self.assertGreater(tendency_b, 1.0)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_transfer_history_survives_source_schema_merge_and_coalesces(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            lived = [
                resident.nervous.perceive(
                    "world",
                    f"shared source evidence {index}",
                    features=(f"merge_support_{index}",),
                    salience=0.58,
                )
                for index in range(3)
            ]
            source_ids = [item.trace_id for item in lived]
            absorbed = self._schema(
                resident,
                "older_equivalent_source",
                "workspace",
                "clean",
                stabilized=True,
                source_trace_ids=source_ids,
            )
            canonical = self._schema(
                resident,
                "surviving_equivalent_source",
                "workspace",
                "clean",
                stabilized=True,
                source_trace_ids=source_ids,
            )
            target = self._schema(
                resident,
                "merge_history_target",
                "system",
                "linux",
            )
            bridge = self._bridge(resident, "merge_history")
            self._set_exact_links(
                resident,
                (
                    (absorbed.trace_id, bridge.trace_id),
                    (target.trace_id, bridge.trace_id),
                ),
            )
            for _ in range(4):
                resident.nervous.record_transfer_feedback(
                    absorbed.trace_id,
                    bridge.trace_id,
                    target.trace_id,
                    status="supported",
                )

            merges = SchemaStructurePlasticity(resident.nervous).compact(
                seed_ids=[canonical.trace_id],
            )
            matching = [
                item
                for item in merges
                if item.absorbed_schema_id == absorbed.trace_id
                and item.canonical_schema_id == canonical.trace_id
            ]
            self.assertTrue(matching)
            resolved = SchemaStructurePlasticity(resident.nervous).resolve_schema(
                absorbed.trace_id
            )
            self.assertEqual(resolved.trace_id, canonical.trace_id)

            tendency, count = resident.nervous.transfer_tendency(
                canonical.trace_id,
                bridge.trace_id,
                target.trace_id,
            )
            self.assertEqual(count, 4)
            self.assertGreater(tendency, 1.0)
            self.assertGreater(
                resident.nervous.link_strength(canonical.trace_id, bridge.trace_id),
                0.0,
            )

            resident.nervous.record_transfer_feedback(
                canonical.trace_id,
                bridge.trace_id,
                target.trace_id,
                status="supported",
            )
            bridge_now = resident.nervous._get_trace(bridge.trace_id)
            history = bridge_now.metadata.get("reality_transfer_history")
            matching_rows = [
                row
                for row in history
                if row.get("source_trace_id") == canonical.trace_id
                and row.get("target_trace_id") == target.trace_id
            ]
            self.assertEqual(len(matching_rows), 1)
            self.assertEqual(matching_rows[0].get("supported"), 5)
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored_tendency, restored_count = restored.nervous.transfer_tendency(
                canonical.trace_id,
                bridge.trace_id,
                target.trace_id,
            )
            self.assertEqual(restored_count, 5)
            self.assertGreater(restored_tendency, 1.0)
            self.assertEqual(restored.store.get_runtime_metrics().model_invocations, 0)
            restored.store.close()


if __name__ == "__main__":
    unittest.main()
