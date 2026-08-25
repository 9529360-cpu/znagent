from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core import ExecutionPath
from zn_agent.core.body import NativeBody
from zn_agent.core.foreground_window_sense import (
    ForegroundWindowObservation,
    NativeForegroundWindowSense,
)
from zn_agent.core.models import utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.visual_region_sense import VisualRegionObservation


_DEFAULT_ACTION_PRECONDITION = object()


class _SemanticClickBody(NativeBody):
    def __init__(self, *, resident=None):
        super().__init__(resident=resident)
        self.pointer_x = 0
        self.pointer_y = 0
        self.screen_width = 101
        self.screen_height = 51
        self.move_calls: list[tuple[int, int]] = []
        self.click_calls = 0

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


class _SemanticVisualRegion:
    def __init__(self, body: _SemanticClickBody):
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


class _SemanticForegroundWindow:
    def __init__(
        self,
        body: _SemanticClickBody,
        *,
        target_before_click: bool = False,
        target_after_click: bool = True,
        drift_after_move: bool = False,
    ):
        self.body = body
        self.target_before_click = bool(target_before_click)
        self.target_after_click = bool(target_after_click)
        self.drift_after_move = bool(drift_after_move)
        self.calls = 0

    @staticmethod
    def _observation(
        *,
        process_id: int,
        process_name: str,
        title: str,
        class_name: str,
    ) -> ForegroundWindowObservation:
        return ForegroundWindowObservation(
            process_id=process_id,
            title=title,
            process_name=process_name,
            class_name=class_name,
            captured_at=utc_now(),
            source="test-foreground-window",
        )

    def probe(self) -> ForegroundWindowObservation:
        self.calls += 1
        if self.body.click_calls > 0:
            if self.target_after_click:
                return self._observation(
                    process_id=200,
                    process_name="notepad.exe",
                    title="Untitled - Notepad",
                    class_name="Notepad",
                )
            return self._observation(
                process_id=100,
                process_name="explorer.exe",
                title="Desktop",
                class_name="Progman",
            )
        if self.drift_after_move and self.body.move_calls:
            return self._observation(
                process_id=300,
                process_name="calc.exe",
                title="Calculator",
                class_name="ApplicationFrameWindow",
            )
        if self.target_before_click:
            return self._observation(
                process_id=200,
                process_name="notepad.exe",
                title="Untitled - Notepad",
                class_name="Notepad",
            )
        return self._observation(
            process_id=100,
            process_name="explorer.exe",
            title="Desktop",
            class_name="Progman",
        )


