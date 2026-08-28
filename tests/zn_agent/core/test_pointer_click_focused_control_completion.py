from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core import ExecutionPath
from zn_agent.core.body import NativeBody
from zn_agent.core.focused_control_sense import FocusedControlObservation
from zn_agent.core.foreground_window_sense import ForegroundWindowObservation
from zn_agent.core.models import utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.visual_region_sense import VisualRegionObservation


class _FocusedClickBody(NativeBody):
    def __init__(self, *, resident=None):
        super().__init__(resident=resident)
        self.pointer_x = 0
        self.pointer_y = 0
        self.screen_width = 101
        self.screen_height = 51
        self.move_calls: list[tuple[int, int]] = []
        self.click_calls = 0
        self.baseline_captured = False

    def _read_primary_pointer_state(self):
        return {
            "coordinate_space": "primary_screen_fraction",
            "x": self.pointer_x,
            "y": self.pointer_y,
            "x_fraction": round(self.pointer_x / (self.screen_width - 1), 6),
            "y_fraction": round(self.pointer_y / (self.screen_height - 1), 6),
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "captured_at": utc_now(),
        }

    def _set_primary_pointer_position(self, x: int, y: int) -> bool:
        self.move_calls.append((int(x), int(y)))
        self.pointer_x = int(x)
        self.pointer_y = int(y)
        return True

    def _send_primary_pointer_click(self, button: str) -> bool:
        self.click_calls += 1
        return button == "left"


class _FocusedVisualRegion:
    def __init__(self, body: _FocusedClickBody):
        self.body = body
        self.calls = 0

    def probe(
        self,
        *,
        center_x_fraction: float,
        center_y_fraction: float,
        width_fraction: float,
        height_fraction: float,
    ) -> VisualRegionObservation:
        self.calls += 1
        if self.body.click_calls == 0:
            self.body.baseline_captured = True
        signature = "after-click-signature" if self.body.click_calls else "before-click-signature"
        return VisualRegionObservation(
            signature=signature,
            source="test-region",
            captured_at=utc_now(),
            screen_width=101,
            screen_height=51,
            left=45,
            top=18,
            right=55,
            bottom=23,
            center_x_fraction=float(center_x_fraction),
            center_y_fraction=float(center_y_fraction),
            width_fraction=float(width_fraction),
            height_fraction=float(height_fraction),
            mean_luminance=0.5,
            raw_frame_persisted=False,
        )


class _FocusedForegroundWindow:
    def __init__(self, body: _FocusedClickBody, *, drift_after_baseline: bool = False):
        self.body = body
        self.drift_after_baseline = bool(drift_after_baseline)
        self.calls = 0

    @staticmethod
    def _observation(process_id: int, process_name: str, title: str, class_name: str):
        return ForegroundWindowObservation(
            process_id=process_id,
            process_name=process_name,
            title=title,
            class_name=class_name,
            captured_at=utc_now(),
            source="test-foreground-window",
        )

    def probe(self) -> ForegroundWindowObservation:
        self.calls += 1
        if self.drift_after_baseline and self.body.baseline_captured:
            return self._observation(300, "calc.exe", "Calculator", "ApplicationFrameWindow")
        if self.body.click_calls > 0:
            return self._observation(200, "notepad.exe", "Untitled - Notepad", "Notepad")
        return self._observation(100, "explorer.exe", "Desktop", "Progman")


class _FocusedControlSense:
    def __init__(
        self,
        body: _FocusedClickBody,
        *,
        target_before_click: bool = False,
        target_after_click: bool = True,
    ):
        self.body = body
        self.target_before_click = bool(target_before_click)
        self.target_after_click = bool(target_after_click)
        self.calls = 0

    @staticmethod
    def _observation(
        process_id: int,
        process_name: str,
        title: str,
        foreground_class_name: str,
        control_class_name: str,
        control_id: int,
        *,
        enabled: bool = True,
        visible: bool = True,
    ) -> FocusedControlObservation:
        return FocusedControlObservation(
            process_id=process_id,
            process_name=process_name,
            foreground_title=title,
            foreground_class_name=foreground_class_name,
            control_class_name=control_class_name,
            control_id=control_id,
            enabled=enabled,
            visible=visible,
            captured_at=utc_now(),
            source="test-focused-control",
        )

    def probe(self) -> FocusedControlObservation:
        self.calls += 1
        if self.body.click_calls > 0:
            if self.target_after_click:
                return self._observation(
                    200,
                    "notepad.exe",
                    "Untitled - Notepad",
                    "Notepad",
                    "Edit",
                    15,
                )
            return self._observation(
                100,
                "explorer.exe",
                "Desktop",
                "Progman",
                "SysListView32",
                1,
            )
        if self.target_before_click:
            return self._observation(
                200,
                "notepad.exe",
                "Untitled - Notepad",
                "Notepad",
                "Edit",
                15,
            )
        return self._observation(
            100,
            "explorer.exe",
            "Desktop",
            "Progman",
            "SysListView32",
            1,
        )


