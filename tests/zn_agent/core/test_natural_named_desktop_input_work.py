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
from zn_agent.core.natural_named_desktop_input_resident import (
    NaturalNamedDesktopInputResidentRuntime,
)
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.visual_region_sense import VisualRegionObservation


TASK = (
    "找到这里昨天改过、名字像账号的那个 txt，在当前打开的软件里找到输入框“账号”，"
    "把里面的内容填进去，然后点击按钮“查询”，窗口变成“查询结果”后确认"
)
_EDIT_RUNTIME = (42, 330, 11)
_OTHER_RUNTIME = (42, 330, 4)
_BUTTON_RUNTIME = (42, 330, 19)


class _DesktopWorld:
    def __init__(self):
        self.title = "客户查询"
        self.focused_runtime = _OTHER_RUNTIME
        self.visual_version = 0


class _NamedInputDesktopBody(KeyboardTextBody):
    SCREEN_WIDTH = 1000
    SCREEN_HEIGHT = 800
    EDIT_X = 0.30
    EDIT_Y = 0.30
    BUTTON_X = 0.50
    BUTTON_Y = 0.4625

    def __init__(self, *, resident, world: _DesktopWorld):
        super().__init__(resident=resident)
        self.world = world
        self.current_text = ""
        self.keyboard_calls: list[str] = []
        self.pointer_x = 10
        self.pointer_y = 10
        self.focus_click_count = 0
        self.submit_click_count = 0

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
            x_fraction = float(action.args["x_fraction"])
            y_fraction = float(action.args["y_fraction"])
            if (
                abs(x_fraction - self.EDIT_X) <= 0.002
                and abs(y_fraction - self.EDIT_Y) <= 0.002
            ):
                self.focus_click_count += 1
                self.world.focused_runtime = _EDIT_RUNTIME
                self.world.visual_version += 1
                return self._ok(action, started, data={"button": "left", "effect": "focus_edit"})
            if (
                abs(x_fraction - self.BUTTON_X) <= 0.002
                and abs(y_fraction - self.BUTTON_Y) <= 0.002
            ):
                self.submit_click_count += 1
                self.world.title = "查询结果"
                self.world.visual_version += 1
                return self._ok(action, started, data={"button": "left", "effect": "submit"})
            raise RuntimeError("unexpected pointer target in named-input task")
        return super()._dispatch(action, started)


class _ForegroundSense:
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


