from __future__ import annotations

import unittest

from zn_agent.core.continuity import compare_continuity_snapshots


def _snapshot():
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
            "wake_count": 5,
            "pulse_count": 10,
            "last_event_id": "evt-1",
            "learning_candidate_ids": ["learn-a", "learn-b"],
        },
        "work": {
            "reference_count": 1,
            "reference_limit": 100,
            "references_may_be_truncated": False,
            "threads": [{"id": "work-a", "created_at": "thread-born"}],
        },
        "verified_learning": {
            "reference_count": 1,
            "total_count": 1,
            "reference_limit": 256,
            "references_may_be_truncated": False,
            "experience_ids": ["vx-a"],
        },
        "provider": {
            "mode": "default",
            "provider": "openai",
            "model": "model-a",
            "base_url": "https://example.invalid",
            "credential": {"configured": False, "source": "none", "environment_name": None},
            "active_routes": [],
            "cognition_available": False,
        },
    }


class ContinuityFailClosedTests(unittest.TestCase):
    def test_pre_transition_truncation_blocks_positive_verdict(self):
        before = _snapshot()
        after = _snapshot()
        before["work"]["references_may_be_truncated"] = True
        before["verified_learning"]["references_may_be_truncated"] = True
        before["verified_learning"]["total_count"] = 300

        verdict = compare_continuity_snapshots(before, after)
        kinds = {item["kind"] for item in verdict["blockers"]}

        self.assertFalse(verdict["compatible"])
        self.assertIn("work_baseline_incomplete", kinds)
        self.assertIn("verified_learning_baseline_incomplete", kinds)

    def test_living_counters_must_not_regress(self):
        before = _snapshot()
        after = _snapshot()
        after["living_self"]["wake_count"] = 4
        after["living_self"]["pulse_count"] = 9

        verdict = compare_continuity_snapshots(before, after)
        kinds = {item["kind"] for item in verdict["blockers"]}

        self.assertFalse(verdict["compatible"])
        self.assertIn("wake_count_regressed", kinds)
        self.assertIn("pulse_count_regressed", kinds)

    def test_pending_learning_candidates_must_survive(self):
        before = _snapshot()
        after = _snapshot()
        after["living_self"]["learning_candidate_ids"] = ["learn-a"]

        verdict = compare_continuity_snapshots(before, after)

        self.assertFalse(verdict["compatible"])
        blocker = next(
            item for item in verdict["blockers"]
            if item["kind"] == "learning_candidate_references_lost"
        )
        self.assertEqual(blocker["missing_reference_ids"], ["learn-b"])

    def test_malformed_schema_fails_closed_without_throwing(self):
        before = _snapshot()
        after = _snapshot()
        before["schema_version"] = "not-an-integer"

        verdict = compare_continuity_snapshots(before, after)

        self.assertFalse(verdict["compatible"])
        self.assertEqual(verdict["blockers"][0]["kind"], "schema_mismatch")


if __name__ == "__main__":
    unittest.main(verbosity=2)
