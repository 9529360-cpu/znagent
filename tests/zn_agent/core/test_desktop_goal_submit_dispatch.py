from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.body import BodyAction
from zn_agent.core.models import utc_now
from zn_agent.core.visual_region_sense import VisualRegionObservation
from tests.zn_agent.core import test_natural_named_desktop_input_work as _natural_named_desktop_input_work
from tests.zn_agent.core.test_natural_named_desktop_input_work import (
    TASK,
    _BUTTON_RUNTIME,
    _DesktopWorld,
    _FocusedTextStateSense,
    _NamedInputDesktopBody,
)


class _StaticSubmitVisualSense:
    """Keep the Button region visually stable while other regions remain observable."""

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
        on_submit = bool(
            abs(center_x_fraction - _NamedInputDesktopBody.BUTTON_X) <= 0.002
            and abs(center_y_fraction - _NamedInputDesktopBody.BUTTON_Y) <= 0.002
        )
        return VisualRegionObservation(
            signature=(
                "submit-region-stable"
                if on_submit
                else f"visual-{self.world.visual_version}"
            ),
            source="test-static-submit-visual",
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


class _ButtonFocusDesktopBody(_NamedInputDesktopBody):
    def _dispatch(self, action: BodyAction, started: str):
        if action.kind == "pointer_click":
            x_fraction = float(action.args["x_fraction"])
            y_fraction = float(action.args["y_fraction"])
            if (
                abs(x_fraction - self.BUTTON_X) <= 0.002
                and abs(y_fraction - self.BUTTON_Y) <= 0.002
            ):
                self.world.focused_runtime = _BUTTON_RUNTIME
        return super()._dispatch(action, started)


class _NoResultButtonBody(_NamedInputDesktopBody):
    def _dispatch(self, action: BodyAction, started: str):
        if action.kind == "pointer_click":
            x_fraction = float(action.args["x_fraction"])
            y_fraction = float(action.args["y_fraction"])
            if (
                abs(x_fraction - self.BUTTON_X) <= 0.002
                and abs(y_fraction - self.BUTTON_Y) <= 0.002
            ):
                self.submit_click_count += 1
                self.world.focused_runtime = _BUTTON_RUNTIME
                self.world.visual_version += 1
                return self._ok(
                    action,
                    started,
                    data={"button": "left", "effect": "submit_without_result"},
                )
        return super()._dispatch(action, started)


class DesktopGoalSubmitDispatchTests(unittest.TestCase):
    @staticmethod
    def _setup(base: Path, workspace: Path, thread_id: str, body_type):
        resident, world, _, controls, ledger = _natural_named_desktop_input_work.NaturalNamedDesktopInputWorkTests._setup(
            base,
            workspace,
            thread_id,
        )
        body = body_type(resident=resident, world=world)
        resident.body = body
        resident.automation_text_state = _FocusedTextStateSense(body, world)
        resident.visual_region = _StaticSubmitVisualSense(world)
        return resident, world, body, controls, ledger

    @staticmethod
    def _source(workspace: Path) -> Path:
        source = workspace / "客户账号-华东.txt"
        source.write_text("ACCT-48291", encoding="utf-8")
        _natural_named_desktop_input_work.NaturalNamedDesktopInputWorkTests._stamp_yesterday(source)
        return source

    def test_submit_dispatch_uses_fresh_task_result_not_transient_button_pixels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            self._source(workspace)
            resident, world, body, _, ledger = self._setup(
                base,
                workspace,
                "submit-static-visual-success",
                _ButtonFocusDesktopBody,
            )
            try:
                _, run = ledger.submit("submit-static-visual-success", TASK)

                self.assertTrue(run.success, run)
                self.assertEqual(body.focus_click_count, 1)
                self.assertEqual(body.keyboard_calls, ["ACCT-48291"])
                self.assertEqual(body.submit_click_count, 1)
                self.assertEqual(world.title, "查询结果")
                actions = [
                    action
                    for action in resident.body.recent_actions(512)
                    if action.event_id == run.event.event_id
                ]
                self.assertEqual(sum(action.kind == "pointer_click" for action in actions), 2)
                self.assertEqual(sum(action.kind == "keyboard_text" for action in actions), 1)
                outcome = resident.store.get_event_outcome(run.event.event_id)
                self.assertIsNotNone(outcome)
                self.assertTrue(outcome.success)
                self.assertIn("title=查询结果", outcome.response)
            finally:
                resident.store.close()

    def test_dispatched_submit_with_unproven_result_never_sends_more_desktop_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            self._source(workspace)
            resident, world, body, _, ledger = self._setup(
                base,
                workspace,
                "submit-static-visual-no-result",
                _NoResultButtonBody,
            )
            try:
                _, run = ledger.submit("submit-static-visual-no-result", TASK)

                self.assertFalse(run.success)
                self.assertEqual(body.focus_click_count, 1)
                self.assertEqual(body.keyboard_calls, ["ACCT-48291"])
                self.assertEqual(body.submit_click_count, 1)
                self.assertEqual(world.title, "客户查询")
                actions = [
                    action
                    for action in resident.body.recent_actions(512)
                    if action.event_id == run.event.event_id
                ]
                self.assertEqual(sum(action.kind == "pointer_click" for action in actions), 2)
                self.assertEqual(sum(action.kind == "keyboard_text" for action in actions), 1)
                self.assertIn("submit action was already dispatched once", run.reason)
                self.assertIn("refusing any additional desktop input", run.reason)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
