from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core import ExecutionPath
from zn_agent.core.automation_element_sense import AutomationElementObservation
from zn_agent.core.focused_control_sense import FocusedControlObservation
from zn_agent.core.focused_text_sense import FocusedTextObservation, NativeFocusedTextSense
from zn_agent.core.foreground_window_sense import ForegroundWindowObservation
from zn_agent.core.keyboard_text_body import KeyboardTextBody
from zn_agent.core.models import utc_now
from zn_agent.core.provider_bridge import build_resident_runtime


class _TextBody(KeyboardTextBody):
    def __init__(self, *, resident, current_text: str = "", partial: bool = False):
        super().__init__(resident=resident)
        self.current_text = current_text
        self.partial = bool(partial)
        self.keyboard_calls: list[str] = []

    def _send_keyboard_text(self, text: str) -> tuple[int, int]:
        self.keyboard_calls.append(text)
        _, units = self.validate_text(text)
        expected = len(units) * 2
        if self.partial:
            return expected - 1, expected
        self.current_text += text
        return expected, expected


class _ForegroundSense:
    def probe(self):
        return ForegroundWindowObservation(
            process_id=200,
            process_name="notepad.exe",
            title="Untitled - Notepad",
            class_name="Notepad",
            captured_at=utc_now(),
            source="test-foreground",
        )


class _FocusedControlSense:
    def probe(self):
        return FocusedControlObservation(
            process_id=200,
            process_name="notepad.exe",
            foreground_title="Untitled - Notepad",
            foreground_class_name="Notepad",
            control_class_name="Edit",
            control_id=1003,
            enabled=True,
            visible=True,
            captured_at=utc_now(),
            source="test-focused-control",
        )


class _AutomationSense:
    RUNTIME_ID = (42, 9, 3)

    def __init__(self, *, control_type: int = 50004, native_window_handle: int = 9003):
        self.control_type = int(control_type)
        self.native_window_handle = int(native_window_handle)
        self.calls = 0

    def probe_focused(self):
        self.calls += 1
        return AutomationElementObservation(
            runtime_id=self.RUNTIME_ID,
            process_id=200,
            process_name="notepad.exe",
            framework_id="Win32",
            control_type=self.control_type,
            class_name="Edit",
            is_enabled=True,
            is_keyboard_focusable=True,
            has_keyboard_focus=True,
            is_offscreen=False,
            native_window_handle=self.native_window_handle,
            captured_at=utc_now(),
            automation_id="edit-1003",
            source="test-uia",
        )

    def probe_at_point(self, x: int, y: int):
        return self.probe_focused()


class _FocusedTextSense:
    def __init__(self, body: _TextBody, *, native_window_handle: int = 9003):
        self.body = body
        self.native_window_handle = int(native_window_handle)
        self.calls = 0

    def probe(self):
        self.calls += 1
        return FocusedTextObservation(
            native_window_handle=self.native_window_handle,
            process_id=200,
            process_name="notepad.exe",
            foreground_title="Untitled - Notepad",
            control_class_name="Edit",
            control_id=1003,
            enabled=True,
            visible=True,
            text_length=len(self.body.current_text),
            text_sha256=NativeFocusedTextSense.digest_text(self.body.current_text),
            is_password=False,
            is_read_only=False,
            captured_at=utc_now(),
            source="test-focused-text",
        )


