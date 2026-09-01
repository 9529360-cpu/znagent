from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, time, timedelta
from pathlib import Path

from zn_agent.core.automation_element_sense import AutomationElementObservation
from zn_agent.core.automation_named_control_sense import NamedAutomationControlObservation
from zn_agent.core.automation_text_state_sense import (
    FocusedAutomationTextObservation,
    NativeFocusedAutomationTextSense,
)
from zn_agent.core.body import BodyAction
from zn_agent.core.foreground_window_sense import ForegroundWindowObservation
from zn_agent.core.keyboard_text_body import KeyboardTextBody
from zn_agent.core.models import utc_now
from zn_agent.core.natural_file_desktop_submit_resident import (
    NaturalFileDesktopSubmitResidentRuntime,
)
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.visual_region_sense import VisualRegionObservation


TASK = (
    "找到这里昨天改过、名字像账号的那个 txt，把里面的内容填到当前打开的软件输入框里，"
    "然后点击按钮“查询”，窗口变成“查询结果”后确认"
)


class _DesktopWorld:
    def __init__(self, *, final_title_on_click: bool = True):
        self.title = "客户查询"
        self.final_title_on_click = final_title_on_click
        self.visual_version = 0


class _CompositeDesktopBody(KeyboardTextBody):
    SCREEN_WIDTH = 1000
    SCREEN_HEIGHT = 800

    def __init__(self, *, resident, world: _DesktopWorld):
        super().__init__(resident=resident)
        self.world = world
        self.current_text = ""
        self.keyboard_calls: list[str] = []
        self.pointer_x = 10
        self.pointer_y = 10
        self.click_count = 0

    def _send_keyboard_text(self, text: str) -> tuple[int, int]:
        self.keyboard_calls.append(text)
        _, units = self.validate_text(text)
        self.current_text += text
        expected = len(units) * 2
        return expected, expected

    def _dispatch(self, action: BodyAction, started: str):
        if action.kind == "pointer_move":
            x_fraction = float(action.args["x_fraction"])
            y_fraction = float(action.args["y_fraction"])
            self.pointer_x = int(round(x_fraction * (self.SCREEN_WIDTH - 1)))
            self.pointer_y = int(round(y_fraction * (self.SCREEN_HEIGHT - 1)))
            return self._ok(
                action,
                started,
                data={
                    "target_x": self.pointer_x,
                    "target_y": self.pointer_y,
                    "screen_width": self.SCREEN_WIDTH,
                    "screen_height": self.SCREEN_HEIGHT,
                },
            )
        if action.kind == "pointer_state":
            return self._ok(
                action,
                started,
                data={
                    "x": self.pointer_x,
                    "y": self.pointer_y,
                    "screen_width": self.SCREEN_WIDTH,
                    "screen_height": self.SCREEN_HEIGHT,
                },
            )
        if action.kind == "pointer_click":
            self.click_count += 1
            self.world.visual_version += 1
            if self.world.final_title_on_click:
                self.world.title = "查询结果"
            return self._ok(action, started, data={"button": "left"})
        return super()._dispatch(action, started)


class _DynamicForegroundSense:
    def __init__(self, world: _DesktopWorld):
        self.world = world

    def probe(self):
        return ForegroundWindowObservation(
            process_id=330,
            process_name="customerapp.exe",
            title=self.world.title,
            class_name="CustomerAppWindow",
            captured_at=utc_now(),
            source="test-desktop-foreground",
        )


class _FocusedEditSense:
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


