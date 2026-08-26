from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.event_outcome_nervous import EventOutcomeNervousSystem
from zn_agent.core.store import KernelStore


class FailingEventOutcomeNervousSystem(EventOutcomeNervousSystem):
    def _before_event_outcome_commit(self, conn, *, event_id, trace) -> None:
        raise RuntimeError("forced failure before nervous outcome commit")


class EventOutcomeNervousSystemTests(unittest.TestCase):
    @staticmethod
    def _outcome(nervous, event_id: str, *, summary: str = "deploy: completed"):
        return nervous.perceive_event_outcome(
            event_id,
            summary,
            features=("task", "native", "success"),
            salience=0.62,
            valence=0.52,
            arousal=0.42,
            metadata={"model_invocations": 0},
        )

    def test_same_event_identity_is_a_complete_plasticity_noop_on_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            nervous = EventOutcomeNervousSystem(store)
            anchor = nervous.perceive(
                "world",
                "resident observed a stable workspace",
                features=("workspace",),
                salience=0.55,
            )

            first = self._outcome(nervous, "event-1")
            first_state = nervous.snapshot()
            first_link = nervous.link_strength(first.trace_id, anchor.trace_id)
            first_repetitions = first.repetitions

            second = self._outcome(nervous, "event-1")
            second_state = nervous.snapshot()
            second_link = nervous.link_strength(second.trace_id, anchor.trace_id)

            self.assertEqual(second.trace_id, first.trace_id)
            self.assertEqual(second.repetitions, first_repetitions)
            self.assertEqual(second_state, first_state)
            self.assertAlmostEqual(second_link, first_link)
            self.assertTrue(nervous.has_event_outcome("event-1"))
            store.close()

    def test_distinct_events_with_same_lived_result_still_strengthen_one_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            nervous = EventOutcomeNervousSystem(store)

            first = self._outcome(nervous, "event-1")
            second = self._outcome(nervous, "event-2")

            self.assertEqual(second.trace_id, first.trace_id)
            self.assertEqual(second.repetitions, first.repetitions + 1)
            self.assertTrue(nervous.has_event_outcome("event-1"))
            self.assertTrue(nervous.has_event_outcome("event-2"))
            store.close()

    def test_failure_before_commit_rolls_back_trace_links_affect_and_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            store = KernelStore(db)
            baseline = EventOutcomeNervousSystem(store)
            anchor = baseline.perceive(
                "world",
                "resident observed a stable workspace",
                features=("workspace",),
                salience=0.55,
            )
            baseline_state = baseline.snapshot()
            baseline_traces = baseline.recent_traces(20)
            cutoff = baseline.repair_from()

            failing = FailingEventOutcomeNervousSystem(store)
            with self.assertRaisesRegex(RuntimeError, "forced failure"):
                self._outcome(failing, "event-crash")

            restored = EventOutcomeNervousSystem(store)
            after_failure = restored.recent_traces(20)
            self.assertEqual(after_failure, baseline_traces)
            self.assertEqual(restored.snapshot(), baseline_state)
            self.assertFalse(restored.has_event_outcome("event-crash"))
            self.assertEqual(restored.repair_from(), cutoff)
            self.assertFalse(
                any(trace.channel == "outcome" for trace in after_failure)
            )

            committed = self._outcome(restored, "event-crash")
            self.assertTrue(restored.has_event_outcome("event-crash"))
            self.assertGreater(
                restored.link_strength(committed.trace_id, anchor.trace_id),
                0.0,
            )
            self.assertEqual(committed.repetitions, 1)
            store.close()

    def test_restart_retry_uses_persisted_receipt_without_reinforcement(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first_store = KernelStore(db)
            first = EventOutcomeNervousSystem(first_store)
            trace = self._outcome(first, "event-restart")
            before = first.snapshot()
            cutoff = first.repair_from()
            first_store.close()

            second_store = KernelStore(db)
            second = EventOutcomeNervousSystem(second_store)
            retried = self._outcome(second, "event-restart")

            self.assertEqual(retried.trace_id, trace.trace_id)
            self.assertEqual(retried.repetitions, trace.repetitions)
            self.assertEqual(second.snapshot(), before)
            self.assertEqual(second.repair_from(), cutoff)
            second_store.close()


if __name__ == "__main__":
    unittest.main()
