from __future__ import annotations

import json

import test_windows_interactive_browser_file_desktop_work as e2e24


class WindowsInteractiveBrowserFileDesktopDiagnosticE2ETests(
    e2e24.WindowsInteractiveBrowserFileDesktopWorkE2ETests
):
    """Temporary interaction-level trace for the surviving E2E-24 desktop failure."""

    @staticmethod
    def _run_to_terminal(
        resident,
        rpc,
        *,
        thread_id: str,
        event_id: str,
        timeout: float = 55.0,
        hook=None,
    ):
        final, trace = e2e24.WindowsInteractiveBrowserFileDesktopWorkE2ETests._run_to_terminal(
            resident,
            rpc,
            thread_id=thread_id,
            event_id=event_id,
            timeout=timeout,
            hook=hook,
        )
        state = resident.store.get_working_state()
        outcome = resident.store.get_event_outcome(event_id)
        desktop_key = getattr(
            resident,
            "_DESKTOP_TASK_OBSERVATION_KEY",
            "resident_desktop_task_observation",
        )
        desktop_progress_key = getattr(
            resident,
            "_DESKTOP_TASK_PROGRESS_KEY",
            "resident_desktop_task_progress",
        )
        actions = [
            {
                "kind": action.kind,
                "success": bool(action.success),
                "error": action.error,
            }
            for action in reversed(resident.body.recent_actions(1024))
            if action.event_id == event_id
        ]
        diagnostic = {
            "terminal": final is not None,
            "finalized": bool(final and final.get("progress", {}).get("finalized")),
            "outcome": (
                {
                    "success": bool(outcome.success),
                    "reason": outcome.reason,
                    "response": outcome.response,
                }
                if outcome is not None
                else None
            ),
            "stage": state.stage,
            "next_action": state.next_action,
            "local_failure": state.data.get("local_failure"),
            "e2e24": state.data.get("resident_e2e24_browser_file_desktop"),
            "desktop_observation": state.data.get(desktop_key),
            "desktop_progress": state.data.get(desktop_progress_key),
            "pointer_execution": state.data.get("native_pointer_click_execution"),
            "keyboard_execution": state.data.get("native_keyboard_text_execution"),
            "action_failures": list(state.data.get("native_action_failure_records") or [])[-8:],
            "actions": actions,
            "trace_tail": trace[-40:],
        }
        print(
            "ZN_E2E24_DESKTOP_DIAGNOSTIC="
            + json.dumps(diagnostic, ensure_ascii=False, default=str)
        )
        return final, trace