class FocusedTextEntryTests(unittest.TestCase):
    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 16) -> None:
        for _ in range(limit):
            if resident.store.get_working_state().stage == stage:
                return
            result = resident.live_once()
            if result is not None:
                raise AssertionError(f"event reached terminal result before {stage}: {result}")
        raise AssertionError(f"resident did not reach {stage}")

    @staticmethod
    def _resident(
        tmp: str,
        *,
        current_text: str = "",
        partial: bool = False,
        automation_control_type: int = 50004,
        automation_hwnd: int = 9003,
        text_hwnd: int = 9003,
    ):
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )
        body = _TextBody(
            resident=resident,
            current_text=current_text,
            partial=partial,
        )
        resident.body = body
        resident.foreground_window = _ForegroundSense()
        resident.focused_control = _FocusedControlSense()
        resident.automation_element = _AutomationSense(
            control_type=automation_control_type,
            native_window_handle=automation_hwnd,
        )
        resident.focused_text = _FocusedTextSense(
            body,
            native_window_handle=text_hwnd,
        )
        return resident, body

    @staticmethod
    def _event(resident, *, text: str = "ZN native text", completion_scope=None):
        return resident.enqueue(
            "type bounded text into the exact focused native Edit",
            kind="ui_state_transition",
            payload={
                "body_action": {
                    "kind": "keyboard_text",
                    "args": {"text": text},
                },
                "expected_outcome": {
                    "kind": "focused_text_equals_action_text",
                },
                "completion_scope": completion_scope
                or {
                    "kind": "focused_native_edit_text",
                    "process_name": "notepad.exe",
                    "title_equals": "Untitled - Notepad",
                    "control_class_name": "Edit",
                    "control_id": 1003,
                    "control_type": 50004,
                    "class_name_equals": "Edit",
                },
                "action_precondition": {
                    "kind": "foreground_window_matches",
                    "process_name": "notepad.exe",
                    "title_equals": "Untitled - Notepad",
                },
                "model_policy": "never",
            },
        )

    def test_empty_exact_target_types_once_then_verifies_fresh_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            try:
                self._event(resident)
                self._advance_until_stage(resident, "native_action")

                self.assertIsNone(resident.live_once())
                prepared = resident.store.get_working_state().data.get(
                    resident._TEXT_PRECONDITION_KEY
                )
                self.assertIsInstance(prepared, dict)
                self.assertEqual(body.keyboard_calls, [])
                self.assertEqual(body.current_text, "")
                self.assertNotIn("text", prepared.get("text_observation", {}))

                self.assertIsNone(resident.live_once())
                self.assertEqual(body.keyboard_calls, ["ZN native text"])
                self.assertEqual(body.current_text, "ZN native text")
                state = resident.store.get_working_state()
                self.assertEqual(state.stage, "native_verification")
                action_result = state.data.get("native_action_result", {})
                self.assertNotIn("text", action_result.get("data", {}))
                self.assertEqual(len(action_result.get("data", {}).get("text_sha256", "")), 64)

                result = resident.live_once()
                self.assertIsNotNone(result)
                self.assertTrue(result.success, result)
                self.assertEqual(result.execution_path, ExecutionPath.BODY)
                self.assertEqual(result.model_invocations, 0)
                self.assertIn("text-digest", result.reason)
                verified = resident.store.get_working_state().data[
                    "native_verification_result"
                ]
                self.assertTrue(verified["verified"])
                self.assertNotIn("text", verified["text_observation"])
            finally:
                resident.store.close()

    def test_already_matching_text_completes_without_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp, current_text="already")
            try:
                self._event(resident, text="already")
                self._advance_until_stage(resident, "native_action")

                result = resident.live_once()

                self.assertIsNotNone(result)
                self.assertTrue(result.success, result)
                self.assertEqual(body.keyboard_calls, [])
                self.assertIn("already matched", result.reason)
            finally:
                resident.store.close()

    def test_nonempty_different_text_fails_before_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp, current_text="existing")
            try:
                self._event(resident, text="new")
                self._advance_until_stage(resident, "native_action")

                self.assertIsNone(resident.live_once())

                state = resident.store.get_working_state()
                self.assertEqual(state.stage, "native_investigation")
                self.assertEqual(body.keyboard_calls, [])
                self.assertIn("non-empty", state.data.get("local_failure", ""))
            finally:
                resident.store.close()

    def test_uia_and_native_text_hwnd_mismatch_fails_before_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp, automation_hwnd=9003, text_hwnd=9004)
            try:
                self._event(resident)
                self._advance_until_stage(resident, "native_action")

                self.assertIsNone(resident.live_once())

                state = resident.store.get_working_state()
                self.assertEqual(state.stage, "native_investigation")
                self.assertEqual(body.keyboard_calls, [])
                self.assertIn("same native HWND", state.data.get("local_failure", ""))
            finally:
                resident.store.close()

    def test_unknown_scope_authority_fails_closed_before_sensing_or_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            try:
                self._event(
                    resident,
                    completion_scope={
                        "kind": "focused_native_edit_text",
                        "process_name": "notepad.exe",
                        "title_equals": "Untitled - Notepad",
                        "control_class_name": "Edit",
                        "control_id": 1003,
                        "control_type": 50004,
                        "class_name_equals": "Edit",
                        "automation_id_equals": "edit-1003",
                    },
                )
                self._advance_until_stage(resident, "native_action")

                self.assertIsNone(resident.live_once())

                state = resident.store.get_working_state()
                self.assertEqual(state.stage, "native_investigation")
                self.assertEqual(body.keyboard_calls, [])
                self.assertIn("unsupported authority fields", state.data.get("local_failure", ""))
            finally:
                resident.store.close()

    def test_started_marker_refuses_blind_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp)
            try:
                self._event(resident)
                self._advance_until_stage(resident, "native_action")
                self.assertIsNone(resident.live_once())
                state = resident.store.get_working_state()
                intent = state.data["native_action_intent"]
                prepared = state.data[resident._TEXT_PRECONDITION_KEY]
                state.data[resident._TEXT_EXECUTION_KEY] = {
                    "intent_id": intent["intent_id"],
                    "status": "started",
                    "input_sent": None,
                    "target_runtime_id": list(prepared["target_runtime_id"]),
                    "expected_text_sha256": prepared["expected_text_sha256"],
                    "expected_text_chars": prepared["expected_text_chars"],
                    "started_at": utc_now(),
                    "action_id": None,
                }
                resident.store.save_working_state(state)

                self.assertIsNone(resident.live_once())

                recovered = resident.store.get_working_state()
                self.assertEqual(recovered.stage, "native_investigation")
                self.assertEqual(body.keyboard_calls, [])
                self.assertIn("refusing blind replay", recovered.data.get("local_failure", ""))
            finally:
                resident.store.close()

    def test_partial_send_returns_to_investigation_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(tmp, partial=True)
            try:
                self._event(resident)
                self._advance_until_stage(resident, "native_action")
                self.assertIsNone(resident.live_once())

                self.assertIsNone(resident.live_once())

                state = resident.store.get_working_state()
                self.assertEqual(state.stage, "native_investigation")
                self.assertEqual(body.keyboard_calls, ["ZN native text"])
                self.assertEqual(body.current_text, "")
                self.assertIn("must not replay blindly", state.data.get("local_failure", ""))
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
