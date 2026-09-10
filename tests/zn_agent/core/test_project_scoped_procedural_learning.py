from __future__ import annotations

import unittest

from zn_agent.core.procedural_tendency import aggregate_candidate_tendencies
from zn_agent.core.verified_experience import VerifiedExperience


class ProjectScopedProceduralLearningTests(unittest.TestCase):
    @staticmethod
    def _experience(index: int, *, workdir: str, event_id: str) -> VerifiedExperience:
        return VerifiedExperience(
            experience_id=f"vx-project-{index}",
            event_id=event_id,
            source="native",
            situation_evidence_fingerprint=f"situation-{index}",
            goal_fingerprint=f"goal-{index}",
            gap_fingerprint=None,
            domains=("domain-git",),
            action_kind="command",
            action_signature_hash=f"action-{index}",
            expected_outcome={
                "kind": "git_path_staged",
                "action_variant": "git_add",
                "workdir_fingerprint": workdir,
                "target_fingerprint": f"target-{index}",
                "verification_signature_hash": "verify-git-stage",
            },
            result_features={
                "kind": "command",
                "effect_class": "potential_side_effect",
                "body_success": True,
                "exit_code": 0,
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
                "kind": "git_path_staged",
                "verified": True,
                "observation_kind": "git_state",
                "observation_success": True,
            },
            verdict="verified",
            group_key="git-stage",
            created_at=f"2026-09-10T10:{index:02d}:00+00:00",
        )

    def test_same_procedure_in_two_projects_forms_two_private_competences(self):
        rows = [
            self._experience(index, workdir="project-a-fingerprint", event_id=f"a-{index}")
            for index in range(1, 5)
        ]
        rows.extend(
            self._experience(index + 10, workdir="project-b-fingerprint", event_id=f"b-{index}")
            for index in range(1, 5)
        )

        candidates = aggregate_candidate_tendencies(rows)
        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(item.support_count == 4 for item in candidates))
        self.assertTrue(all(item.maturity_state == "practiced" for item in candidates))
        self.assertEqual(
            {item.applicability["stable_workdir_fingerprint"] for item in candidates},
            {"project-a-fingerprint", "project-b-fingerprint"},
        )

        for candidate in candidates:
            serialized = repr(candidate.to_dict())
            self.assertNotIn("/project-a", serialized)
            self.assertNotIn("/project-b", serialized)


if __name__ == "__main__":
    unittest.main()
