from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from agent.kernel.action import derive_native_action_intent
from agent.kernel.procedural_applicability import (
    current_expected_outcome,
    evaluate_candidate_applicability,
)
from agent.kernel.procedural_tendency import CandidateProceduralTendency
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class ProceduralApplicabilityTests(unittest.TestCase):
    @staticmethod
    def _stable_json(value) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    @classmethod
    def _fingerprint(cls, value) -> str:
        return hashlib.sha256(cls._stable_json(value).encode("utf-8")).hexdigest()

    @classmethod
    def _candidate(
        cls,
        *,
        action_kind: str = "write_text",
        domain: str = "filesystem",
        target: str | None = None,
        workdir: str | None = None,
        verification_command: str | None = None,
        expected_kind: str = "text_equals",
        expected_exit_code: int | None = None,
        inhibited: bool = False,
    ) -> CandidateProceduralTendency:
        applicability = {
            "stable_target_fingerprint": (
                cls._fingerprint(target) if target is not None else None
            ),
            "stable_workdir_fingerprint": (
                cls._fingerprint(workdir) if workdir is not None else None
            ),
            "stable_verification_signature_hash": (
                cls._fingerprint(
                    {
                        "command": verification_command,
                        "workdir": workdir or None,
                    }
                )
                if verification_command
                else None
            ),
            "target_variants": 1 if target is not None else 0,
            "workdir_variants": 1 if workdir is not None else 0,
            "verification_signature_variants": 1 if verification_command else 0,
            "goal_variants": 2,
            "situation_variants": 2,
            "action_signature_variants": 2,
        }
        return CandidateProceduralTendency(
            tendency_id="pt-test-applicability",
            group_key="group-test",
            action_kind=action_kind,
            domain_fingerprints=(cls._fingerprint(domain),),
            expected_kind=expected_kind,
            expected_exit_code=expected_exit_code,
            effect_class="potential_side_effect",
            failure_class=None,
            support_count=3,
            contradiction_count=0 if not inhibited else 2,
            distinct_event_count=3 if not inhibited else 5,
            native_support_count=3,
            assisted_support_count=0,
            reliability=1.0 if not inhibited else 0.5,
            maturity_state="supported" if not inhibited else "inhibited",
            inhibited=inhibited,
            applicability=applicability,
            recent_verdicts=("verified", "verified"),
            supporting_experience_ids=("vx-1", "vx-2", "vx-3"),
            contradicting_experience_ids=("vx-4", "vx-5") if inhibited else (),
            first_seen_at="2026-08-23T10:00:00+00:00",
            last_seen_at="2026-08-23T12:00:00+00:00",
        )

    @staticmethod
    def _run_to_terminal(resident, limit: int = 48):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach a terminal result")

    def test_matching_task_context_without_observation_remains_untested(self):
        target = "/private/example.txt"
        candidate = self._candidate(target=target)

        evaluation = evaluate_candidate_applicability(
            candidate,
            current_domains=("filesystem",),
            action_kind="write_text",
            action_args={"path": target},
            expected_outcome={"kind": "text_equals", "path": target},
            facts={},
        )

        self.assertEqual(evaluation.status, "untested")
        self.assertIn("target_context", evaluation.matched_fields)
        self.assertIn("target_observed", evaluation.untested_fields)
        self.assertEqual(evaluation.reality_matched_fields, ())

    def test_observed_matching_target_supports_candidate(self):
        target = "/private/example.txt"
        candidate = self._candidate(target=target)

        evaluation = evaluate_candidate_applicability(
            candidate,
            current_domains=("filesystem",),
            action_kind="write_text",
            action_args={"path": target},
            expected_outcome={"kind": "text_equals", "path": target},
            facts={"paths": [{"path": target, "exists": True, "type": "file"}]},
        )

        self.assertEqual(evaluation.status, "supported")
        self.assertIn("target_observed", evaluation.reality_matched_fields)
        self.assertEqual(evaluation.mismatched_fields, ())

    def test_other_target_is_mismatch_even_when_it_was_observed(self):
        learned = "/private/learned.txt"
        current = "/private/other.txt"
        candidate = self._candidate(target=learned)

        evaluation = evaluate_candidate_applicability(
            candidate,
            current_domains=("filesystem",),
            action_kind="write_text",
            action_args={"path": current},
            expected_outcome={"kind": "text_equals", "path": current},
            facts={"paths": [{"path": current, "exists": True, "type": "file"}]},
        )

        self.assertEqual(evaluation.status, "mismatch")
        self.assertIn("target_context", evaluation.mismatched_fields)
        self.assertEqual(evaluation.reality_matched_fields, ())

    def test_generalized_candidate_without_stable_reality_anchor_fails_closed(self):
        candidate = self._candidate()
        candidate = replace(
            candidate,
            applicability={
                **candidate.applicability,
                "target_variants": 2,
                "stable_target_fingerprint": None,
            },
        )

        evaluation = evaluate_candidate_applicability(
            candidate,
            current_domains=("filesystem",),
            action_kind="write_text",
            action_args={"path": "/private/new.txt"},
            expected_outcome={"kind": "text_equals", "path": "/private/new.txt"},
            facts={"paths": [{"path": "/private/new.txt", "exists": False}]},
        )

        self.assertEqual(evaluation.status, "untested")
        self.assertIn("stable_reality_anchor", evaluation.untested_fields)
        self.assertIn("generalized_target", evaluation.untested_fields)

    def test_inhibited_candidate_never_qualifies(self):
        target = "/private/example.txt"
        candidate = self._candidate(target=target, inhibited=True)

        evaluation = evaluate_candidate_applicability(
            candidate,
            current_domains=("filesystem",),
            action_kind="write_text",
            action_args={"path": target},
            expected_outcome={"kind": "text_equals", "path": target},
            facts={"paths": [{"path": target, "exists": True}]},
        )

        self.assertEqual(evaluation.status, "mismatch")
        self.assertIn("candidate_inhibited", evaluation.mismatched_fields)

    def test_command_requires_observed_repository_root_and_keeps_raw_values_private(self):
        workdir = "/private/repository"
        command = "python -m pytest tests/private_case.py"
        candidate = self._candidate(
            action_kind="command",
            workdir=workdir,
            verification_command=command,
            expected_kind="command",
            expected_exit_code=0,
        )
        expected = {
            "kind": "command",
            "command": command,
            "workdir": workdir,
            "expected_exit_code": 0,
        }
        args = {"command": "python build.py", "workdir": workdir}

        untested = evaluate_candidate_applicability(
            candidate,
            current_domains=("filesystem",),
            action_kind="command",
            action_args=args,
            expected_outcome=expected,
            facts={},
        )
        supported = evaluate_candidate_applicability(
            candidate,
            current_domains=("filesystem",),
            action_kind="command",
            action_args=args,
            expected_outcome=expected,
            facts={"git": {"available": True, "root": workdir}},
        )

        self.assertEqual(untested.status, "untested")
        self.assertIn("workdir_observed", untested.untested_fields)
        self.assertEqual(supported.status, "supported")
        self.assertIn("workdir_observed", supported.reality_matched_fields)

        serialized = json.dumps(supported.to_dict(), ensure_ascii=False, sort_keys=True)
        self.assertNotIn(workdir, serialized)
        self.assertNotIn(command, serialized)
        self.assertNotIn("python build.py", serialized)

    def test_real_resident_surfaces_supported_candidate_without_executing_it_and_restores_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "PRIVATE_STABLE_TARGET.txt"
            private_values = [str(root), str(target)]

            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            for index in range(2):
                content = f"PRIVATE_CONTENT_{index}"
                task = f"ensure stable target has PRIVATE_TASK_{index}"
                private_values.extend((content, task))
                event = first.enqueue(
                    task,
                    payload={
                        "path": str(target),
                        "content": content,
                        "required_capabilities": ["filesystem"],
                        "model_policy": "never",
                    },
                )
                result = self._run_to_terminal(first)
                self.assertTrue(result.success)
                self.assertEqual(len(first.verified_experiences.for_event(event.event_id)), 1)

            candidates = first.verified_experiences.candidate_tendencies()
            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            self.assertEqual(candidate.support_count, 2)
            self.assertEqual(candidate.applicability["target_variants"], 1)
            self.assertIsNotNone(candidate.applicability["stable_target_fingerprint"])

            third_content = "PRIVATE_CONTENT_2"
            third_task = "ensure stable target has PRIVATE_TASK_2"
            private_values.extend((third_content, third_task))
            event = first.enqueue(
                third_task,
                payload={
                    "path": str(target),
                    "content": third_content,
                    "required_capabilities": ["filesystem"],
                    "model_policy": "never",
                },
            )

            investigation = None
            for _ in range(8):
                result = first.live_once()
                self.assertIsNone(result)
                self.assertNotIn(
                    "native_action_result",
                    first.store.get_working_state().data,
                )
                investigation = first.investigator.current(event.event_id)
                if investigation is not None and isinstance(
                    investigation.facts.get("paths"), list
                ):
                    break
            self.assertIsNotNone(investigation)
            self.assertIsInstance(investigation.facts.get("paths"), list)

            readiness = first.kernel.self_model.assess_task(
                event.task,
                first._required_capabilities(event),
            )
            intent = derive_native_action_intent(event, facts=investigation.facts)
            self.assertIsNotNone(intent)
            direct_evaluation = evaluate_candidate_applicability(
                candidate,
                current_domains=readiness.domains,
                action_kind=intent.kind,
                action_args=intent.args,
                expected_outcome=current_expected_outcome(event, intent),
                facts=investigation.facts,
            )
            self.assertEqual(
                direct_evaluation.status,
                "supported",
                direct_evaluation.to_dict(),
            )
            self.assertTrue(
                any(
                    candidate.tendency_id in item
                    and "supported by current independent evidence" in item
                    for item in investigation.evidence
                ),
                investigation.evidence,
            )

            pulse = first.pulse()
            situation = first.life.snapshot().current_situation
            self.assertEqual(len(situation.procedural_applicability), 1)
            self.assertEqual(situation.procedural_applicability[0]["status"], "supported")
            self.assertEqual(
                situation.procedural_applicability[0]["tendency_id"],
                candidate.tendency_id,
            )
            self.assertEqual(pulse.thought.action_kind, "investigate")
            self.assertTrue(
                any(
                    "supports procedural candidate" in item
                    and candidate.tendency_id in item
                    for item in pulse.thought.known
                )
            )
            working = first.store.get_working_state()
            self.assertNotIn("native_action_result", working.data)
            self.assertNotIn("procedural_applicability", investigation.facts)

            serialized = json.dumps(
                situation.procedural_applicability,
                ensure_ascii=False,
                sort_keys=True,
            )
            for private in private_values:
                self.assertNotIn(private, serialized)

            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored_pulse = second.pulse()
            restored = second.life.snapshot().current_situation
            self.assertEqual(len(restored.procedural_applicability), 1)
            self.assertEqual(restored.procedural_applicability[0]["status"], "supported")
            self.assertEqual(
                restored.procedural_applicability[0]["tendency_id"],
                candidate.tendency_id,
            )
            self.assertNotIn("native_action_result", second.store.get_working_state().data)
            self.assertTrue(
                any(
                    "supports procedural candidate" in item
                    for item in restored_pulse.thought.known
                )
            )
            second.store.close()


if __name__ == "__main__":
    unittest.main()
