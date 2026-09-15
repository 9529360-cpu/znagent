from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.body import BodyActionResult
from zn_agent.core.device_capability_graph import DeviceCapabilityGraph
from zn_agent.core.models import utc_now
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.windows_companion_body import WindowsCompanionAwareBody
from zn_agent.core.windows_companion_context import NativeWindowsCompanionContextSense


class _RecordingCompanionBody(WindowsCompanionAwareBody):
    def __init__(self, *, device_capabilities, connection_state: str | None = "active"):
        super().__init__(device_capabilities=device_capabilities)
        self.dispatched: list[str] = []
        self.connection_state = connection_state

    def _current_session_connection_state(self, session_id: int) -> str | None:
        del session_id
        return self.connection_state

    def _dispatch(self, action, started):
        self.dispatched.append(action.kind)
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            data={"fake_dispatch": True},
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    @staticmethod
    def _native_activate_exact_application_window(hwnd: int, expected_pid: int):
        raise AssertionError(
            f"native activation must not be reached by blocked preflight: {hwnd}/{expected_pid}"
        )


def _graph(
    *,
    process_session_id: int | None = 3,
    input_desktop_openable: bool | None = True,
    platform_supported: bool = True,
) -> DeviceCapabilityGraph:
    sense = NativeWindowsCompanionContextSense(
        session_probe=lambda: {
            "platform_supported": platform_supported,
            "process_session_id": process_session_id,
            "active_console_session_id": 3,
            "attached_to_active_console": process_session_id == 3 if process_session_id is not None else None,
            "remote_session": False,
            "input_desktop_openable": input_desktop_openable,
            "idle_seconds": 1.0,
        },
        power_probe=lambda: {
            "platform_supported": platform_supported,
            "ac_status": "online",
        },
        network_probe=lambda: {
            "platform_supported": platform_supported,
            "interface_count": 1,
            "up_interface_count": 1,
            "non_loopback_up_interface_count": 1,
            "has_non_loopback_address": True,
        },
    )
    return DeviceCapabilityGraph(
        inventory_provider=lambda: [],
        process_provider=lambda: [],
        window_provider=lambda: [],
        cache_path=None,
        inventory_ttl_seconds=0,
        companion_context_sense=sense,
    )


class WindowsCompanionBodyTests(unittest.TestCase):
    def test_session_zero_blocks_pointer_before_dispatch(self) -> None:
        body = _RecordingCompanionBody(device_capabilities=_graph(process_session_id=0))
        result = body.act("pointer_click", x_fraction=0.5, y_fraction=0.5)

        self.assertFalse(result.success)
        self.assertEqual(result.data.get("disposition"), "session_zero_noninteractive")
        self.assertFalse(result.data.get("dispatch_sent"))
        self.assertEqual(body.dispatched, [])

    def test_unavailable_input_desktop_blocks_keyboard_before_plaintext_dispatch(self) -> None:
        body = _RecordingCompanionBody(
            device_capabilities=_graph(input_desktop_openable=False)
        )
        result = body.act("keyboard_text", text="sensitive transient text")

        self.assertFalse(result.success)
        self.assertEqual(result.data.get("disposition"), "input_desktop_unavailable")
        self.assertFalse(result.data.get("dispatch_sent"))
        self.assertEqual(body.dispatched, [])
        self.assertNotIn("sensitive transient text", repr(result))

    def test_disconnected_session_blocks_input_even_when_desktop_handle_is_openable(self) -> None:
        body = _RecordingCompanionBody(
            device_capabilities=_graph(input_desktop_openable=True),
            connection_state="disconnected",
        )
        result = body.act("pointer_move", x_fraction=0.2, y_fraction=0.3)

        self.assertFalse(result.success)
        self.assertEqual(result.data.get("disposition"), "session_not_actively_connected")
        self.assertEqual(result.data.get("session_connection_state"), "disconnected")
        self.assertEqual(body.dispatched, [])

    def test_unknown_wts_state_fails_closed_before_input(self) -> None:
        body = _RecordingCompanionBody(
            device_capabilities=_graph(),
            connection_state=None,
        )
        result = body.act("pointer_click", x_fraction=0.1, y_fraction=0.1)

        self.assertFalse(result.success)
        self.assertEqual(result.data.get("disposition"), "session_connection_state_unknown")
        self.assertEqual(body.dispatched, [])

    def test_active_session_allows_existing_body_dispatch(self) -> None:
        body = _RecordingCompanionBody(
            device_capabilities=_graph(),
            connection_state="active",
        )
        result = body.act("keyboard_text", text="hello")

        self.assertTrue(result.success)
        self.assertEqual(body.dispatched, ["keyboard_text"])

    def test_read_only_and_noninteractive_actions_are_not_overgated(self) -> None:
        body = _RecordingCompanionBody(
            device_capabilities=_graph(process_session_id=0),
            connection_state="disconnected",
        )
        result = body.act("sense")

        self.assertTrue(result.success)
        self.assertEqual(body.dispatched, ["sense"])

    def test_explicit_windows_context_action_is_read_only_and_bounded(self) -> None:
        body = WindowsCompanionAwareBody(device_capabilities=_graph())
        result = body.act("windows_companion_context")

        self.assertTrue(result.success)
        self.assertTrue(result.data.get("read_only"))
        self.assertFalse(result.data.get("dispatch_sent"))
        self.assertEqual(result.data["session"]["process_session_id"], 3)
        self.assertEqual(result.data["power"]["ac_status"], "online")
        self.assertTrue(result.data["network"]["has_non_loopback_address"])
        self.assertNotIn("interfaces", result.data["network"])
        self.assertNotIn("addresses", result.data["network"])

        refused = body.act("windows_companion_context", unexpected=True)
        self.assertFalse(refused.success)
        self.assertEqual(refused.data.get("disposition"), "unexpected_arguments")
        self.assertFalse(refused.data.get("dispatch_sent"))

    def test_admitted_window_activation_is_blocked_before_native_foreground_call(self) -> None:
        body = _RecordingCompanionBody(
            device_capabilities=_graph(input_desktop_openable=False),
        )
        result = body.activate_admitted_application_window(
            event_id="event-1",
            application_id="app-1",
            expected_window_handle=100,
            expected_process_id=200,
            observed_at="2026-09-15T00:00:00Z",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.data.get("disposition"), "input_desktop_unavailable")
        self.assertFalse(result.data.get("dispatch_sent"))
        self.assertEqual(result.data.get("application_id"), "app-1")
        self.assertEqual(body.dispatched, [])

    def test_final_product_body_reuses_resident_device_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertIsInstance(resident.body, WindowsCompanionAwareBody)
                self.assertIs(resident.body.device_capabilities, resident.device_capabilities)
                context = resident.device_capabilities.companion_context()
                self.assertIsNotNone(context.observed_at)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
