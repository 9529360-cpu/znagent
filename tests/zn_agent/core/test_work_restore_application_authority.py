from __future__ import annotations

import unittest

from zn_agent.core.work_restore_application_authority_resident import (
    WorkRestoreApplicationAuthorityResidentRuntime,
)


class WorkRestoreApplicationAuthorityTests(unittest.TestCase):
    @staticmethod
    def _application_row():
        return {
            "application_id": "restore-app-test",
            "restore_point_id": "restore-point-private",
            "thread_id": "thread-private",
            "event_id": "event-private",
            "target_path": "C:/private/document.txt",
            "status": "approval_required",
            "error": None,
            "created_at": "2026-08-28T00:00:00Z",
            "updated_at": "2026-08-28T00:00:01Z",
            "completed_at": None,
        }

    def test_parent_identity_requires_positive_inode(self):
        base = {
            "observable": True,
            "stable": True,
            "exists": True,
            "type": "directory",
            "path": "C:/workspace",
            "device": 0,
            "inode": 42,
        }
        self.assertTrue(
            WorkRestoreApplicationAuthorityResidentRuntime._same_parent_identity(
                dict(base), dict(base)
            )
        )

        missing_identity = dict(base)
        missing_identity["inode"] = 0
        self.assertFalse(
            WorkRestoreApplicationAuthorityResidentRuntime._same_parent_identity(
                missing_identity, dict(missing_identity)
            )
        )

    def test_unbound_application_projection_omits_work_metadata(self):
        projected = WorkRestoreApplicationAuthorityResidentRuntime._application_public(
            self._application_row()
        )

        self.assertEqual(projected["application_id"], "restore-app-test")
        self.assertEqual(projected["status"], "approval_required")
        self.assertTrue(projected["requires_user_approval"])
        self.assertNotIn("restore_point_id", projected)
        self.assertNotIn("thread_id", projected)
        self.assertNotIn("event_id", projected)
        self.assertNotIn("target_path", projected)

    def test_thread_bound_inspection_returns_full_work_metadata(self):
        row = self._application_row()

        class BoundRuntime(WorkRestoreApplicationAuthorityResidentRuntime):
            def _application_row(self, application_id: str):
                return row if application_id == "restore-app-test" else None

        runtime = object.__new__(BoundRuntime)
        projected = runtime.inspect_work_restore_application_for_thread(
            "thread-private", "restore-app-test"
        )

        self.assertEqual(projected["thread_id"], "thread-private")
        self.assertEqual(projected["restore_point_id"], "restore-point-private")
        self.assertEqual(projected["event_id"], "event-private")
        self.assertEqual(projected["target_path"], "C:/private/document.txt")
        with self.assertRaisesRegex(ValueError, "unknown Work restore application for thread"):
            runtime.inspect_work_restore_application_for_thread(
                "other-thread", "restore-app-test"
            )


if __name__ == "__main__":
    unittest.main()
