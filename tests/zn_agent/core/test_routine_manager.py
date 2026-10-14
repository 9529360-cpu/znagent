from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class RoutineManagerTests(unittest.TestCase):
    @staticmethod
    def _resident(db: Path):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=db,
        )

    def _confirm(self, resident, text: str) -> dict:
        draft = resident.routines.propose(text)
        return resident.routines.confirm(draft)

    def test_propose_confirm_stores_all_six_confirmations(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            routine = self._confirm(resident, "每个工作日 9 点汇总昨天的进展")
            self.assertEqual(routine["task"], "汇总昨天的进展")
            self.assertEqual(routine["status"], "active")
            self.assertEqual(routine["owner"], "ZN")
            self.assertEqual(routine["schedule_kind"], "cron")
            self.assertEqual(routine["schedule_spec"], "0 9 * * 1-5")
            self.assertTrue(routine["input_source"])
            self.assertTrue(routine["expected_result"])
            self.assertTrue(routine["approval_boundary"])
            self.assertEqual(routine["missing_data_policy"], "skip")
            self.assertEqual(routine["auto_pause_after_days"], 14)

            # The underlying trigger organ owns the cadence.
            trigger = resident.recurring_will.get(routine["intention_id"])
            self.assertIsNotNone(trigger)
            assert trigger is not None
            self.assertEqual(trigger.schedule_kind, "cron")
            self.assertEqual(trigger.cron_expression, "0 9 * * 1-5")

            # Status exposes the routine list.
            routines = resident.status()["routines"]
            self.assertEqual(routines["routine_count"], 1)
            self.assertEqual(routines["active_count"], 1)
            resident.store.close()

    def test_pause_resume_edit_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            routine = self._confirm(resident, "每 2 小时检查一次收件箱")
            routine_id = routine["routine_id"]

            paused = resident.routines.pause(routine_id)
            self.assertEqual(paused["status"], "paused")
            self.assertIsNotNone(resident.recurring_will.get(routine["intention_id"]))
            self.assertFalse(
                resident.recurring_will.get(routine["intention_id"]).enabled
            )

            resumed = resident.routines.resume(routine_id)
            self.assertEqual(resumed["status"], "active")
            self.assertTrue(
                resident.recurring_will.get(routine["intention_id"]).enabled
            )

            edited = resident.routines.edit(
                routine_id,
                fields={
                    "task": "检查一次收件箱并汇总未读",
                    "approval_boundary": "只读，不发送",
                    "interval_seconds": 3600,
                },
            )
            self.assertEqual(edited["task"], "检查一次收件箱并汇总未读")
            self.assertEqual(edited["approval_boundary"], "只读，不发送")
            trigger = resident.recurring_will.get(routine["intention_id"])
            self.assertEqual(trigger.interval_seconds, 3600)
            self.assertEqual(trigger.task, "检查一次收件箱并汇总未读")

            deleted = resident.routines.delete(routine_id)
            self.assertTrue(deleted["deleted"])
            self.assertIsNone(resident.routines.get(routine_id))
            self.assertEqual(
                resident.will.get(routine["intention_id"]).status, "completed"
            )
            resident.store.close()

    def test_test_run_is_real_execution_and_closes_on_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            routine = self._confirm(resident, "每 2 小时检查一次收件箱")
            routine_id = routine["routine_id"]
            intention_id = routine["intention_id"]

            run = resident.routines.test_run(routine_id)
            self.assertEqual(run["status"], "running")
            self.assertEqual(run["trigger_kind"], "test_run")
            # A second test run while one is in flight is rejected.
            with self.assertRaisesRegex(ValueError, "in flight"):
                resident.routines.test_run(routine_id)

            # The normal Will path picks the task up and creates the event.
            resident.pulse()
            resident.live_once()
            engaged = resident.will.get(intention_id)
            self.assertEqual(engaged.status, "engaged")
            event = resident.store.get_event(engaged.related_event_id)
            self.assertEqual(event.payload["routine_run_id"], run["run_id"])
            self.assertEqual(
                event.payload["routine_approval_boundary"],
                routine["approval_boundary"],
            )

            resident.will.observe_event_outcome(
                intention_id,
                event_id=engaged.related_event_id,
                success=True,
                summary="收件箱已检查",
            )
            runs = resident.routines.runs(routine_id)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["status"], "succeeded")
            self.assertEqual(runs[0]["summary"], "收件箱已检查")
            resident.store.close()

    def test_scheduled_run_records_failure_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            routine = self._confirm(resident, "每 2 分钟检查一次收件箱")
            routine_id = routine["routine_id"]
            intention_id = routine["intention_id"]

            future = datetime.now(timezone.utc) + timedelta(minutes=3)
            activated = resident.recurring_will.activate_due(now=future)
            self.assertEqual(len(activated), 1)
            runs = resident.routines.runs(routine_id)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["status"], "running")
            self.assertEqual(runs[0]["trigger_kind"], "scheduled")

            resident.pulse()
            resident.live_once()
            engaged = resident.will.get(intention_id)
            resident.will.observe_event_outcome(
                intention_id,
                event_id=engaged.related_event_id,
                success=False,
                summary="收件箱不可达",
            )
            runs = resident.routines.runs(routine_id)
            self.assertEqual(runs[0]["status"], "failed")
            self.assertEqual(runs[0]["failure_reason"], "收件箱不可达")
            resident.store.close()

    def test_cron_trigger_activates_on_wall_clock_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            routine = self._confirm(resident, "每天 9 点汇总昨天的进展")
            trigger = resident.recurring_will.get(routine["intention_id"])
            due = datetime.fromisoformat(trigger.next_due_at)
            # Just past the 09:00 due instant the occurrence materializes.
            activated = resident.recurring_will.activate_due(
                now=due + timedelta(minutes=1)
            )
            self.assertEqual(len(activated), 1)
            runs = resident.routines.runs(routine["routine_id"])
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["trigger_kind"], "scheduled")
            # The next due jumps to the following day (no backlog burst).
            after = resident.recurring_will.get(routine["intention_id"])
            self.assertGreater(
                datetime.fromisoformat(after.next_due_at),
                due,
            )
            resident.store.close()

    def test_run_history_capped_at_twenty(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            routine = self._confirm(resident, "每 2 分钟检查一次收件箱")
            for index in range(25):
                resident.routines._start_run(
                    resident.routines.get(routine["routine_id"]),
                    trigger_kind="scheduled",
                    scheduled_at=(
                        datetime.now(timezone.utc) + timedelta(minutes=index)
                    ).isoformat(),
                )
            self.assertEqual(len(resident.routines.runs(routine["routine_id"])), 20)
            resident.store.close()

    def test_auto_pause_after_no_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            routine = self._confirm(resident, "每 2 分钟检查一次收件箱")
            routine_id = routine["routine_id"]
            # One finished run after confirmation: the routine ran and
            # nobody responded.
            run = resident.routines.test_run(routine_id)
            resident.pulse()
            resident.live_once()
            engaged = resident.will.get(routine["intention_id"])
            resident.will.observe_event_outcome(
                routine["intention_id"],
                event_id=engaged.related_event_id,
                success=True,
                summary="done",
            )
            self.assertEqual(
                resident.routines.runs(routine_id)[0]["status"], "succeeded"
            )

            future = datetime.now(timezone.utc) + timedelta(days=15)
            paused = resident.routines.sweep(now=future)
            self.assertEqual(paused, [routine_id])
            after = resident.routines.get(routine_id)
            self.assertEqual(after.status, "paused")
            self.assertTrue(after.paused_reason.startswith("已自动暂停"))
            self.assertIn(routine_id, resident.status()["routines"]["needs_attention"])
            resident.store.close()

    def test_auto_pause_skips_silent_routines(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            routine = self._confirm(resident, "每 2 分钟检查一次收件箱")
            # No runs since confirmation: silence is not "no response".
            future = datetime.now(timezone.utc) + timedelta(days=30)
            self.assertEqual(resident.routines.sweep(now=future), [])
            self.assertEqual(
                resident.routines.get(routine["routine_id"]).status, "active"
            )
            resident.store.close()

    def test_confirm_rejects_unconfirmed_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            with self.assertRaisesRegex(ValueError, "task must not be empty"):
                resident.routines.confirm({"task": "", "owner": "ZN"})
            self.assertEqual(resident.routines.list_routines(), [])
            resident.store.close()

    def test_rpc_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            server = ResidentRpcServer(resident=resident)

            def call(method: str, params: dict) -> dict:
                response = server.handle({"id": 1, "method": method, "params": params})
                self.assertTrue(response.get("ok"), response)
                return response["result"]

            draft = call("routine_propose", {"text": "每个工作日 9 点汇总昨天的进展"})
            self.assertEqual(draft["task"], "汇总昨天的进展")
            routine = call("routine_confirm", {"draft": draft})
            routine_id = routine["routine_id"]
            listed = call("routine_list", {})
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["routine_id"], routine_id)
            run = call("routine_test_run", {"routine_id": routine_id})
            self.assertEqual(run["trigger_kind"], "test_run")
            # Pause is rejected while the test run is in flight rather than
            # clobbering it; after the run closes, pause succeeds. handle()
            # propagates the rejection (serve_forever wraps it into an
            # error response on the wire).
            with self.assertRaisesRegex(ValueError, "in flight"):
                server.handle(
                    {
                        "id": 2,
                        "method": "routine_pause",
                        "params": {"routine_id": routine_id},
                    }
                )
            resident.pulse()
            resident.live_once()
            engaged = resident.will.get(routine["intention_id"])
            resident.will.observe_event_outcome(
                routine["intention_id"],
                event_id=engaged.related_event_id,
                success=True,
                summary="done",
            )
            paused = call("routine_pause", {"routine_id": routine_id})
            self.assertEqual(paused["status"], "paused")
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
