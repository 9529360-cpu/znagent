from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.kernel.procedural_tendency import aggregate_candidate_tendencies
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack
from agent.kernel.verified_experience import VerifiedExperience


class ProceduralTendencyTests(unittest.TestCase):
    @staticmethod
    def _experience(
        index: int,
        *,
        verdict: str = "verified",
        event_id: str | None = None,
        group_key: str = "group-safe",
        action_kind: str = "write_text",
        source: str = "native",
        target_fingerprint: str | None = None,
    ) -> VerifiedExperience:
        verified = verdict == "verified"
        return VerifiedExperience(
            experience_id=f"vx-{index}",
            event_id=event_id or f"evt-{index}",
            source=source,
            situation_evidence_fingerprint=f"evidence-{index}",
            goal_fingerprint=f"goal-{index}",
            gap_fingerprint=None,
            domains=("domain-fingerprint",),
            action_kind=action_kind,
            action_signature_hash=f"action-{index}",
            expected_outcome={
                "kind": "text_equals",
                "target_fingerprint": target_fingerprint or f"target-{index}",
                "expected_chars": 10 + index,
            },
            result_features={
                "kind": action_kind,
                "effect_class": "potential_side_effect",
                "body_success": True,
                "exit_code": None,
                "timed_out": False,
                "truncated": False,
                "status": None,
                "output_chars": 0,
                "error_present": False,
                "failure_class": None,
                "masked_success": False,
                "masked_success_kind": None,
            },
            verification={
                "kind": "text_equals",
                "verified": verified,
                "observation_kind": "read_text",
                "observation_success": True,
            },
            verdict=verdict,
            group_key=group_key,
            created_at=f"2026-08-23T12:{index:02d}:00+00:00",
        )

    @staticmethod
    def _run_to_terminal(resident, limit: int = 32):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach a terminal result")

    def test_one_success_or_duplicate_same_event_does_not_create_candidate(self):
        one = self._experience(1)
        self.assertEqual(aggregate_candidate_tendencies([one]), [])

        duplicate_same_event = self._experience(2, event_id=one.event_id)
        self.assertEqual(
            aggregate_candidate_tendencies([one, duplicate_same_event]),
            [],
        )

    def test_two_distinct_verified_events_create_non_executable_candidate(self):
        rows = [self._experience(1), self._experience(2)]
        candidates = aggregate_candidate_tendencies(rows)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.support_count, 2)
        self.assertEqual(candidate.contradiction_count, 0)
        self.assertEqual(candidate.distinct_event_count, 2)
        self.assertEqual(candidate.reliability, 1.0)
        self.assertEqual(candidate.maturity_state, "candidate")
        self.assertFalse(candidate.inhibited)
        self.assertEqual(candidate.action_kind, "write_text")
        self.assertEqual(candidate.expected_kind, "text_equals")
        self.assertEqual(candidate.applicability["target_variants"], 2)
        self.assertIsNone(candidate.applicability["stable_target_fingerprint"])
        self.assertEqual(candidate.applicability["goal_variants"], 2)
        self.assertEqual(candidate.applicability["action_signature_variants"], 2)

        # L2 is an observational aggregation. It intentionally has no command,
        # args, handler, callable or activation instruction that could move Body.
        data = candidate.to_dict()
        for forbidden_key in ("command", "args", "handler", "callable", "execute"):
            self.assertNotIn(forbidden_key, data)

    def test_maturity_needs_repeated_support_and_contradiction_can_inhibit(self):
        two = [self._experience(1), self._experience(2)]
        three = [*two, self._experience(3)]
        four = [*three, self._experience(4)]

        self.assertEqual(
            aggregate_candidate_tendencies(two)[0].maturity_state,
            "candidate",
        )
        self.assertEqual(
            aggregate_candidate_tendencies(three)[0].maturity_state,
            "supported",
        )
        self.assertEqual(
            aggregate_candidate_tendencies(four)[0].maturity_state,
            "practiced",
        )

        contested_rows = [
            *three,
            self._experience(5, verdict="contradicted"),
        ]
        contested = aggregate_candidate_tendencies(contested_rows)[0]
        self.assertEqual(contested.support_count, 3)
        self.assertEqual(contested.contradiction_count, 1)
        self.assertEqual(contested.reliability, 0.75)
        self.assertEqual(contested.maturity_state, "contested")
        self.assertFalse(contested.inhibited)

        inhibited_rows = [
            self._experience(1),
            self._experience(2),
            self._experience(5, verdict="contradicted"),
            self._experience(6, verdict="contradicted"),
        ]
        inhibited = aggregate_candidate_tendencies(inhibited_rows)[0]
        self.assertEqual(inhibited.support_count, 2)
        self.assertEqual(inhibited.contradiction_count, 2)
        self.assertEqual(inhibited.reliability, 0.5)
        self.assertEqual(inhibited.recent_verdicts[:2], ("contradicted", "contradicted"))
        self.assertEqual(inhibited.maturity_state, "inhibited")
        self.assertTrue(inhibited.inhibited)

    def test_incompatible_groups_and_actions_do_not_merge(self):
        rows = [
            self._experience(1, group_key="group-a", action_kind="write_text"),
            self._experience(2, group_key="group-a", action_kind="write_text"),
            self._experience(3, group_key="group-b", action_kind="write_text"),
            self._experience(4, group_key="group-b", action_kind="command"),
        ]
        candidates = aggregate_candidate_tendencies(rows)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].group_key, "group-a")
        self.assertEqual(candidates[0].support_count, 2)

    def test_evidence_references_are_bounded(self):
        rows = [self._experience(index) for index in range(1, 14)]
        rows.extend(
            self._experience(index, verdict="contradicted")
            for index in range(20, 31)
        )
        candidate = aggregate_candidate_tendencies(rows)[0]

        self.assertEqual(candidate.support_count, 13)
        self.assertEqual(candidate.contradiction_count, 11)
        self.assertLessEqual(len(candidate.supporting_experience_ids), 8)
        self.assertLessEqual(len(candidate.contradicting_experience_ids), 8)
        self.assertLessEqual(len(candidate.recent_verdicts), 4)

    def test_real_resident_repeated_verified_writes_form_restart_safe_private_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            secret_domain = "SECRET_DOMAIN candidate privacy"
            private_values: list[str] = [secret_domain, str(root)]

            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            for index in range(2):
                target = root / f"SECRET_PATH_{index}.txt"
                content = f"SECRET_CONTENT_{index}"
                task = f"ensure {target} contains SECRET_TASK_{index}"
                private_values.extend((str(target), content, task))
                event = first.enqueue(
                    task,
                    payload={
                        "path": str(target),
                        "content": content,
                        "required_capabilities": [secret_domain],
                        "model_policy": "never",
                    },
                )
                result = self._run_to_terminal(first)
                self.assertTrue(result.success)
                experiences = first.verified_experiences.for_event(event.event_id)
                self.assertEqual(len(experiences), 1)
                self.assertEqual(experiences[0].verdict, "verified")

            candidates = first.verified_experiences.candidate_tendencies()
            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            self.assertEqual(candidate.support_count, 2)
            self.assertEqual(candidate.action_kind, "write_text")
            self.assertEqual(candidate.maturity_state, "candidate")
            self.assertFalse(candidate.inhibited)
            self.assertEqual(candidate.applicability["target_variants"], 2)
            candidate_id = candidate.tendency_id

            serialized = json.dumps(
                candidate.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
            )
            for private_value in private_values:
                self.assertNotIn(private_value, serialized)

            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored = second.verified_experiences.candidate_tendencies()
            self.assertEqual(len(restored), 1)
            self.assertEqual(restored[0].tendency_id, candidate_id)
            self.assertEqual(restored[0].support_count, 2)
            self.assertEqual(restored[0].maturity_state, "candidate")
            second.store.close()


if __name__ == "__main__":
    unittest.main()
