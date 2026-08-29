from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.health_aware_resident import HealthAwareResidentRuntime
from zn_agent.core.provider_bridge import build_resident_runtime


class ResidentMaintenanceSourceTests(unittest.TestCase):
    @staticmethod
    def _make_repo(root: Path) -> None:
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
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "remote",
                "add",
                "origin",
                "https://github.com/9529360-cpu/znagent.git",
            ],
            check=True,
        )

    def test_formal_resident_connects_open_task_to_read_only_source_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "znagent"
            source_root.mkdir()
            self._make_repo(source_root)
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertIsInstance(resident, HealthAwareResidentRuntime)
                for _ in range(3):
                    resident.health.record_failure(
                        "channel:test",
                        AssertionError("resident-source-investigation"),
                    )
                task = resident.health.maintenance_task("channel:test")
                self.assertIsNotNone(task)

                evidence = resident.investigate_maintenance_source(
                    task["task_id"],
                    source_root=source_root,
                    regression_oracle="test:tests/zn_agent/core/test_regression.py",
                )

                self.assertEqual(evidence["authority"], "read_only")
                self.assertEqual(evidence["repository"], "9529360-cpu/znagent")
                self.assertEqual(evidence["investigation"]["status"], "investigating")
                self.assertEqual(evidence["investigation"]["authority"], "evidence_only")

                status = resident.status()
                source_status = status["maintenance_source_evidence"]
                self.assertTrue(source_status["available"])
                self.assertEqual(source_status["evidence_count"], 1)
                projected = source_status["evidence"][0]
                self.assertEqual(projected["task_id"], task["task_id"])
                self.assertEqual(projected["authority"], "read_only")
                self.assertEqual(projected["repository"], "9529360-cpu/znagent")
                self.assertNotIn(str(source_root), repr(source_status))

                investigation = resident.status()["maintenance_investigations"]["investigations"][0]
                self.assertEqual(investigation["baseline_ref"], f"commit:{evidence['head']}")
                self.assertEqual(
                    investigation["regression_oracle"],
                    "test:tests/zn_agent/core/test_regression.py",
                )
            finally:
                resident.managed_browser.close()
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
