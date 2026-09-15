from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.device_capability_graph import DeviceCapabilityGraph
from zn_agent.core.machine_capability import ApplicationInventoryCandidate
from zn_agent.core.machine_capability_body import MachineCapabilityBody
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.windows_companion_context import NativeWindowsCompanionContextSense


class WindowsCompanionApplicationActivationTests(unittest.TestCase):
    @staticmethod
    def _graph(tmp: str):
        executable = Path(tmp) / "fixture.exe"
        executable.write_bytes(b"")
        processes = [
            {"pid": 55, "name": "fixture.exe", "exe": str(executable)},
        ]
        windows = [
            {
                "hwnd": 66,
                "pid": 55,
                "title": "Fixture",
                "class_name": "FixtureWindow",
                "visible": True,
                "foreground": False,
            }
        ]
        graph = DeviceCapabilityGraph(
            inventory_provider=lambda: [
                ApplicationInventoryCandidate(
                    source="app_paths",
                    source_id="fixture",
                    display_name="Fixture",
                    executable_path=str(executable),
                    identity_paths=(str(executable),),
                    launch_kind="executable",
                    launch_target=str(executable),
                )
            ],
            process_provider=lambda: list(processes),
            window_provider=lambda: list(windows),
            cache_path=None,
            inventory_ttl_seconds=0,
            companion_context_sense=NativeWindowsCompanionContextSense(
                session_probe=lambda: {
                    "platform_supported": True,
                    "process_session_id": 3,
                    "active_console_session_id": 3,
                    "attached_to_active_console": True,
                    "remote_session": False,
                    "input_desktop_openable": True,
                    "idle_seconds": 0.0,
                },
                power_probe=lambda: {
                    "platform_supported": True,
                    "ac_status": "online",
                },
                network_probe=lambda: {
                    "platform_supported": True,
                    "interface_count": 1,
                    "up_interface_count": 1,
                    "non_loopback_up_interface_count": 1,
                    "has_non_loopback_address": True,
                },
            ),
        )
        return graph, windows

    def test_ready_companion_session_preserves_exact_existing_window_activation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph, windows = self._graph(tmp)
            app = graph.installed_applications(force_refresh=True)[0]
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            native_calls: list[tuple[int, int]] = []
            try:
                resident.device_capabilities = graph
                resident.body.device_capabilities = graph
                resident.body._current_session_connection_state = lambda _session_id: "active"

                def activate(hwnd: int, pid: int):
                    native_calls.append((hwnd, pid))
                    windows[0]["foreground"] = True
                    return {
                        "success": True,
                        "dispatch_sent": True,
                        "was_minimized": False,
                        "restore_requested": False,
                        "restore_returned_true": False,
                        "set_foreground_returned_true": True,
                        "disposition": "activation_requested",
                    }

                with patch.object(
                    MachineCapabilityBody,
                    "_native_activate_exact_application_window",
                    new=staticmethod(activate),
                ):
                    result = resident.body.act(
                        "activate_application_window",
                        application_id=app.app_id,
                        event_id="evt-companion-activation",
                    )

                self.assertTrue(result.success, result)
                self.assertEqual(native_calls, [(66, 55)])
                self.assertTrue(result.data.get("dispatch_sent"))
                self.assertEqual(result.data.get("window_handle"), 66)
                self.assertEqual(result.data.get("process_id"), 55)
                self.assertEqual(result.data.get("application_id"), app.app_id)
            finally:
                resident.store.close()

    def test_session_disconnect_after_admission_blocks_exact_native_activation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph, _windows = self._graph(tmp)
            app = graph.installed_applications(force_refresh=True)[0]
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            native_calls: list[tuple[int, int]] = []
            states = iter(("active", "disconnected"))
            try:
                resident.device_capabilities = graph
                resident.body.device_capabilities = graph
                resident.body._current_session_connection_state = lambda _session_id: next(states)

                def activate(hwnd: int, pid: int):
                    native_calls.append((hwnd, pid))
                    return {
                        "success": True,
                        "dispatch_sent": True,
                        "disposition": "activation_requested",
                    }

                with patch.object(
                    MachineCapabilityBody,
                    "_native_activate_exact_application_window",
                    new=staticmethod(activate),
                ):
                    result = resident.body.act(
                        "activate_application_window",
                        application_id=app.app_id,
                        event_id="evt-companion-activation-drift",
                    )

                self.assertFalse(result.success)
                self.assertEqual(result.data.get("disposition"), "session_not_actively_connected")
                self.assertFalse(result.data.get("dispatch_sent"))
                self.assertEqual(native_calls, [])
                self.assertIn("disconnected", str(result.error or ""))
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