class PointerClickSemanticCompletionTests(unittest.TestCase):
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
    def _event(
        resident,
        *,
        completion_scope=None,
        action_precondition=_DEFAULT_ACTION_PRECONDITION,
        kind="ui_state_transition",
    ):
        scope = completion_scope or {
            "kind": "foreground_window_matches",
            "process_name": "notepad.exe",
            "title_equals": "Untitled - Notepad",
        }
        payload = {
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
            "model_policy": "never",
        }
        if action_precondition is _DEFAULT_ACTION_PRECONDITION:
            payload["action_precondition"] = {
                "kind": "foreground_window_matches",
                "process_name": "explorer.exe",
                "title_equals": "Desktop",
            }
        elif action_precondition is not None:
            payload["action_precondition"] = action_precondition
        return resident.enqueue(
            "reach the explicitly typed foreground window state",
            kind=kind,
            payload=payload,
        )

    @staticmethod
    def _resident(tmp: str):
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )
        body = _SemanticClickBody(resident=resident)
        resident.body = body
        resident.visual_region = _SemanticVisualRegion(body)
        return resident, body

    def test_ui_state_transition_requires_exact_semantic_scope_before_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            resident.foreground_window = _SemanticForegroundWindow(body)
            self._event(
                resident,
                completion_scope={
                    "kind": "foreground_window_matches",
                    "process_name": "notepad.exe",
                },
            )
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.move_calls, [])
            self.assertEqual(body.click_calls, 0)
            self.assertIn("title_equals", state.data["local_failure"])
            resident.store.close()

    def test_ui_state_transition_requires_typed_event_kind_before_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            foreground = _SemanticForegroundWindow(body)
            resident.foreground_window = foreground
            self._event(resident, kind="user_task")
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.move_calls, [])
            self.assertEqual(body.click_calls, 0)
            self.assertEqual(foreground.calls, 0)
            self.assertIn("ui_state_transition", state.data["local_failure"])
            resident.store.close()

    def test_already_satisfied_ui_state_completes_without_pointer_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            foreground = _SemanticForegroundWindow(body, target_before_click=True)
            resident.foreground_window = foreground
            self._event(resident, action_precondition=None)
            self._advance_until_stage(resident, "native_action")

            result = resident.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.BODY)
            self.assertEqual(body.move_calls, [])
            self.assertEqual(body.click_calls, 0)
            self.assertEqual(resident.visual_region.calls, 0)
            self.assertEqual(foreground.calls, 1)
            self.assertIn("no pointer input was sent", result.reason)
            resident.store.close()

    def test_mutating_ui_transition_requires_action_precondition_before_pointer_movement(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            foreground = _SemanticForegroundWindow(body)
            resident.foreground_window = foreground
            self._event(resident, action_precondition=None)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.move_calls, [])
            self.assertEqual(body.click_calls, 0)
            self.assertEqual(foreground.calls, 1)
            self.assertIn("action_precondition", state.data["local_failure"])
            resident.store.close()

    def test_action_precondition_rejects_unknown_authority_fields_before_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            foreground = _SemanticForegroundWindow(body)
            resident.foreground_window = foreground
            self._event(
                resident,
                action_precondition={
                    "kind": "foreground_window_matches",
                    "process_name": "explorer.exe",
                    "title_equals": "Desktop",
                    "title_contains": "Desk",
                },
            )
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.move_calls, [])
            self.assertEqual(body.click_calls, 0)
            self.assertEqual(foreground.calls, 0)
            self.assertIn("unsupported authority fields", state.data["local_failure"])
            resident.store.close()

    def test_action_precondition_must_match_fresh_foreground_before_pointer_movement(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            foreground = _SemanticForegroundWindow(body)
            resident.foreground_window = foreground
            self._event(
                resident,
                action_precondition={
                    "kind": "foreground_window_matches",
                    "process_name": "calc.exe",
                    "title_equals": "Calculator",
                },
            )
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.move_calls, [])
            self.assertEqual(body.click_calls, 0)
            self.assertEqual(foreground.calls, 1)
            self.assertIn("before pointer movement", state.data["local_failure"])
            resident.store.close()

    def test_ui_state_transition_needs_fresh_semantic_match_after_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            foreground = _SemanticForegroundWindow(body)
            resident.foreground_window = foreground
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            self.assertEqual(body.move_calls, [(50, 20)])
            self.assertEqual(body.click_calls, 0)

            self.assertIsNone(resident.live_once())
            self.assertEqual(body.click_calls, 1)
            self.assertEqual(resident.store.get_working_state().stage, "native_verification")

            result = resident.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.BODY)
            self.assertEqual(body.click_calls, 1)
            self.assertEqual(foreground.calls, 3)
            self.assertEqual(resident.visual_region.calls, 2)
            admission = resident.store.get_working_state().data[
                resident._SEMANTIC_PRECONDITION_KEY
            ]
            self.assertTrue(admission["verified"])
            self.assertTrue(admission["reverified"])
            self.assertIn("foreground-window Sense exactly matched", result.reason)
            self.assertIn("task prose was not used", result.reason)
            resident.store.close()

    def test_foreground_drift_after_pointer_move_fails_before_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            foreground = _SemanticForegroundWindow(body, drift_after_move=True)
            resident.foreground_window = foreground
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            self.assertEqual(body.move_calls, [(50, 20)])
            self.assertEqual(body.click_calls, 0)

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.click_calls, 0)
            self.assertEqual(foreground.calls, 2)
            self.assertEqual(resident.visual_region.calls, 0)
            self.assertIn("drifted after pointer preparation", state.data["local_failure"])
            resident.store.close()

    def test_pre_input_action_precondition_admission_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            foreground = _SemanticForegroundWindow(body)
            resident.foreground_window = foreground
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(body.click_calls, 0)
            state.data[resident._SEMANTIC_PRECONDITION_KEY]["action_precondition"] = {
                "kind": "foreground_window_matches",
                "process_name": "calc.exe",
                "title_equals": "Calculator",
            }
            resident.store.save_working_state(state)

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.click_calls, 0)
            self.assertEqual(foreground.calls, 1)
            self.assertIn("drifted after pointer preparation", state.data["local_failure"])
            resident.store.close()

    def test_semantic_mismatch_after_click_returns_to_investigation_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            foreground = _SemanticForegroundWindow(body, target_after_click=False)
            resident.foreground_window = foreground
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
            semantic = state.data[resident._SEMANTIC_VERIFICATION_KEY]
            self.assertFalse(semantic["verified"])
            self.assertIn("semantic completion failed", state.data["local_failure"])
            self.assertIn("without replaying pointer input", state.next_action)
            resident.store.close()

    def test_post_input_scope_drift_is_rejected_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            resident.foreground_window = _SemanticForegroundWindow(body)
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            self.assertIsNone(resident.live_once())
            self.assertEqual(body.click_calls, 1)
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_verification")
            state.data["native_verification"]["completion_scope"] = {
                "kind": "verified_effect",
                "effect_kind": "visual_region_changed",
            }
            resident.store.save_working_state(state)

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.click_calls, 1)
            self.assertIn("drifted", state.data["local_failure"])
            self.assertIn("without replaying pointer input", state.next_action)
            resident.store.close()

    def test_post_input_action_precondition_drift_is_rejected_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            resident.foreground_window = _SemanticForegroundWindow(body)
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            self.assertIsNone(resident.live_once())
            self.assertEqual(body.click_calls, 1)
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_verification")
            state.data["native_verification"]["action_precondition"] = {
                "kind": "foreground_window_matches",
                "process_name": "calc.exe",
                "title_equals": "Calculator",
            }
            resident.store.save_working_state(state)

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.click_calls, 1)
            self.assertIn("action_precondition drifted", state.data["local_failure"])
            self.assertIn("without replaying pointer input", state.next_action)
            resident.store.close()

    def test_missing_semantic_sense_fails_before_pointer_movement(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            resident.foreground_window = None
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.move_calls, [])
            self.assertEqual(body.click_calls, 0)
            self.assertIn("foreground window Sense", state.data["local_failure"])
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
