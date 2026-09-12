from __future__ import annotations

import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from _current_app_content_cleanup_fixture import (
    FIELD_NAME,
    WorkRecordApp,
    require_input_desktop,
)
from zn_agent.core.current_app_text_cleanup_behavior import _STATE_KEY
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.resident_server import ResidentSocketService
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


TASK = "把我现在这个软件里的这份工作记录整理一下：去掉空行和完全重复的行，每行首尾空格也去掉，保留原来的顺序，然后保存。"
_ACCEPTANCE = "fresh saved result in the same process equals the deterministic cleaned work record"


class WindowsInteractiveCurrentAppContentCleanupE2ETests(unittest.TestCase):
    def _drive(self, root: Path, app: WorkRecordApp, *, intervene=None):
        resident = build_resident_runtime(config={"model": {}}, store_path=root / "kernel.db")
        # Match the actual desktop service composition so the mature pointer
        # lifecycle has the same visual sensing authority used in production.
        service = ResidentSocketService(ResidentRpcServer(resident=resident))
        self.assertIs(resident.visual_region, service.visual_region)
        control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
        thread = "e2e13-" + uuid.uuid4().hex[:8]
        control.ledger.create_thread(thread_id=thread)
        _, event = control.start(
            thread,
            TASK,
            payload={"model_policy": "never"},
            acceptance_criteria=[_ACCEPTANCE],
        )
        self.assertIsNotNone(
            resident.work_ledger.work_item_for_event(event.event_id),
            "normal Product Work ingress must establish the Root Work before Resident execution",
        )

        result = None
        trace: list[dict] = []
        intervened = False
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and result is None:
            app.activate(app.result_hwnd or app.hwnd)
            current = resident.live_once()
            state = resident.store.get_working_state()
            meta = state.data.get(_STATE_KEY)
            meta = meta if isinstance(meta, dict) else {}
            actions = [
                action
                for action in resident.body.recent_actions(1024)
                if action.event_id == event.event_id
            ]
            trace.append(
                {
                    "stage": state.stage,
                    "phase": meta.get("phase"),
                    "reground_count": meta.get("reground_count"),
                    "save_dispatch_count": meta.get("save_dispatch_count"),
                    "actions": [action.kind for action in actions[-8:]],
                }
            )
            if intervene is not None and not intervened and state.stage == "e2e13_replace":
                intervene(resident, state, meta)
                intervened = True
                app.activate(app.hwnd)
                continue
            found = app.wait_result(timeout=0.02)
            if found:
                app.result_hwnd = found
            if current is not None and current.event.event_id == event.event_id:
                result = current
            if result is None:
                time.sleep(0.03)
        return resident, event, result, trace, intervened

    def test_happy_path_real_winforms_valuepattern_save_and_fresh_new_window_readback(self):
        require_input_desktop()
        with tempfile.TemporaryDirectory(prefix="zn-e2e13-happy-", ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            app = WorkRecordApp(root)
            app.start()
            resident = None
            try:
                resident, event, result, trace, _ = self._drive(root, app)
                self.assertIsNotNone(result, json.dumps(trace[-20:], ensure_ascii=False))
                self.assertTrue(result.success, result.reason)
                self.assertEqual(result.model_invocations, 0)
                self.assertTrue(app.result_hwnd)
                self.assertNotEqual(app.result_hwnd, app.hwnd)
                self.assertEqual(app.saved_count(), 1)
                actions = [
                    action
                    for action in resident.body.recent_actions(1024)
                    if action.event_id == event.event_id
                ]
                self.assertEqual(sum(action.kind == "automation_value_replace" for action in actions), 1)
                self.assertEqual(sum(action.kind == "pointer_click" for action in actions), 1)
                history = json.dumps([action.args for action in actions], ensure_ascii=False, default=str)
                self.assertNotIn(app.source, history)
                self.assertNotIn(app.expected, history)
                final = resident.store.get_working_state().data[_STATE_KEY]["final_verification"]
                self.assertEqual(final["new_window_handle"], app.result_hwnd)
                self.assertTrue(final["title_postcondition"])
            finally:
                app.close()
                if resident is not None:
                    resident.store.close()

    def test_stale_edit_runtime_is_rejected_then_freshly_regrounded_before_mutation(self):
        require_input_desktop()
        with tempfile.TemporaryDirectory(prefix="zn-e2e13-stale-", ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            app = WorkRecordApp(root)
            app.start()
            resident = None
            old_runtime: list[int] = []

            def intervene(current_resident, _state, meta):
                old_runtime[:] = list(meta["source_target"]["runtime_id"])
                app.trigger_recreate()
                app.wait_flag_consumed(app.recreate_flag)
                deadline = time.monotonic() + 6
                while time.monotonic() < deadline:
                    app.activate(app.hwnd)
                    fresh = current_resident.named_automation_control.find_unique_edit(
                        process_id=app.process.pid,
                        process_name="powershell.exe",
                        name=FIELD_NAME,
                    )
                    if list(fresh.runtime_id) != old_runtime:
                        return
                    time.sleep(0.03)
                raise RuntimeError("recreated Edit did not acquire a fresh RuntimeId")

            try:
                resident, event, result, trace, intervened = self._drive(root, app, intervene=intervene)
                self.assertTrue(intervened)
                self.assertIsNotNone(result, json.dumps(trace[-20:], ensure_ascii=False))
                self.assertTrue(result.success, result.reason)
                self.assertGreaterEqual(
                    resident.store.get_working_state().data[_STATE_KEY]["reground_count"],
                    1,
                )
                self.assertEqual(app.saved_count(), 1)
                actions = [
                    action
                    for action in resident.body.recent_actions(1024)
                    if action.event_id == event.event_id
                ]
                self.assertEqual(sum(action.kind == "automation_value_replace" for action in actions), 1)
            finally:
                app.close()
                if resident is not None:
                    resident.store.close()

    def test_content_drift_blocks_stale_transform_and_reinvestigates(self):
        require_input_desktop()
        with tempfile.TemporaryDirectory(prefix="zn-e2e13-drift-", ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            app = WorkRecordApp(root)
            app.start()
            resident = None

            def intervene(_resident, _state, _meta):
                app.trigger_drift()
                app.wait_flag_consumed(app.drift_flag)

            try:
                resident, _event, result, trace, intervened = self._drive(root, app, intervene=intervene)
                self.assertTrue(intervened)
                self.assertIsNotNone(result, json.dumps(trace[-20:], ensure_ascii=False))
                self.assertTrue(result.success, result.reason)
                meta = resident.store.get_working_state().data[_STATE_KEY]
                self.assertGreaterEqual(meta["reground_count"], 1)
                self.assertEqual(app.saved_count(), 1)
            finally:
                app.close()
                if resident is not None:
                    resident.store.close()

    def test_ambiguous_same_named_edit_produces_zero_mutation(self):
        require_input_desktop()
        with tempfile.TemporaryDirectory(prefix="zn-e2e13-ambiguous-", ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            app = WorkRecordApp(root, ambiguous=True)
            app.start()
            resident = None
            try:
                resident, event, result, trace, _ = self._drive(root, app)
                self.assertIsNotNone(result, json.dumps(trace[-20:], ensure_ascii=False))
                self.assertFalse(result.success)
                self.assertEqual(app.saved_count(), 0)
                actions = [
                    action
                    for action in resident.body.recent_actions(1024)
                    if action.event_id == event.event_id
                ]
                self.assertFalse(
                    any(action.kind in {"automation_value_replace", "pointer_click"} for action in actions)
                )
            finally:
                app.close()
                if resident is not None:
                    resident.store.close()

    def test_final_application_mismatch_does_not_complete(self):
        require_input_desktop()
        with tempfile.TemporaryDirectory(prefix="zn-e2e13-mismatch-", ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            app = WorkRecordApp(root, mismatch=True)
            app.start()
            resident = None
            try:
                resident, event, result, trace, _ = self._drive(root, app)
                self.assertIsNotNone(result, json.dumps(trace[-20:], ensure_ascii=False))
                self.assertFalse(result.success)
                self.assertEqual(app.saved_count(), 1)
                actions = [
                    action
                    for action in resident.body.recent_actions(1024)
                    if action.event_id == event.event_id
                ]
                self.assertEqual(sum(action.kind == "pointer_click" for action in actions), 1)
                self.assertNotEqual(resident.store.get_working_state().stage, "complete")
            finally:
                app.close()
                if resident is not None:
                    resident.store.close()


if __name__ == "__main__":
    unittest.main()
