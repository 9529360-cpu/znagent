from __future__ import annotations

import unittest
from dataclasses import dataclass
from types import SimpleNamespace

from zn_agent.core.models import AgentEvent
from zn_agent.core.windows_companion_current_app_guard import (
    _STATE_KEY,
    evaluate_windows_companion_start_context,
    install_windows_companion_current_app_guard,
)
from zn_agent.core.windows_companion_work_context import bind_windows_companion_work_context


TASK = "把我现在这个软件里的这份工作记录整理一下：去掉空行和完全重复的行，每行首尾空格也去掉，保留原来的顺序，然后保存。"


def _frame(**overrides):
    values = {
        "frame_version": "windows-companion-frame:v1",
        "fingerprint": "a" * 64,
        "session_fingerprint": "b" * 64,
        "power_fingerprint": "c" * 64,
        "network_fingerprint": "d" * 64,
        "display_fingerprint": "e" * 64,
        "foreground_fingerprint": "f" * 64,
        "foreground_process_id": 4242,
        "foreground_process_name": "fixture.exe",
        "foreground_window_handle": 101,
        "monitor_count": 1,
        "has_non_loopback_network": True,
        "ac_status": "online",
        "input_desktop_openable": True,
        "observed_at": "2026-09-15T12:00:00Z",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _Graph:
    def __init__(self, frames):
        self.frames = list(frames)
        self.last = self.frames[-1]

    def companion_frame(self):
        if self.frames:
            self.last = self.frames.pop(0)
        return self.last


def _payload_from(frame):
    payload = {}
    bound = bind_windows_companion_work_context(
        payload,
        device_capabilities=_Graph([frame]),
    )
    if bound is None:
        raise AssertionError("fixture frame did not produce bounded Work context")
    return payload


@dataclass
class _State:
    data: dict
    stage: str = "orient"
    next_action: str | None = None
    blocked_by: str | None = None


class _Store:
    def __init__(self):
        self.saved = 0

    def save_working_state(self, _state):
        self.saved += 1


class _Resident:
    def __init__(self, graph):
        self.device_capabilities = graph
        self.store = _Store()
        self.original_calls = 0
        self.terminal_calls = []

        def original(event, state, *, readiness, learning_evidence, thought=None):
            self.original_calls += 1
            return "original-result"

        self._advance_event_step = original

    def _checkpoint_terminal_failure(self, event, state, *, reason):
        self.terminal_calls.append((event.event_id, reason))
        state.stage = "terminal_failure"
        return "terminal-result"


class WindowsCompanionCurrentAppGuardTests(unittest.TestCase):
    def test_irrelevant_power_network_display_drift_does_not_retarget_current_app(self) -> None:
        start = _frame()
        fresh = _frame(
            fingerprint="1" * 64,
            power_fingerprint="2" * 64,
            network_fingerprint="3" * 64,
            display_fingerprint="4" * 64,
            has_non_loopback_network=False,
            ac_status="offline",
            monitor_count=2,
            observed_at="2026-09-15T12:01:00Z",
        )
        status = evaluate_windows_companion_start_context(
            _payload_from(start),
            device_capabilities=_Graph([fresh]),
        )

        self.assertTrue(status.bound)
        self.assertTrue(status.ready)
        self.assertEqual(status.disposition, "ready")
        self.assertTrue(status.session_matches)
        self.assertTrue(status.foreground_matches)
        self.assertNotEqual(status.start_fingerprint, status.fresh_fingerprint)

    def test_foreground_drift_fails_closed_even_in_same_session(self) -> None:
        status = evaluate_windows_companion_start_context(
            _payload_from(_frame()),
            device_capabilities=_Graph(
                [
                    _frame(
                        fingerprint="1" * 64,
                        foreground_fingerprint="9" * 64,
                        foreground_process_id=5151,
                        foreground_process_name="other.exe",
                        foreground_window_handle=202,
                    )
                ]
            ),
        )

        self.assertTrue(status.bound)
        self.assertFalse(status.ready)
        self.assertEqual(status.disposition, "foreground_drift")
        self.assertTrue(status.session_matches)
        self.assertFalse(status.foreground_matches)

    def test_session_drift_fails_closed_before_current_app_grounding(self) -> None:
        status = evaluate_windows_companion_start_context(
            _payload_from(_frame()),
            device_capabilities=_Graph(
                [
                    _frame(
                        fingerprint="1" * 64,
                        session_fingerprint="8" * 64,
                    )
                ]
            ),
        )

        self.assertFalse(status.ready)
        self.assertEqual(status.disposition, "session_drift")
        self.assertFalse(status.session_matches)

    def test_invalid_reserved_context_is_not_treated_as_legacy_unbound(self) -> None:
        payload = _payload_from(_frame())
        payload["windows_companion_start_context"]["foreground"]["window_handle"] = 101

        status = evaluate_windows_companion_start_context(
            payload,
            device_capabilities=_Graph([_frame()]),
        )

        self.assertTrue(status.bound)
        self.assertFalse(status.ready)
        self.assertEqual(status.disposition, "bound_context_invalid")

    def test_explicit_null_reserved_context_is_not_treated_as_legacy_unbound(self) -> None:
        status = evaluate_windows_companion_start_context(
            {"windows_companion_start_context": None},
            device_capabilities=_Graph([_frame()]),
        )

        self.assertTrue(status.bound)
        self.assertFalse(status.ready)
        self.assertEqual(status.disposition, "bound_context_invalid")

    def test_missing_context_preserves_legacy_direct_event_behavior(self) -> None:
        status = evaluate_windows_companion_start_context(
            {},
            device_capabilities=_Graph([_frame()]),
        )
        self.assertFalse(status.bound)
        self.assertTrue(status.ready)
        self.assertEqual(status.disposition, "legacy_unbound")

    def test_installed_guard_blocks_before_existing_current_app_behavior_on_drift(self) -> None:
        resident = _Resident(
            _Graph(
                [
                    _frame(
                        fingerprint="1" * 64,
                        foreground_fingerprint="9" * 64,
                        foreground_process_id=5151,
                        foreground_process_name="other.exe",
                    )
                ]
            )
        )
        install_windows_companion_current_app_guard(resident)
        event = AgentEvent(
            event_id="event-current-app-drift",
            kind="desktop_user_event",
            task=TASK,
            payload=_payload_from(_frame()),
        )
        state = _State(data={})

        result = resident._advance_event_step(
            event,
            state,
            readiness=None,
            learning_evidence=None,
        )

        self.assertEqual(result, "terminal-result")
        self.assertEqual(resident.original_calls, 0)
        self.assertEqual(len(resident.terminal_calls), 1)
        self.assertEqual(state.stage, "terminal_failure")
        self.assertEqual(
            state.data[_STATE_KEY]["disposition"],
            "foreground_drift",
        )
        self.assertFalse(state.data[_STATE_KEY]["ready"])
        self.assertGreaterEqual(resident.store.saved, 1)

    def test_installed_guard_delegates_legacy_unbound_event(self) -> None:
        resident = _Resident(_Graph([_frame()]))
        install_windows_companion_current_app_guard(resident)
        event = AgentEvent(
            event_id="event-current-app-legacy",
            kind="desktop_user_event",
            task=TASK,
            payload={},
        )
        state = _State(data={})

        result = resident._advance_event_step(
            event,
            state,
            readiness=None,
            learning_evidence=None,
        )

        self.assertEqual(result, "original-result")
        self.assertEqual(resident.original_calls, 1)
        self.assertEqual(resident.terminal_calls, [])
        self.assertNotIn(_STATE_KEY, state.data)


if __name__ == "__main__":
    unittest.main()
