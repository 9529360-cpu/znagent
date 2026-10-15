from __future__ import annotations

import unittest

from zn_agent.core.project_team import assemble_team
from zn_agent.core.team_coordinator import (
    TASK_STATUSES as AF3_TASK_STATUSES,
    CoordinatorDecision,
)
from zn_agent.core.team_task_state import (
    TASK_STATUSES,
    RevisionConflictError,
    TaskDeletedError,
    TaskNotFoundError,
    TaskSnapshot,
    TeamTaskStateStore,
)


class TeamTaskStateTests(unittest.TestCase):
    def test_status_vocabulary_shared_with_af3(self):
        self.assertEqual(TASK_STATUSES, AF3_TASK_STATUSES)

    def test_create_and_full_snapshot_round_trip(self):
        store = TeamTaskStateStore()
        created = store.create_task(
            "t-1",
            "team-1",
            title="Design",
            objective="Design the module",
            assignee="架构-01",
            depends_on=(),
            acceptance_criteria=("contract clear",),
            write_scopes=("agents/arch",),
        )
        self.assertEqual(created.revision, 1)
        self.assertFalse(created.deleted)
        rebuilt = TaskSnapshot.from_dict(created.to_dict())
        self.assertEqual(rebuilt, created)
        self.assertEqual(rebuilt.to_dict(), created.to_dict())
        # Every field survives: history + tombstone fields included.
        self.assertEqual(len(rebuilt.history), 1)
        self.assertEqual(rebuilt.history[0]["to"], "todo")
        self.assertEqual(rebuilt.deleted_at, "")
        self.assertEqual(rebuilt.deleted_reason, "")

    def test_cas_update_bumps_revision_and_rejects_stale(self):
        store = TeamTaskStateStore()
        store.create_task("t-1", "team-1", title="Design")
        updated = store.update_task(
            "t-1", expected_revision=1, status="in_progress", reason="started"
        )
        self.assertEqual(updated.revision, 2)
        self.assertEqual(updated.status, "in_progress")
        # Stale revision: rejected, stored data untouched (no data loss).
        with self.assertRaises(RevisionConflictError) as caught:
            store.update_task("t-1", expected_revision=1, status="done")
        self.assertEqual(caught.exception.expected, 1)
        self.assertEqual(caught.exception.actual, 2)
        current = store.get_task("t-1")
        self.assertEqual(current.revision, 2)
        self.assertEqual(current.status, "in_progress")
        self.assertEqual(current.title, "Design")

    def test_lost_update_two_readers_one_writer_wins(self):
        store = TeamTaskStateStore()
        store.create_task("t-1", "team-1", title="Design")
        reader_a = store.get_task("t-1")
        reader_b = store.get_task("t-1")
        self.assertEqual(reader_a.revision, reader_b.revision)
        store.update_task(
            "t-1",
            expected_revision=reader_a.revision,
            status="in_progress",
        )
        with self.assertRaises(RevisionConflictError):
            store.update_task(
                "t-1",
                expected_revision=reader_b.revision,
                status="failed",
            )
        self.assertEqual(store.get_task("t-1").status, "in_progress")

    def test_noop_write_consumes_no_revision(self):
        store = TeamTaskStateStore()
        store.create_task("t-1", "team-1", title="Design")
        same = store.update_task("t-1", expected_revision=1, title="Design")
        self.assertEqual(same.revision, 1)
        self.assertEqual(len(same.history), 1)

    def test_illegal_transition_changes_nothing(self):
        store = TeamTaskStateStore()
        store.create_task("t-1", "team-1", title="Design")
        store.update_task("t-1", expected_revision=1, status="done")
        with self.assertRaises(ValueError):
            store.update_task("t-1", expected_revision=2, status="todo")
        current = store.get_task("t-1")
        self.assertEqual(current.revision, 2)
        self.assertEqual(current.status, "done")
        # failed -> todo retry is allowed (same rule as AF-3).
        store.create_task("t-2", "team-1", title="Build")
        store.update_task("t-2", expected_revision=1, status="failed")
        retried = store.update_task("t-2", expected_revision=2, status="todo")
        self.assertEqual(retried.status, "todo")

    def test_tombstone_delete_keeps_row_queryable(self):
        store = TeamTaskStateStore()
        store.create_task("t-1", "team-1", title="Design")
        store.update_task("t-1", expected_revision=1, status="in_progress")
        tombstone = store.delete_task("t-1", reason="scope cut")
        self.assertTrue(tombstone.deleted)
        self.assertEqual(tombstone.revision, 3)
        self.assertEqual(tombstone.status, "in_progress")  # last status kept
        self.assertEqual(tombstone.deleted_reason, "scope cut")
        self.assertTrue(tombstone.deleted_at)
        self.assertEqual(len(tombstone.history), 3)
        self.assertEqual(tombstone.history[-1]["to"], "deleted")
        # Excluded from live listings, present in tombstone listings.
        self.assertEqual(store.list_tasks(), [])
        self.assertEqual(store.list_tasks(include_deleted=True), [tombstone])
        self.assertEqual(store.list_tombstones(), [tombstone])
        self.assertEqual(store.get_tombstone("t-1"), tombstone)
        self.assertEqual(
            store.get_task("t-1", include_deleted=True), tombstone
        )
        # Live read + update + re-delete all refuse the tombstone.
        with self.assertRaises(TaskDeletedError):
            store.get_task("t-1")
        with self.assertRaises(TaskDeletedError):
            store.update_task("t-1", expected_revision=3, status="todo")
        with self.assertRaises(TaskDeletedError):
            store.delete_task("t-1")
        # There is deliberately no hard-delete API.
        self.assertFalse(hasattr(store, "hard_delete"))
        self.assertFalse(hasattr(store, "delete_permanently"))
        self.assertFalse(hasattr(store, "purge"))
        self.assertFalse(hasattr(store, "erase"))

    def test_unknown_task_errors(self):
        store = TeamTaskStateStore()
        with self.assertRaises(TaskNotFoundError):
            store.get_task("nope")
        with self.assertRaises(TaskNotFoundError):
            store.update_task("nope", expected_revision=1, status="todo")
        with self.assertRaises(TaskNotFoundError):
            store.delete_task("nope")
        with self.assertRaises(TaskNotFoundError):
            store.check_write_scope("nope", "x/y")

    def test_write_scopes_advisory_never_blocks(self):
        store = TeamTaskStateStore()
        store.create_task(
            "t-1", "team-1", write_scopes=("agents/dev", "docs")
        )
        inside = store.check_write_scope("t-1", "agents/dev/SOUL.md")
        self.assertTrue(inside.in_scope)
        self.assertEqual(inside.warning, "")
        # Segment-boundary prefix: agents/dev2 is NOT inside agents/dev.
        outside = store.check_write_scope("t-1", "agents/dev2/SOUL.md")
        self.assertFalse(outside.in_scope)
        self.assertIn("advisory", outside.warning)
        # Advisory is not a block: the check returns, nothing raises,
        # and the out-of-scope attempt is recorded for audit.
        advisories = store.list_advisories()
        self.assertEqual(len(advisories), 1)
        self.assertEqual(advisories[0]["path"], "agents/dev2/SOUL.md")
        self.assertEqual(advisories[0]["task_id"], "t-1")
        # In-scope checks are not logged (no noise).
        store.check_write_scope("t-1", "docs/notes.md")
        self.assertEqual(len(store.list_advisories()), 1)

    def test_write_scopes_empty_means_unrestricted(self):
        store = TeamTaskStateStore()
        store.create_task("t-1", "team-1")
        advisory = store.check_write_scope("t-1", "anywhere/at/all.md")
        self.assertTrue(advisory.in_scope)
        self.assertEqual(store.list_advisories(), ())

    def test_write_scopes_validation(self):
        store = TeamTaskStateStore()
        with self.assertRaises(ValueError):
            store.create_task("t-1", "team-1", write_scopes=("/abs",))
        with self.assertRaises(ValueError):
            store.create_task("t-1", "team-1", write_scopes=("../escape",))
        with self.assertRaises(ValueError):
            store.create_task("t-1", "team-1", write_scopes=("",))
        with self.assertRaises(ValueError):
            store.create_task(
                "t-1", "team-1", write_scopes=("agents/dev", "agents/dev")
            )

    def test_check_scope_on_tombstone_advises_without_raising(self):
        store = TeamTaskStateStore()
        store.create_task("t-1", "team-1", write_scopes=("agents/dev",))
        store.delete_task("t-1", reason="cut")
        advisory = store.check_write_scope("t-1", "agents/dev/x.md")
        self.assertFalse(advisory.in_scope)
        self.assertIn("deleted", advisory.warning)

    def test_sync_from_team_is_idempotent(self):
        team = assemble_team("Demo", ("researcher", "architect"))
        store = TeamTaskStateStore()
        first = store.sync_from_team(team)
        self.assertEqual(len(first), 2)
        self.assertTrue(all(s.revision == 1 for s in first))
        self.assertTrue(all(s.status == "todo" for s in first))
        self.assertEqual(first[1].depends_on, (first[0].task_id,))
        second = store.sync_from_team(team)
        self.assertEqual(second, first)
        self.assertEqual(len(store.list_tasks()), 2)

    def test_mirror_decision_read_then_cas(self):
        store = TeamTaskStateStore()
        store.create_task("w-1", "team-1")
        store.create_task("w-2", "team-1")
        dispatched = store.mirror_decision(
            CoordinatorDecision(action="dispatch", work_item_id="w-1")
        )
        assert dispatched is not None
        self.assertEqual(dispatched.status, "in_progress")
        self.assertEqual(dispatched.revision, 2)
        done = store.mirror_decision(
            CoordinatorDecision(action="complete", work_item_id="w-1")
        )
        assert done is not None
        self.assertEqual(done.status, "done")
        self.assertEqual(done.revision, 3)
        # Non-state actions and unknown tasks are skipped, never raise.
        self.assertIsNone(
            store.mirror_decision(
                CoordinatorDecision(action="wait", work_item_id="w-2")
            )
        )
        self.assertIsNone(
            store.mirror_decision(
                CoordinatorDecision(action="team_complete")
            )
        )
        self.assertIsNone(
            store.mirror_decision(
                CoordinatorDecision(action="dispatch", work_item_id="ghost")
            )
        )
        self.assertEqual(store.get_task("w-2").status, "todo")

    def test_mirror_decision_skips_tombstone(self):
        store = TeamTaskStateStore()
        store.create_task("w-1", "team-1")
        store.delete_task("w-1", reason="cut")
        self.assertIsNone(
            store.mirror_decision(
                CoordinatorDecision(action="dispatch", work_item_id="w-1")
            )
        )
        self.assertTrue(store.get_tombstone("w-1") is not None)

    def test_export_import_round_trip_keeps_tombstones(self):
        store = TeamTaskStateStore()
        store.create_task("t-1", "team-1", title="Design")
        store.update_task("t-1", expected_revision=1, status="done")
        store.create_task("t-2", "team-1", title="Cut")
        store.delete_task("t-2", reason="scope cut")
        store.check_write_scope("t-1", "outside/x.md")
        rebuilt = TeamTaskStateStore.import_snapshots(
            store.export_snapshots(),
            advisories=store.export_advisories(),
        )
        self.assertEqual(
            rebuilt.export_snapshots(), store.export_snapshots()
        )
        self.assertEqual(
            rebuilt.export_advisories(), store.export_advisories()
        )
        tombstone = rebuilt.get_tombstone("t-2")
        assert tombstone is not None
        self.assertEqual(tombstone.deleted_reason, "scope cut")
        self.assertEqual(rebuilt.get_task("t-1").status, "done")
        # Imported store keeps working: CAS continues from imported rev.
        continued = rebuilt.update_task(
            "t-1", expected_revision=2, title="Design v2"
        )
        self.assertEqual(continued.revision, 3)


if __name__ == "__main__":
    unittest.main()
