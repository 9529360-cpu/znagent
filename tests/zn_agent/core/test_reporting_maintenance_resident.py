from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.reporting_maintenance_resident import ReportingMaintenanceResidentRuntime


class ReportingMaintenanceResidentTests(unittest.TestCase):
    @staticmethod
    def _close(resident) -> None:
        try:
            resident.managed_browser.close()
        finally:
            resident.store.close()

    def test_formal_resident_projects_repeated_probable_defect_to_one_private_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
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
                self.assertEqual(status["authority"], "local_outbox_only")
                self.assertFalse(status["transport_available"])
                self.assertEqual(status["report_count"], 1)
                self.assertEqual(status["pending_count"], 1)
                report = status["reports"][0]
                self.assertEqual(report["failure_class"], "probable_zn_defect")
                self.assertEqual(report["exception_type"], "AssertionError")
                self.assertEqual(report["occurrences"], 3)
                self.assertNotIn("body:command", repr(report))
                self.assertNotIn(secret, repr(report))
            finally:
                self._close(resident)
            self.assertNotIn(secret.encode("utf-8"), db.read_bytes())

    def test_configured_https_transport_is_connected_but_health_projection_stays_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime(
                config={
                    "model": {},
                    "zn_resident": {
                        "upstream_bug_report": {
                            "endpoint": "https://reports.example.test/v1/reports",
                            "timeout_seconds": 4,
                        }
                    },
                },
                store_path=db,
            )
            try:
                self.assertIsNotNone(resident.upstream_bug_report_transport)
                self.assertEqual(
                    resident.upstream_bug_report_transport.endpoint,
                    "https://reports.example.test/v1/reports",
                )
                for _ in range(3):
                    resident.health.record_failure(
                        "body:command", AssertionError("local formation only")
                    )
                status = resident.status()["upstream_bug_reports"]
                self.assertTrue(status["transport_available"])
                self.assertEqual(status["authority"], "bounded_operator_transport")
                self.assertEqual(status["pending_count"], 1)
                self.assertEqual(status["reports"][0]["dispatch_attempts"], 0)
            finally:
                self._close(resident)

    def test_report_transport_configuration_rejects_non_https_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                resident = build_resident_runtime(
                    config={
                        "model": {},
                        "zn_resident": {
                            "upstream_bug_report": {
                                "endpoint": "http://reports.example.test/v1/reports"
                            }
                        },
                    },
                    store_path=Path(tmp) / "kernel.db",
                )
                self._close(resident)

    def test_restart_repairs_missing_report_projection_without_duplication(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                owner = resident.upstream_bug_reports
                self.assertIsNotNone(owner)

                original_prepare = owner.prepare
                owner.prepare = lambda task: (_ for _ in ()).throw(
                    sqlite3.Error("projection unavailable")
                )
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
            finally:
                self._close(resident)

            restarted = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                first = restarted.status()["upstream_bug_reports"]
                self.assertEqual(first["report_count"], 1)
                self.assertEqual(first["pending_count"], 1)
            finally:
                self._close(restarted)

            again = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                second = again.status()["upstream_bug_reports"]
                self.assertEqual(second["report_count"], 1)
                self.assertEqual(second["pending_count"], 1)
            finally:
                self._close(again)

    def test_report_projection_failure_never_rolls_back_health_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                owner = resident.upstream_bug_reports
                self.assertIsNotNone(owner)
                owner.prepare = lambda task: (_ for _ in ()).throw(
                    RuntimeError("report owner failed")
                )

                for _ in range(3):
                    health = resident.health.record_failure(
                        "body:command", AssertionError("health must survive")
                    )

                self.assertTrue(health["maintenance_candidate"])
                task = resident.health.maintenance_task("body:command")
                self.assertIsNotNone(task)
                self.assertEqual(task["status"], "open")
                self.assertEqual(owner.snapshot()["report_count"], 0)
            finally:
                self._close(resident)


if __name__ == "__main__":
    unittest.main()
