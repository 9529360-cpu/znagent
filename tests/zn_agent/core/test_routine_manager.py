from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing as closing_sqlite
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zn_agent.core.approval_cards import ApprovalCardStore
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

    def _approve_pending_card(self, db: Path, *, decision: str = "allow_once") -> dict:
        """Decide the single pending approval card for a held occurrence."""
        store = ApprovalCardStore(str(db))
        pending = store.pending_requests()
        self.assertEqual(len(pending), 1, f"expected one pending card, got {len(pending)}")
        decided = store.decide(pending[0].request_id, decision)
        return decided.to_dict()

    def _pending_cards(self, db: Path) -> list:
        return ApprovalCardStore(str(db)).pending_requests()

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
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            routine = self._confirm(resident, "每 2 小时检查一次收件箱")
            routine_id = routine["routine_id"]
            intention_id = routine["intention_id"]

            # The default boundary holds the test run: nothing is handed
            # to Will until the approval card is decided.
            run = resident.routines.test_run(routine_id)
            self.assertEqual(run["status"], "awaiting_approval")
            self.assertEqual(run["trigger_kind"], "test_run")
            self.assertIsNone(resident.will.get(intention_id).next_task)
            self._approve_pending_card(db)

            # The sweep resumes the held test run on the next pulse.
            resident.pulse()
            resumed = resident.routines.runs(routine_id)
            self.assertEqual(resumed[0]["status"], "running")
            # A second test run while one is in flight is rejected.
            with self.assertRaisesRegex(ValueError, "in flight"):
                resident.routines.test_run(routine_id)

            # The normal Will path picks the task up and creates the event.
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
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            routine = self._confirm(resident, "每 2 分钟检查一次收件箱")
            routine_id = routine["routine_id"]
            intention_id = routine["intention_id"]

            future = datetime.now(timezone.utc) + timedelta(minutes=3)
            activated = resident.recurring_will.activate_due(now=future)
            self.assertEqual(len(activated), 1)
            runs = resident.routines.runs(routine_id)
            self.assertEqual(len(runs), 1)
            # Held for approval: no handoff yet.
            self.assertEqual(runs[0]["status"], "awaiting_approval")
            self.assertEqual(runs[0]["trigger_kind"], "scheduled")
            self.assertIsNone(resident.will.get(intention_id).next_task)

            # Approval releases the occurrence through the trigger retry.
            self._approve_pending_card(db)
            resident.pulse()
            runs = resident.routines.runs(routine_id)
            self.assertEqual(runs[0]["status"], "running")

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

    def test_held_scheduled_occurrence_card_carries_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            routine = self._confirm(resident, "每 2 分钟检查一次收件箱")
            routine_id = routine["routine_id"]
            intention_id = routine["intention_id"]

            future = datetime.now(timezone.utc) + timedelta(minutes=3)
            resident.recurring_will.activate_due(now=future)
            # Held: nothing handed to Will, no event, one card.
            self.assertIsNone(resident.will.get(intention_id).next_task)
            self.assertIsNone(resident.will.get(intention_id).related_event_id)
            cards = self._pending_cards(db)
            self.assertEqual(len(cards), 1)
            card = cards[0]
            self.assertEqual(card.source, "routine")
            self.assertEqual(card.action_kind, "production_change")
            self.assertEqual(card.scope, f"routine:{routine_id}")
            self.assertEqual(card.target, routine["task"])
            self.assertIn(routine["approval_boundary"], card.value_text)

            # Repeated pulses while pending create no duplicate card.
            resident.pulse()
            resident.pulse()
            self.assertEqual(len(self._pending_cards(db)), 1)
            self.assertIsNone(resident.will.get(intention_id).next_task)

            # Approval releases the occurrence through the trigger retry.
            self._approve_pending_card(db)
            resident.pulse()
            self.assertIsNotNone(resident.will.get(intention_id).next_task)
            self.assertEqual(len(self._pending_cards(db)), 0)
            resident.store.close()

    def test_denied_occurrence_never_executes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            routine = self._confirm(resident, "每 2 分钟检查一次收件箱")
            routine_id = routine["routine_id"]
            intention_id = routine["intention_id"]

            future = datetime.now(timezone.utc) + timedelta(minutes=3)
            resident.recurring_will.activate_due(now=future)
            cards = self._pending_cards(db)
            self.assertEqual(len(cards), 1)
            ApprovalCardStore(str(db)).decide(cards[0].request_id, "deny")

            resident.pulse()
            resident.pulse()
            runs = resident.routines.runs(routine_id)
            self.assertEqual(runs[0]["status"], "failed")
            self.assertIn("denied", runs[0]["failure_reason"] or "")
            # Never handed to Will: no task, no event.
            self.assertIsNone(resident.will.get(intention_id).next_task)
            self.assertIsNone(resident.will.get(intention_id).related_event_id)
            # Deny is sticky for the routine's task: a test run is
            # refused too until the user explicitly reconsiders.
            with self.assertRaisesRegex(ValueError, "denied"):
                resident.routines.test_run(routine_id)
            resident.store.close()

    def test_empty_boundary_occurrence_runs_without_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            routine = self._confirm(resident, "每 2 小时检查一次收件箱")
            routine_id = routine["routine_id"]

            # Clearing the boundary means unrestricted: the confirmation
            # accepts an empty boundary, and occurrences skip the gate.
            edited = resident.routines.edit(
                routine_id, fields={"approval_boundary": ""}
            )
            self.assertEqual(edited["approval_boundary"], "")
            run = resident.routines.test_run(routine_id)
            self.assertEqual(run["status"], "running")
            self.assertEqual(self._pending_cards(db), [])

            resident.pulse()
            resident.live_once()
            engaged = resident.will.get(routine["intention_id"])
            self.assertEqual(engaged.status, "engaged")
            resident.will.observe_event_outcome(
                routine["intention_id"],
                event_id=engaged.related_event_id,
                success=True,
                summary="done",
            )
            self.assertEqual(
                resident.routines.runs(routine_id)[0]["status"], "succeeded"
            )
            resident.store.close()

    def test_always_allow_rule_lets_later_occurrences_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            routine = self._confirm(resident, "每 2 小时检查一次收件箱")
            routine_id = routine["routine_id"]

            first = resident.routines.test_run(routine_id)
            self.assertEqual(first["status"], "awaiting_approval")
            self._approve_pending_card(db, decision="always_allow")
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

            # The always_allow rule releases the next occurrence with no
            # new card.
            second = resident.routines.test_run(routine_id)
            self.assertEqual(second["status"], "running")
            self.assertEqual(self._pending_cards(db), [])
            resident.store.close()

    def test_edit_voids_held_occurrence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            routine = self._confirm(resident, "每 2 分钟检查一次收件箱")
            routine_id = routine["routine_id"]
            intention_id = routine["intention_id"]

            future = datetime.now(timezone.utc) + timedelta(minutes=3)
            resident.recurring_will.activate_due(now=future)
            self.assertEqual(
                resident.routines.runs(routine_id)[0]["status"],
                "awaiting_approval",
            )
            resident.routines.edit(
                routine_id, fields={"task": "检查一次收件箱并汇总未读"}
            )
            runs = resident.routines.runs(routine_id)
            self.assertEqual(runs[0]["status"], "failed")
            self.assertIn("edited", runs[0]["failure_reason"] or "")
            # The edited routine does not resurrect the held occurrence.
            resident.pulse()
            self.assertIsNone(resident.will.get(intention_id).next_task)
            resident.store.close()

    def test_pause_voids_held_occurrence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            routine = self._confirm(resident, "每 2 分钟检查一次收件箱")
            routine_id = routine["routine_id"]
            intention_id = routine["intention_id"]

            future = datetime.now(timezone.utc) + timedelta(minutes=3)
            resident.recurring_will.activate_due(now=future)
            self.assertEqual(
                resident.routines.runs(routine_id)[0]["status"],
                "awaiting_approval",
            )
            paused = resident.routines.pause(routine_id)
            self.assertEqual(paused["status"], "paused")
            runs = resident.routines.runs(routine_id)
            self.assertEqual(runs[0]["status"], "failed")
            self.assertIn("paused", runs[0]["failure_reason"] or "")
            # Resume does not resurrect the voided occurrence.
            resident.routines.resume(routine_id)
            resident.pulse()
            self.assertIsNone(resident.will.get(intention_id).next_task)
            resident.store.close()

    def test_expired_card_voids_held_occurrence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            routine = self._confirm(resident, "每 2 分钟检查一次收件箱")
            routine_id = routine["routine_id"]
            intention_id = routine["intention_id"]

            future = datetime.now(timezone.utc) + timedelta(minutes=3)
            resident.recurring_will.activate_due(now=future)
            cards = self._pending_cards(db)
            self.assertEqual(len(cards), 1)
            # Simulate the 10-minute unattended TTL passing: the card is
            # past its expiry, nobody decided it.
            with closing_sqlite(sqlite3.connect(str(db))) as conn:
                conn.execute(
                    "UPDATE approval_requests SET expires_at=? WHERE request_id=?",
                    (
                        (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                        cards[0].request_id,
                    ),
                )
                conn.commit()

            resident.pulse()
            runs = resident.routines.runs(routine_id)
            self.assertEqual(runs[0]["status"], "failed")
            self.assertIn("expired", runs[0]["failure_reason"] or "")
            self.assertIsNone(resident.will.get(intention_id).next_task)
            self.assertIsNone(resident.will.get(intention_id).related_event_id)
            resident.store.close()

    def test_stale_held_occurrence_is_voided_by_sweep(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            routine = self._confirm(resident, "每 2 小时检查一次收件箱")
            routine_id = routine["routine_id"]

            run = resident.routines.test_run(routine_id)
            self.assertEqual(run["status"], "awaiting_approval")
            # Backstop state: the card is gone and the hold is over a day
            # old (e.g. no pulse ran). The sweep must not leave it held.
            with closing_sqlite(sqlite3.connect(str(db))) as conn:
                conn.execute(
                    "DELETE FROM approval_requests WHERE request_id IN "
                    "(SELECT approval_request_id "
                    "FROM resident_routine_held_occurrences WHERE run_id=?)",
                    (run["run_id"],),
                )
                conn.execute(
                    "UPDATE resident_routine_runs SET started_at=? WHERE run_id=?",
                    (
                        (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
                        run["run_id"],
                    ),
                )
                conn.commit()

            resident.routines.sweep()
            runs = resident.routines.runs(routine_id)
            self.assertEqual(runs[0]["status"], "failed")
            self.assertIn("24", runs[0]["failure_reason"] or "")
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
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            routine = self._confirm(resident, "每 2 分钟检查一次收件箱")
            routine_id = routine["routine_id"]
            # One finished run after confirmation: the routine ran and
            # nobody responded. The run first waits for its approval.
            run = resident.routines.test_run(routine_id)
            self.assertEqual(run["status"], "awaiting_approval")
            self._approve_pending_card(db)
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
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
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
            # The boundary holds the test run: the approval card appears
            # on approval_list and decides through approval_decide.
            self.assertEqual(run["status"], "awaiting_approval")
            approvals = call("approval_list", {})
            self.assertEqual(len(approvals["pending"]), 1)
            decided = call(
                "approval_decide",
                {
                    "request_id": approvals["pending"][0]["request_id"],
                    "decision": "allow_once",
                },
            )
            self.assertEqual(decided["request"]["status"], "approved_once")
            # Pause is rejected while the test run is in flight rather than
            # clobbering it; after the run closes, pause succeeds. handle()
            # propagates the rejection (serve_forever wraps it into an
            # error response on the wire).
            resident.pulse()
            with self.assertRaisesRegex(ValueError, "in flight"):
                server.handle(
                    {
                        "id": 2,
                        "method": "routine_pause",
                        "params": {"routine_id": routine_id},
                    }
                )
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
