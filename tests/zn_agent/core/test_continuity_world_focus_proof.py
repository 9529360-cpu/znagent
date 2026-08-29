from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.continuity_reference_proof import resident_state_proof


def _connect(path: Path):
    return closing(sqlite3.connect(path))


class ContinuityWorldFocusProofTests(unittest.TestCase):
    def test_world_focus_observation_freshness_can_advance_without_changing_continuity(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "kernel.db"
            with _connect(database) as conn:
                conn.execute(
                    "CREATE TABLE world_focuses("
                    "focus_id TEXT PRIMARY KEY,enabled INTEGER NOT NULL,priority INTEGER NOT NULL,"
                    "updated_at TEXT NOT NULL,data TEXT NOT NULL)"
                )
                focus = {
                    "focus_id": "world-1",
                    "topic": "private long-lived topic",
                    "priority": 4,
                    "interval_seconds": 1800,
                    "enabled": True,
                    "source": "self",
                    "last_observed_at": "2026-01-01T00:00:00+00:00",
                    "last_observation_hash": "old-hash",
                    "last_source_state": {"source-a": {"fingerprint": "old"}},
                    "last_error": None,
                    "created_at": "born",
                    "updated_at": "old",
                }
                conn.execute(
                    "INSERT INTO world_focuses VALUES(?,?,?,?,?)",
                    ("world-1", 1, 4, "old", json.dumps(focus)),
                )
                conn.commit()

            before = resident_state_proof(database)
            self.assertEqual(before["section_counts"]["world_focus_anchors"], 1)
            self.assertNotIn("private long-lived topic", repr(before))

            focus.update(
                {
                    "last_observed_at": "2026-01-02T00:00:00+00:00",
                    "last_observation_hash": "new-hash",
                    "last_source_state": {"source-b": {"fingerprint": "new"}},
                    "last_error": "temporary provider failure",
                    "updated_at": "new",
                }
            )
            with _connect(database) as conn:
                conn.execute(
                    "UPDATE world_focuses SET updated_at=?,data=? WHERE focus_id=?",
                    ("new", json.dumps(focus), "world-1"),
                )
                conn.commit()

            after_observation = resident_state_proof(database)
            self.assertEqual(before["digest"], after_observation["digest"])

    def test_losing_or_rewriting_world_focus_intent_changes_continuity_proof(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "kernel.db"
            with _connect(database) as conn:
                conn.execute(
                    "CREATE TABLE world_focuses("
                    "focus_id TEXT PRIMARY KEY,enabled INTEGER NOT NULL,priority INTEGER NOT NULL,"
                    "updated_at TEXT NOT NULL,data TEXT NOT NULL)"
                )
                focus = {
                    "focus_id": "world-1",
                    "topic": "private long-lived topic",
                    "priority": 4,
                    "interval_seconds": 1800,
                    "enabled": True,
                    "source": "self",
                    "last_observed_at": None,
                    "last_observation_hash": None,
                    "last_source_state": {},
                    "last_error": None,
                    "created_at": "born",
                    "updated_at": "born",
                }
                conn.execute(
                    "INSERT INTO world_focuses VALUES(?,?,?,?,?)",
                    ("world-1", 1, 4, "born", json.dumps(focus)),
                )
                conn.commit()

            before = resident_state_proof(database)
            focus["topic"] = "different durable topic"
            with _connect(database) as conn:
                conn.execute(
                    "UPDATE world_focuses SET data=? WHERE focus_id=?",
                    (json.dumps(focus), "world-1"),
                )
                conn.commit()
            rewritten = resident_state_proof(database)
            self.assertNotEqual(before["digest"], rewritten["digest"])

            with _connect(database) as conn:
                conn.execute("DELETE FROM world_focuses WHERE focus_id=?", ("world-1",))
                conn.commit()
            lost = resident_state_proof(database)
            self.assertNotEqual(before["digest"], lost["digest"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
