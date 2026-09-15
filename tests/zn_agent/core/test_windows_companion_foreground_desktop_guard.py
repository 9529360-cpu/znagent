from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.windows_companion_foreground_desktop_guard import (
    _STATE_KEY,
    install_windows_companion_foreground_desktop_guard,
)
from zn_agent.core.windows_companion_work_context import (
    bind_windows_companion_work_context,
)


def _frame(*, pid: int = 4242, foreground: str = "f"):
    return SimpleNamespace(
        frame_version="windows-companion-frame:v1",
        fingerprint=("a" if foreground == "f" else "9") * 64,
        session_fingerprint="b" * 64,
        power_fingerprint="c" * 64,
        network_fingerprint="d" * 64,
        display_fingerprint="e" * 64,
        foreground_fingerprint=foreground * 64,
        foreground_process_id=pid,
        foreground_process_name="fixture.exe",
        foreground_window_handle=101 if pid == 4242 else 202,
        monitor_count=1,
        has_non_loopback_network=True,
        ac_status="online",
        input_desktop_openable=True,
        observed_at="2026-09-15T12:00:00Z",
    )


class _Graph:
    def __init__(self, frame):
        self.frame = frame

    def companion_frame(self):
        return self.frame


class _Store:
    def __init__(self):
        self.saved = 0

    def save_working_state(self, _state):
        self.saved += 1


class _Resident:
    _DESKTOP_TASK_PROGRESS_KEY = "resident_desktop_task_progress"

    def __init__(self, graph):
        self.device_capabilities = graph
        self.store = _Store()
        self.investigation_calls = 0
        self.native_action_calls = 0
        self.failures: list[str] = []

    def _desktop_task_investigation(self, event, state, *, readiness, thought=None):
        self.investigation_calls += 1
        return {
            "event_id": event.event_id,
            "readiness": readiness,
            "thought": thought,
        }

    def _native_action_step(self, event, state, *, readiness, thought=None):
        self.native_action_calls += 1
        return {
            "event_id": event.event_id,
            "readiness": readiness,
            "thought": thought,
            "native": True,
        }

    def _checkpoint_terminal_failure(self, event, state, *, reason):
        self.failures.append(reason)
        state.stage = "terminal_failure"
        state.blocked_by = reason
        return SimpleNamespace(event=event, success=False, reason=reason)


class _State:
    def __init__(self):
        self.data = {}
        self.stage = "native_investigation"
        self.blocked_by = None


def _bound_payload(frame) -> dict:
    payload: dict = {}
    bound = bind_windows_companion_work_context(
        payload,
        device_capabilities=_Graph(frame),
    )
    if bound is None:
        raise AssertionError("fixture did not bind companion start context")
    return payload


def _desktop_event(payload: dict, *, event_id: str = "evt-desktop"):
    return SimpleNamespace(
        event_id=event_id,
        kind="desktop_user_event",
        task="fill the current app",
        payload={
            **payload,
            "workspace_path": "C:/fixture-workspace",
            "desktop_task_goal": {
                "kind": "workspace_to_foreground_desktop",
                "source_name_hint": "order",
                "input_name": "Order ID",
                "button_name": "Find",
                "expected_title": None,
                "source_modified_yesterday": False,
            },
        },
    )