class _AutomationSense:
    def __init__(self, world: _DesktopWorld):
        self.world = world

    @staticmethod
    def _edit(*, focused: bool):
        return AutomationElementObservation(
            runtime_id=_EDIT_RUNTIME,
            process_id=330,
            process_name="customerapp.exe",
            framework_id="WPF",
            control_type=50004,
            class_name="TextBox",
            is_enabled=True,
            is_keyboard_focusable=True,
            has_keyboard_focus=focused,
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

    @staticmethod
    def _other():
        return AutomationElementObservation(
            runtime_id=_OTHER_RUNTIME,
            process_id=330,
            process_name="customerapp.exe",
            framework_id="WPF",
            control_type=50000,
            class_name="Button",
            is_enabled=True,
            is_keyboard_focusable=True,
            has_keyboard_focus=True,
            is_offscreen=False,
            native_window_handle=0,
            captured_at=utc_now(),
            automation_id="other-control",
            is_password=False,
            source="test-desktop-uia",
        )

    def probe_at_point(self, x: int, y: int):
        expected_x = int(round(_NamedInputDesktopBody.EDIT_X * (_NamedInputDesktopBody.SCREEN_WIDTH - 1)))
        expected_y = int(round(_NamedInputDesktopBody.EDIT_Y * (_NamedInputDesktopBody.SCREEN_HEIGHT - 1)))
        if abs(int(x) - expected_x) > 2 or abs(int(y) - expected_y) > 2:
            raise RuntimeError("point probe was not aimed at the exact named Edit")
        return self._edit(focused=self.world.focused_runtime == _EDIT_RUNTIME)

    def probe_focused(self):
        if self.world.focused_runtime == _EDIT_RUNTIME:
            return self._edit(focused=True)
        return self._other()


class _FocusedTextStateSense:
    def __init__(self, body: _NamedInputDesktopBody, world: _DesktopWorld):
        self.body = body
        self.world = world

    def probe(self):
        if self.world.focused_runtime != _EDIT_RUNTIME:
            raise RuntimeError("named Edit is not focused")
        return FocusedAutomationTextObservation(
            runtime_id=_EDIT_RUNTIME,
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


class _NamedControls:
    def __init__(self, world: _DesktopWorld, *, reject_edit: bool = False):
        self.world = world
        self.reject_edit = reject_edit
        self.edit_calls = 0
        self.button_calls = 0

    def find_unique_edit(self, *, process_id: int, process_name: str, name: str):
        self.edit_calls += 1
        if self.reject_edit:
            raise RuntimeError("named Edit is password/read-only/unsafe")
        return NamedAutomationControlObservation(
            runtime_id=_EDIT_RUNTIME,
            process_id=process_id,
            process_name=process_name,
            name=name,
            control_type=50004,
            class_name="TextBox",
            is_enabled=True,
            is_offscreen=False,
            left=250,
            top=220,
            right=350,
            bottom=260,
            center_x_fraction=_NamedInputDesktopBody.EDIT_X,
            center_y_fraction=_NamedInputDesktopBody.EDIT_Y,
            captured_at=utc_now(),
            is_keyboard_focusable=True,
            has_keyboard_focus=self.world.focused_runtime == _EDIT_RUNTIME,
            is_password=False,
            is_value_pattern_available=True,
            value_is_read_only=False,
            source="test-exact-name-edit",
        )

    def find_unique_button(self, *, process_id: int, process_name: str, name: str):
        self.button_calls += 1
        return NamedAutomationControlObservation(
            runtime_id=_BUTTON_RUNTIME,
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
            center_x_fraction=_NamedInputDesktopBody.BUTTON_X,
            center_y_fraction=_NamedInputDesktopBody.BUTTON_Y,
            captured_at=utc_now(),
            source="test-exact-name-button",
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
            left=200,
            top=160,
            right=600,
            bottom=430,
            center_x_fraction=center_x_fraction,
            center_y_fraction=center_y_fraction,
            width_fraction=width_fraction,
            height_fraction=height_fraction,
            raw_frame_persisted=False,
        )


class NaturalNamedDesktopInputWorkTests(unittest.TestCase):
    @staticmethod
    def _stamp_yesterday(path: Path) -> None:
        now = datetime.now().astimezone()
        stamp = datetime.combine(
            now.date() + timedelta(days=-1),
            time(12),
            tzinfo=now.tzinfo,
        ).timestamp()
        os.utime(path, (stamp, stamp))

    @classmethod
    def _setup(cls, base: Path, workspace: Path, thread_id: str, *, reject_edit: bool = False):
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=base / "kernel.db",
        )
        world = _DesktopWorld()
        body = _NamedInputDesktopBody(resident=resident, world=world)
        controls = _NamedControls(world, reject_edit=reject_edit)
        resident.body = body
        resident.foreground_window = _ForegroundSense(world)
        resident.automation_element = _AutomationSense(world)
        resident.automation_text_state = _FocusedTextStateSense(body, world)
        resident.named_automation_control = controls
        resident.visual_region = _VisualSense(world)
        ledger = RecoveryBoundedWorkLedger(resident)
        ledger.create_thread(thread_id=thread_id)
        ledger.attach_workspace(thread_id, workspace)
        return resident, world, body, controls, ledger

    def test_plain_work_finds_named_edit_focuses_it_then_fills_and_submits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            target = workspace / "客户账号-华东.txt"
            target.write_text("ACCT-48291", encoding="utf-8")
            self._stamp_yesterday(target)

            resident, world, body, controls, ledger = self._setup(
                base,
                workspace,
                "named-input",
            )
            try:
                self.assertIsInstance(resident, NaturalNamedDesktopInputResidentRuntime)
                self.assertNotEqual(world.focused_runtime, _EDIT_RUNTIME)

                snapshot, run = ledger.submit("named-input", TASK)

                self.assertTrue(run.success, run)
                self.assertEqual(run.model_invocations, 0)
                self.assertEqual(world.focused_runtime, _EDIT_RUNTIME)
                self.assertEqual(body.focus_click_count, 1)
                self.assertEqual(body.keyboard_calls, ["ACCT-48291"])
                self.assertEqual(body.current_text, "ACCT-48291")
                self.assertEqual(body.submit_click_count, 1)
                self.assertEqual(world.title, "查询结果")
                self.assertGreaterEqual(controls.edit_calls, 3)
                self.assertGreaterEqual(controls.button_calls, 2)

                actions = [
                    item
                    for item in reversed(resident.body.recent_actions(512))
                    if item.event_id == run.event.event_id
                ]
                self.assertEqual(sum(item.kind == "pointer_click" for item in actions), 2)
                self.assertEqual(sum(item.kind == "keyboard_text" for item in actions), 1)
                final = resident.store.get_event_outcome(run.event.event_id)
                self.assertIsNotNone(final)
                self.assertTrue(final.success)
                self.assertIn("title=查询结果", final.response)
                self.assertEqual([message.role for message in snapshot[1]], ["user", "zn", "activity"])
            finally:
                resident.store.close()

    def test_unsafe_named_edit_stops_before_focus_or_text_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            target = workspace / "客户账号-A.txt"
            target.write_text("A-100", encoding="utf-8")
            self._stamp_yesterday(target)

            resident, world, body, controls, ledger = self._setup(
                base,
                workspace,
                "unsafe-named-input",
                reject_edit=True,
            )
            try:
                _, run = ledger.submit("unsafe-named-input", TASK)

                self.assertFalse(run.success)
                self.assertEqual(body.focus_click_count, 0)
                self.assertEqual(body.keyboard_calls, [])
                self.assertEqual(body.submit_click_count, 0)
                self.assertEqual(controls.edit_calls, 1)
                self.assertIn("safe named desktop input", run.reason)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
