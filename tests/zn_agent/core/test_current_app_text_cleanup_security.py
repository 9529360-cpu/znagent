from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.automation_named_control_sense import NamedAutomationControlObservation
from zn_agent.core.automation_text_content import (
    AutomationTextRead,
    AutomationTextTargetSnapshot,
    AutomationValueReplacementResult,
    _WindowsAutomationTextWorker,
    text_sha256,
)
from zn_agent.core.current_app_text_body import CurrentAppTextAwareBody
from zn_agent.core.current_app_text_cleanup_behavior import _STATE_KEY
from zn_agent.core.current_app_text_cleanup_goal import (
    CurrentAppTextCleanupGoal,
    deterministic_text_cleanup,
)
from zn_agent.core.foreground_window_sense import ForegroundWindowObservation
from zn_agent.core.machine_capability_body import MachineCapabilityBody
from zn_agent.core.models import WorkingState, utc_now
from zn_agent.core.provider_bridge import build_resident_runtime


RID = (71, 72, 73)
RID_RECREATED = (71, 72, 99)
SOURCE = " A \r\n\r\nB\r\n A "
RESULT = "A\r\nB"
TASK = "把我现在这个软件里的这份工作记录整理一下：去掉空行和完全重复的行，每行首尾空格也去掉，保留原来的顺序，然后保存。"


def _target(**overrides):
    values = {
        "runtime_id": RID,
        "process_id": 222,
        "process_name": "fixture.exe",
        "window_handle": 8181,
        "name": "工作记录",
        "control_type": 50004,
        "class_name": "WindowsForms10.EDIT.app.0",
        "is_enabled": True,
        "is_offscreen": False,
        "is_password": False,
        "is_value_pattern_available": True,
        "value_is_read_only": False,
        "captured_at": "2026-09-13T00:00:00+00:00",
        "source": "test-uia",
    }
    values.update(overrides)
    return AutomationTextTargetSnapshot(**values)


class NativeReplacementTargetPolicyTests(unittest.TestCase):
    def _require(self, target, *, allow_read_only=False):
        _WindowsAutomationTextWorker._require_target(
            target,
            process_id=222,
            process_name="fixture.exe",
            window_handle=8181,
            name="工作记录",
            runtime_id=RID,
            allow_read_only=allow_read_only,
        )

    def test_password_read_only_disabled_offscreen_and_missing_valuepattern_are_rejected(self):
        cases = [
            _target(is_password=True),
            _target(value_is_read_only=True),
            _target(is_enabled=False),
            _target(is_offscreen=True),
            _target(is_value_pattern_available=False),
        ]
        for target in cases:
            with self.subTest(target=target), self.assertRaises(RuntimeError):
                self._require(target)

    def test_stale_runtime_wrong_process_wrong_hwnd_and_wrong_control_type_are_rejected(self):
        cases = [
            _target(runtime_id=(1, 2, 999)),
            _target(process_id=333),
            _target(process_name="other.exe"),
            _target(window_handle=9999),
            _target(control_type=50000),
        ]
        for target in cases:
            with self.subTest(target=target), self.assertRaises(RuntimeError):
                self._require(target)

    def test_read_only_is_permitted_only_for_explicit_verification(self):
        self._require(_target(value_is_read_only=True), allow_read_only=True)


class ProductBodyCompositionTests(unittest.TestCase):
    def test_e2e13_extends_final_machine_capability_body_instead_of_downgrading_it(self):
        self.assertTrue(issubclass(CurrentAppTextAwareBody, MachineCapabilityBody))
        self.assertTrue(
            CurrentAppTextAwareBody._requires_guard(
                "browser_fill_named_text_and_click_named_button_to_url", {}
            )
        )

        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertIsInstance(resident.body, CurrentAppTextAwareBody)
                self.assertIsInstance(resident.body, MachineCapabilityBody)
                self.assertTrue(hasattr(resident.body, "device_capabilities"))
                self.assertTrue(
                    callable(getattr(resident.body, "activate_admitted_application_window", None))
                )
            finally:
                resident.store.close()


