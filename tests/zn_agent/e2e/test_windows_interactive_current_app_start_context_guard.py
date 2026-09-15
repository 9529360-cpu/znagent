from __future__ import annotations

import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from _current_app_content_cleanup_fixture import WorkRecordApp, require_input_desktop
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.windows_companion_current_app_guard import _STATE_KEY
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


TASK = "把我现在这个软件里的这份工作记录整理一下：去掉空行和完全重复的行，每行首尾空格也去掉，保留原来的顺序，然后保存。"
_ACCEPTANCE = "fresh saved result in the same process equals the deterministic cleaned work record"


class WindowsInteractiveCurrentAppStartContextGuardE2ETests(unittest.TestCase):
    def test_switching_to_another_app_after_work_start_refuses_silent_retarget(self) -> None:
        require_input_desktop()
        with tempfile.TemporaryDirectory(
            prefix="zn-e2e13-start-context-",
            ignore_cleanup_errors=True,
        ) as tmp:
            root = Path(tmp)
            app1_root = root / "app1"
            app2_root = root / "app2"
            app1_root.mkdir()
            app2_root.mkdir()
            app1 = WorkRecordApp(app1_root)
            app2 = WorkRecordApp(app2_root)
            resident = None
            try:
                app1.start()
                resident = build_resident_runtime(
                    config={"model": {}},
                    store_path=root / "kernel.db",
                )
                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
                thread = "e2e13-context-" + uuid.uuid4().hex[:8]
                control.ledger.create_thread(thread_id=thread)

                # Capture the user's actual "现在这个软件" while app1 is
                # provably foreground. Work ingress stores only bounded/hash
                # evidence; no HWND becomes reusable authority.
                app1.activate(app1.hwnd)
                _, event = control.start(
                    thread,
                    TASK,
                    payload={"model_policy": "never"},
                    acceptance_criteria=[_ACCEPTANCE],
                )
                persisted = resident.store.get_event(event.event_id)
                self.assertIsNotNone(persisted)
                assert persisted is not None
                start_context = persisted.payload.get("windows_companion_start_context")
                self.assertIsInstance(start_context, dict)
                assert isinstance(start_context, dict)
                self.assertFalse(start_context.get("execution_authority"))
                self.assertTrue(start_context.get("fresh_revalidation_required"))
                self.assertNotIn("window_handle", repr(start_context))

                # The user changes foreground after the instruction. A naive
                # execution-time interpretation of "current app" would now
                # retarget app2. The companion guard must reject that drift
                # before E2E-13 grounds an Edit or dispatches any mutation.
                app2.start()
                result = None
                trace: list[dict] = []
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline and result is None:
                    app2.activate(app2.hwnd)
                    current = resident.live_once()
                    state = resident.store.get_working_state()
                    guard = state.data.get(_STATE_KEY)
                    trace.append(
                        {
                            "stage": state.stage,
                            "guard": guard if isinstance(guard, dict) else None,
                        }
                    )
                    if current is not None and current.event.event_id == event.event_id:
                        result = current
                    if result is None:
                        time.sleep(0.03)

                self.assertIsNotNone(result, json.dumps(trace[-20:], ensure_ascii=False))
                assert result is not None
                self.assertFalse(result.success)
                self.assertIn("start context", str(result.reason or "").lower())
                self.assertIn("foreground_drift", str(result.reason or ""))
                self.assertEqual(app1.saved_count(), 0)
                self.assertEqual(app2.saved_count(), 0)

                actions = [
                    action
                    for action in resident.body.recent_actions(1024)
                    if action.event_id == event.event_id
                ]
                self.assertFalse(
                    any(
                        action.kind in {"automation_value_replace", "pointer_click"}
                        for action in actions
                    ),
                    "start-context drift must fail before any current-app mutation",
                )

                state = resident.store.get_working_state()
                guard = state.data.get(_STATE_KEY)
                self.assertIsInstance(guard, dict)
                assert isinstance(guard, dict)
                self.assertTrue(guard.get("bound"))
                self.assertFalse(guard.get("ready"))
                self.assertEqual(guard.get("disposition"), "foreground_drift")

                print(
                    "ZN_WINDOWS_CURRENT_APP_START_GUARD_EVIDENCE="
                    f"{{\"event_id\":\"{event.event_id}\","
                    f"\"disposition\":\"{guard.get('disposition')}\","
                    f"\"mutation_count\":{sum(action.kind == 'automation_value_replace' for action in actions)},"
                    f"\"save_click_count\":{sum(action.kind == 'pointer_click' for action in actions)},"
                    f"\"app1_save_count\":{app1.saved_count()},"
                    f"\"app2_save_count\":{app2.saved_count()}}}",
                    flush=True,
                )
            finally:
                app2.close()
                app1.close()
                if resident is not None:
                    resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
