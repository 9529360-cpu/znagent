from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.machine_capability import ApplicationInventoryCandidate, DeviceCapabilityGraph
from zn_agent.core.machine_capability_body import MachineCapabilityBody
from zn_agent.core.store import KernelStore


class _RecordingBody(MachineCapabilityBody):
    def __init__(self, *args, **kwargs):
        self.dispatched: list[str] = []
        super().__init__(*args, **kwargs)

    def _dispatch_resolved_application(self, application):
        self.dispatched.append(application.app_id)
        return 7777


class MachineCapabilityBodyTests(unittest.TestCase):
    def _fixture(self, tmp: str, *, processes=None, windows=None):
        executable = Path(tmp) / "notepad.exe"
        executable.write_bytes(b"")
        process_rows = processes if processes is not None else []
        window_rows = windows if windows is not None else []
        graph = DeviceCapabilityGraph(
            inventory_provider=lambda: [
                ApplicationInventoryCandidate(
                    source="app_paths", source_id="notepad", display_name="Notepad",
                    executable_path=str(executable), identity_paths=(str(executable),),
                    launch_kind="executable", launch_target=str(executable),
                )
            ],
            process_provider=lambda: list(process_rows),
            window_provider=lambda: list(window_rows),
            cache_path=Path(tmp) / "apps.json", inventory_ttl_seconds=0,
        )
        app = graph.installed_applications(force_refresh=True)[0]
        store = KernelStore(Path(tmp) / "kernel.db")
        body = _RecordingBody(store=store, device_capabilities=graph)
        return store, body, app, executable

    def test_raw_launch_material_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, body, app, executable = self._fixture(tmp)
            try:
                result = body.act(
                    "launch_application", event_id="evt-raw",
                    application_id=app.app_id, executable_path=str(executable),
                )
                self.assertFalse(result.success)
                self.assertFalse(result.data["dispatch_sent"])
                self.assertEqual(body.dispatched, [])
            finally:
                store.close()

    def test_visible_existing_instance_does_not_duplicate_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            store, body, app, executable = self._fixture(tmp, processes=processes, windows=windows)
            processes.append({"pid": 55, "name": "notepad.exe", "exe": str(executable)})
            windows.append({
                "hwnd": 66, "pid": 55, "title": "Untitled - Notepad",
                "class_name": "Notepad", "visible": True, "foreground": False,
            })
            try:
                result = body.act("launch_application", event_id="evt-running", application_id=app.app_id)
                self.assertTrue(result.success)
                self.assertEqual(result.data["disposition"], "already_running")
                self.assertFalse(result.data["dispatch_sent"])
                self.assertEqual(body.dispatched, [])
            finally:
                store.close()

    def test_running_without_visible_window_fails_conservatively(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            store, body, app, executable = self._fixture(tmp, processes=processes)
            processes.append({"pid": 55, "name": "notepad.exe", "exe": str(executable)})
            try:
                result = body.act("launch_application", event_id="evt-hidden", application_id=app.app_id)
                self.assertFalse(result.success)
                self.assertEqual(result.data["disposition"], "already_running_without_visible_window")
                self.assertEqual(body.dispatched, [])
            finally:
                store.close()

    def test_launch_uses_resolved_identity_and_existing_replay_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, body, app, _ = self._fixture(tmp)
            try:
                first = body.act("launch_application", event_id="evt-launch", application_id=app.app_id)
                self.assertTrue(first.success)
                self.assertTrue(first.data["dispatch_sent"])
                self.assertEqual(first.data["dispatched_process_id"], 7777)
                self.assertEqual(body.dispatched, [app.app_id])

                second = body.act("launch_application", event_id="evt-launch", application_id=app.app_id)
                self.assertFalse(second.success)
                self.assertTrue(second.data["replay_blocked"])
                self.assertEqual(body.dispatched, [app.app_id])
            finally:
                store.close()

    def test_unknown_identity_never_fabricates_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, body, app, _ = self._fixture(tmp)
            try:
                result = body.act(
                    "launch_application", event_id="evt-missing",
                    application_id=app.app_id + "-missing",
                )
                self.assertFalse(result.success)
                self.assertEqual(result.data["disposition"], "not_installed")
                self.assertEqual(body.dispatched, [])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
