from __future__ import annotations

import tempfile
from pathlib import Path

from tests.zn_agent.core.test_maintenance_publication import MaintenancePublicationPreparationTests


class MaintenancePublicationDiagnostic(MaintenancePublicationPreparationTests):
    def test_direct_preparation_surfaces_failure_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            target = "runtime/python/zn_agent/core/repair_fixture.py"
            resident = self._resident(tmp, self._responses(target))
            task = self._open_task(resident, "channel:publication-direct-diagnostic")
            branch = f"work/self-maintenance-{task['task_id'][:12]}-direct"
            attempt_root = source_root.parent / ".zn-maintenance-worktrees" / "publication-direct"
            try:
                resident.investigate_maintenance_source(
                    task["task_id"],
                    source_root=source_root,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )
                result = resident._maintenance_cognitive_orchestrator().derive_execute_and_review(
                    task["task_id"],
                    source_root=source_root,
                    attempt_root=attempt_root,
                    branch_ref=branch,
                )
                self.assertEqual(result["semantic_review"]["decision"], "accept")
                try:
                    prepared = resident.prepare_accepted_maintenance_publication(
                        task["task_id"], source_root=source_root
                    )
                except Exception:
                    status = self._git(
                        attempt_root, "status", "--porcelain=v1", "--untracked-files=all", check=False
                    )
                    others = self._git(
                        attempt_root,
                        "ls-files",
                        "--others",
                        "--exclude-standard",
                        check=False,
                    )
                    print("DIAGNOSTIC_STATUS_BEGIN")
                    print(status.stdout)
                    print("DIAGNOSTIC_UNTRACKED_BEGIN")
                    print(others.stdout)
                    print("DIAGNOSTIC_END")
                    raise
                self.assertEqual(prepared["authority"], "local_commit_only")
            finally:
                self._cleanup(source_root, attempt_root, branch)
                resident.managed_browser.close()
                resident.store.close()
