from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.suggestions import SuggestionEngine
from zn_agent.core.work import ResidentWorkLedger


class SuggestionsTests(unittest.TestCase):
    @staticmethod
    def _resident(db: Path):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=db,
        )

    def _engine(self, tmp: str):
        db = Path(tmp) / "kernel.db"
        resident = self._resident(db)
        ledger = ResidentWorkLedger(resident)
        engine = SuggestionEngine(resident, ledger)
        return resident, ledger, engine

    def test_empty_resident_has_no_suggestions_and_nothing_is_invented(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, engine = self._engine(tmp)
            self.assertEqual(engine.list_suggestions(), [])
            # An ordinary (non-routine) memory fact is not a task.
            resident.memory.remember("favorite color", "blue")
            self.assertEqual(engine.list_suggestions(), [])
            # A thread with only a successful-looking ZN reply is finished.
            thread = _ledger.create_thread(thread_id="work-done")
            _ledger.append_message(thread.thread_id, role="zn", text="Done.")
            self.assertEqual(engine.list_suggestions(), [])
            resident.store.close()

    def test_failed_work_suggests_continuing_in_the_same_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, engine = self._engine(tmp)
            thread = ledger.create_thread(thread_id="work-failed")
            _snapshot, run = ledger.submit(thread.thread_id, "check the inbox")
            self.assertFalse(run.success)

            suggestions = engine.list_suggestions()
            self.assertEqual(len(suggestions), 1)
            item = suggestions[0]
            self.assertEqual(item["kind"], "failed_work")
            self.assertEqual(item["task"], "check the inbox")
            self.assertEqual(item["thread_id"], "work-failed")
            self.assertEqual(item["source"]["type"], "work")
            self.assertEqual(item["source"]["thread_id"], "work-failed")

            # Deterministic: the same state yields the same suggestion.
            self.assertEqual(engine.list_suggestions(), suggestions)
            resident.store.close()

    def test_in_flight_work_is_not_suggested(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, engine = self._engine(tmp)
            thread = ledger.create_thread(thread_id="work-active")
            _snapshot, _event = ledger.start(thread.thread_id, "do this now")
            self.assertEqual(engine.list_suggestions(), [])
            resident.store.close()

    def test_interrupted_work_suggests_the_unanswered_user_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, engine = self._engine(tmp)
            thread = ledger.create_thread(thread_id="work-interrupted")
            ledger.append_message(
                thread.thread_id, role="user", text="summarize the notes"
            )
            suggestions = engine.list_suggestions()
            self.assertEqual(len(suggestions), 1)
            self.assertEqual(suggestions[0]["kind"], "interrupted_work")
            self.assertEqual(suggestions[0]["task"], "summarize the notes")
            self.assertEqual(suggestions[0]["thread_id"], "work-interrupted")
            resident.store.close()

    def test_dismissal_suppresses_for_seven_days_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident, ledger, engine = self._engine(tmp)
            thread = ledger.create_thread(thread_id="work-dismiss")
            ledger.submit(thread.thread_id, "check the inbox")
            key = engine.list_suggestions()[0]["key"]

            dismissed = engine.dismiss(key)
            self.assertTrue(dismissed["dismissed"])
            self.assertEqual(engine.list_suggestions(), [])

            # A rebuilt engine on the same ZN home still suppresses it.
            resident.store.close()
            restored = self._resident(db)
            restored_engine = SuggestionEngine(
                restored, ResidentWorkLedger(restored)
            )
            self.assertEqual(restored_engine.list_suggestions(), [])

            # After the 7-day window the same suggestion may return.
            past = datetime.now(timezone.utc) - timedelta(days=8)
            restored_engine.dismiss(key, now=past)
            self.assertEqual(len(restored_engine.list_suggestions()), 1)
            restored.store.close()

    def test_dismissal_row_carries_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident, ledger, engine = self._engine(tmp)
            thread = ledger.create_thread(thread_id="work-stamps")
            ledger.submit(thread.thread_id, "check the inbox")
            key = engine.list_suggestions()[0]["key"]
            engine.dismiss(key)
            resident.store.close()
            with sqlite3.connect(db) as conn:
                row = conn.execute(
                    "SELECT dismissed_at, expires_at FROM "
                    "resident_suggestion_dismissals WHERE suggestion_key=?",
                    (key,),
                ).fetchone()
            self.assertIsNotNone(row)
            assert row is not None
            dismissed_at = datetime.fromisoformat(row[0])
            expires_at = datetime.fromisoformat(row[1])
            self.assertEqual(expires_at - dismissed_at, timedelta(days=7))

    def test_upcoming_recurring_trigger_suggests_with_schedule_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, engine = self._engine(tmp)
            now = datetime.now(timezone.utc)
            intention = resident.schedule_recurring_intention(
                "weekly review",
                task="review the weekly notes",
                interval_seconds=3600,
                source="user",
                first_due_at=now + timedelta(hours=1),
            )
            suggestions = engine.list_suggestions(now=now)
            self.assertEqual(len(suggestions), 1)
            item = suggestions[0]
            self.assertEqual(item["kind"], "recurring_upcoming")
            self.assertEqual(item["task"], "review the weekly notes")
            self.assertIsNone(item["thread_id"])
            self.assertEqual(item["source"]["type"], "schedule")
            self.assertEqual(item["source"]["intention_id"], intention.intention_id)

            # Once Will has picked the occurrence up, do not duplicate it.
            resident.will.set_next_step(
                intention.intention_id,
                "review the weekly notes",
                payload={},
            )
            self.assertEqual(engine.list_suggestions(now=now), [])
            resident.store.close()

    def test_overdue_recurring_trigger_is_a_due_suggestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, engine = self._engine(tmp)
            now = datetime.now(timezone.utc)
            resident.schedule_recurring_intention(
                "daily check",
                task="check the daily inbox",
                interval_seconds=3600,
                source="user",
                first_due_at=now - timedelta(minutes=5),
            )
            suggestions = engine.list_suggestions(now=now)
            self.assertEqual(len(suggestions), 1)
            self.assertEqual(suggestions[0]["kind"], "recurring_due")
            resident.store.close()

    def test_routine_memory_fact_suggests_with_memory_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, engine = self._engine(tmp)
            resident.memory.remember(
                "routine:weekly review", "review the weekly notes"
            )
            suggestions = engine.list_suggestions()
            self.assertEqual(len(suggestions), 1)
            item = suggestions[0]
            self.assertEqual(item["kind"], "routine")
            self.assertEqual(item["task"], "review the weekly notes")
            self.assertEqual(item["source"]["type"], "memory")
            self.assertEqual(item["source"]["fact_key"], "routine:weekly review")
            resident.store.close()

    def test_suggestions_rpc_lists_and_dismisses(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            try:
                server = ResidentRpcServer(
                    resident=resident,
                    input_stream=io.StringIO(),
                    output_stream=io.StringIO(),
                )
                thread = server.work.create_thread(thread_id="work-rpc")
                server.work.submit(thread.thread_id, "check the inbox")

                listed = server.handle(
                    {"id": "1", "method": "suggestions_list", "params": {}}
                )
                self.assertTrue(listed["ok"])
                self.assertEqual(len(listed["result"]), 1)
                key = listed["result"][0]["key"]
                self.assertEqual(listed["result"][0]["thread_id"], "work-rpc")

                dismissed = server.handle(
                    {
                        "id": "2",
                        "method": "suggestions_dismiss",
                        "params": {"key": key},
                    }
                )
                self.assertTrue(dismissed["ok"])
                self.assertTrue(dismissed["result"]["dismissed"])

                listed_again = server.handle(
                    {"id": "3", "method": "suggestions_list", "params": {}}
                )
                self.assertTrue(listed_again["ok"])
                self.assertEqual(listed_again["result"], [])
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
