from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.user_goals import UserGoalManager


class UserGoalTests(unittest.TestCase):
    @staticmethod
    def _resident(db: Path):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=db,
        )

    def test_create_get_and_list_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            goal = resident.user_goals.create_goal(
                "Ship ZN 1.0", "First usable resident build"
            )
            self.assertTrue(goal["goal_id"].startswith("ugoal-"))
            self.assertEqual(goal["status"], "active")
            self.assertEqual(goal["progress"], [])
            self.assertIsNone(goal["completed_at"])
            self.assertIsNone(goal["archived_at"])

            fetched = resident.user_goals.get(goal["goal_id"])
            assert fetched is not None
            self.assertEqual(fetched.title, "Ship ZN 1.0")

            active = resident.user_goals.list_goals(status="active")
            self.assertEqual([item["goal_id"] for item in active], [goal["goal_id"]])
            self.assertEqual(active[0]["progress_count"], 0)
            self.assertIsNone(active[0]["latest_progress_at"])

            # Status summary rides on the resident status, like routines.
            summary = resident.status()["user_goals"]
            self.assertEqual(summary["goal_count"], 1)
            self.assertEqual(summary["active_count"], 1)
            resident.store.close()

    def test_create_rejects_bad_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            with self.assertRaisesRegex(ValueError, "title must not be empty"):
                resident.user_goals.create_goal("   ")
            with self.assertRaisesRegex(ValueError, "unknown goal status"):
                resident.user_goals.create_goal("X", status="done")
            self.assertEqual(resident.user_goals.list_goals(), [])
            resident.store.close()

    def test_progress_is_append_only_and_snapshot_returns_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            goal = resident.user_goals.create_goal("Read 12 books")
            goal_id = goal["goal_id"]

            first = resident.user_goals.add_progress(
                goal_id, "Finished book 1", evidence_ref="notes/book1.md"
            )
            second = resident.user_goals.add_progress(goal_id, "Finished book 2")
            self.assertEqual(first["source"], "user")
            self.assertEqual(first["evidence_ref"], "notes/book1.md")
            self.assertNotEqual(first["entry_id"], second["entry_id"])

            # Snapshot carries every entry, oldest first; list carries counts.
            snapshot = resident.user_goals.snapshot(goal_id)
            self.assertEqual(
                [entry["content"] for entry in snapshot["progress"]],
                ["Finished book 1", "Finished book 2"],
            )
            listed = resident.user_goals.list_goals()[0]
            self.assertEqual(listed["progress_count"], 2)
            self.assertIsNotNone(listed["latest_progress_at"])
            self.assertEqual(
                [entry["content"] for entry in resident.user_goals.list_progress(goal_id)],
                ["Finished book 1", "Finished book 2"],
            )

            # No edit/delete API exists for progress entries (append-only).
            self.assertFalse(hasattr(resident.user_goals, "edit_progress"))
            self.assertFalse(hasattr(resident.user_goals, "delete_progress"))
            with self.assertRaisesRegex(ValueError, "must not be empty"):
                resident.user_goals.add_progress(goal_id, "  ")
            resident.store.close()

    def test_complete_keeps_goal_queryable_and_never_deletes(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            goal = resident.user_goals.create_goal("Launch landing page")
            goal_id = goal["goal_id"]
            resident.user_goals.add_progress(goal_id, "Draft live")

            done = resident.user_goals.complete_goal(goal_id)
            self.assertEqual(done["status"], "completed")
            self.assertIsNotNone(done["completed_at"])
            # Completion stamps the archive marker, but the status stays
            # "completed" and everything stays queryable: complete != delete.
            self.assertIsNotNone(done["archived_at"])
            self.assertEqual(
                [entry["content"] for entry in done["progress"]], ["Draft live"]
            )
            self.assertIsNotNone(resident.user_goals.get(goal_id))
            self.assertEqual(
                [item["goal_id"] for item in resident.user_goals.list_goals()],
                [goal_id],
            )
            self.assertEqual(
                [
                    item["goal_id"]
                    for item in resident.user_goals.list_goals(status="completed")
                ],
                [goal_id],
            )
            self.assertEqual(resident.user_goals.list_goals(status="active"), [])

            # Completing twice is idempotent; progress on a completed goal
            # is rejected rather than silently reopening it.
            again = resident.user_goals.complete_goal(goal_id)
            self.assertEqual(again["status"], "completed")
            with self.assertRaisesRegex(ValueError, "completed goal"):
                resident.user_goals.add_progress(goal_id, "One more")
            # There is no delete API for goals either.
            self.assertFalse(hasattr(resident.user_goals, "delete_goal"))
            self.assertFalse(hasattr(resident.user_goals, "delete"))
            resident.store.close()

    def test_archive_shelves_without_completing(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            goal = resident.user_goals.create_goal("Learn piano (someday)")
            goal_id = goal["goal_id"]

            shelved = resident.user_goals.archive_goal(goal_id)
            self.assertEqual(shelved["status"], "archived")
            self.assertIsNotNone(shelved["archived_at"])
            self.assertIsNone(shelved["completed_at"])
            self.assertIsNotNone(resident.user_goals.get(goal_id))

            # Archiving twice is idempotent; an archived goal cannot be
            # completed afterwards — archive is a terminal shelf state.
            self.assertEqual(
                resident.user_goals.archive_goal(goal_id)["status"], "archived"
            )
            with self.assertRaisesRegex(ValueError, "archived goal"):
                resident.user_goals.complete_goal(goal_id)
            with self.assertRaisesRegex(ValueError, "archived goal"):
                resident.user_goals.add_progress(goal_id, "Practiced")
            resident.store.close()

    def test_background_write_without_context_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            goal = resident.user_goals.create_goal("Weekly report")
            goal_id = goal["goal_id"]

            # Direct background calls: no context, empty context, or a
            # background source without context all fail and write nothing.
            with self.assertRaisesRegex(PermissionError, "require a routine"):
                resident.user_goals.record_background_progress(
                    goal_id, "Routine says hi", routine_context=None
                )
            with self.assertRaisesRegex(PermissionError, "require a routine"):
                resident.user_goals.record_background_progress(
                    goal_id, "Routine says hi", routine_context={}
                )
            with self.assertRaisesRegex(PermissionError, "require a routine"):
                resident.user_goals.add_progress(
                    goal_id, "Sneaky", source="routine"
                )
            with self.assertRaisesRegex(PermissionError, "require a routine"):
                resident.user_goals.add_progress(
                    goal_id, "Sneaky", source="scheduled", routine_context=None
                )
            self.assertEqual(resident.user_goals.list_progress(goal_id), [])

            # A forged context (unknown routine / unknown run) is rejected
            # too: the context must match a real recorded routine run.
            with self.assertRaisesRegex(PermissionError, "unknown routine_id"):
                resident.user_goals.record_background_progress(
                    goal_id,
                    "Forged",
                    routine_context={
                        "source": "routine",
                        "routine_id": "routine-doesnotexist",
                        "routine_run_id": "run-doesnotexist",
                    },
                )
            self.assertEqual(resident.user_goals.list_progress(goal_id), [])
            resident.store.close()

    def test_background_write_with_real_routine_run_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            goal = resident.user_goals.create_goal("Inbox zero")
            goal_id = goal["goal_id"]

            draft = resident.routines.propose("每 2 小时检查一次收件箱")
            routine = resident.routines.confirm(draft)
            run = resident.routines.test_run(routine["routine_id"])

            entry = resident.user_goals.record_background_progress(
                goal_id,
                "Routine checked the inbox",
                routine_context={
                    "source": "routine",
                    "routine_id": routine["routine_id"],
                    "routine_run_id": run["run_id"],
                },
                evidence_ref="routine run",
            )
            self.assertEqual(entry["source"], "routine")
            self.assertEqual(entry["routine_id"], routine["routine_id"])
            self.assertEqual(entry["routine_run_id"], run["run_id"])
            self.assertEqual(
                [e["content"] for e in resident.user_goals.list_progress(goal_id)],
                ["Routine checked the inbox"],
            )

            # A real routine id with a bogus run id is still rejected.
            with self.assertRaisesRegex(PermissionError, "unknown routine_run_id"):
                resident.user_goals.record_background_progress(
                    goal_id,
                    "Forged run",
                    routine_context={
                        "source": "routine",
                        "routine_id": routine["routine_id"],
                        "routine_run_id": "run-doesnotexist",
                    },
                )
            resident.store.close()

    def test_foreground_entry_must_not_carry_routine_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            goal = resident.user_goals.create_goal("Honest provenance")
            with self.assertRaisesRegex(ValueError, "must not carry"):
                resident.user_goals.add_progress(
                    goal["goal_id"],
                    "Pretending to be background",
                    source="user",
                    routine_context={"source": "routine"},
                )
            self.assertEqual(
                resident.user_goals.list_progress(goal["goal_id"]), []
            )
            resident.store.close()

    def test_goals_persist_across_manager_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            goal = resident.user_goals.create_goal("Persistent goal")
            resident.user_goals.add_progress(goal["goal_id"], "Step one")
            resident.user_goals.complete_goal(goal["goal_id"])

            # A fresh manager on the same store sees the same durable state.
            fresh = UserGoalManager(resident)
            snapshot = fresh.snapshot(goal["goal_id"])
            self.assertEqual(snapshot["status"], "completed")
            self.assertEqual(
                [entry["content"] for entry in snapshot["progress"]],
                ["Step one"],
            )
            resident.store.close()

    def test_unknown_goal_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            with self.assertRaises(KeyError):
                resident.user_goals.snapshot("ugoal-missing")
            with self.assertRaises(KeyError):
                resident.user_goals.add_progress("ugoal-missing", "x")
            with self.assertRaises(KeyError):
                resident.user_goals.complete_goal("ugoal-missing")
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