class PointerClickFocusedControlCompletionTests(unittest.TestCase):
    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 16) -> None:
        for _ in range(limit):
            if resident.store.get_working_state().stage == stage:
                return
            result = resident.live_once()
            if result is not None:
                raise AssertionError(
                    f"event reached terminal result before stage {stage}: {result}"
                )
        raise AssertionError(
            f"resident did not reach stage {stage}; current="
            f"{resident.store.get_working_state().stage}"
        )

    @staticmethod
    def _resident(tmp: str):
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )
        body = _FocusedClickBody(resident=resident)
        resident.body = body
        resident.visual_region = _FocusedVisualRegion(body)
        resident.foreground_window = _FocusedForegroundWindow(body)
        resident.focused_control = _FocusedControlSense(body)
        return resident, body

    @staticmethod
    def _event(resident, *, completion_scope=None):
        scope = completion_scope or {
            "kind": "focused_control_matches",
            "process_name": "notepad.exe",
            "title_equals": "Untitled - Notepad",
            "control_class_name": "Edit",
            "control_id": 15,
        }
        return resident.enqueue(
            "focus the exact native control",
            kind="ui_state_transition",
            payload={
                "body_action": {
                    "kind": "pointer_click",
                    "args": {
                        "x_fraction": 0.5,
                        "y_fraction": 0.4,
                        "button": "left",
                    },
                },
                "expected_outcome": {
                    "kind": "visual_region_changed",
                    "width_fraction": 0.08,
                    "height_fraction": 0.08,
                },
                "completion_scope": scope,
                "action_precondition": {
                    "kind": "foreground_window_matches",
                    "process_name": "explorer.exe",
                    "title_equals": "Desktop",
                },
                "model_policy": "never",
            },
        )

    def test_exact_focused_control_match_after_click_completes_typed_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            focused = resident.focused_control
            foreground = resident.foreground_window
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            self.assertEqual(body.move_calls, [(50, 20)])
            self.assertEqual(body.click_calls, 0)

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_verification")
            self.assertEqual(body.click_calls, 1)
            admission = state.data[resident._SEMANTIC_PRECONDITION_KEY]
            self.assertTrue(admission["reverified"])
            self.assertEqual(admission["reverified_phase"], "final_before_pointer_input")

            result = resident.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.BODY)
            self.assertEqual(body.click_calls, 1)
            self.assertEqual(focused.calls, 2)
            self.assertEqual(foreground.calls, 2)
            self.assertEqual(resident.visual_region.calls, 2)
            self.assertIn("focused native-control class/id", result.reason)
            self.assertIn("task prose was not used", result.reason)
            resident.store.close()

    def test_already_focused_target_completes_without_pointer_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            resident.focused_control = _FocusedControlSense(body, target_before_click=True)
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            result = resident.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(body.move_calls, [])
            self.assertEqual(body.click_calls, 0)
            self.assertEqual(resident.focused_control.calls, 1)
            self.assertEqual(resident.foreground_window.calls, 0)
            self.assertEqual(resident.visual_region.calls, 0)
            self.assertIn("no pointer input was sent", result.reason)
            resident.store.close()

    def test_invalid_focused_scope_fails_before_any_probe_or_movement(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            self._event(
                resident,
                completion_scope={
                    "kind": "focused_control_matches",
                    "process_name": "notepad.exe",
                    "title_equals": "Untitled - Notepad",
                    "control_class_name": "Edit",
                    "control_id": 0,
                },
            )
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.move_calls, [])
            self.assertEqual(body.click_calls, 0)
            self.assertEqual(resident.focused_control.calls, 0)
            self.assertEqual(resident.foreground_window.calls, 0)
            self.assertIn("positive control_id", state.data["local_failure"])
            resident.store.close()

    def test_focused_control_mismatch_after_click_returns_to_investigation_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            resident.focused_control = _FocusedControlSense(body, target_after_click=False)
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            self.assertIsNone(resident.live_once())
            self.assertEqual(body.click_calls, 1)
            self.assertEqual(resident.store.get_working_state().stage, "native_verification")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.click_calls, 1)
            verification = state.data[resident._FOCUSED_VERIFICATION_KEY]
            self.assertFalse(verification["verified"])
            self.assertIn("semantic completion failed", state.data["local_failure"])
            self.assertIn("without replaying pointer input", state.next_action)
            resident.store.close()

    def test_final_source_drift_after_visual_baseline_aborts_before_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            resident.foreground_window = _FocusedForegroundWindow(
                body,
                drift_after_baseline=True,
            )
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            self.assertEqual(body.click_calls, 0)
            self.assertFalse(body.baseline_captured)

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.click_calls, 0)
            self.assertTrue(body.baseline_captured)
            execution = state.data[resident._POINTER_CLICK_EXECUTION_KEY]
            self.assertEqual(execution["status"], "aborted")
            self.assertFalse(execution["input_sent"])
            self.assertIn("focused-control input boundary", state.data["local_failure"])
            resident.store.close()

    def test_missing_focused_control_sense_fails_before_pointer_movement(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            resident.focused_control = None
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.move_calls, [])
            self.assertEqual(body.click_calls, 0)
            self.assertIn("focused-control Sense", state.data["local_failure"])
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
