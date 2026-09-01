from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, time, timedelta
from pathlib import Path

from zn_agent.core.automation_element_sense import AutomationElementObservation
from zn_agent.core.automation_text_state_sense import (
    FocusedAutomationTextObservation,
    NativeFocusedAutomationTextSense,
)
from zn_agent.core.foreground_window_sense import ForegroundWindowObservation
from zn_agent.core.keyboard_text_body import KeyboardTextBody
from zn_agent.core.models import utc_now
from zn_agent.core.natural_file_desktop_resident import NaturalFileDesktopResidentRuntime
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger


TASK = "找到这里昨天改过、名字像账号的那个 txt，把里面的内容填到当前打开的软件输入框里，填完确认"


class _DesktopTextBody(KeyboardTextBody):
    def __init__(self, *, resident, current_text: str = ""):
        super().__init__(resident=resident)
        self.current_text = current_text
        self.keyboard_calls: list[str] = []

    def _send_keyboard_text(self, text: str) -> tuple[int, int]:
        self.keyboard_calls.append(text)
        _, units = self.validate_text(text)
        self.current_text += text
        expected = len(units) * 2
        return expected, expected


class _DesktopForegroundSense:
    def probe(self):
        return ForegroundWindowObservation(
            process_id=330,
            process_name="customerapp.exe",
            title="Customer Lookup",
            class_name="CustomerAppWindow",
            captured_at=utc_now(),
            source="test-desktop-foreground",
        )


class _DesktopAutomationSense:
    RUNTIME_ID = (42, 330, 5)

    def probe_focused(self):
        return AutomationElementObservation(
            runtime_id=self.RUNTIME_ID,
            process_id=330,
            process_name="customerapp.exe",
            framework_id="WPF",
            control_type=50004,
            class_name="TextBox",
            is_enabled=True,
            is_keyboard_focusable=True,
            has_keyboard_focus=True,
            is_offscreen=False,
            native_window_handle=0,
            captured_at=utc_now(),
            automation_id="account-input",
            is_password=False,
            is_value_pattern_available=True,
            is_text_pattern_available=False,
            value_is_read_only=False,
            source="test-desktop-uia",
        )


class _DesktopTextStateSense:
    def __init__(self, body: _DesktopTextBody):
        self.body = body

    def probe(self):
        return FocusedAutomationTextObservation(
            runtime_id=_DesktopAutomationSense.RUNTIME_ID,
            process_id=330,
            process_name="customerapp.exe",
            framework_id="WPF",
            control_type=50004,
            class_name="TextBox",
            automation_id="account-input",
            native_window_handle=0,
            is_enabled=True,
            is_keyboard_focusable=True,
            has_keyboard_focus=True,
            is_offscreen=False,
            is_password=False,
            is_value_pattern_available=True,
            value_is_read_only=False,
            text_length=len(self.body.current_text),
            text_sha256=NativeFocusedAutomationTextSense.digest_text(self.body.current_text),
            captured_at=utc_now(),
            source="test-desktop-uia-text",
        )