class _SuccessfulReplacement:
    def replace_exact(self, **kwargs):
        return AutomationValueReplacementResult(
            success=True,
            mutation_dispatched=True,
            postcondition_verified=True,
            process_id=kwargs["process_id"],
            process_name=kwargs["process_name"],
            window_handle=kwargs["window_handle"],
            name=kwargs["name"],
            runtime_id=tuple(kwargs["runtime_id"]),
            source_chars=kwargs["source_chars"],
            source_sha256=kwargs["source_sha256"],
            result_chars=kwargs["result_chars"],
            result_sha256=kwargs["result_sha256"],
        )


class DurableBodyRedactionTests(unittest.TestCase):
    def test_product_body_history_never_persists_raw_replacement_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=store_path,
            )
            try:
                resident.body._automation_value_replacement = _SuccessfulReplacement()
                response = resident.body.act(
                    "automation_value_replace",
                    event_id="evt-e2e13-redaction",
                    process_id=222,
                    process_name="fixture.exe",
                    window_handle=8181,
                    name="工作记录",
                    runtime_id=list(RID),
                    source_chars=len(SOURCE),
                    source_sha256=text_sha256(SOURCE),
                    replacement_text=RESULT,
                    result_chars=len(RESULT),
                    result_sha256=text_sha256(RESULT),
                )
                self.assertTrue(response.success, response.error)
                with closing(sqlite3.connect(store_path)) as conn:
                    row = conn.execute(
                        "SELECT action_json FROM native_body_actions WHERE action_id = ?",
                        (response.action_id,),
                    ).fetchone()
                self.assertIsNotNone(row)
                persisted = json.loads(str(row[0]))
                args = persisted["args"]
                self.assertNotIn("replacement_text", args)
                self.assertTrue(args.get("replacement_text_redacted"))
                self.assertEqual(args.get("replacement_chars"), len(RESULT))
                self.assertEqual(args.get("replacement_sha256"), text_sha256(RESULT))
                serialized = json.dumps(persisted, ensure_ascii=False, sort_keys=True)
                self.assertNotIn(SOURCE, serialized)
                self.assertNotIn(RESULT, serialized)
            finally:
                resident.store.close()


class _Foreground:
    def __init__(self, *, hwnd=8181, pid=222, process_name="fixture.exe"):
        self.hwnd = int(hwnd)
        self.pid = int(pid)
        self.process_name = str(process_name)

    def probe(self):
        return ForegroundWindowObservation(
            process_id=self.pid,
            title="ZN 工作记录",
            process_name=self.process_name,
            class_name="WindowsForms10.Window",
            captured_at=utc_now(),
            window_handle=self.hwnd,
        )


class _Named:
    def __init__(self, runtime_id=RID_RECREATED):
        self.runtime_id = tuple(runtime_id)

    def find_unique_edit(self, **_kwargs):
        return NamedAutomationControlObservation(
            runtime_id=self.runtime_id,
            process_id=222,
            process_name="fixture.exe",
            name="工作记录",
            control_type=50004,
            class_name="WindowsForms10.EDIT.app.0",
            is_enabled=True,
            is_offscreen=False,
            left=10,
            top=10,
            right=210,
            bottom=140,
            center_x_fraction=0.25,
            center_y_fraction=0.30,
            captured_at=utc_now(),
            is_keyboard_focusable=True,
            has_keyboard_focus=True,
            is_password=False,
            is_value_pattern_available=True,
            value_is_read_only=False,
        )


class _CurrentText:
    def __init__(self, text: str, *, runtime_id=RID_RECREATED):
        self.text = str(text)
        self.runtime_id = tuple(runtime_id)

    def read_exact(self, **_kwargs):
        snapshot = _target(runtime_id=self.runtime_id, captured_at=utc_now())
        return AutomationTextRead(self.text, snapshot, snapshot)


class _ForbiddenReplacementDispatch:
    def __init__(self):
        self.calls = 0

    def replace_exact(self, **_kwargs):
        self.calls += 1
        raise AssertionError("restart recovery must not dispatch an additional SetValue")