class WindowsCompanionForegroundDesktopGuardTests(unittest.TestCase):
    def test_foreground_drift_blocks_before_desktop_investigation(self):
        payload = _bound_payload(_frame())
        graph = _Graph(_frame(pid=5252, foreground="8"))
        resident = _Resident(graph)
        install_windows_companion_foreground_desktop_guard(resident)
        state = _State()
        event = _desktop_event(payload, event_id="evt-drift")

        result = resident._desktop_task_investigation(
            event,
            state,
            readiness={"ready": True},
        )

        self.assertFalse(result.success)
        self.assertEqual(resident.investigation_calls, 0)
        self.assertEqual(state.stage, "terminal_failure")
        self.assertEqual(state.data[_STATE_KEY]["disposition"], "foreground_drift")
        self.assertFalse(state.data[_STATE_KEY]["pre_submit_context_admitted"])
        self.assertEqual(state.data[_STATE_KEY]["last_guard_phase"], "desktop_investigation")
        self.assertFalse(
            state.data[_STATE_KEY]["historical_context_is_execution_authority"]
        )

    def test_matching_context_is_rechecked_on_later_pre_submit_investigation(self):
        payload = _bound_payload(_frame())
        graph = _Graph(_frame())
        resident = _Resident(graph)
        install_windows_companion_foreground_desktop_guard(resident)
        state = _State()
        event = _desktop_event(payload, event_id="evt-reinvestigate")

        first = resident._desktop_task_investigation(
            event,
            state,
            readiness="first",
        )
        self.assertEqual(first["readiness"], "first")
        self.assertEqual(resident.investigation_calls, 1)
        self.assertTrue(state.data[_STATE_KEY]["pre_submit_context_admitted"])

        graph.frame = _frame(pid=6262, foreground="7")
        second = resident._desktop_task_investigation(
            event,
            state,
            readiness="later",
        )

        self.assertFalse(second.success)
        self.assertEqual(resident.investigation_calls, 1)
        self.assertEqual(state.data[_STATE_KEY]["disposition"], "foreground_drift")
        self.assertFalse(state.data[_STATE_KEY]["pre_submit_context_admitted"])

    def test_drift_after_grounding_blocks_before_native_action_entry(self):
        payload = _bound_payload(_frame())
        graph = _Graph(_frame())
        resident = _Resident(graph)
        install_windows_companion_foreground_desktop_guard(resident)
        state = _State()
        event = _desktop_event(payload, event_id="evt-native-action")

        resident._desktop_task_investigation(
            event,
            state,
            readiness="grounded",
        )
        self.assertEqual(resident.investigation_calls, 1)

        graph.frame = _frame(pid=7373, foreground="6")
        result = resident._native_action_step(
            event,
            state,
            readiness="act",
        )

        self.assertFalse(result.success)
        self.assertEqual(resident.native_action_calls, 0)
        self.assertEqual(state.data[_STATE_KEY]["disposition"], "foreground_drift")
        self.assertEqual(state.data[_STATE_KEY]["last_guard_phase"], "native_action_entry")

    def test_post_submit_completion_is_not_locked_to_historical_foreground(self):
        payload = _bound_payload(_frame())
        graph = _Graph(_frame(pid=8484, foreground="5"))
        resident = _Resident(graph)
        install_windows_companion_foreground_desktop_guard(resident)
        state = _State()
        state.data[resident._DESKTOP_TASK_PROGRESS_KEY] = {"submit_dispatched": True}
        event = _desktop_event(payload, event_id="evt-post-submit")

        result = resident._desktop_task_investigation(
            event,
            state,
            readiness="completion",
        )

        self.assertEqual(result["readiness"], "completion")
        self.assertEqual(resident.investigation_calls, 1)
        self.assertTrue(state.data[_STATE_KEY]["post_submit_guard_skipped"])
        self.assertFalse(
            state.data[_STATE_KEY]["historical_context_is_execution_authority"]
        )

    def test_explicit_null_reserved_context_fails_closed_before_grounding(self):
        resident = _Resident(_Graph(_frame()))
        install_windows_companion_foreground_desktop_guard(resident)
        state = _State()
        event = _desktop_event(
            {"windows_companion_start_context": None},
            event_id="evt-null",
        )

        result = resident._desktop_task_investigation(
            event,
            state,
            readiness=None,
        )

        self.assertFalse(result.success)
        self.assertEqual(resident.investigation_calls, 0)
        self.assertEqual(state.data[_STATE_KEY]["disposition"], "bound_context_invalid")

    def test_legacy_unbound_event_preserves_existing_desktop_goal_behavior(self):
        resident = _Resident(_Graph(_frame()))
        install_windows_companion_foreground_desktop_guard(resident)
        state = _State()
        event = _desktop_event({}, event_id="evt-legacy")

        investigation = resident._desktop_task_investigation(
            event,
            state,
            readiness="legacy",
        )
        action = resident._native_action_step(
            event,
            state,
            readiness="legacy-action",
        )

        self.assertEqual(investigation["readiness"], "legacy")
        self.assertEqual(action["readiness"], "legacy-action")
        self.assertEqual(resident.investigation_calls, 1)
        self.assertEqual(resident.native_action_calls, 1)
        self.assertTrue(state.data[_STATE_KEY]["legacy_unbound"])
        self.assertTrue(state.data[_STATE_KEY]["pre_submit_context_admitted"])

    def test_non_desktop_native_action_is_not_over_gated(self):
        payload = _bound_payload(_frame())
        resident = _Resident(_Graph(_frame(pid=9595, foreground="4")))
        install_windows_companion_foreground_desktop_guard(resident)
        state = _State()
        event = SimpleNamespace(
            event_id="evt-other",
            kind="desktop_user_event",
            task="other work",
            payload=payload,
        )

        result = resident._native_action_step(
            event,
            state,
            readiness="other",
        )

        self.assertEqual(result["readiness"], "other")
        self.assertEqual(resident.native_action_calls, 1)
        self.assertNotIn(_STATE_KEY, state.data)


if __name__ == "__main__":
    unittest.main()
