from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from test_windows_interactive_desktop_modal_recovery import (
    TASK,
    _MODAL_STATE_KEY,
    _ModalRecoveryOrderApp,
)
from test_windows_interactive_desktop_semantic_grounding import (
    SOURCE_VALUE,
    WindowsInteractiveDesktopSemanticGroundingE2ETests,
    _SemanticProposal,
)
from test_windows_interactive_text_entry import WindowsInteractiveTextEntryE2ETests


class WindowsInteractiveModalRecoveryDiagnostic(unittest.TestCase):
    def test_report_post_dismiss_recovery_fields(self) -> None:
        WindowsInteractiveTextEntryE2ETests._require_input_desktop()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            source = workspace / "订单资料.txt"
            source.write_text(SOURCE_VALUE, encoding="utf-8")
            WindowsInteractiveDesktopSemanticGroundingE2ETests._stamp_yesterday(source)
            app = _ModalRecoveryOrderApp(root)
            app.start()
            resident = build_resident_runtime(config={"model": {}}, store_path=root / "kernel.db")
            try:
                WindowsInteractiveDesktopSemanticGroundingE2ETests._enable_cognition(
                    resident, _SemanticProposal()
                )
                ledger = RecoveryBoundedWorkLedger(resident)
                thread = "desktop-modal-recovery-diagnostic"
                ledger.create_thread(thread_id=thread)
                ledger.attach_workspace(thread, workspace)
                app.activate()
                _, event = ledger.start(thread, TASK, payload={"model_policy": "on_demand"})
                observation_key = getattr(
                    resident,
                    "_DESKTOP_TASK_OBSERVATION_KEY",
                    "resident_desktop_task_observation",
                )
                triggered = False
                result = None
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline and result is None:
                    state = resident.store.get_working_state()
                    observation = state.data.get(observation_key)
                    observation = observation if isinstance(observation, dict) else {}
                    target = observation.get("target")
                    target = target if isinstance(target, dict) else {}
                    actions = [
                        action
                        for action in resident.body.recent_actions(256)
                        if action.event_id == event.event_id
                    ]
                    if (
                        not triggered
                        and str(observation.get("phase") or "") == "focus"
                        and target.get("runtime_id")
                        and not any(a.kind in {"pointer_click", "keyboard_text"} for a in actions)
                    ):
                        app.trigger_modal()
                        modal_deadline = time.monotonic() + 8
                        while time.monotonic() < modal_deadline and not app.modal_hwnd():
                            time.sleep(0.03)
                        self.assertTrue(app.modal_hwnd())
                        triggered = True
                        continue
                    if not app.modal_hwnd():
                        try:
                            app.activate()
                        except RuntimeError:
                            pass
                    result = resident.live_once()
                    if result is not None and result.event.event_id != event.event_id:
                        result = None
                    time.sleep(0.025)

                final_state = resident.store.get_working_state()
                recovery = final_state.data.get(_MODAL_STATE_KEY)
                recovery = recovery if isinstance(recovery, dict) else {}
                diagnostic = {
                    "result_success": None if result is None else bool(result.success),
                    "result_reason": None if result is None else str(result.reason),
                    "phase": recovery.get("phase"),
                    "dispatch_count": recovery.get("dispatch_count"),
                    "recovery_observations": recovery.get("recovery_observations"),
                    "last_recovery_observation": recovery.get("last_recovery_observation"),
                    "safe_count": app.safe_count(),
                    "risky_count": app.risky_count(),
                    "modal_hwnd_now": app.modal_hwnd(),
                    "parent_hwnd": app.hwnd,
                }
                print("ZN_E2E15_RECOVERY_DIAGNOSTIC=" + json.dumps(diagnostic, ensure_ascii=False, sort_keys=True))
                self.assertTrue(triggered)
                self.assertEqual(app.safe_count(), 1)
                self.assertEqual(app.risky_count(), 0)
                self.assertEqual(recovery.get("dispatch_count"), 1)
            finally:
                resident.store.close()
                app.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
