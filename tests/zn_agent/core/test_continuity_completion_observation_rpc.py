from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core import CapabilityResult, ExactTaskCapability
from zn_agent.core.browser_rpc import BrowserResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


def _resident(database: Path):
    resident = build_resident_runtime_from_existing_stack(
        config={"model": {}},
        store_path=database,
    )
    resident.capabilities.register(
        ExactTaskCapability(
            name="continuity-completion-observation",
            triggers=("complete for continuity",),
            handler=lambda event, state: CapabilityResult(
                success=True,
                response="durable completion",
            ),
        )
    )
    return resident


class CompletionObservationContinuityRpcTests(unittest.TestCase):
    def test_pending_observation_may_repair_to_completed_across_reconstruction(self):
        with tempfile.TemporaryDirectory() as root:
            database = Path(root) / "kernel.db"
            first = _resident(database)
            first_server = BrowserResidentRpcServer(resident=first)
            original_observe = first.life.observe_action
            try:
                def fail_observation(run):
                    raise RuntimeError("temporary private life failure")

                first.life.observe_action = fail_observation
                result = first.submit("complete for continuity")
                self.assertTrue(result.success)
                state = first.completion_observations.state(result.event.event_id)
                self.assertEqual(state["status"], "pending")
                baseline = first_server.handle(
                    {"id": "baseline", "method": "continuity_snapshot", "params": {}}
                )["result"]
                self.assertEqual(
                    baseline["resident_state"]["full_state_proof"]["section_counts"][
                        "completion_observations"
                    ],
                    1,
                )
            finally:
                first.life.observe_action = original_observe
                first.managed_browser.close()
                first.store.close()

            second = _resident(database)
            second_server = BrowserResidentRpcServer(resident=second)
            try:
                repaired = second.completion_observations.state(result.event.event_id)
                self.assertEqual(repaired["status"], "completed")
                response = second_server.handle(
                    {
                        "id": "compare",
                        "method": "continuity_compare",
                        "params": {"baseline": baseline},
                    }
                )
                verdict = response["result"]["verdict"]
                self.assertTrue(verdict["compatible"], verdict)
                self.assertEqual(verdict["blockers"], [])
            finally:
                second.managed_browser.close()
                second.store.close()

    def test_lost_observation_journal_row_blocks_formal_continuity(self):
        with tempfile.TemporaryDirectory() as root:
            database = Path(root) / "kernel.db"
            resident = _resident(database)
            server = BrowserResidentRpcServer(resident=resident)
            original_observe = resident.life.observe_action
            try:
                def fail_observation(run):
                    raise RuntimeError("temporary private life failure")

                resident.life.observe_action = fail_observation
                result = resident.submit("complete for continuity")
                baseline = server.handle(
                    {"id": "baseline", "method": "continuity_snapshot", "params": {}}
                )["result"]
                with closing(sqlite3.connect(database)) as conn:
                    conn.execute(
                        "DELETE FROM resident_completion_observations WHERE event_id=?",
                        (result.event.event_id,),
                    )
                    conn.commit()

                response = server.handle(
                    {
                        "id": "compare",
                        "method": "continuity_compare",
                        "params": {"baseline": baseline},
                    }
                )
                verdict = response["result"]["verdict"]
                self.assertFalse(verdict["compatible"])
                self.assertIn(
                    "resident_state_references_lost",
                    {item["kind"] for item in verdict["blockers"]},
                )
            finally:
                resident.life.observe_action = original_observe
                resident.managed_browser.close()
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
