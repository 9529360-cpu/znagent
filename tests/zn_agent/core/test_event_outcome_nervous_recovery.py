from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.event_outcome_nervous import has_event_outcome
from zn_agent.core.models import ExecutionPath, ResidentRunResult
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class EventOutcomeNervousRecoveryTests(unittest.TestCase):
    @staticmethod
    def _complete(resident, event):
        claimed = resident.store.claim_event(event.event_id)
        if claimed is None:
            raise AssertionError("test event was not claimable")
        result = ResidentRunResult(
            event=claimed,
            execution_path=ExecutionPath.INVESTIGATION,
            success=True,
            response="resident completed the local check",
            model_invocations=0,
        )
        return resident._complete_result(claimed, result)

    def test_terminal_event_survives_nervous_failure_and_restart_repairs_only_perception(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            event = resident.enqueue(
                "verify one resident-local invariant",
                payload={"model_policy": "never"},
            )

            def fail_before_commit(*args, **kwargs):
                raise RuntimeError("forced nervous crash before commit")

            resident._before_nervous_outcome_commit = fail_before_commit
            completed = self._complete(resident, event)

            self.assertTrue(completed.success)
            self.assertIsNotNone(resident.store.get_event_outcome(event.event_id))
            self.assertFalse(has_event_outcome(resident.nervous, event.event_id))
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            self.assertTrue(has_event_outcome(restored.nervous, event.event_id))
            outcome_traces = [
                trace
                for trace in restored.nervous.recent_traces(100)
                if trace.channel == "outcome"
                and trace.metadata.get("event_id") == event.event_id
            ]
            self.assertEqual(len(outcome_traces), 1)
            self.assertEqual(outcome_traces[0].repetitions, 1)
            trace_id = outcome_traces[0].trace_id
            restored.store.close()

            restarted_again = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            same_trace = restarted_again.nervous._get_trace(trace_id)
            self.assertIsNotNone(same_trace)
            self.assertEqual(same_trace.repetitions, 1)
            self.assertTrue(has_event_outcome(restarted_again.nervous, event.event_id))
            restarted_again.store.close()

    def test_successful_completion_receives_nervous_receipt_without_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            event = resident.enqueue(
                "observe immediate durable outcome perception",
                payload={"model_policy": "never"},
            )

            completed = self._complete(resident, event)

            self.assertTrue(completed.success)
            self.assertTrue(has_event_outcome(resident.nervous, event.event_id))
            matching = [
                trace
                for trace in resident.nervous.recent_traces(100)
                if trace.channel == "outcome"
                and trace.metadata.get("event_id") == event.event_id
            ]
            self.assertEqual(len(matching), 1)
            resident.store.close()

    def test_final_nervous_owner_cannot_prune_a_receipted_outcome_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            event = resident.enqueue(
                "retain terminal outcome identity through nervous pruning",
                payload={"model_policy": "never"},
            )
            completed = self._complete(resident, event)
            matching = [
                trace
                for trace in resident.nervous.recent_traces(100)
                if trace.channel == "outcome"
                and trace.metadata.get("event_id") == event.event_id
            ]
            self.assertEqual(len(matching), 1)
            trace = matching[0]

            self.assertFalse(resident.nervous._delete_trace(trace.trace_id))
            self.assertIsNotNone(resident.nervous._get_trace(trace.trace_id))
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            try:
                restored_event = restored.store.get_event(event.event_id)
                restored_outcome = restored.store.get_event_outcome(event.event_id)
                retried = restored._perceive_event_outcome(
                    restored_event,
                    restored_outcome,
                )

                self.assertEqual(retried.trace_id, trace.trace_id)
                self.assertEqual(retried.repetitions, trace.repetitions)
                self.assertTrue(has_event_outcome(restored.nervous, event.event_id))
                self.assertTrue(completed.success)
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main()
