from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.health_observation import ResidentHealthJournal
from zn_agent.core.maintenance_investigation import MaintenanceInvestigationLedger
from zn_agent.core.maintenance_source import MaintenanceSourceInvestigator


class MaintenanceSourceInvestigationTests(unittest.TestCase):
    @staticmethod
    def _store(tmp: str):
        return SimpleNamespace(path=Path(tmp) / "kernel.db")

    @staticmethod
    def _open_task(journal: ResidentHealthJournal):
        for _ in range(3):
            journal.record_failure("channel:test", AssertionError("source-investigation"))
        task = journal.maintenance_task("channel:test")
        assert task is not None
        return task

    @staticmethod
    def _make_repo(root: Path, *, origin: str = "https://example.invalid/zn-source.git") -> None:
        (root / "runtime" / "python" / "zn_agent" / "core").mkdir(parents=True)
        tests = root / "tests" / "zn_agent" / "core"
        tests.mkdir(parents=True)
        (root / "ZN.md").write_text("# ZN\n", encoding="utf-8")
        (root / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
        (tests / "test_regression.py").write_text("def test_regression(): pass\n", encoding="utf-8")
        subprocess.run(["git", "init", "-b", "dev/zn-agent", str(root)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "zn@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "ZN Test"], check=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "baseline"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(root), "remote", "add", "origin", origin], check=True)

    def test_open_task_binds_exact_zn_root_and_records_read_only_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "znagent"
            root.mkdir()
            self._make_repo(root)
            store = self._store(tmp)
            journal = ResidentHealthJournal(store)
            ledger = MaintenanceInvestigationLedger(store)
            task = self._open_task(journal)
            investigator = MaintenanceSourceInvestigator(store, ledger)

            evidence = investigator.investigate(
                task["task_id"],
                source_root=root,
                regression_oracle="test:tests/zn_agent/core/test_regression.py",
            )

            self.assertEqual(len(evidence["origin_fingerprint"]), 64)
            self.assertNotIn("example.invalid", repr(evidence))
            self.assertEqual(evidence["branch"], "dev/zn-agent")
            self.assertFalse(evidence["dirty"])
            self.assertEqual(evidence["changed_files"], 0)
            self.assertEqual(evidence["authority"], "read_only")
            self.assertTrue(evidence["oracle_available"])
            self.assertEqual(evidence["investigation"]["authority"], "evidence_only")
            self.assertEqual(evidence["investigation"]["baseline_ref"], f"commit:{evidence['head']}")
            self.assertEqual(
                evidence["investigation"]["regression_oracle"],
                "test:tests/zn_agent/core/test_regression.py",
            )

            snapshot = investigator.snapshot()
            self.assertEqual(snapshot["evidence_count"], 1)
            persisted = snapshot["evidence"][0]
            self.assertEqual(persisted["authority"], "read_only")
            self.assertEqual(persisted["origin_fingerprint"], evidence["origin_fingerprint"])
            self.assertNotIn(str(root), repr(persisted))
            self.assertNotIn("example.invalid", repr(persisted))

    def test_dirty_state_is_bounded_and_fingerprinted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "znagent"
            root.mkdir()
            self._make_repo(root)
            (root / "ZN.md").write_text("# changed\n", encoding="utf-8")
            (root / "local.tmp").write_text("untracked\n", encoding="utf-8")
            store = self._store(tmp)
            journal = ResidentHealthJournal(store)
            ledger = MaintenanceInvestigationLedger(store)
            task = self._open_task(journal)
            investigator = MaintenanceSourceInvestigator(store, ledger)

            evidence = investigator.investigate(
                task["task_id"],
                source_root=root,
                regression_oracle="test:tests/zn_agent/core/test_regression.py",
            )

            self.assertTrue(evidence["dirty"])
            self.assertIn("ZN.md", evidence["changed_paths"])
            self.assertIn("local.tmp", evidence["changed_paths"])
            self.assertEqual(len(evidence["changed_fingerprint"]), 64)

    def test_rejects_work_subdirectory_missing_ownership_and_non_test_oracle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "znagent"
            root.mkdir()
            self._make_repo(root)
            store = self._store(tmp)
            journal = ResidentHealthJournal(store)
            ledger = MaintenanceInvestigationLedger(store)
            task = self._open_task(journal)
            investigator = MaintenanceSourceInvestigator(store, ledger)

            with self.assertRaises(ValueError):
                investigator.investigate(
                    task["task_id"],
                    source_root=root / "runtime",
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )
            with self.assertRaises(ValueError):
                investigator.investigate(
                    task["task_id"],
                    source_root=root,
                    regression_oracle="command:pytest -q",
                )

            foreign = Path(tmp) / "foreign"
            foreign.mkdir()
            subprocess.run(["git", "init", "-b", "dev/zn-agent", str(foreign)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(foreign), "config", "user.email", "zn@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(foreign), "config", "user.name", "ZN Test"], check=True)
            (foreign / "README.md").write_text("not ZN\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(foreign), "add", "."], check=True)
            subprocess.run(["git", "-C", str(foreign), "commit", "-m", "baseline"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(foreign), "remote", "add", "origin", "https://example.invalid/other.git"], check=True)
            with self.assertRaises(ValueError):
                investigator.investigate(
                    task["task_id"],
                    source_root=foreign,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )

    def test_source_identity_is_not_baked_to_one_repository_slug(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "custom-upstream"
            root.mkdir()
            self._make_repo(root, origin="https://code.example.test/product/zn.git")
            store = self._store(tmp)
            journal = ResidentHealthJournal(store)
            ledger = MaintenanceInvestigationLedger(store)
            task = self._open_task(journal)
            evidence = MaintenanceSourceInvestigator(store, ledger).investigate(
                task["task_id"],
                source_root=root,
                regression_oracle="test:tests/zn_agent/core/test_regression.py",
            )
            self.assertEqual(len(evidence["origin_fingerprint"]), 64)
            self.assertNotIn("code.example.test", repr(evidence))

    def test_closed_task_cannot_investigate_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "znagent"
            root.mkdir()
            self._make_repo(root)
            store = self._store(tmp)
            journal = ResidentHealthJournal(store)
            ledger = MaintenanceInvestigationLedger(store)
            task = self._open_task(journal)
            journal.record_success("channel:test")
            investigator = MaintenanceSourceInvestigator(store, ledger)

            with self.assertRaises(RuntimeError):
                investigator.investigate(
                    task["task_id"],
                    source_root=root,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )

    def test_only_fixed_git_subprocesses_are_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "znagent"
            root.mkdir()
            self._make_repo(root)
            store = self._store(tmp)
            journal = ResidentHealthJournal(store)
            ledger = MaintenanceInvestigationLedger(store)
            task = self._open_task(journal)
            investigator = MaintenanceSourceInvestigator(store, ledger)

            real_run = subprocess.run
            calls: list[list[str]] = []

            def observed_run(args, **kwargs):
                calls.append(list(args))
                self.assertEqual(args[0], "git")
                self.assertEqual(args[1], "-C")
                self.assertNotIn("shell", kwargs)
                return real_run(args, **kwargs)

            with patch("zn_agent.core.maintenance_source.subprocess.run", side_effect=observed_run):
                investigator.investigate(
                    task["task_id"],
                    source_root=root,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )

            verbs = [call[3] for call in calls]
            self.assertEqual(
                verbs,
                ["rev-parse", "remote", "rev-parse", "branch", "status", "diff", "diff", "ls-files"],
            )


if __name__ == "__main__":
    unittest.main()
