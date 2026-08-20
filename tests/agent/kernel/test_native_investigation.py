from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from agent.kernel import ExecutionPath
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class NativeInvestigationTests(unittest.TestCase):
    def test_resident_answers_its_current_working_directory_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )

            result = resident.submit("what is my current working directory?")
            investigations = resident.investigator.recent(1)

            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.INVESTIGATION)
            self.assertEqual(result.response, os.getcwd())
            self.assertEqual(result.model_invocations, 0)
            self.assertIsNone(resident.life.snapshot().current_impasse)
            self.assertEqual(len(investigations), 1)
            self.assertEqual(investigations[0].status, "resolved")
            self.assertIn("inspect resident body state", investigations[0].probes)
            resident.store.close()

    def test_resident_checks_a_referenced_path_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "evidence.txt"
            target.write_text("zn", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )

            result = resident.submit(
                f"does {target} exist?",
                payload={"path": str(target)},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.INVESTIGATION)
            self.assertIn("exists", result.response)
            latest = resident.investigator.recent(1)[0]
            self.assertEqual(latest.facts["paths"][0]["exists"], True)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_resident_checks_process_state_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )

            result = resident.submit(
                f"is pid {os.getpid()} running?",
                payload={"pid": os.getpid()},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.INVESTIGATION)
            self.assertIn("alive", result.response)
            self.assertEqual(result.model_invocations, 0)
            resident.store.close()

    def test_unresolved_investigation_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            result = first.submit(
                "diagnose an unfamiliar failure that has no local evidence yet",
                payload={"model_policy": "never"},
            )
            first_investigation = first.investigator.recent(1)[0]

            self.assertFalse(result.success)
            self.assertEqual(first_investigation.status, "open")
            self.assertTrue(first_investigation.unresolved)
            self.assertGreaterEqual(first_investigation.rounds, 1)
            investigation_id = first_investigation.investigation_id
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored = second.investigator.recent(1)[0]
            self.assertEqual(restored.investigation_id, investigation_id)
            self.assertEqual(restored.status, "open")
            self.assertTrue(restored.evidence)
            self.assertIsNotNone(second.life.snapshot().current_impasse)
            second.store.close()


if __name__ == "__main__":
    unittest.main()
