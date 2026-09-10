from __future__ import annotations

import hashlib
import json
import unittest

from zn_agent.core.procedural_applicability import evaluate_candidate_applicability
from zn_agent.core.procedural_tendency import aggregate_candidate_tendencies
from zn_agent.core.verified_experience import VerifiedExperience


def _fingerprint(value) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
            domains=(_fingerprint("it/git"),),
            action_kind="command",
            action_signature_hash=f"action-{index}",
            expected_outcome={
                "kind": "git_path_staged",
                "action_variant": "git_add",
                "workdir_fingerprint": workdir,
                "target_fingerprint": f"target-{index}",
                "verification_signature_hash": None,
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

    def test_same_project_multi_target_git_candidate_accepts_fresh_observed_target(self):
        root = "repo-alpha"
        workdir_fingerprint = _fingerprint(root)
        rows = [
            self._experience(index, workdir=workdir_fingerprint, event_id=f"evt-{index}")
            for index in range(1, 5)
        ]
        candidate = aggregate_candidate_tendencies(rows)[0]
        self.assertEqual(candidate.applicability["target_variants"], 4)
        self.assertIsNone(candidate.applicability["stable_target_fingerprint"])
        self.assertEqual(
            candidate.applicability["stable_workdir_fingerprint"],
            workdir_fingerprint,
        )

        current_target = "fresh-target.txt"
        expected = {
            "kind": "git_path_staged",
            "path": current_target,
            "workdir": root,
            "action_variant": "git_add",
            "current_goal_proven": True,
        }
        args = {"command": "git add -- fresh-target.txt", "workdir": root}
        facts = {
            "paths": [{"path": current_target, "exists": True, "type": "file"}],
            "git": {
                "available": True,
                "root": root,
                "staged_paths": [],
                "unstaged_paths": [current_target],
                "untracked_paths": [],
                "conflicted_paths": [],
            },
        }

        supported = evaluate_candidate_applicability(
            candidate,
            current_domains=("it/git",),
            action_kind="command",
            action_args=args,
            expected_outcome=expected,
            facts=facts,
        )
        self.assertEqual(supported.status, "supported", supported.to_dict())
        self.assertIn("workdir_observed", supported.reality_matched_fields)
        self.assertIn("target_observed", supported.reality_matched_fields)

        missing_target_observation = evaluate_candidate_applicability(
            candidate,
            current_domains=("it/git",),
            action_kind="command",
            action_args=args,
            expected_outcome=expected,
            facts={"git": facts["git"]},
        )
        self.assertEqual(missing_target_observation.status, "untested")
        self.assertIn("target_observed", missing_target_observation.untested_fields)

        wrong_root = evaluate_candidate_applicability(
            candidate,
            current_domains=("it/git",),
            action_kind="command",
            action_args={**args, "workdir": "repo-beta"},
            expected_outcome={**expected, "workdir": "repo-beta"},
            facts={
                "paths": facts["paths"],
                "git": {**facts["git"], "root": "repo-beta"},
            },
        )
        self.assertEqual(wrong_root.status, "mismatch")
        self.assertIn("workdir_context", wrong_root.mismatched_fields)


if __name__ == "__main__":
    unittest.main()
