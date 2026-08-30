from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.reporting_maintenance_resident import ReportingMaintenanceResidentRuntime


class ReportingMaintenanceResidentTests(unittest.TestCase):
    def test_formal_resident_projects_repeated_probable_defect_to_one_private_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            self.assertIsInstance(resident, ReportingMaintenanceResidentRuntime)

            secret = "credential=never-report-this"
            for _ in range(3):
                health = resident.health.record_failure(
                    "body:command",
                    AssertionError(f"broken invariant {secret}"),
                )

            self.assertTrue(health["maintenance_candidate"])
            status = resident.status()["upstream_bug_reports"]
            self.assertTrue(status["available"])
            self.assertEqual(status["report_count"], 1)
            self.assertEqual(status["pending_count"], 1)
            report = status["reports"][0]
            self.assertEqual(report["failure_class"], "probable_zn_defect")
            self.assertEqual(report["exception_type"], "AssertionError")
            self.assertEqual(report["occurrences"], 3)
            self.assertNotIn("body:command", repr(report))
            self.assertNotIn(secret, repr(report))
            resident.store.close()
            self.assertNotIn(secret.encode("utf-8"), db.read_bytes())

    def test_restart_repairs_missing_report_projection_without_duplication(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            owner = resident.upstream_bug_reports
            self.assertIsNotNone(owner)

            original_prepare = owner.prepare
            owner.prepare = lambda task: (_ for _ in ()).throw(sqlite3.Error("projection unavailable"))
            try:
                for _ in range(3):
                    health = resident.health.record_failure(
                        "body:command", AssertionError("durable incident")
                    )
            finally:
                owner.prepare = original_prepare

            self.assertTrue(health["maintenance_candidate"])
            self.assertEqual(resident.health.maintenance_tasks()["open_count"], 1)
            self.assertEqual(owner.snapshot()["report_count"], 0)
            resident.store.close()

            restarted = build_resident_runtime(config={"model": {}}, store_path=db)
            first = restarted.status()["upstream_bug_reports"]
            self.assertEqual(first["report_count"], 1)
            self.assertEqual(first["pending_count"], 1)
            restarted.store.close()

            again = build_resident_runtime(config={"model": {}}, store_path=db)
            second = again.status()["upstream_bug_reports"]
            self.assertEqual(second["report_count"], 1)
            self.assertEqual(second["pending_count"], 1)
            again.store.close()

    def test_report_projection_failure_never_rolls_back_health_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            owner = resident.upstream_bug_reports
            self.assertIsNotNone(owner)
            owner.prepare = lambda task: (_ for _ in ()).throw(RuntimeError("report owner failed"))

            for _ in range(3):
                health = resident.health.record_failure(
                    "body:command", AssertionError("health must survive")
                )

            self.assertTrue(health["maintenance_candidate"])
            task = resident.health.maintenance_task("body:command")
            self.assertIsNotNone(task)
            self.assertEqual(task["status"], "open")
            self.assertEqual(owner.snapshot()["report_count"], 0)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
