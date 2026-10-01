from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class RecurringWillBehaviorTests(unittest.TestCase):
    @staticmethod
    def _resident(db: Path):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=db,
        )

    def test_due_trigger_materializes_into_existing_will_and_event_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            now = datetime.now(timezone.utc)
            intention = resident.schedule_recurring_intention(
                "keep this project status grounded over time",
                task="review the current project status from fresh evidence",
                interval_seconds=60,
                source="user",
                priority=4,
                first_due_at=now - timedelta(seconds=1),
            )

            activated = resident.recurring_will.activate_due(now=now)
            self.assertEqual(len(activated), 1)

            ready = resident.will.get(intention.intention_id)
            self.assertIsNotNone(ready)
            assert ready is not None
            self.assertEqual(
                ready.next_task,
                "review the current project status from fresh evidence",
            )
            self.assertFalse(ready.next_payload["execution_authority"])
            self.assertTrue(ready.next_payload["fresh_revalidation_required"])
            self.assertEqual(
                ready.next_payload["recurring_intention_id"],
                intention.intention_id,
            )

            trigger = resident.recurring_will.get(intention.intention_id)
            self.assertIsNotNone(trigger)
            assert trigger is not None
            self.assertIsNone(trigger.pending_scheduled_at)
            self.assertGreater(
                datetime.fromisoformat(trigger.next_due_at),
                now,
            )

            pulse = resident.pulse()
            self.assertEqual(pulse.thought.action_kind, "intention")
            self.assertEqual(pulse.thought.action_target, intention.intention_id)

            # The recurring organ never executes the task itself. The existing
            # Will path creates the ordinary durable event on the next life step.
            self.assertIsNone(resident.live_once())
            engaged = resident.will.get(intention.intention_id)
            self.assertIsNotNone(engaged)
            assert engaged is not None
            self.assertEqual(engaged.status, "engaged")
            self.assertIsNotNone(engaged.related_event_id)

            event = resident.store.get_event(engaged.related_event_id)
            self.assertIsNotNone(event)
            assert event is not None
            self.assertEqual(event.kind, "intention_step")
            self.assertFalse(event.payload["execution_authority"])
            self.assertTrue(event.payload["fresh_revalidation_required"])
            self.assertEqual(event.payload["intention_id"], intention.intention_id)
            self.assertEqual(len(resident.store.list_events(limit=20)), 1)
            resident.store.close()

    def test_pending_occurrence_recovers_after_restart_without_duplicate_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            fixed = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
            first = self._resident(db)
            intention = first.schedule_recurring_intention(
                "periodically reassess one durable goal",
                task="reassess the durable goal from current evidence",
                interval_seconds=60,
                first_due_at=fixed - timedelta(seconds=1),
            )

            original_set_next_step = first.will.set_next_step

            def crash_before_will_handoff(*args, **kwargs):
                raise RuntimeError("simulated crash before Will handoff")

            first.will.set_next_step = crash_before_will_handoff
            try:
                with self.assertRaisesRegex(RuntimeError, "before Will handoff"):
                    first.recurring_will.activate_due(now=fixed)
            finally:
                first.will.set_next_step = original_set_next_step

            stamped = first.recurring_will.get(intention.intention_id)
            self.assertIsNotNone(stamped)
            assert stamped is not None
            self.assertIsNotNone(stamped.pending_scheduled_at)
            self.assertGreater(datetime.fromisoformat(stamped.next_due_at), fixed)
            self.assertIsNone(first.will.get(intention.intention_id).next_task)
            pending_at = stamped.pending_scheduled_at
            first.store.close()

            restored = self._resident(db)
            recovered = restored.recurring_will.activate_due(now=fixed)
            self.assertEqual(len(recovered), 1)
            ready = restored.will.get(intention.intention_id)
            self.assertIsNotNone(ready)
            assert ready is not None
            self.assertEqual(
                ready.next_payload["recurring_scheduled_at"],
                pending_at,
            )
            trigger = restored.recurring_will.get(intention.intention_id)
            self.assertIsNotNone(trigger)
            assert trigger is not None
            self.assertIsNone(trigger.pending_scheduled_at)

            # The same resident time cannot hand the recovered occurrence to
            # Will twice, and the normal Will path creates one event only.
            self.assertEqual(restored.recurring_will.activate_due(now=fixed), [])
            self.assertIsNone(restored.live_once())
            self.assertEqual(len(restored.store.list_events(limit=20)), 1)
            restored.store.close()

    def test_missed_intervals_coalesce_and_engaged_intention_never_overlaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            fixed = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
            intention = resident.intend(
                "keep one recurring objective alive",
                source="user",
                priority=3,
            )
            resident.recurring_will.register(
                intention.intention_id,
                task="inspect the recurring objective using current evidence",
                interval_seconds=60,
                first_due_at=fixed - timedelta(seconds=4 * 60),
            )

            first = resident.recurring_will.activate_due(now=fixed)
            self.assertEqual(len(first), 1)
            ready = resident.will.get(intention.intention_id)
            self.assertIsNotNone(ready)
            assert ready is not None
            self.assertEqual(ready.next_payload["recurring_coalesced_missed"], 4)
            self.assertEqual(
                datetime.fromisoformat(ready.next_payload["recurring_scheduled_at"]),
                fixed,
            )
            trigger = resident.recurring_will.get(intention.intention_id)
            self.assertEqual(
                datetime.fromisoformat(trigger.next_due_at),
                fixed + timedelta(seconds=60),
            )
            self.assertEqual(resident.recurring_will.activate_due(now=fixed), [])

            resident.will.engage(intention.intention_id, "evt-recurring-held")
            later = fixed + timedelta(seconds=4 * 60)
            self.assertEqual(resident.recurring_will.activate_due(now=later), [])
            still_waiting = resident.recurring_will.get(intention.intention_id)
            self.assertEqual(
                datetime.fromisoformat(still_waiting.next_due_at),
                fixed + timedelta(seconds=60),
            )

            resident.will.observe_event_outcome(
                intention.intention_id,
                event_id="evt-recurring-held",
                success=True,
                summary="the prior recurring occurrence finished",
            )
            second = resident.recurring_will.activate_due(now=later)
            self.assertEqual(len(second), 1)
            next_ready = resident.will.get(intention.intention_id)
            self.assertIsNotNone(next_ready)
            assert next_ready is not None
            self.assertEqual(
                next_ready.next_payload["recurring_coalesced_missed"],
                3,
            )
            self.assertEqual(
                datetime.fromisoformat(
                    next_ready.next_payload["recurring_scheduled_at"]
                ),
                later,
            )
            self.assertEqual(resident.recurring_will.activate_due(now=later), [])
            resident.store.close()

    def test_trigger_admission_is_bounded_and_registration_failure_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            with self.assertRaisesRegex(ValueError, "at least 60 seconds"):
                resident.schedule_recurring_intention(
                    "do not create a tight resident loop",
                    task="reassess current state",
                    interval_seconds=1,
                )

            rows = resident.will.list_all(limit=20)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, "paused")
            self.assertEqual(resident.recurring_will.list(), [])

            with self.assertRaisesRegex(ValueError, "timezone offset"):
                resident.recurring_will.register(
                    rows[0].intention_id,
                    task="reassess current state",
                    interval_seconds=60,
                    first_due_at="2026-09-16T12:00:00",
                )
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
