from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.focused_modern_text_resident import FocusedModernTextResidentRuntime
from zn_agent.core.health_aware_resident import HealthAwareResidentRuntime
from zn_agent.core.provider_bridge import build_resident_runtime


class ResidentMaintenanceStatusTests(unittest.TestCase):
    def test_formal_resident_status_projects_durable_health_tasks_and_investigations(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=database)
            try:
                self.assertIsInstance(resident, HealthAwareResidentRuntime)
                self.assertIsInstance(resident, FocusedModernTextResidentRuntime)

                initial = resident.status()
                self.assertTrue(initial["resident_health"]["healthy"])
                self.assertEqual(initial["maintenance_tasks"]["task_count"], 0)
                self.assertEqual(
                    initial["maintenance_investigations"]["investigation_count"],
                    0,
                )

                for _ in range(3):
                    resident.health.record_failure(
                        "channel:test",
                        AssertionError("internal invariant failed"),
                    )

                projected = resident.status()
                self.assertFalse(projected["resident_health"]["healthy"])
                self.assertEqual(projected["resident_health"]["maintenance_candidate_count"], 1)
                self.assertEqual(projected["maintenance_tasks"]["open_count"], 1)
                self.assertEqual(projected["maintenance_tasks"]["tasks"][0]["organ"], "channel:test")
                investigations = projected["maintenance_investigations"]
                self.assertEqual(investigations["active_count"], 1)
                self.assertEqual(investigations["investigation_count"], 1)
                investigation = investigations["investigations"][0]
                self.assertEqual(investigation["organ"], "channel:test")
                self.assertEqual(investigation["source_task_status"], "open")
                self.assertEqual(investigation["status"], "pending")
                self.assertEqual(investigation["authority"], "evidence_only")
                self.assertEqual(investigation["attempt_count"], 0)
            finally:
                resident.managed_browser.close()
                resident.store.close()

            reopened = build_resident_runtime(config={"model": {}}, store_path=database)
            try:
                durable = reopened.status()
                self.assertEqual(durable["maintenance_tasks"]["open_count"], 1)
                self.assertEqual(
                    durable["maintenance_tasks"]["tasks"][0]["organ"],
                    "channel:test",
                )
                self.assertEqual(
                    durable["maintenance_investigations"]["active_count"],
                    1,
                )
                self.assertEqual(
                    durable["maintenance_investigations"]["investigations"][0]["status"],
                    "pending",
                )
                reopened.health.record_success("channel:test")
                recovered = reopened.status()
                self.assertTrue(recovered["resident_health"]["healthy"])
                self.assertEqual(recovered["maintenance_tasks"]["open_count"], 0)
                self.assertEqual(
                    recovered["maintenance_tasks"]["tasks"][0]["close_reason"],
                    "organ_recovered",
                )
                closed_investigation = recovered["maintenance_investigations"]
                self.assertEqual(closed_investigation["active_count"], 0)
                self.assertEqual(
                    closed_investigation["investigations"][0]["status"],
                    "closed",
                )
                self.assertEqual(
                    closed_investigation["investigations"][0]["close_reason"],
                    "organ_recovered",
                )
            finally:
                reopened.managed_browser.close()
                reopened.store.close()

    def test_existing_rpc_status_exposes_read_only_maintenance_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                for _ in range(3):
                    resident.health.record_failure(
                        "channel:test",
                        NotImplementedError("missing internal implementation"),
                    )
                rpc = ResidentRpcServer(resident=resident)
                response = rpc.handle({"id": "health-status", "method": "status", "params": {}})

                self.assertTrue(response["ok"])
                status = response["result"]
                self.assertEqual(status["maintenance_tasks"]["open_count"], 1)
                task = status["maintenance_tasks"]["tasks"][0]
                self.assertEqual(task["organ"], "channel:test")
                self.assertEqual(task["failure_class"], "probable_zn_defect")
                self.assertEqual(status["maintenance_investigations"]["active_count"], 1)
                investigation = status["maintenance_investigations"]["investigations"][0]
                self.assertEqual(investigation["task_id"], task["task_id"])
                self.assertEqual(investigation["authority"], "evidence_only")
                self.assertEqual(investigation["status"], "pending")
                self.assertNotIn("missing internal implementation", repr(status))
            finally:
                resident.managed_browser.close()
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
