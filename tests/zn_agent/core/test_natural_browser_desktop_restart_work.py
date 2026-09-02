from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.zn_agent.core.test_natural_browser_desktop_submit_work import (
    _CODE,
    TASK,
    NaturalBrowserDesktopSubmitWorkTests,
)


class NaturalBrowserDesktopRestartWorkTests(unittest.TestCase):
    def _reach_durable_research_checkpoint(self, resident, ledger, thread_id: str):
        _, event = ledger.start(thread_id, TASK)
        for _ in range(192):
            state = resident.store.get_working_state()
            research = state.data.get(resident._BROWSER_DESKTOP_RESEARCH_STATE_KEY)
            progress = state.data.get(resident._DESKTOP_SUBMIT_STATE_KEY)
            if (
                state.current_event_id == event.event_id
                and state.stage == "native_deliberation"
                and isinstance(research, dict)
                and research.get("release_code") == _CODE
                and not (isinstance(progress, dict) and progress.get("typed_verified"))
            ):
                return event
            self.assertIsNone(resident.live_once())
        raise AssertionError(
            "browser-to-desktop Work did not reach the durable post-research/pre-desktop checkpoint"
        )

    @staticmethod
    def _run_existing_event(resident, event_id: str):
        for _ in range(256):
            completed = resident.result_for(event_id)
            if completed is not None:
                return completed
            result = resident.live_once()
            if result is not None and result.event.event_id == event_id:
                return result
        raise AssertionError(
            f"restored browser-to-desktop event did not terminate: {resident.store.get_working_state()}"
        )

    @staticmethod
    def _forbid_research_replay(resident) -> None:
        def unexpected_research(references):
            raise AssertionError(
                "durable two-source research must not be repeated merely because Resident restarted"
            )

        resident._research_managed_references = unexpected_research

    def test_restart_after_research_continues_same_event_from_fresh_desktop_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            thread_id = "browser-desktop-restart"
            first, _, first_body, _, first_ledger = NaturalBrowserDesktopSubmitWorkTests._setup(
                base,
                thread_id,
            )
            try:
                event = self._reach_durable_research_checkpoint(
                    first,
                    first_ledger,
                    thread_id,
                )
                event_id = event.event_id
                self.assertEqual(first_body.keyboard_calls, [])
                self.assertEqual(first_body.click_count, 0)
                self.assertIsNone(first.result_for(event_id))
            finally:
                first.store.close()

            restored, world, body, named, restored_ledger = NaturalBrowserDesktopSubmitWorkTests._setup(
                base,
                thread_id,
            )
            try:
                self._forbid_research_replay(restored)
                run = self._run_existing_event(restored, event_id)

                self.assertTrue(run.success, run)
                self.assertEqual(run.event.event_id, event_id)
                self.assertEqual(restored_ledger.get_run(event_id).thread_id, thread_id)
                self.assertEqual(body.keyboard_calls, [_CODE])
                self.assertEqual(body.click_count, 1)
                self.assertEqual(world.title, "查询结果")
                self.assertGreaterEqual(named.calls, 2)
                events = [item.event_id for item in restored.store.list_events(limit=64)]
                self.assertEqual(events.count(event_id), 1)
            finally:
                restored.store.close()

    def test_restart_after_research_uses_new_foreground_and_stops_before_input_if_it_is_unsafe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            thread_id = "browser-desktop-restart-foreground"
            first, _, first_body, _, first_ledger = NaturalBrowserDesktopSubmitWorkTests._setup(
                base,
                thread_id,
            )
            try:
                event = self._reach_durable_research_checkpoint(
                    first,
                    first_ledger,
                    thread_id,
                )
                event_id = event.event_id
                self.assertEqual(first_body.keyboard_calls, [])
                self.assertEqual(first_body.click_count, 0)
            finally:
                first.store.close()

            restored, _, body, named, restored_ledger = NaturalBrowserDesktopSubmitWorkTests._setup(
                base,
                thread_id,
                foreground_process="msedge.exe",
            )
            try:
                self._forbid_research_replay(restored)
                run = self._run_existing_event(restored, event_id)

                self.assertFalse(run.success)
                self.assertEqual(run.event.event_id, event_id)
                self.assertEqual(restored_ledger.get_run(event_id).thread_id, thread_id)
                self.assertEqual(body.keyboard_calls, [])
                self.assertEqual(body.click_count, 0)
                self.assertEqual(named.calls, 0)
                self.assertIn("focused non-browser application", run.reason)
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
