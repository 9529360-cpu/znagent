from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.veteran_candidate_projection import (
    VeteranCandidateProjector,
    VeteranProjectionError,
    final_candidate_from_status,
)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class VeteranCandidateProjectionTests(unittest.TestCase):
    def test_final_candidate_requires_operator_owned_bound_proof(self) -> None:
        status = {
            "mission": {
                "id": "mission-1",
                "phase": "finalize",
                "status": "awaiting-operator-merge",
                "activeCandidateId": "candidate-1",
                "activeMergeProposalId": "merge-1",
            },
            "candidates": [
                {
                    "id": "candidate-1",
                    "commitSha": "c" * 40,
                    "sourceHead": "b" * 40,
                    "ref": "refs/veteran/candidates/candidate-1",
                }
            ],
            "mergeProposals": [
                {
                    "id": "merge-1",
                    "candidateId": "candidate-1",
                    "candidateCommitSha": "c" * 40,
                    "expectedSourceHead": "b" * 40,
                    "status": "proposed",
                    "automaticMerge": False,
                    "automaticPush": False,
                    "requiresOperatorAction": True,
                    "proof": {
                        "validation": {"status": "skipped"},
                        "review": {"status": "passed"},
                        "semanticReview": {"status": "skipped"},
                    },
                }
            ],
        }
        candidate = final_candidate_from_status(status)
        self.assertEqual(candidate.candidate_commit, "c" * 40)
        self.assertEqual(candidate.source_head, "b" * 40)

        status["mergeProposals"][0]["automaticMerge"] = True
        with self.assertRaises(VeteranProjectionError):
            final_candidate_from_status(status)

    def test_projection_changes_worktree_only_and_is_restart_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            git(repo, "init", "-b", "main")
            git(repo, "config", "user.email", "zn@example.invalid")
            git(repo, "config", "user.name", "ZN Test")
            (repo / "app file.txt").write_text("old\n", encoding="utf-8")
            (repo / "delete.txt").write_text("remove me\n", encoding="utf-8")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "base")
            base = git(repo, "rev-parse", "HEAD")

            (repo / "app file.txt").write_text("new\n", encoding="utf-8")
            (repo / "new.txt").write_text("created\n", encoding="utf-8")
            (repo / "delete.txt").unlink()
            git(repo, "add", "-A")
            git(repo, "commit", "-m", "candidate")
            candidate = git(repo, "rev-parse", "HEAD")
            git(repo, "reset", "--hard", base)

            projector = VeteranCandidateProjector(repo)
            final = type(
                "Candidate",
                (),
                {
                    "source_head": base,
                    "candidate_commit": candidate,
                },
            )()
            first = projector.project(final)
            self.assertFalse(first.already_applied)
            self.assertEqual(git(repo, "rev-parse", "HEAD"), base)
            self.assertEqual(git(repo, "diff", "--cached", "--name-only"), "")
            self.assertEqual((repo / "app file.txt").read_text(encoding="utf-8"), "new\n")
            self.assertEqual((repo / "new.txt").read_text(encoding="utf-8"), "created\n")
            self.assertFalse((repo / "delete.txt").exists())
            dirty = subprocess.run(
                ["git", "status", "--porcelain=v1", "--untracked-files=all"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertIn("app file.txt", dirty)
            self.assertIn("new.txt", dirty)
            self.assertIn("delete.txt", dirty)

            second = projector.project(final)
            self.assertTrue(second.already_applied)
            self.assertEqual(first.paths, second.paths)

    def test_projection_blocks_unknown_or_out_of_candidate_workspace_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            git(repo, "init", "-b", "main")
            git(repo, "config", "user.email", "zn@example.invalid")
            git(repo, "config", "user.name", "ZN Test")
            (repo / "app.txt").write_text("old\n", encoding="utf-8")
            git(repo, "add", "app.txt")
            git(repo, "commit", "-m", "base")
            base = git(repo, "rev-parse", "HEAD")
            (repo / "app.txt").write_text("candidate\n", encoding="utf-8")
            git(repo, "commit", "-am", "candidate")
            candidate = git(repo, "rev-parse", "HEAD")
            git(repo, "reset", "--hard", base)

            projector = VeteranCandidateProjector(repo)
            final = type(
                "Candidate",
                (),
                {
                    "source_head": base,
                    "candidate_commit": candidate,
                },
            )()

            (repo / "other.txt").write_text("unrelated\n", encoding="utf-8")
            with self.assertRaisesRegex(
                VeteranProjectionError,
                "outside the Veteran candidate",
            ):
                projector.project(final)
            (repo / "other.txt").unlink()

            (repo / "app.txt").write_text("third-party edit\n", encoding="utf-8")
            with self.assertRaisesRegex(
                VeteranProjectionError,
                "neither the bound base nor candidate",
            ):
                projector.project(final)


if __name__ == "__main__":
    unittest.main()