class _FocusedTextStateSense:
    def __init__(self, body: _CompositeDesktopBody):
        self.body = body

    def probe(self):
        return FocusedAutomationTextObservation(
            runtime_id=_FocusedEditSense.RUNTIME_ID,
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


class _NamedButtonSense:
    DEFAULT_RUNTIME_ID = (42, 330, 9)

    def __init__(
        self,
        *,
        fail: bool = False,
        runtime_ids: list[tuple[int, ...]] | None = None,
    ):
        self.fail = fail
        self.calls = 0
        self.runtime_ids = list(runtime_ids or [self.DEFAULT_RUNTIME_ID])

    def find_unique_button(self, *, process_id: int, process_name: str, name: str):
        self.calls += 1
        if self.fail:
            raise RuntimeError("button is ambiguous")
        index = min(self.calls - 1, len(self.runtime_ids) - 1)
        runtime_id = tuple(self.runtime_ids[index])
        return NamedAutomationControlObservation(
            runtime_id=runtime_id,
            process_id=process_id,
            process_name=process_name,
            name=name,
            control_type=50000,
            class_name="Button",
            is_enabled=True,
            is_offscreen=False,
            left=450,
            top=350,
            right=550,
            bottom=390,
            center_x_fraction=0.5,
            center_y_fraction=0.4625,
            captured_at=utc_now(),
            source="test-exact-name",
        )


class _VisualSense:
    def __init__(self, world: _DesktopWorld):
        self.world = world

    def probe(
        self,
        *,
        center_x_fraction: float,
        center_y_fraction: float,
        width_fraction: float,
        height_fraction: float,
    ):
        return VisualRegionObservation(
            signature=f"visual-{self.world.visual_version}",
            source="test-visual",
            captured_at=utc_now(),
            screen_width=1000,
            screen_height=800,
            left=440,
            top=330,
            right=560,
            bottom=410,
            center_x_fraction=center_x_fraction,
            center_y_fraction=center_y_fraction,
            width_fraction=width_fraction,
            height_fraction=height_fraction,
            raw_frame_persisted=False,
        )


class NaturalFileDesktopSubmitWorkTests(unittest.TestCase):
    @staticmethod
    def _stamp(path: Path, days: int) -> None:
        now = datetime.now().astimezone()
        stamp = datetime.combine(
            now.date() + timedelta(days=days),
            time(12),
            tzinfo=now.tzinfo,
        ).timestamp()
        os.utime(path, (stamp, stamp))

    @staticmethod
    def _setup(
        base: Path,
        workspace: Path,
        thread: str,
        *,
        final_title_on_click: bool = True,
        named_button_fail: bool = False,
        named_button_runtime_ids: list[tuple[int, ...]] | None = None,
    ):
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=base / "kernel.db",
        )
        world = _DesktopWorld(final_title_on_click=final_title_on_click)
        body = _CompositeDesktopBody(resident=resident, world=world)
        named = _NamedButtonSense(
            fail=named_button_fail,
            runtime_ids=named_button_runtime_ids,
        )
        resident.body = body
        resident.foreground_window = _DynamicForegroundSense(world)
        resident.automation_element = _FocusedEditSense()
        resident.automation_text_state = _FocusedTextStateSense(body)
        resident.named_automation_control = named
        resident.visual_region = _VisualSense(world)
        ledger = RecoveryBoundedWorkLedger(resident)
        ledger.create_thread(thread_id=thread)
        ledger.attach_workspace(thread, workspace)
        return resident, world, body, named, ledger

    def test_plain_work_fills_file_value_clicks_named_button_and_verifies_final_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            target = workspace / "客户账号-华东.txt"
            target.write_text("ACCT-48291", encoding="utf-8")
            self._stamp(target, -1)

            resident, world, body, named, ledger = self._setup(
                base,
                workspace,
                "desktop-submit",
            )
            try:
                self.assertIsInstance(resident, NaturalFileDesktopSubmitResidentRuntime)
                snapshot, run = ledger.submit("desktop-submit", TASK)

                self.assertTrue(run.success, run)
                self.assertEqual(run.model_invocations, 0)
                self.assertEqual(body.keyboard_calls, ["ACCT-48291"])
                self.assertEqual(body.current_text, "ACCT-48291")
                self.assertEqual(body.click_count, 1)
                self.assertEqual(world.title, "查询结果")
                self.assertGreaterEqual(named.calls, 2, "button must be discovered then revalidated before input")

                actions = [
                    item
                    for item in reversed(resident.body.recent_actions(512))
                    if item.event_id == run.event.event_id
                ]
                self.assertEqual(sum(item.kind == "keyboard_text" for item in actions), 1)
                self.assertEqual(sum(item.kind == "pointer_click" for item in actions), 1)
                self.assertGreaterEqual(sum(item.kind == "read_text" for item in actions), 3)
                keyboard = next(item for item in actions if item.kind == "keyboard_text")
                self.assertNotIn("text", keyboard.data)
                final = resident.store.get_event_outcome(run.event.event_id)
                self.assertIsNotNone(final)
                self.assertTrue(final.success)
                self.assertIn("title=查询结果", final.response)
                self.assertEqual([message.role for message in snapshot[1]], ["user", "zn", "activity"])
            finally:
                resident.store.close()

    def test_button_replacement_before_input_is_resensed_then_new_target_is_clicked_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            target = workspace / "客户账号-A.txt"
            target.write_text("A-100", encoding="utf-8")
            self._stamp(target, -1)

            first_button = (42, 330, 9)
            replacement_button = (42, 330, 10)
            resident, world, body, named, ledger = self._setup(
                base,
                workspace,
                "button-replaced",
                named_button_runtime_ids=[
                    first_button,
                    replacement_button,
                    replacement_button,
                    replacement_button,
                ],
            )
            try:
                _, run = ledger.submit("button-replaced", TASK)

                self.assertTrue(run.success, run)
                self.assertEqual(body.keyboard_calls, ["A-100"])
                self.assertEqual(body.click_count, 1)
                self.assertEqual(world.title, "查询结果")
                self.assertGreaterEqual(named.calls, 4)

                investigation = resident.investigator.current(run.event.event_id)
                self.assertIsNotNone(investigation)
                button_fact = investigation.facts[
                    NaturalFileDesktopSubmitResidentRuntime._BUTTON_FACT_KEY
                ]
                self.assertEqual(tuple(button_fact["runtime_id"]), replacement_button)
                self.assertGreaterEqual(investigation.rounds, 4)

                records = resident.store.get_working_state().data.get(
                    resident._FAILED_ACTION_RECORDS_KEY,
                    [],
                )
                self.assertTrue(
                    any(
                        "RuntimeId changed before input" in str(item.get("failure") or "")
                        for item in records
                    ),
                    records,
                )
                actions = [
                    item
                    for item in reversed(resident.body.recent_actions(512))
                    if item.event_id == run.event.event_id
                ]
                self.assertEqual(sum(item.kind == "pointer_click" for item in actions), 1)
            finally:
                resident.store.close()

    def test_ambiguous_named_button_stops_after_verified_text_without_clicking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            target = workspace / "客户账号-A.txt"
            target.write_text("A-100", encoding="utf-8")
            self._stamp(target, -1)

            resident, world, body, named, ledger = self._setup(
                base,
                workspace,
                "button-ambiguous",
                named_button_fail=True,
            )
            try:
                _, run = ledger.submit("button-ambiguous", TASK)
                self.assertFalse(run.success)
                self.assertEqual(body.keyboard_calls, ["A-100"])
                self.assertEqual(body.click_count, 0)
                self.assertEqual(world.title, "客户查询")
                self.assertEqual(named.calls, 1)
                self.assertIn("exactly one safe named Button", run.reason)
            finally:
                resident.store.close()

    def test_click_is_never_replayed_when_final_window_state_is_not_proven(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            target = workspace / "客户账号-A.txt"
            target.write_text("A-100", encoding="utf-8")
            self._stamp(target, -1)

            resident, world, body, named, ledger = self._setup(
                base,
                workspace,
                "final-unproven",
                final_title_on_click=False,
            )
            try:
                _, run = ledger.submit("final-unproven", TASK)
                self.assertFalse(run.success)
                self.assertEqual(body.keyboard_calls, ["A-100"])
                self.assertEqual(body.click_count, 1)
                self.assertEqual(world.title, "客户查询")
                self.assertGreaterEqual(named.calls, 2)
                self.assertIn("will not replay", run.reason)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
