from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

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
from zn_agent.core.natural_browser_desktop_submit_resident import (
    NaturalBrowserDesktopSubmitResidentRuntime,
)
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.visual_region_sense import VisualRegionObservation


TASK = (
    "在我已授权的当前浏览器页面里找两个参考入口，确认两个来源给出的 release code 一致，"
    "然后把查到的 code 填到当前打开的软件输入框里，点击按钮“查询”，窗口变成“查询结果”后确认"
)
_INITIAL_URL = "https://portal.example.test/work"
_CODE = "REL-2026.09"


class _AuthorizedRelay:
    def __init__(self, tab_id: int = 17):
        self.tab_id = tab_id

    def authorized_tab(self):
        return SimpleNamespace(tab_id=self.tab_id)


class _DesktopWorld:
    def __init__(
        self,
        *,
        process_name: str = "customerapp.exe",
        title: str = "客户查询",
        final_title_on_click: bool = True,
    ):
        self.process_name = process_name
        self.title = title
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


class _ForegroundSense:
    def __init__(self, world: _DesktopWorld):
        self.world = world

    def probe(self):
        return ForegroundWindowObservation(
            process_id=330,
            process_name=self.world.process_name,
            title=self.world.title,
            class_name="CustomerAppWindow",
            captured_at=utc_now(),
            source="test-desktop-foreground",
        )


class _FocusedEditSense:
    RUNTIME_ID = (42, 330, 5)

    def __init__(self, world: _DesktopWorld):
        self.world = world

    def probe_focused(self):
        return AutomationElementObservation(
            runtime_id=self.RUNTIME_ID,
            process_id=330,
            process_name=self.world.process_name,
            framework_id="WPF",
            control_type=50004,
            class_name="TextBox",
            is_enabled=True,
            is_keyboard_focusable=True,
            has_keyboard_focus=True,
            is_offscreen=False,
            native_window_handle=0,
            captured_at=utc_now(),
            automation_id="release-code-input",
            is_password=False,
            is_value_pattern_available=True,
            is_text_pattern_available=False,
            value_is_read_only=False,
            source="test-desktop-uia",
        )


