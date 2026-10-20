from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.recurring_will_behavior import fingerprint_file


class FileChangeTriggerTests(unittest.TestCase):
    @staticmethod
    def _resident(db: Path):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=db,
        )

    def _register(self, resident, path: Path, **kwargs):
        intention = resident.intend(
            "watch a file for changes",
            source="user",
            priority=0,
            complete_on_step_success=False,
        )
        kwargs.setdefault("task", "process the changed file")
        kwargs.setdefault("debounce_seconds", 0)
        trigger = resident.recurring_will.register(
            intention.intention_id,
            schedule_kind="file_changed",
            file_path=str(path),
            **kwargs,
        )
        return intention, trigger

    def test_change_generates_exactly_one_occurrence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            watched = Path(tmp) / "inbox.txt"
            watched.write_text("v0")
            resident = self._resident(db)
            now = datetime.now(timezone.utc)
            intention, trigger = self._register(resident, watched)

            # The registration baselines the current content: no fire yet.
            self.assertEqual(resident.recurring_will.activate_due(now=now), [])
            self.assertIsNone(resident.will.get(intention.intention_id).next_task)
            self.assertEqual(trigger.file_fingerprint, fingerprint_file(str(watched)))

            watched.write_text("v1")
            activated = resident.recurring_will.activate_due(now=now)
            self.assertEqual(len(activated), 1)

            ready = resident.will.get(intention.intention_id)
            self.assertIsNotNone(ready)
            assert ready is not None
            self.assertEqual(ready.next_task, "process the changed file")
            payload = ready.next_payload
            self.assertFalse(payload["execution_authority"])
            self.assertTrue(payload["fresh_revalidation_required"])
            self.assertEqual(payload["recurring_intention_id"], intention.intention_id)
            self.assertEqual(payload["recurring_schedule_kind"], "file_changed")
            self.assertEqual(payload["file_trigger_path"], str(watched))
            self.assertEqual(
                payload["file_trigger_fingerprint"], fingerprint_file(str(watched))
            )
            self.assertEqual(payload["recurring_coalesced_missed"], 1)

            # The pending stamp clears once the occurrence reaches Will.
            stamped = resident.recurring_will.get(intention.intention_id)
            self.assertIsNotNone(stamped)
            assert stamped is not None
            self.assertIsNone(stamped.pending_scheduled_at)

            # The same quiet fingerprint never fires twice.
            self.assertEqual(resident.recurring_will.activate_due(now=now), [])

            # The trigger never executes itself: the ordinary Will event
            # path creates exactly one durable event.
            self.assertIsNone(resident.live_once())
            engaged = resident.will.get(intention.intention_id)
            self.assertIsNotNone(engaged)
            assert engaged is not None
            self.assertEqual(engaged.status, "engaged")
            event = resident.store.get_event(engaged.related_event_id)
            self.assertIsNotNone(event)
            assert event is not None
            self.assertEqual(event.kind, "intention_step")
            self.assertTrue(event.payload["fresh_revalidation_required"])
            self.assertEqual(len(resident.store.list_events(limit=20)), 1)
            resident.store.close()

    def test_debounce_window_merges_burst_into_one_trailing_edge(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            watched = Path(tmp) / "inbox.txt"
            watched.write_text("v0")
            resident = self._resident(db)
            t0 = datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)
            intention, _ = self._register(resident, watched, debounce_seconds=3600)

            watched.write_text("v1")
            self.assertEqual(resident.recurring_will.activate_due(now=t0), [])
            first = resident.recurring_will.get(intention.intention_id)
            assert first is not None
            self.assertEqual(first.last_change_at, t0.isoformat())
            self.assertEqual(first.file_change_count, 1)
            self.assertIsNone(resident.will.get(intention.intention_id).next_task)

            # A second change inside the window restarts it (trailing edge).
            t1 = t0 + timedelta(seconds=10)
            watched.write_text("v2")
            self.assertEqual(resident.recurring_will.activate_due(now=t1), [])
            second = resident.recurring_will.get(intention.intention_id)
            assert second is not None
            self.assertEqual(second.last_change_at, t1.isoformat())
            self.assertEqual(second.file_change_count, 2)

            t2 = t1 + timedelta(seconds=10)
            watched.write_text("v3")
            self.assertEqual(resident.recurring_will.activate_due(now=t2), [])
            third = resident.recurring_will.get(intention.intention_id)
            assert third is not None
            self.assertEqual(third.file_change_count, 3)

            # Still inside the restarted window: nothing due.
            self.assertEqual(
                resident.recurring_will.activate_due(now=t2 + timedelta(seconds=3599)),
                [],
            )
            self.assertIsNone(resident.will.get(intention.intention_id).next_task)

            # One second past the quiet window: exactly one occurrence for
            # the whole burst, carrying the final fingerprint.
            due_at = t2 + timedelta(seconds=3601)
            activated = resident.recurring_will.activate_due(now=due_at)
            self.assertEqual(len(activated), 1)
            ready = resident.will.get(intention.intention_id)
            assert ready is not None
            payload = ready.next_payload
            self.assertEqual(payload["recurring_coalesced_missed"], 3)
            self.assertEqual(
                payload["file_trigger_fingerprint"], fingerprint_file(str(watched))
            )
            self.assertEqual(payload["file_trigger_changed_at"], t2.isoformat())
            self.assertEqual(payload["file_trigger_debounce_seconds"], 3600)
            # recurring_scheduled_at is the instant the change became due
            # (last change + debounce), not the poll instant.
            self.assertEqual(
                payload["recurring_scheduled_at"],
                (t2 + timedelta(seconds=3600)).isoformat(),
            )

            self.assertIsNone(resident.live_once())
            self.assertEqual(len(resident.store.list_events(limit=20)), 1)
            # And no second occurrence afterwards.
            self.assertEqual(
                resident.recurring_will.activate_due(now=due_at + timedelta(hours=2)),
                [],
            )
            resident.store.close()

    def test_quiet_file_never_fires(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            watched = Path(tmp) / "inbox.txt"
            watched.write_text("steady")
            resident = self._resident(db)
            intention, _ = self._register(resident, watched, debounce_seconds=60)
            base = datetime(2026, 10, 20, 4, 0, tzinfo=timezone.utc)
            for offset in (0, 100, 10000):
                self.assertEqual(
                    resident.recurring_will.activate_due(
                        now=base + timedelta(seconds=offset)
                    ),
                    [],
                )
            self.assertIsNone(resident.will.get(intention.intention_id).next_task)
            resident.store.close()

    def test_created_file_triggers_from_missing_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            watched = Path(tmp) / "appears-later.txt"
            resident = self._resident(db)
            now = datetime.now(timezone.utc)
            intention, trigger = self._register(resident, watched)
            self.assertEqual(trigger.file_fingerprint, "missing")

            self.assertEqual(resident.recurring_will.activate_due(now=now), [])

            watched.write_text("now I exist")
            activated = resident.recurring_will.activate_due(now=now)
            self.assertEqual(len(activated), 1)
            ready = resident.will.get(intention.intention_id)
            assert ready is not None
            self.assertEqual(ready.next_payload["file_trigger_path"], str(watched))
            resident.store.close()

    def test_deleted_file_triggers_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            watched = Path(tmp) / "doomed.txt"
            watched.write_text("here today")
            resident = self._resident(db)
            now = datetime.now(timezone.utc)
            intention, _ = self._register(resident, watched)

            watched.unlink()
            activated = resident.recurring_will.activate_due(now=now)
            self.assertEqual(len(activated), 1)
            ready = resident.will.get(intention.intention_id)
            assert ready is not None
            self.assertEqual(ready.next_payload["file_trigger_fingerprint"], "missing")
            # A persistently missing file does not re-trigger.
            self.assertEqual(resident.recurring_will.activate_due(now=now), [])
            resident.store.close()

    def test_restart_neither_loses_nor_bursts(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            watched = Path(tmp) / "inbox.txt"
            watched.write_text("v0")
            t0 = datetime(2026, 10, 20, 5, 0, tzinfo=timezone.utc)

            first = self._resident(db)
            intention, _ = self._register(first, watched, debounce_seconds=3600)
            watched.write_text("v1")
            self.assertEqual(first.recurring_will.activate_due(now=t0), [])
            first.store.close()

            # Restart with the file now quiet: the pending change is not
            # lost, and it still fires exactly once after the window.
            second = self._resident(db)
            self.assertEqual(
                second.recurring_will.activate_due(now=t0 + timedelta(seconds=1800)),
                [],
            )
            activated = second.recurring_will.activate_due(
                now=t0 + timedelta(seconds=3601)
            )
            self.assertEqual(len(activated), 1)
            ready = second.will.get(intention.intention_id)
            assert ready is not None
            self.assertEqual(ready.next_task, "process the changed file")
            self.assertEqual(
                ready.next_payload["file_trigger_fingerprint"],
                fingerprint_file(str(watched)),
            )
            # No burst on later pulses.
            self.assertEqual(
                second.recurring_will.activate_due(now=t0 + timedelta(hours=5)), []
            )
            second.store.close()

    def test_change_while_down_fires_once_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            watched = Path(tmp) / "inbox.txt"
            watched.write_text("v0")
            t_down = datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)

            first = self._resident(db)
            intention, _ = self._register(first, watched, debounce_seconds=3600)
            first.store.close()

            # The file changes while no process is polling.
            watched.write_text("v1")

            second = self._resident(db)
            # The change is observed at restart and starts a fresh window;
            # it does not fire immediately and does not burst.
            self.assertEqual(second.recurring_will.activate_due(now=t_down), [])
            changed = second.recurring_will.get(intention.intention_id)
            assert changed is not None
            self.assertEqual(changed.last_change_at, t_down.isoformat())

            activated = second.recurring_will.activate_due(
                now=t_down + timedelta(seconds=3601)
            )
            self.assertEqual(len(activated), 1)
            ready = second.will.get(intention.intention_id)
            assert ready is not None
            self.assertEqual(ready.next_payload["recurring_coalesced_missed"], 1)
            self.assertEqual(
                second.recurring_will.activate_due(
                    now=t_down + timedelta(hours=3)
                ),
                [],
            )
            second.store.close()

    def test_crash_between_stamp_and_handoff_recovers_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            watched = Path(tmp) / "inbox.txt"
            watched.write_text("v0")
            fixed = datetime(2026, 10, 20, 7, 0, tzinfo=timezone.utc)

            first = self._resident(db)
            intention, _ = self._register(first, watched)
            watched.write_text("v1")

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
            self.assertIsNone(first.will.get(intention.intention_id).next_task)
            pending_at = stamped.pending_scheduled_at
            first.store.close()

            restored = self._resident(db)
            recovered = restored.recurring_will.activate_due(now=fixed)
            self.assertEqual(len(recovered), 1)
            ready = restored.will.get(intention.intention_id)
            assert ready is not None
            self.assertEqual(ready.next_payload["recurring_scheduled_at"], pending_at)
            self.assertEqual(
                ready.next_payload["file_trigger_fingerprint"],
                fingerprint_file(str(watched)),
            )
            trigger = restored.recurring_will.get(intention.intention_id)
            assert trigger is not None
            self.assertIsNone(trigger.pending_scheduled_at)

            # No duplicate handoff on the next pulse.
            self.assertEqual(restored.recurring_will.activate_due(now=fixed), [])
            self.assertIsNone(restored.live_once())
            self.assertEqual(len(restored.store.list_events(limit=20)), 1)
            restored.store.close()

    def test_invalid_registration_params_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            watched = Path(tmp) / "inbox.txt"
            watched.write_text("v0")
            resident = self._resident(db)

            with self.assertRaises(KeyError):
                resident.recurring_will.register(
                    "intention-that-does-not-exist",
                    task="x",
                    schedule_kind="file_changed",
                    file_path=str(watched),
                )

            intention = resident.intend(
                "watch a file",
                source="user",
                priority=0,
                complete_on_step_success=False,
            )
            with self.assertRaisesRegex(ValueError, "file_path"):
                resident.recurring_will.register(
                    intention.intention_id,
                    task="x",
                    schedule_kind="file_changed",
                    file_path="   ",
                )
            with self.assertRaisesRegex(ValueError, "debounce_seconds"):
                resident.recurring_will.register(
                    intention.intention_id,
                    task="x",
                    schedule_kind="file_changed",
                    file_path=str(watched),
                    debounce_seconds=-5,
                )
            # Nothing was registered by the failed attempts.
            self.assertIsNone(
                resident.recurring_will.get(intention.intention_id)
            )
            resident.store.close()

    def test_disable_stops_polling(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            watched = Path(tmp) / "inbox.txt"
            watched.write_text("v0")
            resident = self._resident(db)
            now = datetime.now(timezone.utc)
            intention, _ = self._register(resident, watched)

            resident.recurring_will.disable(intention.intention_id)
            watched.write_text("v1")
            self.assertEqual(resident.recurring_will.activate_due(now=now), [])
            self.assertIsNone(resident.will.get(intention.intention_id).next_task)
            resident.store.close()

    def test_schedule_file_change_intention_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            watched = Path(tmp) / "inbox.txt"
            watched.write_text("v0")
            resident = self._resident(db)
            now = datetime.now(timezone.utc)

            intention = resident.schedule_file_change_intention(
                "watch the inbox file",
                task="handle the inbox change",
                file_path=str(watched),
                debounce_seconds=0,
                source="user",
                priority=1,
            )
            trigger = resident.recurring_will.get(intention.intention_id)
            self.assertIsNotNone(trigger)
            assert trigger is not None
            self.assertEqual(trigger.schedule_kind, "file_changed")
            self.assertEqual(trigger.file_path, str(watched))
            self.assertEqual(trigger.debounce_seconds, 0)

            watched.write_text("v1")
            activated = resident.recurring_will.activate_due(now=now)
            self.assertEqual(len(activated), 1)
            ready = resident.will.get(intention.intention_id)
            assert ready is not None
            self.assertEqual(ready.next_task, "handle the inbox change")

            triggers = resident.status()["recurring_will"]["triggers"]
            kinds = {
                item["intention_id"]: item["schedule_kind"] for item in triggers
            }
            self.assertEqual(kinds.get(intention.intention_id), "file_changed")
            resident.store.close()

    def test_fingerprint_file_missing_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp:
            ghost = Path(tmp) / "nope.txt"
            self.assertEqual(fingerprint_file(str(ghost)), "missing")
            real = Path(tmp) / "real.txt"
            real.write_text("same")
            first = fingerprint_file(str(real))
            self.assertTrue(first.startswith("sha256:"))
            self.assertEqual(first, fingerprint_file(str(real)))
            real.write_text("different")
            self.assertNotEqual(first, fingerprint_file(str(real)))
