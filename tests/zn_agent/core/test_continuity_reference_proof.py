from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.continuity import compare_continuity_snapshots
from zn_agent.core.continuity_reference_proof import (
    verified_experience_reference_proof,
    work_reference_proof,
)


def _base_snapshot():
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
            "learning_candidate_ids": [],
        },
        "work": {
            "reference_count": 0,
            "total_count": 0,
            "reference_limit": 100,
            "references_may_be_truncated": False,
            "threads": [],
        },
        "verified_learning": {
            "reference_count": 0,
            "total_count": 0,
            "reference_limit": 256,
            "references_may_be_truncated": False,
            "experience_ids": [],
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


class ContinuityReferenceProofTests(unittest.TestCase):
    def test_proofs_cover_complete_tables_and_ignore_row_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "kernel.db"
            with sqlite3.connect(database) as conn:
                conn.executescript(
                    """
                    CREATE TABLE work_threads(thread_id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
                    CREATE TABLE verified_experiences(experience_id TEXT PRIMARY KEY);
                    """
                )
                conn.executemany(
                    "INSERT INTO work_threads(thread_id,created_at) VALUES(?,?)",
                    [("work-z", "2026-01-02"), ("work-a", "2026-01-01")],
                )
                conn.executemany(
                    "INSERT INTO verified_experiences(experience_id) VALUES(?)",
                    [("vx-z",), ("vx-a",)],
                )
                conn.commit()

            work = work_reference_proof(database)
            learning = verified_experience_reference_proof(database)

            self.assertEqual(work["algorithm"], "sha256")
            self.assertEqual(work["count"], 2)
            self.assertEqual(len(work["digest"]), 64)
            self.assertEqual(learning["count"], 2)
            self.assertEqual(len(learning["digest"]), 64)

    def test_complete_proof_allows_bounded_diagnostic_refs_to_be_truncated(self):
        before = _base_snapshot()
        after = _base_snapshot()
        proof = {"algorithm": "sha256", "count": 500, "digest": "a" * 64}
        for snapshot in (before, after):
            snapshot["work"].update(
                {
                    "reference_count": 100,
                    "total_count": 500,
                    "references_may_be_truncated": True,
                    "full_reference_proof": dict(proof),
                    "threads": [{"id": f"work-{index}", "created_at": "born"} for index in range(100)],
                }
            )
            snapshot["verified_learning"].update(
                {
                    "reference_count": 256,
                    "total_count": 500,
                    "references_may_be_truncated": True,
                    "full_reference_proof": dict(proof),
                    "experience_ids": [f"vx-{index}" for index in range(256)],
                }
            )

        verdict = compare_continuity_snapshots(before, after)

        self.assertTrue(verdict["compatible"], verdict)

    def test_changed_complete_proof_blocks_positive_verdict_without_exporting_ids(self):
        before = _base_snapshot()
        after = _base_snapshot()
        before["work"]["full_reference_proof"] = {
            "algorithm": "sha256",
            "count": 500,
            "digest": "a" * 64,
        }
        after["work"]["full_reference_proof"] = {
            "algorithm": "sha256",
            "count": 499,
            "digest": "b" * 64,
        }

        verdict = compare_continuity_snapshots(before, after)
        blocker = next(item for item in verdict["blockers"] if item["kind"] == "work_reference_proof_changed")

        self.assertFalse(verdict["compatible"])
        self.assertEqual(blocker, {"kind": "work_reference_proof_changed", "before_count": 500, "after_count": 499})

    def test_old_schema2_baseline_without_proof_uses_bounded_fallback_against_new_snapshot(self):
        before = _base_snapshot()
        after = _base_snapshot()
        before["work"]["threads"] = [{"id": "work-a", "created_at": "born"}]
        after["work"].update(
            {
                "threads": [{"id": "work-a", "created_at": "born"}],
                "full_reference_proof": {
                    "algorithm": "sha256",
                    "count": 1,
                    "digest": "a" * 64,
                },
            }
        )
        after["verified_learning"]["full_reference_proof"] = {
            "algorithm": "sha256",
            "count": 0,
            "digest": "b" * 64,
        }

        verdict = compare_continuity_snapshots(before, after)

        self.assertTrue(verdict["compatible"], verdict)

    def test_truncated_legacy_baseline_still_fails_closed_against_new_snapshot(self):
        before = _base_snapshot()
        after = _base_snapshot()
        before["work"]["references_may_be_truncated"] = True
        after["work"]["full_reference_proof"] = {
            "algorithm": "sha256",
            "count": 500,
            "digest": "a" * 64,
        }

        verdict = compare_continuity_snapshots(before, after)
        kinds = {item["kind"] for item in verdict["blockers"]}

        self.assertFalse(verdict["compatible"])
        self.assertIn("work_baseline_incomplete", kinds)

    def test_invalid_baseline_proof_fails_closed(self):
        before = _base_snapshot()
        after = _base_snapshot()
        before["verified_learning"]["full_reference_proof"] = {
            "algorithm": "sha256",
            "count": 1,
            "digest": "not-a-digest",
        }

        verdict = compare_continuity_snapshots(before, after)
        kinds = {item["kind"] for item in verdict["blockers"]}

        self.assertFalse(verdict["compatible"])
        self.assertIn("verified_learning_continuity_unproven", kinds)


if __name__ == "__main__":
    unittest.main(verbosity=2)
