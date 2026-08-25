from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core import ExecutionPath
from zn_agent.core.automation_element_sense import AutomationElementObservation
from zn_agent.core.body import NativeBody
from zn_agent.core.foreground_window_sense import ForegroundWindowObservation
from zn_agent.core.models import utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.visual_region_sense import VisualRegionObservation


class _AutomationClickBody(NativeBody):
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


class _AutomationVisualRegion:
    def __init__(self, body: _AutomationClickBody):
        self.body = body
        self.calls = 0

    def probe(self, *, center_x_fraction, center_y_fraction, width_fraction, height_fraction):
        self.calls += 1
        if self.body.click_calls == 0:
            self.body.baseline_captured = True
        return VisualRegionObservation(
            signature="after" if self.body.click_calls else "before",
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


class _AutomationForegroundWindow:
    def __init__(self, body: _AutomationClickBody, *, drift_after_baseline=False):
        self.body = body
        self.drift_after_baseline = bool(drift_after_baseline)
        self.calls = 0

    def probe(self):
        self.calls += 1
        if self.drift_after_baseline and self.body.baseline_captured:
            return ForegroundWindowObservation(
                process_id=400,
                process_name="calc.exe",
                title="Calculator",
                class_name="ApplicationFrameWindow",
                captured_at=utc_now(),
                source="test-foreground",
            )
        return ForegroundWindowObservation(
            process_id=200,
            process_name="notepad.exe",
            title="Untitled - Notepad",
            class_name="Notepad",
            captured_at=utc_now(),
            source="test-foreground",
        )


class _AutomationElementSense:
    TARGET_RUNTIME = (42, 7, 9)
    OTHER_RUNTIME = (42, 8, 1)

    def __init__(
        self,
        body: _AutomationClickBody,
        *,
        target_before_click=False,
        target_after_click=True,
        target_focusable=True,
    ):
        self.body = body
        self.target_before_click = bool(target_before_click)
        self.target_after_click = bool(target_after_click)
        self.target_focusable = bool(target_focusable)
        self.point_calls: list[tuple[int, int]] = []
        self.focused_calls = 0

    @staticmethod
    def _observation(runtime_id, *, focused, focusable=True):
        return AutomationElementObservation(
            runtime_id=tuple(runtime_id),
            process_id=200,
            process_name="notepad.exe",
            framework_id="test-framework",
            control_type=50004,
            class_name="TestEdit",
            is_enabled=True,
            is_keyboard_focusable=bool(focusable),
            has_keyboard_focus=bool(focused),
            is_offscreen=False,
            native_window_handle=0,
            captured_at=utc_now(),
            source="test-uia",
        )

    def probe_at_point(self, x: int, y: int):
        self.point_calls.append((int(x), int(y)))
        return self._observation(
            self.TARGET_RUNTIME,
            focused=False,
            focusable=self.target_focusable,
        )

    def probe_focused(self):
        self.focused_calls += 1
        if self.body.click_calls > 0:
            runtime_id = self.TARGET_RUNTIME if self.target_after_click else self.OTHER_RUNTIME
            return self._observation(runtime_id, focused=True)
        runtime_id = self.TARGET_RUNTIME if self.target_before_click else self.OTHER_RUNTIME
        return self._observation(runtime_id, focused=True)


class PointerClickAutomationFocusCompletionTests(unittest.TestCase):
    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 16):
        for _ in range(limit):
            if resident.store.get_working_state().stage == stage:
                return
            result = resident.live_once()
            if result is not None:
                raise AssertionError(f"event reached terminal result before {stage}: {result}")
        raise AssertionError(f"resident did not reach {stage}")

    @staticmethod
    def _resident(tmp: str):
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )
        body = _AutomationClickBody(resident=resident)
        resident.body = body
        resident.visual_region = _AutomationVisualRegion(body)
        resident.foreground_window = _AutomationForegroundWindow(body)
        resident.automation_element = _AutomationElementSense(body)
        return resident, body

    @staticmethod
    def _event(resident, *, completion_scope=None):
        return resident.enqueue(
            "focus the exact UI element at the pointer target",
            kind="ui_state_transition",
            payload={
                "body_action": {
                    "kind": "pointer_click",
                    "args": {"x_fraction": 0.5, "y_fraction": 0.4, "button": "left"},
                },
                "expected_outcome": {
                    "kind": "visual_region_changed",
                    "width_fraction": 0.08,
                    "height_fraction": 0.08,
                },
                "completion_scope": completion_scope or {
                    "kind": "focused_automation_element_at_pointer",
                    "process_name": "notepad.exe",
                    "title_equals": "Untitled - Notepad",
                },
                "action_precondition": {
                    "kind": "foreground_window_matches",
                    "process_name": "notepad.exe",
                    "title_equals": "Untitled - Notepad",
                },
                "model_policy": "never",
            },
        )

    def test_exact_preclick_uia_target_receives_focus_after_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            sense = resident.automation_element
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            self.assertEqual(body.move_calls, [(50, 20)])
            self.assertEqual(body.click_calls, 0)

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_verification")
            self.assertEqual(body.click_calls, 1)
            target = state.data[resident._AUTOMATION_TARGET_KEY]
            self.assertEqual(tuple(target["runtime_id"]), _AutomationElementSense.TARGET_RUNTIME)
            admission = state.data[resident._SEMANTIC_PRECONDITION_KEY]
            self.assertTrue(admission["reverified"])

            result = resident.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.BODY)
            self.assertEqual(body.click_calls, 1)
            self.assertEqual(sense.point_calls, [(50, 20), (50, 20)])
            self.assertEqual(sense.focused_calls, 2)
            self.assertEqual(resident.visual_region.calls, 2)
            self.assertIn("exact opaque element", result.reason)
            self.assertIn("no UI Automation control pattern", result.reason)
            resident.store.close()

    def test_already_focused_exact_target_completes_without_movement_or_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            resident.automation_element = _AutomationElementSense(body, target_before_click=True)
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            result = resident.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(body.move_calls, [])
            self.assertEqual(body.click_calls, 0)
            self.assertEqual(resident.automation_element.point_calls, [(50, 20)])
            self.assertEqual(resident.automation_element.focused_calls, 1)
            self.assertEqual(resident.visual_region.calls, 0)
            self.assertIn("no pointer movement or input was sent", result.reason)
            resident.store.close()

    def test_final_target_must_be_focusable_before_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            resident.automation_element = _AutomationElementSense(body, target_focusable=False)
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.click_calls, 0)
            execution = state.data[resident._POINTER_CLICK_EXECUTION_KEY]
            self.assertEqual(execution["status"], "aborted")
            self.assertFalse(execution["input_sent"])
            self.assertIn("keyboard-focusable", state.data["local_failure"])
            resident.store.close()

    def test_postclick_focus_mismatch_returns_to_investigation_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            resident.automation_element = _AutomationElementSense(body, target_after_click=False)
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            self.assertIsNone(resident.live_once())
            self.assertEqual(body.click_calls, 1)
            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.click_calls, 1)
            verification = state.data[resident._AUTOMATION_VERIFICATION_KEY]
            self.assertFalse(verification["verified"])
            self.assertIn("without replaying pointer input", state.next_action)
            resident.store.close()

    def test_final_foreground_drift_aborts_before_uia_target_capture_and_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            sense = resident.automation_element
            resident.foreground_window = _AutomationForegroundWindow(body, drift_after_baseline=True)
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            self.assertEqual(sense.point_calls, [(50, 20)])
            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.click_calls, 0)
            self.assertEqual(sense.point_calls, [(50, 20)])
            self.assertIn("automation-focus input boundary", state.data["local_failure"])
            resident.store.close()

    def test_invalid_scope_fails_before_probe_or_movement(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            self._event(
                resident,
                completion_scope={
                    "kind": "focused_automation_element_at_pointer",
                    "process_name": "notepad.exe",
                    "title_equals": "Untitled - Notepad",
                    "name_equals": "unsafe authority",
                },
            )
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.move_calls, [])
            self.assertEqual(body.click_calls, 0)
            self.assertEqual(resident.automation_element.point_calls, [])
            self.assertIn("unsupported authority fields", state.data["local_failure"])
            resident.store.close()

    def test_source_window_must_equal_destination_window_for_element_focus(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            event = resident.enqueue(
                "focus the exact UI element at the pointer target",
                kind="ui_state_transition",
                payload={
                    "body_action": {
                        "kind": "pointer_click",
                        "args": {"x_fraction": 0.5, "y_fraction": 0.4, "button": "left"},
                    },
                    "expected_outcome": {
                        "kind": "visual_region_changed",
                        "width_fraction": 0.08,
                        "height_fraction": 0.08,
                    },
                    "completion_scope": {
                        "kind": "focused_automation_element_at_pointer",
                        "process_name": "notepad.exe",
                        "title_equals": "Untitled - Notepad",
                    },
                    "action_precondition": {
                        "kind": "foreground_window_matches",
                        "process_name": "notepad.exe",
                        "title_equals": "Another Notepad Window",
                    },
                    "model_policy": "never",
                },
            )
            self.assertIsNotNone(event)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.move_calls, [])
            self.assertEqual(body.click_calls, 0)
            self.assertEqual(resident.automation_element.point_calls, [])
            self.assertIn("same exact foreground process/title", state.data["local_failure"])
            resident.store.close()

    def test_missing_automation_sense_fails_before_pointer_movement(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            resident.automation_element = None
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.move_calls, [])
            self.assertEqual(body.click_calls, 0)
            self.assertIn("automation-element Sense", state.data["local_failure"])
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
