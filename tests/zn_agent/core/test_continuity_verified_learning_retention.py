from __future__ import annotations

import unittest

from zn_agent.core.continuity import compare_continuity_snapshots


def _proof(*hashes: str) -> dict:
    return {
        "algorithm": "sha256",
        "count": len(hashes),
        "digest": "d" * 64,
        "reference_hashes": list(hashes),
    }


def _snapshot(*, hashes: tuple[str, ...], capacity: int | None) -> dict:
    learning = {
        "reference_count": min(len(hashes), 256),
        "total_count": len(hashes),
        "reference_limit": 256,
        "references_may_be_truncated": len(hashes) > 256,
        "experience_ids": [],
        "full_reference_proof": _proof(*hashes),
    }
    if capacity is not None:
        learning["retention_capacity"] = capacity
    return {
        "schema_version": 2,
        "identity": {
            "name": "ZN Agent",
            "version": "0.2.0",
            "created_at": "identity-born",
            "updated_at": "identity-now",
        },
        "living_self": {
            "name": "ZN",
            "version": "0.2.0",
            "born_at": "living-born",
            "wake_count": 1,
            "pulse_count": 1,
            "last_event_id": None,
            "learning_candidate_ids": [],
        },
        "work": {
            "reference_count": 0,
            "total_count": 0,
            "reference_limit": 100,
            "references_may_be_truncated": False,
            "threads": [],
        },
        "verified_learning": learning,
        "provider": {},
    }


class VerifiedLearningRetentionContinuityTests(unittest.TestCase):
    A = "a" * 64
    B = "b" * 64
    C = "c" * 64
    D = "d" * 64

    def test_growth_below_capacity_keeps_all_baseline_learning(self):
        before = _snapshot(hashes=(self.A,), capacity=3)
        after = _snapshot(hashes=(self.A, self.B), capacity=3)
        self.assertTrue(compare_continuity_snapshots(before, after)["compatible"])

    def test_loss_below_capacity_is_not_explained_by_retention(self):
        before = _snapshot(hashes=(self.A,), capacity=3)
        after = _snapshot(hashes=(self.B,), capacity=3)
        verdict = compare_continuity_snapshots(before, after)
        self.assertFalse(verdict["compatible"])
        self.assertIn(
            "verified_learning_references_lost",
            {item["kind"] for item in verdict["blockers"]},
        )

    def test_overflow_from_below_capacity_may_legitimately_prune(self):
        before = _snapshot(hashes=(self.A, self.B), capacity=3)
        after = _snapshot(hashes=(self.B, self.C, self.D), capacity=3)
        self.assertTrue(compare_continuity_snapshots(before, after)["compatible"])

    def test_full_store_turnover_may_legitimately_prune(self):
        before = _snapshot(hashes=(self.A, self.B), capacity=2)
        after = _snapshot(hashes=(self.B, self.C), capacity=2)
        self.assertTrue(compare_continuity_snapshots(before, after)["compatible"])

    def test_loss_with_candidate_below_capacity_stays_blocked(self):
        before = _snapshot(hashes=(self.A, self.B), capacity=3)
        after = _snapshot(hashes=(self.B, self.C), capacity=3)
        verdict = compare_continuity_snapshots(before, after)
        self.assertFalse(verdict["compatible"])
        self.assertIn(
            "verified_learning_references_lost",
            {item["kind"] for item in verdict["blockers"]},
        )

    def test_retention_capacity_regression_blocks_even_without_hash_loss(self):
        before = _snapshot(hashes=(self.A, self.B), capacity=3)
        after = _snapshot(hashes=(self.A, self.B), capacity=2)
        verdict = compare_continuity_snapshots(before, after)
        self.assertFalse(verdict["compatible"])
        self.assertIn(
            "verified_learning_retention_capacity_regressed",
            {item["kind"] for item in verdict["blockers"]},
        )

    def test_capacity_growth_does_not_justify_dropping_old_learning(self):
        before = _snapshot(hashes=(self.A, self.B), capacity=2)
        after = _snapshot(hashes=(self.B, self.C, self.D), capacity=3)
        verdict = compare_continuity_snapshots(before, after)
        self.assertFalse(verdict["compatible"])
        self.assertIn(
            "verified_learning_references_lost",
            {item["kind"] for item in verdict["blockers"]},
        )

    def test_missing_candidate_capacity_fails_closed_when_baseline_has_it(self):
        before = _snapshot(hashes=(self.A, self.B), capacity=2)
        after = _snapshot(hashes=(self.A, self.B), capacity=None)
        verdict = compare_continuity_snapshots(before, after)
        self.assertFalse(verdict["compatible"])
        self.assertIn(
            "verified_learning_continuity_unproven",
            {item["kind"] for item in verdict["blockers"]},
        )

    def test_proof_count_above_capacity_fails_closed_if_loss_occurs(self):
        before = _snapshot(hashes=(self.A, self.B, self.C), capacity=2)
        after = _snapshot(hashes=(self.B, self.C), capacity=2)
        verdict = compare_continuity_snapshots(before, after)
        self.assertFalse(verdict["compatible"])
        self.assertIn(
            "verified_learning_continuity_unproven",
            {item["kind"] for item in verdict["blockers"]},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