class NaturalFileDesktopWorkTests(unittest.TestCase):
    @staticmethod
    def _stamp(path: Path, days: int) -> None:
        now = datetime.now().astimezone()
        stamp = datetime.combine(now.date() + timedelta(days=days), time(12), tzinfo=now.tzinfo).timestamp()
        os.utime(path, (stamp, stamp))

    @staticmethod
    def _setup(base: Path, workspace: Path, thread: str, *, current_text: str = ""):
        resident = build_resident_runtime(config={"model": {}}, store_path=base / "kernel.db")
        body = _DesktopTextBody(resident=resident, current_text=current_text)
        resident.body = body
        resident.foreground_window = _DesktopForegroundSense()
        resident.automation_element = _DesktopAutomationSense()
        resident.automation_text_state = _DesktopTextStateSense(body)
        ledger = RecoveryBoundedWorkLedger(resident)
        ledger.create_thread(thread_id=thread)
        ledger.attach_workspace(thread, workspace)
        return resident, body, ledger

    @staticmethod
    def _actions(resident, event_id: str):
        return [item for item in reversed(resident.body.recent_actions(512)) if item.event_id == event_id]

    @staticmethod
    def _run_to_terminal(resident, event_id: str):
        for _ in range(192):
            done = resident.result_for(event_id)
            if done is not None:
                return done
            result = resident.live_once()
            if result is not None and result.event.event_id == event_id:
                return result
        raise AssertionError(f"event did not terminate: {resident.store.get_working_state()}")

    def test_plain_work_reads_one_real_file_then_fills_focused_desktop_edit_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            target = workspace / "客户账号-华东.txt"
            today = workspace / "客户账号-今天.txt"
            other = workspace / "客户合同.txt"
            target.write_text("ACCT-48291", encoding="utf-8")
            today.write_text("TODAY-0001", encoding="utf-8")
            other.write_text("OTHER-0001", encoding="utf-8")
            self._stamp(target, -1)
            self._stamp(today, 0)
            self._stamp(other, -1)

            resident, body, ledger = self._setup(base, workspace, "file-desktop")
            try:
                self.assertIsInstance(resident, NaturalFileDesktopResidentRuntime)
                snapshot, run = ledger.submit("file-desktop", TASK)

                self.assertTrue(run.success, run)
                self.assertEqual(run.model_invocations, 0)
                self.assertEqual(body.current_text, "ACCT-48291")
                self.assertEqual(body.keyboard_calls, ["ACCT-48291"])
                self.assertEqual(target.read_text(encoding="utf-8"), "ACCT-48291")
                self.assertEqual(today.read_text(encoding="utf-8"), "TODAY-0001")

                event = run.event
                self.assertEqual(event.kind, "desktop_user_event")
                for key in ("path", "file", "text", "content", "body_action", "native_action"):
                    self.assertNotIn(key, event.payload)
                facts = resident.investigator.current(event.event_id).facts
                source = facts["natural_file_desktop_source"]
                destination = facts["natural_file_desktop_destination"]
                self.assertTrue(source["complete"])
                self.assertEqual(source["path"], str(target.resolve()))
                self.assertNotIn("text", source)
                self.assertNotIn("content", source)
                self.assertTrue(destination["complete"])
                self.assertEqual(destination["completion_scope"]["process_name"], "customerapp.exe")

                actions = self._actions(resident, event.event_id)
                self.assertEqual(sum(item.kind == "keyboard_text" for item in actions), 1)
                self.assertGreaterEqual(sum(item.kind == "read_text" for item in actions), 3)
                self.assertFalse([item for item in actions if item.kind == "write_text"])
                keyboard = next(item for item in actions if item.kind == "keyboard_text")
                self.assertNotIn("text", keyboard.data)
                self.assertEqual([message.role for message in snapshot[1]], ["user", "zn", "activity"])
            finally:
                resident.store.close()

    def test_ambiguous_yesterday_sources_stop_before_desktop_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            first = workspace / "客户账号-A.txt"
            second = workspace / "客户账号-B.txt"
            for path, text in ((first, "A-100"), (second, "B-200")):
                path.write_text(text, encoding="utf-8")
                self._stamp(path, -1)
            resident, body, ledger = self._setup(base, workspace, "ambiguous")
            try:
                _, run = ledger.submit("ambiguous", TASK)
                self.assertFalse(run.success)
                self.assertEqual(body.keyboard_calls, [])
                self.assertIn("ambiguous", run.reason.lower())
            finally:
                resident.store.close()

    def test_nonempty_different_desktop_edit_is_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            target = workspace / "客户账号-A.txt"
            target.write_text("A-100", encoding="utf-8")
            self._stamp(target, -1)
            resident, body, ledger = self._setup(base, workspace, "occupied", current_text="KEEP-ME")
            try:
                _, run = ledger.submit("occupied", TASK)
                self.assertFalse(run.success)
                self.assertEqual(body.keyboard_calls, [])
                self.assertEqual(body.current_text, "KEEP-ME")
                self.assertIn("different text", run.reason.lower())
            finally:
                resident.store.close()

    def test_source_identity_change_after_deliberation_blocks_keyboard_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            target = workspace / "客户账号-A.txt"
            target.write_text("A-100", encoding="utf-8")
            self._stamp(target, -1)
            resident, body, ledger = self._setup(base, workspace, "source-race")
            try:
                _, event = ledger.start("source-race", TASK)
                for _ in range(128):
                    state = resident.store.get_working_state()
                    if state.current_event_id == event.event_id and state.stage == "native_action":
                        break
                    self.assertIsNone(resident.live_once())
                else:
                    self.fail("file-to-desktop Work did not reach native_action")

                target.write_text("A-CHANGED", encoding="utf-8")
                run = self._run_to_terminal(resident, event.event_id)
                self.assertFalse(run.success)
                self.assertEqual(body.keyboard_calls, [])
                self.assertIn("identity no longer matches", run.reason.lower())
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