class _FocusedTextStateSense:
    def __init__(self, body: _CompositeDesktopBody, world: _DesktopWorld):
        self.body = body
        self.world = world

    def probe(self):
        return FocusedAutomationTextObservation(
            runtime_id=_FocusedEditSense.RUNTIME_ID,
            process_id=330,
            process_name=self.world.process_name,
            framework_id="WPF",
            control_type=50004,
            class_name="TextBox",
            automation_id="release-code-input",
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
    def __init__(self):
        self.calls = 0

    def find_unique_button(self, *, process_id: int, process_name: str, name: str):
        self.calls += 1
        return NamedAutomationControlObservation(
            runtime_id=(42, 330, 9),
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


class NaturalBrowserDesktopSubmitWorkTests(unittest.TestCase):
    @staticmethod
    def _initial_browser_context():
        return {
            "tab_id": 17,
            "url": _INITIAL_URL,
            "title": "Release portal",
            "observed_at": utc_now(),
            "references": [
                {
                    "href": "https://reference-a.example.test/release",
                    "text": "Release reference A",
                },
                {
                    "href": "https://reference-b.example.test/record",
                    "text": "Release reference B",
                },
            ],
        }

    @staticmethod
    def _research_result():
        return {
            "release_code": _CODE,
            "sources": [
                {
                    "source_url": "https://reference-a.example.test/release",
                    "evidence_url": "https://reference-a.example.test/release/detail",
                    "release_code": _CODE,
                    "observed_at": utc_now(),
                },
                {
                    "source_url": "https://reference-b.example.test/record",
                    "evidence_url": "https://reference-b.example.test/record",
                    "release_code": _CODE,
                    "observed_at": utc_now(),
                },
            ],
        }

    @classmethod
    def _setup(
        cls,
        base: Path,
        thread: str,
        *,
        fresh_url: str = _INITIAL_URL,
        research_error: str | None = None,
        foreground_process: str = "customerapp.exe",
    ):
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=base / "kernel.db",
        )
        world = _DesktopWorld(process_name=foreground_process)
        body = _CompositeDesktopBody(resident=resident, world=world)
        named = _NamedButtonSense()
        resident.body = body
        resident.foreground_window = _ForegroundSense(world)
        resident.automation_element = _FocusedEditSense(world)
        resident.automation_text_state = _FocusedTextStateSense(body, world)
        resident.named_automation_control = named
        resident.visual_region = _VisualSense(world)
        resident.user_browser_extension = _AuthorizedRelay(17)
        resident._discover_authorized_reference_context = cls._initial_browser_context

        if research_error is None:
            resident._research_managed_references = lambda references: cls._research_result()
        else:
            def failed_research(references):
                raise RuntimeError(research_error)
            resident._research_managed_references = failed_research

        resident.probe_user_browser_extension_tab = lambda: {
            "authorized": True,
            "tab_id": 17,
            "url": fresh_url,
            "title": "Release portal",
            "observed_at": utc_now(),
            "source": "test-user-browser",
        }
        ledger = RecoveryBoundedWorkLedger(resident)
        ledger.create_thread(thread_id=thread)
        return resident, world, body, named, ledger

    @staticmethod
    def _event_actions(resident, event_id: str):
        return [
            item
            for item in reversed(resident.body.recent_actions(512))
            if item.event_id == event_id
        ]

    def test_plain_work_researches_two_sources_then_completes_current_desktop_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            resident, world, body, named, ledger = self._setup(base, "browser-desktop")
            try:
                self.assertIsInstance(resident, NaturalBrowserDesktopSubmitResidentRuntime)
                snapshot, run = ledger.submit("browser-desktop", TASK)

                self.assertTrue(run.success, run)
                self.assertEqual(run.model_invocations, 0)
                self.assertEqual(body.keyboard_calls, [_CODE])
                self.assertEqual(body.current_text, _CODE)
                self.assertEqual(body.click_count, 1)
                self.assertEqual(world.title, "查询结果")
                self.assertGreaterEqual(named.calls, 2)
                self.assertNotIn(_CODE, str(run.event.payload))

                actions = self._event_actions(resident, run.event.event_id)
                self.assertEqual(sum(item.kind == "keyboard_text" for item in actions), 1)
                self.assertEqual(sum(item.kind == "pointer_click" for item in actions), 1)
                final = resident.store.get_event_outcome(run.event.event_id)
                self.assertIsNotNone(final)
                self.assertTrue(final.success)
                self.assertIn("title=查询结果", final.response)
                research = resident.store.get_working_state().data.get(
                    resident._BROWSER_DESKTOP_RESEARCH_STATE_KEY,
                    {},
                )
                self.assertEqual(len(research.get("sources") or ()), 2)
                self.assertNotIn("cookie", str(research).lower())
                self.assertNotIn("profile", str(research).lower())
                self.assertEqual([message.role for message in snapshot[1]], ["user", "zn", "activity"])
            finally:
                resident.store.close()

    def test_reference_disagreement_stops_before_any_desktop_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, world, body, named, ledger = self._setup(
                Path(tmp),
                "research-disagree",
                research_error="two distinct sources did not agree on one release code",
            )
            try:
                _, run = ledger.submit("research-disagree", TASK)
                self.assertFalse(run.success)
                self.assertEqual(body.keyboard_calls, [])
                self.assertEqual(body.click_count, 0)
                self.assertEqual(named.calls, 0)
                self.assertIn("two distinct sources", run.reason)
            finally:
                resident.store.close()

    def test_authorized_user_page_change_during_research_stops_before_desktop_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, world, body, named, ledger = self._setup(
                Path(tmp),
                "page-changed",
                fresh_url="https://portal.example.test/other",
            )
            try:
                _, run = ledger.submit("page-changed", TASK)
                self.assertFalse(run.success)
                self.assertEqual(body.keyboard_calls, [])
                self.assertEqual(body.click_count, 0)
                self.assertEqual(named.calls, 0)
                self.assertIn("changed during managed reference research", run.reason)
            finally:
                resident.store.close()

    def test_current_foreground_is_freshly_checked_after_research_before_desktop_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, world, body, named, ledger = self._setup(
                Path(tmp),
                "wrong-foreground",
                foreground_process="msedge.exe",
            )
            try:
                _, run = ledger.submit("wrong-foreground", TASK)
                self.assertFalse(run.success)
                self.assertEqual(body.keyboard_calls, [])
                self.assertEqual(body.click_count, 0)
                self.assertEqual(named.calls, 0)
                self.assertIn("focused non-browser application", run.reason)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
