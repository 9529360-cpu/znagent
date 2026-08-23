from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from agent.kernel.action import (
    NativeActionIntent,
    derive_native_action_intent,
    derive_native_action_intents,
)
from agent.kernel.models import AgentEvent
from agent.kernel.procedural_influence import (
    select_procedurally_influenced_intent,
    strongest_supported_action_influence,
)
from agent.kernel.procedural_resident import ProcedurallyInfluencedResidentRuntime
from agent.kernel.procedural_tendency import CandidateProceduralTendency
from agent.kernel.provider_bridge import build_resident_runtime
from agent.kernel.world_closed_loop import WorldAwareTransferResidentRuntime


class ProceduralInfluenceTests(unittest.TestCase):
    @staticmethod
    def _fingerprint(value) -> str:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _candidate(
        cls,
        *,
        target: str,
        maturity_state: str = "supported",
        reliability: float = 1.0,
        inhibited: bool = False,
    ) -> CandidateProceduralTendency:
        return CandidateProceduralTendency(
            tendency_id="pt-action-influence",
            group_key="group-action-influence",
            action_kind="write_text",
            domain_fingerprints=(cls._fingerprint("filesystem"),),
            expected_kind="text_equals",
            expected_exit_code=None,
            effect_class="potential_side_effect",
            failure_class=None,
            support_count=3,
            contradiction_count=0,
            distinct_event_count=3,
            native_support_count=3,
            assisted_support_count=0,
            reliability=reliability,
            maturity_state=maturity_state,
            inhibited=inhibited,
            applicability={
                "stable_target_fingerprint": cls._fingerprint(target),
                "stable_workdir_fingerprint": None,
                "stable_verification_signature_hash": None,
                "target_variants": 1,
                "workdir_variants": 0,
                "verification_signature_variants": 0,
                "goal_variants": 3,
                "situation_variants": 3,
                "action_signature_variants": 3,
            },
            recent_verdicts=("verified", "verified", "verified"),
            supporting_experience_ids=("vx-1", "vx-2", "vx-3"),
            contradicting_experience_ids=(),
            first_seen_at="2026-08-23T10:00:00+00:00",
            last_seen_at="2026-08-23T12:00:00+00:00",
        )

    @staticmethod
    def _choice_event(target: str, content: str) -> AgentEvent:
        return AgentEvent(
            event_id="evt-current-choice-set",
            task="choose one current native route for the stable target",
            payload={
                # Top-level path exists only so current Investigation observes
                # the reality anchor. Action arguments stay inside the current
                # structured choice set and are never supplied by learning.
                "path": target,
                "required_capabilities": ["filesystem"],
                "native_action_options": [
                    {
                        "kind": "command",
                        "args": {
                            "command": "python -c \"print('default command')\"",
                        },
                    },
                    {
                        "kind": "write_text",
                        "args": {
                            "path": target,
                            "content": content,
                            "append": False,
                            "create_parents": True,
                        },
                    },
                ],
            },
        )

    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 48) -> None:
        for _ in range(limit):
            if resident.store.get_working_state().stage == stage:
                return
            result = resident.live_once()
            if result is not None:
                raise AssertionError(
                    f"event reached terminal result before stage {stage}: {result}"
                )
        raise AssertionError(
            f"resident did not reach stage {stage}; current="
            f"{resident.store.get_working_state().stage}"
        )

    @staticmethod
    def _run_to_terminal(resident, limit: int = 64):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach a terminal result")

    def test_native_action_choice_set_preserves_default_order_and_explicit_exclusivity(self):
        target = "/private/current.txt"
        event = self._choice_event(target, "current content")
        facts = {"paths": [{"path": target, "exists": True, "type": "file"}]}

        intents = derive_native_action_intents(event, facts=facts)
        self.assertEqual([item.kind for item in intents], ["command", "write_text"])
        self.assertTrue(all(item.source == "structured_choice" for item in intents))
        self.assertEqual(derive_native_action_intent(event, facts=facts).kind, "command")

        explicit = AgentEvent(
            event_id="evt-explicit",
            task="perform the explicit current movement",
            payload={
                "body_action": {"kind": "write_text", "path": target, "content": "x"},
                "native_action_options": event.payload["native_action_options"],
            },
        )
        explicit_intents = derive_native_action_intents(explicit, facts=facts)
        self.assertEqual(len(explicit_intents), 1)
        self.assertEqual(explicit_intents[0].source, "structured_event")
        self.assertEqual(explicit_intents[0].args["content"], "x")

    def test_ordinary_multi_clause_task_is_not_reinterpreted_as_alternatives(self):
        target = "/private/current.txt"
        event = AgentEvent(
            event_id="evt-sequential-looking-task",
            task="run the current command and ensure the target contains requested content",
            payload={
                "command": "python -c \"print('first obligation')\"",
                "path": target,
                "content": "second obligation",
            },
        )
        facts = {"paths": [{"path": target, "exists": True, "type": "file"}]}

        intents = derive_native_action_intents(event, facts=facts)

        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].kind, "command")

    def test_supported_candidate_can_only_reorder_current_safe_intents(self):
        target = "/private/stable.txt"
        content = "PRIVATE_CURRENT_CONTENT"
        event = self._choice_event(target, content)
        facts = {"paths": [{"path": target, "exists": True, "type": "file"}]}
        candidate = self._candidate(target=target)
        intents = derive_native_action_intents(event, facts=facts)

        selected, influence = select_procedurally_influenced_intent(
            event,
            intents,
            candidates=(candidate,),
            current_domains=("filesystem",),
            facts=facts,
        )

        self.assertIsNotNone(influence)
        self.assertEqual(selected.kind, "write_text")
        self.assertEqual(selected.args["path"], target)
        self.assertEqual(selected.args["content"], content)
        self.assertEqual(influence.tendency_id, candidate.tendency_id)
        serialized = json.dumps(influence.to_dict(), sort_keys=True)
        self.assertNotIn(target, serialized)
        self.assertNotIn(content, serialized)
        self.assertNotIn(event.task, serialized)
        self.assertNotIn("default command", serialized)

    def test_immature_mismatched_revoked_and_unsafe_shapes_have_zero_positive_influence(self):
        target = "/private/stable.txt"
        event = self._choice_event(target, "content")
        facts = {"paths": [{"path": target, "exists": True, "type": "file"}]}
        write_intent = derive_native_action_intents(event, facts=facts)[1]

        immature = self._candidate(target=target, maturity_state="candidate")
        self.assertIsNone(
            strongest_supported_action_influence(
                event,
                write_intent,
                candidates=(immature,),
                current_domains=("filesystem",),
                facts=facts,
            )
        )

        mismatched = self._candidate(target="/private/other.txt")
        self.assertIsNone(
            strongest_supported_action_influence(
                event,
                write_intent,
                candidates=(mismatched,),
                current_domains=("filesystem",),
                facts=facts,
            )
        )

        supported = self._candidate(target=target)
        self.assertIsNone(
            strongest_supported_action_influence(
                event,
                write_intent,
                candidates=(supported,),
                current_domains=("filesystem",),
                facts=facts,
                revoked_tendency_ids=(supported.tendency_id,),
            )
        )

        command_intent = derive_native_action_intents(event, facts=facts)[0]
        self.assertIsNone(
            strongest_supported_action_influence(
                event,
                command_intent,
                candidates=(supported,),
                current_domains=("filesystem",),
                facts=facts,
            )
        )
        append_intent = NativeActionIntent(
            intent_id="act-append",
            event_id=event.event_id,
            kind="write_text",
            args={"path": target, "content": "more", "append": True},
            source="structured_choice",
        )
        self.assertIsNone(
            strongest_supported_action_influence(
                event,
                append_intent,
                candidates=(supported,),
                current_domains=("filesystem",),
                facts=facts,
            )
        )

    def test_active_world_runtime_uses_supported_write_bias_then_revokes_on_prediction_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "stable.txt"
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            self.assertIsInstance(resident, ProcedurallyInfluencedResidentRuntime)
            self.assertIsInstance(resident, WorldAwareTransferResidentRuntime)

            # Three distinct independently verified events are required before
            # L2 reaches the action-eligible `supported` maturity state.
            for index in range(3):
                event = resident.enqueue(
                    f"ensure stable target contains practice state {index}",
                    payload={
                        "path": str(target),
                        "content": f"practice-{index}",
                        "required_capabilities": ["filesystem"],
                        "model_policy": "never",
                    },
                )
                result = self._run_to_terminal(resident)
                self.assertTrue(result.success)
                self.assertEqual(len(resident.verified_experiences.for_event(event.event_id)), 1)

            candidates = resident.verified_experiences.candidate_tendencies()
            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            self.assertEqual(candidate.maturity_state, "supported")
            self.assertEqual(candidate.support_count, 3)

            choice_payload = {
                "path": str(target),
                "required_capabilities": ["filesystem"],
                "model_policy": "never",
                "native_action_options": [
                    {
                        "kind": "command",
                        "args": {
                            "command": "python -c \"print('DEFAULT_COMMAND_SHOULD_NOT_RUN')\"",
                        },
                    },
                    {
                        "kind": "write_text",
                        "args": {
                            "path": str(target),
                            "content": "learned-success",
                            "append": False,
                            "create_parents": True,
                        },
                    },
                ],
            }
            event = resident.enqueue(
                "choose one current native route for the stable target",
                payload=choice_payload,
            )
            self._advance_until_stage(resident, "native_action")
            investigation = resident.investigator.current(event.event_id)
            self.assertIsNotNone(investigation)
            default = derive_native_action_intent(event, facts=investigation.facts)
            self.assertIsNotNone(default)
            self.assertEqual(default.kind, "command")

            state = resident.store.get_working_state()
            self.assertEqual(state.data["native_action_intent"]["kind"], "write_text")
            self.assertEqual(
                state.data["native_action_intent"]["args"]["content"],
                "learned-success",
            )
            influence = state.data.get("procedural_action_influence")
            self.assertIsInstance(influence, dict)
            self.assertEqual(influence["tendency_id"], candidate.tendency_id)
            self.assertFalse(influence["revoked"])

            self.assertIsNone(resident.live_once())
            self.assertEqual(resident.store.get_working_state().stage, "native_verification")
            action_thought = resident.life.snapshot().current_thought
            self.assertIsNotNone(action_thought)
            self.assertTrue(
                any(
                    candidate.tendency_id in item and "currently biases" in item
                    for item in action_thought.known
                )
            )
            result = resident.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(target.read_text(encoding="utf-8"), "learned-success")
            movements = [
                item.kind
                for item in resident.body.recent_actions(40)
                if item.event_id == event.event_id
            ]
            self.assertIn("write_text", movements)
            self.assertIn("read_text", movements)
            self.assertNotIn("command", movements)

            second_payload = {
                "path": str(target),
                "required_capabilities": ["filesystem"],
                "model_policy": "never",
                "native_action_options": [
                    {
                        "kind": "command",
                        "args": {
                            "command": "python -c \"print('SECOND_DEFAULT_SHOULD_NOT_RUN')\"",
                        },
                    },
                    {
                        "kind": "write_text",
                        "args": {
                            "path": str(target),
                            "content": "learned-but-contradicted",
                            "append": False,
                            "create_parents": True,
                        },
                    },
                ],
            }
            event2 = resident.enqueue(
                "choose one current native route for the stable target again",
                payload=second_payload,
            )
            self._advance_until_stage(resident, "native_action")
            state2 = resident.store.get_working_state()
            active = state2.data.get("procedural_action_influence")
            self.assertIsInstance(active, dict)
            active_tendency = active["tendency_id"]
            self.assertEqual(state2.data["native_action_intent"]["kind"], "write_text")

            self.assertIsNone(resident.live_once())
            self.assertEqual(resident.store.get_working_state().stage, "native_verification")
            target.write_text("reality changed after movement", encoding="utf-8")
            self.assertIsNone(resident.live_once())
            contradicted = resident.store.get_working_state()
            self.assertEqual(contradicted.stage, "native_investigation")
            self.assertTrue(contradicted.data["procedural_action_influence"]["revoked"])
            self.assertEqual(
                contradicted.data["procedural_action_influence"]["revocation_reason"],
                "verification_contradiction",
            )
            self.assertIn(
                active_tendency,
                contradicted.data["procedural_revoked_tendencies"],
            )
            self.assertFalse(contradicted.data["native_verification_result"]["verified"])
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
