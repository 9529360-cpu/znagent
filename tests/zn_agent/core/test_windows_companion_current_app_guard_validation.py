from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.windows_companion_current_app_guard import (
    evaluate_windows_companion_start_context,
)
from zn_agent.core.windows_companion_work_context import (
    bind_windows_companion_work_context,
)


class _Graph:
    def companion_frame(self):
        return SimpleNamespace(
            frame_version="windows-companion-frame:v1",
            fingerprint="a" * 64,
            session_fingerprint="b" * 64,
            power_fingerprint="c" * 64,
            network_fingerprint="d" * 64,
            display_fingerprint="e" * 64,
            foreground_fingerprint="f" * 64,
            foreground_process_id=4242,
            foreground_process_name="fixture.exe",
            foreground_window_handle=101,
            monitor_count=1,
            has_non_loopback_network=True,
            ac_status="online",
            input_desktop_openable=True,
            observed_at="2026-09-15T12:00:00Z",
        )


def _payload() -> dict:
    payload: dict = {}
    bounded = bind_windows_companion_work_context(
        payload,
        device_capabilities=_Graph(),
    )
    if bounded is None:
        raise AssertionError("fixture did not produce bounded companion context")
    return payload


def _status(payload: dict):
    return evaluate_windows_companion_start_context(
        payload,
        device_capabilities=_Graph(),
    )


class WindowsCompanionCurrentAppGuardValidationTests(unittest.TestCase):
    def assert_invalid(self, payload: dict) -> None:
        status = _status(payload)
        self.assertTrue(status.bound)
        self.assertFalse(status.ready)
        self.assertEqual(status.disposition, "bound_context_invalid")

    def test_overlong_process_name_is_rejected_instead_of_truncated(self) -> None:
        payload = _payload()
        payload["windows_companion_start_context"]["foreground"]["process_name"] = (
            "fixture.exe" + "x" * 260
        )
        self.assert_invalid(payload)

    def test_noncanonical_process_name_whitespace_is_rejected(self) -> None:
        payload = _payload()
        payload["windows_companion_start_context"]["foreground"]["process_name"] = (
            " fixture.exe "
        )
        self.assert_invalid(payload)

    def test_string_process_id_is_rejected_instead_of_coerced(self) -> None:
        payload = _payload()
        payload["windows_companion_start_context"]["foreground"]["process_id"] = "4242"
        self.assert_invalid(payload)

    def test_uppercase_fingerprint_is_rejected_instead_of_normalized(self) -> None:
        payload = _payload()
        payload["windows_companion_start_context"]["components"]["session"] = "B" * 64
        self.assert_invalid(payload)


if __name__ == "__main__":
    unittest.main()