class CurrentAppReplacementRestartRecoveryTests(unittest.TestCase):
    @staticmethod
    def _goal():
        return CurrentAppTextCleanupGoal(
            kind="foreground_desktop_text_cleanup",
            field_name="工作记录",
            save_button_name="保存",
            transform="trim_drop_blank_dedupe_stable",
        )

    @classmethod
    def _seed_stale_replace_state(cls, resident, event):
        transformed = deterministic_text_cleanup(SOURCE)
        state = WorkingState(
            current_event_id=event.event_id,
            stage="e2e13_replace",
            next_action="freshly revalidate source identity/content then perform exact bounded replacement",
            data={
                _STATE_KEY: {
                    "version": 1,
                    "goal": cls._goal().to_dict(),
                    "phase": "replace",
                    "process_id": 222,
                    "process_name": "fixture.exe",
                    "source_window_handle": 8181,
                    "source_window_title": "ZN 工作记录",
                    "source_target": {
                        "runtime_id": list(RID),
                        "process_id": 222,
                        "process_name": "fixture.exe",
                        "semantic_name": "工作记录",
                    },
                    "source_evidence": {
                        "chars": len(SOURCE),
                        "sha256": text_sha256(SOURCE),
                        "semantic_target_name": "工作记录",
                    },
                    "transform": transformed.audit,
                    "reground_count": 0,
                    "save_dispatch_count": 0,
                    "final_observation_count": 0,
                    "started_at": utc_now(),
                }
            },
        )
        resident.store.save_working_state(state)
        return transformed

    @staticmethod
    def _seed_attempt(resident, event, transformed, *, status: str):
        args = {
            "process_id": 222,
            "process_name": "fixture.exe",
            "window_handle": 8181,
            "name": "工作记录",
            "runtime_id": list(RID),
            "source_chars": transformed.source_chars,
            "source_sha256": transformed.source_sha256,
            "replacement_text": transformed.result_text,
            "result_chars": transformed.result_chars,
            "result_sha256": transformed.result_sha256,
        }
        attempt_id = f"sidefx-e2e13-{status}"
        resident.body._start_attempt(
            attempt_id=attempt_id,
            event_id=event.event_id,
            kind="automation_value_replace",
            signature_hash=resident.body._signature_hash("automation_value_replace", args),
        )
        if status == "observed":
            resident.body._finish_attempt(
                attempt_id,
                type("Observed", (), {
                    "completed_at": utc_now(),
                    "action_id": "replace-observed-before-checkpoint",
                    "success": True,
                })(),
            )
        return attempt_id

    @staticmethod
    def _attempt_status(store_path: Path, attempt_id: str):
        with closing(sqlite3.connect(store_path)) as conn:
            row = conn.execute(
                "SELECT status FROM resident_side_effect_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
        return str(row[0]) if row is not None else None

    @staticmethod
    def _restore(store_path: Path, *, current_text=RESULT, runtime_id=RID_RECREATED):
        resident = build_resident_runtime(config={"model": {}}, store_path=store_path)
        resident.foreground_window = _Foreground()
        resident.named_automation_control = _Named(runtime_id)
        resident.current_app_text_content = _CurrentText(current_text, runtime_id=runtime_id)
        forbidden = _ForbiddenReplacementDispatch()
        resident.body._automation_value_replacement = forbidden
        return resident, forbidden

    def _exercise_restart_recovery(self, *, attempt_status: str):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            first = build_resident_runtime(config={"model": {}}, store_path=store_path)
            event = first.enqueue(
                TASK,
                kind="desktop_user_event",
                payload={"model_policy": "never"},
            )
            transformed = self._seed_stale_replace_state(first, event)
            attempt_id = self._seed_attempt(
                first,
                event,
                transformed,
                status=attempt_status,
            )
            first.store.close()

            restored, forbidden = self._restore(store_path)
            try:
                restored_event = restored.store.get_event(event.event_id)
                self.assertIsNotNone(restored_event)
                state = restored.store.get_working_state()
                result = restored._advance_event_step(
                    restored_event,
                    state,
                    readiness=None,
                    learning_evidence=[],
                )
                self.assertIsNone(result)
                self.assertEqual(forbidden.calls, 0)
                recovered = restored.store.get_working_state()
                self.assertEqual(recovered.stage, "e2e13_verify_replacement")
                recovery = recovered.data[_STATE_KEY]["replacement_recovery"]
                self.assertEqual(recovery["attempt_id"], attempt_id)
                self.assertEqual(recovery["status_before"], attempt_status)
                self.assertEqual(recovery["status_after"], "verified_effect")
                self.assertEqual(recovery["additional_replacement_dispatches"], 0)
                self.assertEqual(tuple(recovery["runtime_id"]), RID_RECREATED)
                self.assertEqual(self._attempt_status(store_path, attempt_id), "verified_effect")

                # Recovery only proves the interrupted mutation. The normal path
                # still performs one fresh exact read before Save admission.
                self.assertIsNone(
                    restored._advance_event_step(
                        restored_event,
                        recovered,
                        readiness=None,
                        learning_evidence=[],
                    )
                )
                after_verify = restored.store.get_working_state()
                self.assertEqual(after_verify.stage, "e2e13_save_prepare")
                self.assertEqual(forbidden.calls, 0)

                durable = json.dumps(after_verify.data, ensure_ascii=False, sort_keys=True)
                self.assertNotIn(SOURCE, durable)
                self.assertNotIn(RESULT, durable)
            finally:
                restored.store.close()

    def test_started_crash_restart_resolves_fresh_expected_result_with_zero_setvalue_replay(self):
        self._exercise_restart_recovery(attempt_status="started")

    def test_observed_before_checkpoint_restart_resolves_with_zero_setvalue_replay(self):
        self._exercise_restart_recovery(attempt_status="observed")

    def test_recovery_resolution_crash_is_restart_safe_and_still_zero_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            first = build_resident_runtime(config={"model": {}}, store_path=store_path)
            event = first.enqueue(TASK, kind="desktop_user_event", payload={"model_policy": "never"})
            transformed = self._seed_stale_replace_state(first, event)
            attempt_id = self._seed_attempt(first, event, transformed, status="started")
            self.assertTrue(
                first.body.resolve_uncertain_attempt(
                    attempt_id,
                    event_id=event.event_id,
                    status="verified_effect",
                )
            )
            # Simulate a second crash before WorkingState leaves e2e13_replace.
            first.store.close()

            restored, forbidden = self._restore(store_path)
            try:
                restored_event = restored.store.get_event(event.event_id)
                state = restored.store.get_working_state()
                self.assertIsNone(
                    restored._advance_event_step(
                        restored_event,
                        state,
                        readiness=None,
                        learning_evidence=[],
                    )
                )
                self.assertEqual(forbidden.calls, 0)
                self.assertEqual(restored.store.get_working_state().stage, "e2e13_verify_replacement")
                self.assertEqual(self._attempt_status(store_path, attempt_id), "verified_effect")
            finally:
                restored.store.close()

    def test_unresolved_attempt_with_mismatched_current_text_fails_closed_without_new_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            first = build_resident_runtime(config={"model": {}}, store_path=store_path)
            event = first.enqueue(TASK, kind="desktop_user_event", payload={"model_policy": "never"})
            transformed = self._seed_stale_replace_state(first, event)
            attempt_id = self._seed_attempt(first, event, transformed, status="started")
            first.store.close()

            restored, forbidden = self._restore(store_path, current_text="用户在崩溃后又改了内容")
            try:
                restored_event = restored.store.get_event(event.event_id)
                state = restored.store.get_working_state()
                result = restored._advance_event_step(
                    restored_event,
                    state,
                    readiness=None,
                    learning_evidence=[],
                )
                self.assertIsNotNone(result)
                self.assertFalse(result.success)
                self.assertEqual(forbidden.calls, 0)
                self.assertEqual(self._attempt_status(store_path, attempt_id), "started")
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main()
