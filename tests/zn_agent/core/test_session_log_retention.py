from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zn_agent.core.session_log import (
    SessionLog,
    SessionLogRetentionPolicy,
    SessionPruneReport,
    rebuild_model_request,
)
from zn_agent.core.store import KernelStore

NOW = datetime(2026, 10, 21, 7, 0, 0, tzinfo=timezone.utc)


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def _store_event(store: KernelStore, session_id: str, request_id: str, created_at: str) -> None:
    store.append_session_event(
        {
            "seq": 0,
            "event_id": f"sev-{request_id}",
            "session_id": session_id,
            "request_id": request_id,
            "kind": "model_request_sent",
            "created_at": created_at,
            "payload": {"provider": "p", "model": "m", "request": {"q": 1}},
        }
    )


def _seed_store(store: KernelStore, plan: list[tuple[str, str, int]]) -> None:
    """plan: (session_id, created_at_iso, event_count)."""
    for session_id, created_at, count in plan:
        for i in range(count):
            _store_event(store, session_id, f"r-{session_id}-{i}", created_at)


def _seed_memory(log: SessionLog, plan: list[tuple[str, str, int]]) -> None:
    for session_id, created_at, count in plan:
        for i in range(count):
            event = log.emit(
                "model_request_sent",
                request_id=f"r-{session_id}-{i}",
                session_id=session_id,
                payload={"provider": "p"},
            )
            event.created_at = created_at


class RetentionPolicyTest(unittest.TestCase):
    def test_default_policy_is_conservative_and_active(self):
        policy = SessionLogRetentionPolicy()
        self.assertEqual(policy.max_age_days, 90)
        self.assertEqual(policy.max_sessions, 1000)
        # The log exposes the default without any configuration: the policy
        # is on unless explicitly replaced.
        self.assertEqual(SessionLog().retention, policy)

    def test_invalid_policy_rejected(self):
        for bad in (0, -1, True, "90", 1.5):
            with self.assertRaises(ValueError, msg=f"max_age_days={bad!r}"):
                SessionLogRetentionPolicy(max_age_days=bad)
            with self.assertRaises(ValueError, msg=f"max_sessions={bad!r}"):
                SessionLogRetentionPolicy(max_sessions=bad)


class PruneStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = KernelStore(Path(self._tmp.name) / "kernel.db")
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self.store.close)

    def test_prune_deletes_only_old_sessions(self):
        _seed_store(
            self.store,
            [
                ("s-old-1", _iso(100), 2),
                ("s-old-2", _iso(95), 1),
                ("s-fresh", _iso(0.01), 2),
            ],
        )
        log = SessionLog(self.store)
        report = log.prune_sessions(now=NOW)

        self.assertIsInstance(report, SessionPruneReport)
        self.assertFalse(report.dry_run)
        self.assertEqual(sorted(report.deleted_sessions), ["s-old-1", "s-old-2"])
        self.assertEqual(report.deleted_events, 3)
        # The fresh session is untouched and still rebuildable.
        self.assertEqual(len(self.store.session_events_for_request("r-s-fresh-0")), 1)
        rebuilt = rebuild_model_request(log, "r-s-fresh-0")
        self.assertEqual(rebuilt["provider"], "p")
        # Old sessions are gone entirely (whole sessions, never partial).
        self.assertEqual(self.store.session_events_for_request("r-s-old-1-0"), [])
        self.assertEqual(
            self.store.session_events_for_request("r-s-old-1-1"), []
        )

    def test_prune_keeps_recent_sessions_under_default_policy(self):
        _seed_store(
            self.store,
            [(f"s-recent-{i}", _iso(i * 0.5), 1) for i in range(5)],
        )
        report = SessionLog(self.store).prune_sessions(now=NOW)
        self.assertEqual(report.deleted_sessions, [])
        self.assertEqual(report.deleted_events, 0)
        self.assertEqual(report.retained_boundary["retained_sessions"], 5)

    def test_keep_recent_sessions_is_an_explicit_cap(self):
        _seed_store(
            self.store,
            [
                ("s-a", _iso(3), 1),
                ("s-b", _iso(2), 1),
                ("s-c", _iso(1), 1),
            ],
        )
        policy = SessionLogRetentionPolicy(max_age_days=90, max_sessions=2)
        report = SessionLog(self.store).prune_sessions(policy, now=NOW)
        # Beyond the newest 2, the oldest session is a candidate even though
        # it is not age-expired: keep-recent-N is an explicit hard cap.
        self.assertEqual(report.deleted_sessions, ["s-a"])
        self.assertEqual(
            len(self.store.session_events_for_request("r-s-c-0")), 1
        )
        self.assertEqual(
            len(self.store.session_events_for_request("r-s-b-0")), 1
        )

    def test_dry_run_deletes_nothing_but_journals(self):
        _seed_store(self.store, [("s-old", _iso(100), 2), ("s-fresh", _iso(0), 1)])
        report = SessionLog(self.store).prune_sessions(dry_run=True, now=NOW)

        self.assertTrue(report.dry_run)
        self.assertEqual(report.candidates, ["s-old"])
        self.assertEqual(report.deleted_sessions, [])
        self.assertEqual(report.deleted_events, 0)
        # Nothing was deleted.
        self.assertEqual(len(self.store.session_events_for_request("r-s-old-0")), 1)
        # But the dry run is still journaled.
        entries = self.store.session_log_prunes()
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["dry_run"])
        self.assertEqual(entries[0]["deleted_events"], 0)
        self.assertEqual(entries[0]["candidate_sessions"], 1)

    def test_prune_writes_journal_with_boundary(self):
        _seed_store(
            self.store,
            [("s-old", _iso(120), 2), ("s-keep-1", _iso(10), 1), ("s-keep-2", _iso(1), 1)],
        )
        log = SessionLog(self.store)
        report = log.prune_sessions(now=NOW)

        entries = self.store.session_log_prunes()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["prune_id"], report.prune_id)
        self.assertFalse(entry["dry_run"])
        self.assertEqual(entry["deleted_sessions"], 1)
        self.assertEqual(entry["deleted_events"], 2)
        self.assertEqual(entry["candidate_sessions"], 1)
        self.assertEqual(
            entry["policy"], {"max_age_days": 90, "max_sessions": 1000}
        )
        boundary = entry["retained_boundary"]
        self.assertEqual(boundary["retained_sessions"], 2)
        self.assertEqual(boundary["oldest_retained_session_id"], "s-keep-1")
        self.assertEqual(
            boundary["oldest_retained_last_activity"], _iso(10)
        )

    def test_fail_closed_on_unparseable_timestamps(self):
        _seed_store(self.store, [("s-old", _iso(100), 1)])
        _store_event(self.store, "s-broken", "r-broken-0", "not-a-timestamp")
        report = SessionLog(self.store).prune_sessions(now=NOW)

        self.assertEqual(report.deleted_sessions, ["s-old"])
        self.assertGreaterEqual(report.skipped_sessions, 1)
        # The session with an undeterminable boundary survives.
        self.assertEqual(len(self.store.session_events_for_request("r-broken-0")), 1)

    def test_fail_closed_on_empty_session_id(self):
        _store_event(self.store, "", "r-naked-0", _iso(200))
        _seed_store(self.store, [("s-old", _iso(100), 1)])
        report = SessionLog(self.store).prune_sessions(now=NOW)

        self.assertEqual(report.deleted_sessions, ["s-old"])
        self.assertEqual(len(self.store.session_events_for_request("r-naked-0")), 1)

    def test_unparseable_now_refuses_to_prune(self):
        _seed_store(self.store, [("s-old", _iso(100), 1)])
        log = SessionLog(self.store)
        with self.assertRaises(ValueError):
            log.prune_sessions(now="not-a-time")
        # Nothing deleted, nothing journaled.
        self.assertEqual(len(self.store.session_events_for_request("r-s-old-0")), 1)
        self.assertEqual(self.store.session_log_prunes(), [])

    def test_write_path_still_works_after_prune(self):
        _seed_store(self.store, [("s-old", _iso(100), 1)])
        log = SessionLog(self.store)
        log.prune_sessions(now=NOW)
        event = log.emit(
            "model_request_sent",
            request_id="r-new-0",
            session_id="s-new",
            payload={"provider": "p"},
        )
        self.assertGreater(event.seq, 0)
        self.assertEqual(len(log.events_for_request("r-new-0")), 1)


class PruneMemoryTest(unittest.TestCase):
    def test_memory_path_prune_and_journal(self):
        log = SessionLog()
        _seed_memory(
            log,
            [("s-old", _iso(100), 2), ("s-fresh", _iso(0.01), 1)],
        )
        report = log.prune_sessions(now=NOW)

        self.assertEqual(report.deleted_sessions, ["s-old"])
        self.assertEqual(report.deleted_events, 2)
        self.assertEqual(len(log.events_for_request("r-s-fresh-0")), 1)
        self.assertEqual(log.events_for_request("r-s-old-0"), [])
        journal = log.prune_journal
        self.assertEqual(len(journal), 1)
        self.assertEqual(journal[0].prune_id, report.prune_id)

    def test_memory_path_fail_closed_on_garbage_timestamp(self):
        log = SessionLog()
        event = log.emit(
            "model_request_sent", request_id="r-x-0", session_id="s-x", payload={}
        )
        event.created_at = "garbage"
        report = log.prune_sessions(now=NOW)
        self.assertEqual(report.deleted_sessions, [])
        self.assertEqual(len(log.events_for_request("r-x-0")), 1)


if __name__ == "__main__":
    unittest.main()
