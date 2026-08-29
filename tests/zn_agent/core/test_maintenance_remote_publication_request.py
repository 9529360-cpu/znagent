from __future__ import annotations

import tempfile
from pathlib import Path

from tests.zn_agent.core.test_maintenance_publication import MaintenancePublicationPreparationTests


class MaintenanceRemotePublicationRequestTests(MaintenancePublicationPreparationTests):
    def test_accepted_repair_forms_request_only_remote_publication_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            target = "runtime/python/zn_agent/core/repair_fixture.py"
            resident = self._resident(tmp, self._responses(target))
            task = self._open_task(resident, "channel:remote-publication-request")
            branch = f"work/self-maintenance-{task['task_id'][:12]}-remote-request"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "remote-request-one"
            try:
                resident.investigate_maintenance_source(
                    task["task_id"],
                    source_root=source_root,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )
                result = resident.run_cognitive_maintenance_repair(
                    task["task_id"],
                    source_root=source_root,
                    attempt_root=attempt_root,
                    branch_ref=branch,
                )

                prepared = result["publication_preparation"]
                request = result["remote_publication_request"]
                self.assertTrue(prepared["completed"])
                self.assertTrue(request["completed"])
                self.assertEqual(request["authority"], "request_only")
                self.assertEqual(request["state"], "awaiting_repository_authority")
                self.assertEqual(request["repository"], "9529360-cpu/znagent")
                self.assertEqual(request["target_base_ref"], "dev/zn-agent")
                self.assertEqual(request["requested_action"], "push_branch_open_pull_request")
                self.assertEqual(request["branch_ref"], branch)
                self.assertEqual(request["commit_sha"], prepared["commit_sha"])
                self.assertEqual(request["commit_fingerprint"], prepared["commit_fingerprint"])
                self.assertEqual(request["changed_fingerprint"], prepared["changed_fingerprint"])
                self.assertEqual(request["diff_fingerprint"], prepared["diff_fingerprint"])

                again = resident.request_maintenance_remote_publication(
                    task["task_id"], source_root=source_root
                )
                self.assertEqual(again["request_key"], request["request_key"])
                self.assertEqual(again["commit_sha"], prepared["commit_sha"])

                status = resident.status()["maintenance_remote_publication_requests"]
                self.assertTrue(status["available"])
                self.assertEqual(status["request_count"], 1)
                self.assertEqual(status["requests"][0]["authority"], "request_only")
                self.assertNotIn(str(source_root), repr(status))
                self.assertNotIn(str(attempt_root), repr(status))
                self.assertNotIn("VALUE = 2", repr(status))
                self.assertNotIn("token", repr(status).lower())
            finally:
                self._cleanup(source_root, attempt_root, branch)
                resident.managed_browser.close()
                resident.store.close()

    def test_remote_publication_request_requires_prepared_accepted_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            resident = self._resident(tmp)
            task = self._open_task(resident, "channel:remote-publication-no-commit")
            try:
                with self.assertRaisesRegex(RuntimeError, "accepted investigation"):
                    resident.request_maintenance_remote_publication(
                        task["task_id"], source_root=source_root
                    )
                status = resident.status()["maintenance_remote_publication_requests"]
                self.assertEqual(status["request_count"], 0)
            finally:
                resident.managed_browser.close()
                resident.store.close()

    def test_prepared_branch_drift_blocks_revalidating_remote_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            target = "runtime/python/zn_agent/core/repair_fixture.py"
            resident = self._resident(tmp, self._responses(target))
            task = self._open_task(resident, "channel:remote-publication-drift")
            branch = f"work/self-maintenance-{task['task_id'][:12]}-remote-drift"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "remote-request-drift"
            try:
                resident.investigate_maintenance_source(
                    task["task_id"],
                    source_root=source_root,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )
                result = resident.run_cognitive_maintenance_repair(
                    task["task_id"],
                    source_root=source_root,
                    attempt_root=attempt_root,
                    branch_ref=branch,
                )
                self.assertTrue(result["remote_publication_request"]["completed"])

                (attempt_root / "runtime/python/zn_agent/core/repair_fixture.py").write_text(
                    "VALUE = 3\n", encoding="utf-8"
                )
                self._git(attempt_root, "add", target)
                self._git(attempt_root, "commit", "-m", "advance after publication request")

                with self.assertRaisesRegex(RuntimeError, "branch moved after preparation"):
                    resident.request_maintenance_remote_publication(
                        task["task_id"], source_root=source_root
                    )
            finally:
                self._cleanup(source_root, attempt_root, branch)
                resident.managed_browser.close()
                resident.store.close()
