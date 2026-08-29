from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.continuity import ContinuitySnapshotService, compare_continuity_snapshots
from zn_agent.core.continuity_reference_proof import (
    long_lived_neural_reference_proof,
    resident_state_proof,
    verified_experience_reference_proof,
    work_state_proof,
)


def _connect(path: Path):
    return closing(sqlite3.connect(path))


def _init_database(path: Path) -> None:
    with _connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE work_threads(thread_id TEXT PRIMARY KEY,title TEXT NOT NULL,metadata_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE work_messages(message_id TEXT PRIMARY KEY,thread_id TEXT NOT NULL,role TEXT NOT NULL,text TEXT NOT NULL,detail_json TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE work_artifacts(artifact_id TEXT PRIMARY KEY,thread_id TEXT NOT NULL,event_id TEXT NOT NULL,kind TEXT NOT NULL,name TEXT NOT NULL,path TEXT,content TEXT NOT NULL,metadata_json TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE work_runs(event_id TEXT PRIMARY KEY,thread_id TEXT NOT NULL,message_id TEXT NOT NULL,task TEXT NOT NULL,ledger_state TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,finalized_at TEXT);
            CREATE TABLE verified_experiences(experience_id TEXT PRIMARY KEY);
            CREATE TABLE identity(id INTEGER PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE goals(goal_id TEXT PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE experiences(experience_id TEXT PRIMARY KEY,goal_id TEXT NOT NULL,data TEXT NOT NULL);
            CREATE TABLE capabilities(name TEXT PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE proposals(proposal_id TEXT PRIMARY KEY,goal_id TEXT NOT NULL,data TEXT NOT NULL);
            CREATE TABLE events(event_id TEXT PRIMARY KEY,status TEXT NOT NULL,priority INTEGER NOT NULL,created_at TEXT NOT NULL,data TEXT NOT NULL);
            CREATE TABLE event_outcomes(event_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,data TEXT NOT NULL);
            CREATE TABLE working_state(id INTEGER PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE facts(fact_key TEXT PRIMARY KEY,value_json TEXT NOT NULL,aliases_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE resident_intentions(intention_id TEXT PRIMARY KEY,status TEXT NOT NULL,priority INTEGER NOT NULL,updated_at TEXT NOT NULL,data TEXT NOT NULL);
            CREATE TABLE resident_event_accounting(event_id TEXT NOT NULL,kind TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(event_id,kind));
            CREATE TABLE resident_side_effect_attempts(attempt_id TEXT PRIMARY KEY,event_id TEXT NOT NULL,signature_hash TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,started_at TEXT NOT NULL,completed_at TEXT,result_action_id TEXT,result_success INTEGER);
            CREATE TABLE living_self(id INTEGER PRIMARY KEY,data TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE life_impasses(impasse_id TEXT PRIMARY KEY,event_id TEXT NOT NULL,status TEXT NOT NULL,updated_at TEXT NOT NULL,data TEXT NOT NULL);
            CREATE TABLE life_learning_candidates(candidate_id TEXT PRIMARY KEY,source_impasse_id TEXT NOT NULL,created_at TEXT NOT NULL,status TEXT NOT NULL,data TEXT NOT NULL);
            CREATE TABLE neural_traces(trace_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL UNIQUE,channel TEXT NOT NULL,strength REAL NOT NULL,salience REAL NOT NULL,repetitions INTEGER NOT NULL,last_seen_at TEXT NOT NULL,data TEXT NOT NULL);
            CREATE TABLE world_focuses(focus_id TEXT PRIMARY KEY,enabled INTEGER NOT NULL,priority INTEGER NOT NULL,updated_at TEXT NOT NULL,data TEXT NOT NULL);
            """
        )


def _base_snapshot() -> dict:
    return {
        "schema_version": 2,
        "identity": {"name": "ZN Agent", "version": "0.2.0", "created_at": "identity-born", "updated_at": "identity-now"},
        "living_self": {"name": "ZN", "version": "0.2.0", "born_at": "living-born", "wake_count": 5, "pulse_count": 10, "last_event_id": "evt-1", "learning_candidate_ids": []},
        "work": {"reference_count": 0, "total_count": 0, "reference_limit": 100, "references_may_be_truncated": False, "threads": []},
        "verified_learning": {"reference_count": 0, "total_count": 0, "reference_limit": 256, "references_may_be_truncated": False, "experience_ids": []},
        "provider": {"mode": "default", "provider": "openai", "model": "model-a", "base_url": "https://example.invalid", "credential": {"configured": False, "source": "none", "environment_name": None}, "active_routes": [], "cognition_available": False},
    }


def _proof(*hashes: str) -> dict:
    return {"algorithm": "sha256", "count": len(hashes), "digest": "d" * 64, "reference_hashes": list(hashes)}


class ContinuityReferenceProofTests(unittest.TestCase):
    def test_resident_proof_hides_private_content_and_detects_durable_entity_loss(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "kernel.db"
            _init_database(database)
            identity = {"name": "ZN Agent", "purpose": "private purpose", "principles": ["private principle"], "created_at": "identity-born"}
            living = {"name": "ZN", "born_at": "living-born", "wake_count": 5, "pulse_count": 10}
            intention = {"intention_id": "intent-1", "description": "private enduring intention", "source": "self", "priority": 7, "status": "active", "next_task": "private next task", "created_at": "born", "updated_at": "now"}
            with _connect(database) as conn:
                conn.execute("INSERT INTO identity VALUES(?,?)", (1, json.dumps(identity)))
                conn.execute("INSERT INTO living_self VALUES(?,?,?)", (1, json.dumps(living), "now"))
                conn.execute("INSERT INTO facts VALUES(?,?,?,?,?)", ("secret-fact", '"private value"', '[]', "born", "now"))
                conn.execute("INSERT INTO resident_intentions VALUES(?,?,?,?,?)", ("intent-1", "active", 7, "now", json.dumps(intention)))
                conn.execute("INSERT INTO resident_event_accounting VALUES(?,?,?)", ("evt-1", "native_body_success", "now"))
                conn.execute("INSERT INTO resident_side_effect_attempts VALUES(?,?,?,?,?,?,?,?,?)", ("attempt-1", "evt-1", "signature", "body", "started", "born", None, None, None))
                conn.commit()
            before = resident_state_proof(database)
            self.assertEqual(len(before["reference_hashes"]), before["count"])
            self.assertNotIn("private enduring intention", repr(before))
            self.assertNotIn("private next task", repr(before))
            self.assertNotIn("private value", repr(before))
            self.assertNotIn("secret-fact", repr(before))
            with _connect(database) as conn:
                conn.execute("DELETE FROM resident_intentions WHERE intention_id='intent-1'")
                conn.commit()
            after_loss = resident_state_proof(database)
            self.assertFalse(set(before["reference_hashes"]).issubset(after_loss["reference_hashes"]))

    def test_resident_proof_allows_status_progress_but_protects_intention_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "kernel.db"
            _init_database(database)
            identity = {"name": "ZN Agent", "purpose": "continue", "principles": ["preserve"], "created_at": "identity-born", "version": "0.2.0", "updated_at": "old"}
            living = {"name": "ZN", "born_at": "living-born", "wake_count": 1, "pulse_count": 1, "current_thought": None, "body": {"pid": 1}}
            intention = {"intention_id": "intent-1", "description": "keep going", "source": "self", "priority": 3, "status": "active", "current_step": None, "created_at": "born", "updated_at": "old"}
            with _connect(database) as conn:
                conn.execute("INSERT INTO identity VALUES(?,?)", (1, json.dumps(identity)))
                conn.execute("INSERT INTO living_self VALUES(?,?,?)", (1, json.dumps(living), "old"))
                conn.execute("INSERT INTO resident_intentions VALUES(?,?,?,?,?)", ("intent-1", "active", 3, "old", json.dumps(intention)))
                conn.commit()
            before = resident_state_proof(database)
            identity.update({"version": "0.3.0", "updated_at": "new"})
            living.update({"wake_count": 2, "pulse_count": 3, "current_thought": {"sequence": 3}, "body": {"pid": 2}})
            intention.update({"status": "completed", "current_step": "done", "updated_at": "new"})
            with _connect(database) as conn:
                conn.execute("UPDATE identity SET data=? WHERE id=1", (json.dumps(identity),))
                conn.execute("UPDATE living_self SET data=?,updated_at=? WHERE id=1", (json.dumps(living), "new"))
                conn.execute("UPDATE resident_intentions SET status=?,updated_at=?,data=? WHERE intention_id=?", ("completed", "new", json.dumps(intention), "intent-1"))
                conn.commit()
            after_progress = resident_state_proof(database)
            self.assertEqual(before["reference_hashes"], after_progress["reference_hashes"])
            intention["description"] = "rewritten identity"
            with _connect(database) as conn:
                conn.execute("UPDATE resident_intentions SET data=? WHERE intention_id=?", (json.dumps(intention), "intent-1"))
                conn.commit()
            self.assertNotEqual(before["reference_hashes"], resident_state_proof(database)["reference_hashes"])

    def test_long_lived_neural_references_allow_growth_but_detect_loss(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "kernel.db"
            _init_database(database)
            with _connect(database) as conn:
                conn.execute("INSERT INTO neural_traces VALUES(?,?,?,?,?,?,?,?)", ("schema-a", "fp-a", "schema", 0.7, 0.8, 1, "t1", '{}'))
                conn.execute("INSERT INTO neural_traces VALUES(?,?,?,?,?,?,?,?)", ("repeat-a", "fp-b", "world", 0.4, 0.5, 2, "t1", '{}'))
                conn.commit()
            before = long_lived_neural_reference_proof(database)
            with _connect(database) as conn:
                conn.execute("UPDATE neural_traces SET strength=?,salience=?,last_seen_at=? WHERE trace_id='schema-a'", (0.99, 0.95, "t2"))
                conn.execute("INSERT INTO neural_traces VALUES(?,?,?,?,?,?,?,?)", ("schema-b", "fp-c", "schema", 0.6, 0.7, 1, "t2", '{}'))
                conn.commit()
            after_growth = long_lived_neural_reference_proof(database)
            self.assertTrue(set(before["reference_hashes"]).issubset(after_growth["reference_hashes"]))
            with _connect(database) as conn:
                conn.execute("DELETE FROM neural_traces WHERE trace_id='repeat-a'")
                conn.commit()
            after_loss = long_lived_neural_reference_proof(database)
            self.assertFalse(set(before["reference_hashes"]).issubset(after_loss["reference_hashes"]))

    def test_work_proof_protects_immutable_payload_while_allowing_new_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "kernel.db"
            _init_database(database)
            with _connect(database) as conn:
                conn.execute("INSERT INTO work_threads VALUES(?,?,?,?,?)", ("work-a", "title", "{}", "born", "now"))
                conn.execute("INSERT INTO work_messages VALUES(?,?,?,?,?,?)", ("msg-a", "work-a", "user", "private text", "{}", "born"))
                conn.execute("INSERT INTO work_artifacts VALUES(?,?,?,?,?,?,?,?,?)", ("artifact-a", "work-a", "event-a", "text", "result", None, "private artifact", "{}", "born"))
                conn.execute("INSERT INTO work_runs VALUES(?,?,?,?,?,?,?,?)", ("event-a", "work-a", "msg-a", "private task", "running", "born", "now", None))
                conn.commit()
            before = work_state_proof(database)
            self.assertEqual(before["thread_count"], 1)
            self.assertEqual(before["count"], 4)
            self.assertNotIn("private text", repr(before))
            self.assertNotIn("private artifact", repr(before))
            self.assertNotIn("private task", repr(before))
            with _connect(database) as conn:
                conn.execute("UPDATE work_runs SET ledger_state=?,updated_at=?,finalized_at=? WHERE event_id=?", ("done", "later", "later", "event-a"))
                conn.execute("INSERT INTO work_threads VALUES(?,?,?,?,?)", ("work-b", "new", "{}", "later", "later"))
                conn.commit()
            after_progress = work_state_proof(database)
            self.assertTrue(set(before["reference_hashes"]).issubset(after_progress["reference_hashes"]))
            with _connect(database) as conn:
                conn.execute("UPDATE work_messages SET text=? WHERE message_id=?", ("corrupted text", "msg-a"))
                conn.commit()
            after_corruption = work_state_proof(database)
            self.assertFalse(set(before["reference_hashes"]).issubset(after_corruption["reference_hashes"]))

    def test_verified_learning_reference_proof_allows_growth(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "kernel.db"
            _init_database(database)
            with _connect(database) as conn:
                conn.execute("INSERT INTO verified_experiences VALUES(?)", ("vx-a",))
                conn.commit()
            before = verified_experience_reference_proof(database)
            with _connect(database) as conn:
                conn.execute("INSERT INTO verified_experiences VALUES(?)", ("vx-b",))
                conn.commit()
            after = verified_experience_reference_proof(database)
            self.assertTrue(set(before["reference_hashes"]).issubset(after["reference_hashes"]))

    def test_exact_work_reference_limit_is_not_reported_as_truncated(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "kernel.db"
            _init_database(database)
            rows = [(f"work-{index:03d}", f"2026-01-{(index % 28) + 1:02d}") for index in range(100)]
            with _connect(database) as conn:
                conn.executemany("INSERT INTO work_threads VALUES(?,?,?,?,?)", [(thread_id, "title", "{}", created_at, created_at) for thread_id, created_at in rows])
                conn.commit()
            threads = [SimpleNamespace(thread_id=thread_id, created_at=created_at) for thread_id, created_at in rows]
            work = SimpleNamespace(path=database, list_threads=lambda *, limit: threads[:limit])
            verified = SimpleNamespace(path=database, recent=lambda limit: [], count=lambda: 0)
            resident = SimpleNamespace(store=SimpleNamespace(path=database), identity=SimpleNamespace(name="ZN Agent", version="0.2.0", created_at="identity-born", updated_at="identity-now"), life=SimpleNamespace(snapshot=lambda: SimpleNamespace(name="ZN", version="0.2.0", born_at="living-born", wake_count=1, pulse_count=1, last_event_id=None, learning_candidates=())), verified_experiences=verified)
            provider_settings = SimpleNamespace(snapshot=lambda: {"mode": "default", "provider": "", "model": "", "credential": {}, "active_routes": [], "cognition_available": False})
            snapshot = ContinuitySnapshotService(resident, work=work, provider_settings=provider_settings).snapshot()
            self.assertEqual(snapshot["work"]["reference_count"], 100)
            self.assertEqual(snapshot["work"]["total_count"], 100)
            self.assertFalse(snapshot["work"]["references_may_be_truncated"])
            self.assertEqual(snapshot["work"]["full_state_proof"]["thread_count"], 100)

    def test_hashed_proof_allows_candidate_growth_and_blocks_baseline_loss(self):
        before = _base_snapshot()
        after = _base_snapshot()
        a = "a" * 64
        b = "b" * 64
        before["resident_state"] = {"full_state_proof": _proof(a)}
        after["resident_state"] = {"full_state_proof": _proof(a, b)}
        self.assertTrue(compare_continuity_snapshots(before, after)["compatible"])
        after["resident_state"] = {"full_state_proof": _proof(b)}
        verdict = compare_continuity_snapshots(before, after)
        blocker = next(item for item in verdict["blockers"] if item["kind"] == "resident_state_references_lost")
        self.assertFalse(verdict["compatible"])
        self.assertEqual(blocker["missing_reference_count"], 1)
        self.assertNotIn(a, repr(blocker))

    def test_complete_hashes_remove_bounded_reference_ceiling(self):
        before = _base_snapshot()
        after = _base_snapshot()
        old_hash = "a" * 64
        new_hash = "b" * 64
        for snapshot in (before, after):
            snapshot["work"].update({"reference_count": 100, "total_count": 500, "references_may_be_truncated": True, "threads": []})
            snapshot["verified_learning"].update({"reference_count": 256, "total_count": 500, "references_may_be_truncated": True, "experience_ids": []})
        before["work"]["full_state_proof"] = _proof(old_hash)
        after["work"]["full_state_proof"] = _proof(old_hash, new_hash)
        before["verified_learning"]["full_reference_proof"] = _proof(old_hash)
        after["verified_learning"]["full_reference_proof"] = _proof(old_hash, new_hash)
        self.assertTrue(compare_continuity_snapshots(before, after)["compatible"])

    def test_old_schema2_baseline_without_new_proofs_keeps_bounded_fallback(self):
        before = _base_snapshot()
        after = _base_snapshot()
        before["work"]["threads"] = [{"id": "work-a", "created_at": "born"}]
        after["work"]["threads"] = [{"id": "work-a", "created_at": "born"}]
        after["work"]["full_state_proof"] = _proof("a" * 64)
        after["resident_state"] = {"full_state_proof": _proof("b" * 64)}
        after["long_lived_memory"] = {"full_reference_proof": _proof("c" * 64)}
        self.assertTrue(compare_continuity_snapshots(before, after)["compatible"])

    def test_truncated_legacy_baseline_still_fails_closed(self):
        before = _base_snapshot()
        after = _base_snapshot()
        before["work"]["references_may_be_truncated"] = True
        after["work"]["full_state_proof"] = _proof("a" * 64)
        verdict = compare_continuity_snapshots(before, after)
        self.assertFalse(verdict["compatible"])
        self.assertIn("work_baseline_incomplete", {item["kind"] for item in verdict["blockers"]})

    def test_invalid_hashed_baseline_proof_fails_closed(self):
        before = _base_snapshot()
        after = _base_snapshot()
        before["verified_learning"]["full_reference_proof"] = {"algorithm": "sha256", "count": 1, "digest": "d" * 64, "reference_hashes": ["not-a-hash"]}
        verdict = compare_continuity_snapshots(before, after)
        self.assertFalse(verdict["compatible"])
        self.assertIn("verified_learning_continuity_unproven", {item["kind"] for item in verdict["blockers"]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
