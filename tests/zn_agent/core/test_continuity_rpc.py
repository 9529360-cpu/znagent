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

    def test_formal_resident_proves_same_subject_after_real_runtime_reconstruction(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            first_server = BrowserResidentRpcServer(resident=first)
            try:
                first.live_once()
                first.intend(
                    "preserve this resident intention across process reconstruction",
                    next_task="observe continuity",
                )
                first.memory.remember(
                    "continuity-test-fact",
                    {"meaning": "resident-owned durable memory"},
                )
                first.follow_world(
                    "preserve this durable world attention across reconstruction",
                    priority=3,
                    interval_seconds=3600,
                )
                # Repeated neural experience is outside normal consolidation's
                # pruning rule and therefore belongs to long-lived continuity.
                first.nervous.perceive("world", "persistent continuity cue", features=("continuity",))
                first.nervous.perceive("world", "persistent continuity cue", features=("continuity",))
                baseline = first_server.handle(
                    {"id": "snapshot", "method": "continuity_snapshot", "params": {}}
                )["result"]
            finally:
                first.managed_browser.close()
                first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            second_server = BrowserResidentRpcServer(resident=second)
            try:
                second.live_once()
                response = second_server.handle(
                    {
                        "id": "compare",
                        "method": "continuity_compare",
                        "params": {"baseline": baseline},
                    }
                )
                self.assertTrue(response["ok"])
                verdict = response["result"]["verdict"]
                self.assertTrue(verdict["compatible"], verdict)
                self.assertEqual(verdict["blockers"], [])
                self.assertEqual(
                    response["result"]["current"]["resident_state"]["full_state_proof"],
                    baseline["resident_state"]["full_state_proof"],
                )
                self.assertEqual(
                    response["result"]["current"]["long_lived_memory"]["full_reference_proof"],
                    baseline["long_lived_memory"]["full_reference_proof"],
                )
                focuses = second.world.focuses(enabled_only=False, limit=10)
                self.assertEqual(len(focuses), 1)
                self.assertEqual(
                    focuses[0].topic,
                    "preserve this durable world attention across reconstruction",
                )
            finally:
                second.managed_browser.close()
                second.store.close()

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
