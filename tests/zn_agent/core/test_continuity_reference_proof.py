from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.continuity import (
    ContinuitySnapshotService,
    compare_continuity_snapshots,
)
from zn_agent.core.continuity_reference_proof import (
    resident_state_proof,
    verified_experience_reference_proof,
    work_state_proof,
)


def _init_database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE work_threads(
                thread_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE work_messages(
                message_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                detail_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE work_artifacts(
                artifact_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                path TEXT,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE work_runs(
                event_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                task TEXT NOT NULL,
                ledger_state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finalized_at TEXT
            );
            CREATE TABLE verified_experiences(experience_id TEXT PRIMARY KEY);
            CREATE TABLE identity(id INTEGER PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE goals(goal_id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE experiences(experience_id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE capabilities(name TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE proposals(proposal_id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE events(event_id TEXT PRIMARY KEY, status TEXT NOT NULL, priority INTEGER NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE event_outcomes(event_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE working_state(id INTEGER PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE facts(fact_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, aliases_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE resident_side_effect_attempts(
                attempt_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                signature_hash TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                result_action_id TEXT,
                result_success INTEGER
            );
            CREATE TABLE living_self(id INTEGER PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE life_impasses(impasse_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE life_learning_candidates(candidate_id TEXT PRIMARY KEY, source_impasse_id TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL);
            """
        )
        conn.commit()


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
    def test_resident_state_proof_covers_memory_checkpoint_and_replay_state_without_exporting_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "kernel.db"
            _init_database(database)
            identity = {
                "name": "ZN Agent",
                "version": "0.2.0",
                "purpose": "private purpose",
                "principles": ["private principle"],
                "created_at": "identity-born",
                "updated_at": "identity-now",
            }
            living = {
                "name": "ZN",
                "version": "0.2.0",
                "born_at": "living-born",
                "wake_count": 5,
                "pulse_count": 10,
                "last_wake_at": "wake-a",
                "last_pulse_at": "pulse-a",
                "mode": "awake",
                "attention": "volatile attention",
                "intention": "volatile intention",
                "drives": [],
                "observations": ["volatile observation"],
                "open_questions": ["private question"],
                "capabilities": [],
                "external_brains": [],
                "body": {"pid": 1},
                "current_situation": {"sequence": 1},
                "current_thought": {"sequence": 1},
                "current_impasse": {"impasse_id": "imp-1"},
                "learning_candidates": ["learn-1"],
                "last_event_id": "evt-1",
                "last_action_summary": "private result",
            }
            with sqlite3.connect(database) as conn:
                conn.execute("INSERT INTO identity VALUES(?,?)", (1, json.dumps(identity)))
                conn.execute("INSERT INTO living_self VALUES(?,?,?)", (1, json.dumps(living), "now"))
                conn.execute("INSERT INTO goals VALUES(?,?)", ("goal-1", '{"task":"private goal"}'))
                conn.execute("INSERT INTO working_state VALUES(?,?)", (1, '{"current_event_id":"evt-1","stage":"acting"}'))
                conn.execute("INSERT INTO facts VALUES(?,?,?,?,?)", ("secret-fact", '"private value"', '[]', "born", "now"))
                conn.execute(
                    "INSERT INTO resident_side_effect_attempts VALUES(?,?,?,?,?,?,?,?,?)",
                    ("attempt-1", "evt-1", "hash", "body", "started", "born", None, None, None),
                )
                conn.execute("INSERT INTO life_impasses VALUES(?,?,?,?,?)", ("imp-1", "evt-1", "open", "now", '{"reason":"private blocker"}'))
                conn.execute("INSERT INTO life_learning_candidates VALUES(?,?,?,?,?)", ("learn-1", "imp-1", "born", "candidate", '{"resolution_summary":"private learning"}'))
                conn.commit()

            before = resident_state_proof(database)
            with sqlite3.connect(database) as conn:
                conn.execute("UPDATE facts SET value_json=? WHERE fact_key=?", ('"different private value"', "secret-fact"))
                conn.commit()
            after = resident_state_proof(database)

            self.assertEqual(before["algorithm"], "sha256")
            self.assertGreaterEqual(before["count"], 8)
            self.assertEqual(before["section_counts"]["facts"], 1)
            self.assertNotEqual(before["digest"], after["digest"])
            self.assertNotIn("private purpose", repr(before))
            self.assertNotIn("private question", repr(before))
            self.assertNotIn("private value", repr(before))
            self.assertNotIn("private blocker", repr(before))
            self.assertNotIn("private learning", repr(before))

    def test_resident_state_proof_ignores_lifecycle_volatility_but_protects_self_anchors(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "kernel.db"
            _init_database(database)
            identity = {
                "name": "ZN Agent",
                "version": "0.2.0",
                "purpose": "continue",
                "principles": ["preserve continuity"],
                "created_at": "identity-born",
                "updated_at": "identity-now",
            }
            living = {
                "name": "ZN",
                "version": "0.2.0",
                "born_at": "living-born",
                "wake_count": 5,
                "pulse_count": 10,
                "last_wake_at": "wake-a",
                "last_pulse_at": "pulse-a",
                "mode": "awake",
                "attention": "task-a",
                "intention": "observe",
                "drives": ["maintain continuity"],
                "observations": ["old"],
                "open_questions": ["question-a"],
                "capabilities": ["cap-a"],
                "external_brains": ["brain-a"],
                "body": {"pid": 1},
                "current_situation": {"sequence": 10},
                "current_thought": {"sequence": 10},
                "current_impasse": None,
                "learning_candidates": ["learn-a"],
                "last_event_id": "evt-a",
                "last_action_summary": "summary-a",
            }
            with sqlite3.connect(database) as conn:
                conn.execute("INSERT INTO identity VALUES(?,?)", (1, json.dumps(identity)))
                conn.execute("INSERT INTO living_self VALUES(?,?,?)", (1, json.dumps(living), "now"))
                conn.commit()

            before = resident_state_proof(database)
            living.update({
                "wake_count": 6,
                "pulse_count": 12,
                "last_wake_at": "wake-b",
                "last_pulse_at": "pulse-b",
                "mode": "observing",
                "attention": None,
                "intention": "different volatile intention",
                "observations": ["new"],
                "capabilities": ["cap-b"],
                "external_brains": [],
                "body": {"pid": 2},
                "current_situation": {"sequence": 12},
                "current_thought": {"sequence": 12},
            })
            identity.update({"version": "0.3.0", "updated_at": "identity-new"})
            with sqlite3.connect(database) as conn:
                conn.execute("UPDATE identity SET data=? WHERE id=1", (json.dumps(identity),))
                conn.execute("UPDATE living_self SET data=?,updated_at=? WHERE id=1", (json.dumps(living), "later"))
                conn.commit()
            after_restart = resident_state_proof(database)
            self.assertEqual(before["digest"], after_restart["digest"])

            living["open_questions"] = []
            with sqlite3.connect(database) as conn:
                conn.execute("UPDATE living_self SET data=? WHERE id=1", (json.dumps(living),))
                conn.commit()
            after_loss = resident_state_proof(database)
            self.assertNotEqual(before["digest"], after_loss["digest"])

    def test_work_proof_covers_complete_durable_state_without_exporting_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "kernel.db"
            _init_database(database)
            with sqlite3.connect(database) as conn:
                conn.execute("INSERT INTO work_threads VALUES(?,?,?,?,?)", ("work-a", "title", "{}", "2026-01-01", "2026-01-02"))
                conn.execute("INSERT INTO work_messages VALUES(?,?,?,?,?,?)", ("msg-a", "work-a", "user", "private text", "{}", "2026-01-01"))
                conn.execute("INSERT INTO work_artifacts VALUES(?,?,?,?,?,?,?,?,?)", ("artifact-a", "work-a", "event-a", "text", "result", None, "private artifact", "{}", "2026-01-01"))
                conn.execute("INSERT INTO work_runs VALUES(?,?,?,?,?,?,?,?)", ("event-a", "work-a", "msg-a", "private task", "done", "2026-01-01", "2026-01-02", "2026-01-02"))
                conn.commit()

            before = work_state_proof(database)
            with sqlite3.connect(database) as conn:
                conn.execute("UPDATE work_messages SET text=? WHERE message_id=?", ("different private text", "msg-a"))
                conn.commit()
            after = work_state_proof(database)

            self.assertEqual(before["algorithm"], "sha256")
            self.assertEqual(before["count"], 1)
            self.assertEqual(before["row_count"], 4)
            self.assertEqual(before["section_counts"]["work_messages"], 1)
            self.assertEqual(len(before["digest"]), 64)
            self.assertNotEqual(before["digest"], after["digest"])
            self.assertNotIn("private text", repr(before))
            self.assertNotIn("private artifact", repr(before))
            self.assertNotIn("private task", repr(before))

    def test_learning_proof_covers_complete_id_set(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "kernel.db"
            _init_database(database)
            with sqlite3.connect(database) as conn:
                conn.executemany("INSERT INTO verified_experiences(experience_id) VALUES(?)", [("vx-z",), ("vx-a",)])
                conn.commit()
            learning = verified_experience_reference_proof(database)
            self.assertEqual(learning["algorithm"], "sha256")
            self.assertEqual(learning["count"], 2)
            self.assertEqual(len(learning["digest"]), 64)

    def test_exact_work_reference_limit_is_not_reported_as_truncated(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "kernel.db"
            _init_database(database)
            rows = [(f"work-{index:03d}", f"2026-01-{(index % 28) + 1:02d}") for index in range(100)]
            with sqlite3.connect(database) as conn:
                conn.executemany("INSERT INTO work_threads VALUES(?,?,?,?,?)", [(thread_id, "title", "{}", created_at, created_at) for thread_id, created_at in rows])
                conn.commit()

            threads = [SimpleNamespace(thread_id=thread_id, created_at=created_at) for thread_id, created_at in rows]
            work = SimpleNamespace(path=database, list_threads=lambda *, limit: threads[:limit])
            verified = SimpleNamespace(path=database, recent=lambda limit: [], count=lambda: 0)
            resident = SimpleNamespace(
                store=SimpleNamespace(path=database),
                identity=SimpleNamespace(name="ZN Agent", version="0.2.0", created_at="identity-born", updated_at="identity-now"),
                life=SimpleNamespace(snapshot=lambda: SimpleNamespace(name="ZN", version="0.2.0", born_at="living-born", wake_count=1, pulse_count=1, last_event_id=None, learning_candidates=())),
                verified_experiences=verified,
            )
            provider_settings = SimpleNamespace(snapshot=lambda: {"mode": "default", "provider": "", "model": "", "credential": {}, "active_routes": [], "cognition_available": False})

            snapshot = ContinuitySnapshotService(resident, work=work, provider_settings=provider_settings).snapshot()

            self.assertEqual(snapshot["work"]["reference_count"], 100)
            self.assertEqual(snapshot["work"]["total_count"], 100)
            self.assertFalse(snapshot["work"]["references_may_be_truncated"])
            self.assertEqual(snapshot["work"]["full_state_proof"]["count"], 100)
            self.assertIn("full_state_proof", snapshot["resident_state"])

    def test_complete_proofs_allow_bounded_diagnostic_refs_to_be_truncated(self):
        before = _base_snapshot()
        after = _base_snapshot()
        proof = {"algorithm": "sha256", "count": 500, "digest": "a" * 64}
        for snapshot in (before, after):
            snapshot["work"].update({"reference_count": 100, "total_count": 500, "references_may_be_truncated": True, "full_state_proof": dict(proof), "threads": [{"id": f"work-{index}", "created_at": "born"} for index in range(100)]})
            snapshot["verified_learning"].update({"reference_count": 256, "total_count": 500, "references_may_be_truncated": True, "full_reference_proof": dict(proof), "experience_ids": [f"vx-{index}" for index in range(256)]})

        verdict = compare_continuity_snapshots(before, after)
        self.assertTrue(verdict["compatible"], verdict)

    def test_changed_complete_resident_state_blocks_positive_verdict_without_exporting_digest(self):
        before = _base_snapshot()
        after = _base_snapshot()
        before["resident_state"] = {"full_state_proof": {"algorithm": "sha256", "count": 10, "digest": "a" * 64}}
        after["resident_state"] = {"full_state_proof": {"algorithm": "sha256", "count": 9, "digest": "b" * 64}}

        verdict = compare_continuity_snapshots(before, after)
        blocker = next(item for item in verdict["blockers"] if item["kind"] == "resident_state_full_state_proof_changed")
        self.assertFalse(verdict["compatible"])
        self.assertEqual(blocker["before_count"], 10)
        self.assertEqual(blocker["after_count"], 9)
        self.assertNotIn("digest", blocker)

    def test_missing_post_transition_resident_state_proof_fails_closed_when_baseline_has_one(self):
        before = _base_snapshot()
        after = _base_snapshot()
        before["resident_state"] = {"full_state_proof": {"algorithm": "sha256", "count": 1, "digest": "a" * 64}}

        verdict = compare_continuity_snapshots(before, after)
        kinds = {item["kind"] for item in verdict["blockers"]}
        self.assertFalse(verdict["compatible"])
        self.assertIn("resident_state_continuity_unproven", kinds)

    def test_old_schema2_baseline_without_resident_state_proof_remains_compatible(self):
        before = _base_snapshot()
        after = _base_snapshot()
        after["resident_state"] = {"full_state_proof": {"algorithm": "sha256", "count": 1, "digest": "a" * 64}}

        verdict = compare_continuity_snapshots(before, after)
        self.assertTrue(verdict["compatible"], verdict)

    def test_changed_complete_work_state_blocks_positive_verdict_without_exporting_digest(self):
        before = _base_snapshot()
        after = _base_snapshot()
        before["work"]["full_state_proof"] = {"algorithm": "sha256", "count": 500, "digest": "a" * 64}
        after["work"]["full_state_proof"] = {"algorithm": "sha256", "count": 500, "digest": "b" * 64}

        verdict = compare_continuity_snapshots(before, after)
        blocker = next(item for item in verdict["blockers"] if item["kind"] == "work_full_state_proof_changed")
        self.assertFalse(verdict["compatible"])
        self.assertEqual(blocker["before_count"], 500)
        self.assertEqual(blocker["after_count"], 500)
        self.assertNotIn("digest", blocker)

    def test_old_schema2_baseline_without_proof_uses_bounded_fallback_against_new_snapshot(self):
        before = _base_snapshot()
        after = _base_snapshot()
        before["work"]["threads"] = [{"id": "work-a", "created_at": "born"}]
        after["work"].update({"threads": [{"id": "work-a", "created_at": "born"}], "full_state_proof": {"algorithm": "sha256", "count": 1, "digest": "a" * 64}})
        after["verified_learning"]["full_reference_proof"] = {"algorithm": "sha256", "count": 0, "digest": "b" * 64}

        verdict = compare_continuity_snapshots(before, after)
        self.assertTrue(verdict["compatible"], verdict)

    def test_truncated_legacy_baseline_still_fails_closed_against_new_snapshot(self):
        before = _base_snapshot()
        after = _base_snapshot()
        before["work"]["references_may_be_truncated"] = True
        after["work"]["full_state_proof"] = {"algorithm": "sha256", "count": 500, "digest": "a" * 64}

        verdict = compare_continuity_snapshots(before, after)
        kinds = {item["kind"] for item in verdict["blockers"]}
        self.assertFalse(verdict["compatible"])
        self.assertIn("work_baseline_incomplete", kinds)

    def test_invalid_baseline_proof_fails_closed(self):
        before = _base_snapshot()
        after = _base_snapshot()
        before["verified_learning"]["full_reference_proof"] = {"algorithm": "sha256", "count": 1, "digest": "not-a-digest"}

        verdict = compare_continuity_snapshots(before, after)
        kinds = {item["kind"] for item in verdict["blockers"]}
        self.assertFalse(verdict["compatible"])
        self.assertIn("verified_learning_continuity_unproven", kinds)


if __name__ == "__main__":
    unittest.main(verbosity=2)
