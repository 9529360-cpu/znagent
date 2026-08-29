from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.browser_rpc import BrowserResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class ContinuityRpcTests(unittest.TestCase):
    def test_formal_resident_compares_baseline_against_current_subject_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            server = BrowserResidentRpcServer(resident=resident)
            try:
                snapshot_response = server.handle(
                    {"id": "snapshot", "method": "continuity_snapshot", "params": {}}
                )
                self.assertTrue(snapshot_response["ok"])
                baseline = snapshot_response["result"]
                self.assertEqual(baseline["schema_version"], 2)

                compare_response = server.handle(
                    {
                        "id": "compare",
                        "method": "continuity_compare",
                        "params": {"baseline": baseline},
                    }
                )
                self.assertTrue(compare_response["ok"])
                self.assertTrue(compare_response["result"]["verdict"]["compatible"])
                self.assertEqual(compare_response["result"]["verdict"]["blockers"], [])
                self.assertEqual(
                    compare_response["result"]["current"]["living_self"]["born_at"],
                    baseline["living_self"]["born_at"],
                )
            finally:
                resident.managed_browser.close()
                resident.store.close()

    def test_continuity_compare_requires_structured_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            server = BrowserResidentRpcServer(resident=resident)
            try:
                with self.assertRaisesRegex(ValueError, "requires baseline object"):
                    server.handle(
                        {
                            "id": "compare",
                            "method": "continuity_compare",
                            "params": {"baseline": "not-a-snapshot"},
                        }
                    )
            finally:
                resident.managed_browser.close()
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
