from __future__ import annotations

import hashlib
import json
import unittest

from zn_agent.core.procedural_applicability import evaluate_candidate_applicability
from zn_agent.core.procedural_tendency import CandidateProceduralTendency


class ProceduralApplicabilityContractTests(unittest.TestCase):
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

    def test_observed_workdir_without_current_verification_contract_is_untested(self):
        workdir = "/private/repository"
        verification_command = "python -m pytest"
        candidate = CandidateProceduralTendency(
            tendency_id="pt-incomplete-contract",
            group_key="group-command",
            action_kind="command",
            domain_fingerprints=(self._fingerprint("filesystem"),),
            expected_kind="command",
            expected_exit_code=0,
            effect_class="potential_side_effect",
            failure_class=None,
            support_count=3,
            contradiction_count=0,
            distinct_event_count=3,
            native_support_count=3,
            assisted_support_count=0,
            reliability=1.0,
            maturity_state="supported",
            inhibited=False,
            applicability={
                "stable_target_fingerprint": None,
                "stable_workdir_fingerprint": self._fingerprint(workdir),
                "stable_verification_signature_hash": self._fingerprint(
                    {"command": verification_command, "workdir": workdir}
                ),
                "target_variants": 0,
                "workdir_variants": 1,
                "verification_signature_variants": 1,
                "goal_variants": 2,
                "situation_variants": 2,
                "action_signature_variants": 2,
            },
            recent_verdicts=("verified", "verified"),
            supporting_experience_ids=("vx-1", "vx-2", "vx-3"),
            contradicting_experience_ids=(),
            first_seen_at="2026-08-23T10:00:00+00:00",
            last_seen_at="2026-08-23T12:00:00+00:00",
        )

        evaluation = evaluate_candidate_applicability(
            candidate,
            current_domains=("filesystem",),
            action_kind="command",
            action_args={"command": "python build.py", "workdir": workdir},
            expected_outcome=None,
            facts={"git": {"available": True, "root": workdir}},
        )

        self.assertEqual(evaluation.status, "untested")
        self.assertIn("workdir_observed", evaluation.reality_matched_fields)
        self.assertIn("expected_kind", evaluation.untested_fields)
        self.assertIn("expected_exit_code", evaluation.untested_fields)
        self.assertIn("verification_signature", evaluation.untested_fields)


if __name__ == "__main__":
    unittest.main()
