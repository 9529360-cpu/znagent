from __future__ import annotations

import hashlib
import json
import unittest

from agent.kernel.procedural_applicability import evaluate_candidate_applicability
from agent.kernel.procedural_tendency import aggregate_candidate_tendencies
from agent.kernel.verified_experience import VerifiedExperience


class ProceduralActionVariantTests(unittest.TestCase):
    @staticmethod
    def _fingerprint(value) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()

    @classmethod
    def _experience(
        cls,
        index: int,
        *,
        variant: str | None,
    ) -> VerifiedExperience:
        target = "/private/stable.txt"
        expected = {
            "kind": "text_equals",
            "target_fingerprint": cls._fingerprint(target),
            "expected_chars": 10 + index,
        }
        if variant is not None:
            expected["action_variant"] = variant
        return VerifiedExperience(
            experience_id=f"vx-variant-{variant}-{index}",
            event_id=f"evt-variant-{variant}-{index}",
            source="native",
            situation_evidence_fingerprint=f"evidence-{index}",
            goal_fingerprint=f"goal-{index}",
            gap_fingerprint=None,
            domains=(cls._fingerprint("filesystem"),),
            action_kind="write_text",
            action_signature_hash=f"action-{variant}-{index}",
            expected_outcome=expected,
            result_features={
                "kind": "write_text",
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
                "verified": True,
                "observation_kind": "read_text",
                "observation_success": True,
            },
            verdict="verified",
            # Deliberately identical: the L2 compatibility profile itself must
            # preserve the privacy-safe variant rather than trusting group_key.
            group_key="same-legacy-group",
            created_at=f"2026-08-23T15:{index:02d}:00+00:00",
        )

    def test_append_and_replace_do_not_merge_and_cross_variant_influence_mismatches(self):
        rows = [
            self._experience(1, variant="replace"),
            self._experience(2, variant="replace"),
            self._experience(3, variant="append"),
            self._experience(4, variant="append"),
        ]

        candidates = aggregate_candidate_tendencies(rows)

        self.assertEqual(len(candidates), 2)
        by_variant = {
            candidate.applicability["stable_action_variant"]: candidate
            for candidate in candidates
        }
        self.assertEqual(set(by_variant), {"append", "replace"})
        self.assertEqual(by_variant["append"].support_count, 2)
        self.assertEqual(by_variant["replace"].support_count, 2)

        target = "/private/stable.txt"
        mismatch = evaluate_candidate_applicability(
            by_variant["replace"],
            current_domains=("filesystem",),
            action_kind="write_text",
            action_args={"path": target, "append": True},
            expected_outcome={
                "kind": "text_equals",
                "path": target,
                "action_variant": "append",
            },
            facts={"paths": [{"path": target, "exists": True, "type": "file"}]},
        )
        self.assertEqual(mismatch.status, "mismatch")
        self.assertIn("action_variant", mismatch.mismatched_fields)

    def test_retained_legacy_write_candidate_without_variant_fails_closed(self):
        legacy = aggregate_candidate_tendencies(
            [
                self._experience(5, variant=None),
                self._experience(6, variant=None),
            ]
        )
        self.assertEqual(len(legacy), 1)
        candidate = legacy[0]
        self.assertIsNone(candidate.applicability["stable_action_variant"])
        self.assertEqual(candidate.applicability["action_variant_variants"], 0)

        target = "/private/stable.txt"
        evaluation = evaluate_candidate_applicability(
            candidate,
            current_domains=("filesystem",),
            action_kind="write_text",
            action_args={"path": target, "append": False},
            expected_outcome={
                "kind": "text_equals",
                "path": target,
                "action_variant": "replace",
            },
            facts={"paths": [{"path": target, "exists": True, "type": "file"}]},
        )

        self.assertEqual(evaluation.status, "untested")
        self.assertIn("action_variant", evaluation.untested_fields)


if __name__ == "__main__":
    unittest.main()
