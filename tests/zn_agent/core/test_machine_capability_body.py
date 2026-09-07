from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.machine_capability import ApplicationInventoryCandidate, DeviceCapabilityGraph
from zn_agent.core.machine_capability_body import (
    MachineCapabilityBody,
    _activate_exact_application_window,
)
from zn_agent.core.store import KernelStore


class _RecordingBody(MachineCapabilityBody):
    def __init__(self, *args, **kwargs):
        self.dispatched: list[str] = []
        self.activations: list[tuple[int, int]] = []
        self.activation_result = {
            "success": True,
            "dispatch_sent": True,
            "was_minimized": False,
            "restore_requested": False,
            "restore_returned_true": False,
            "set_foreground_returned_true": True,
            "disposition": "activation_requested",
        }
        super().__init__(*args, **kwargs)

    def _dispatch_resolved_application(self, application):
        self.dispatched.append(application.app_id)
        return 7777

    def _native_activate_exact_application_window(self, hwnd, expected_pid):
        self.activations.append((int(hwnd), int(expected_pid)))
        return dict(self.activation_result)


class _SequencedProvider:
    def __init__(self, *values):
        self.values = list(values)
        self.calls = 0

    def __call__(self):
        index = min(self.calls, len(self.values) - 1)
        self.calls += 1
        return list(self.values[index])


class _FakeActivationApi:
    SW_RESTORE = 9

    def __init__(self, *, pid=55, minimized=False, foreground_result=True, visible=True, valid=True):
        self.pid = pid
        self.minimized = minimized
        self.foreground_result = foreground_result
        self.visible = visible
        self.valid = valid
        self.calls: list[tuple] = []

    def is_window(self, hwnd):
        self.calls.append(("IsWindow", hwnd))
        return self.valid

    def window_process_id(self, hwnd):
        self.calls.append(("GetWindowThreadProcessId", hwnd))
        return self.pid

    def is_window_visible(self, hwnd):
        self.calls.append(("IsWindowVisible", hwnd))
        return self.visible

    def is_iconic(self, hwnd):
        self.calls.append(("IsIconic", hwnd))
        return self.minimized

    def show_window_async(self, hwnd, command):
        self.calls.append(("ShowWindowAsync", hwnd, command))
        return True

    def set_foreground_window(self, hwnd):
        self.calls.append(("SetForegroundWindow", hwnd))
        return self.foreground_result


class MachineCapabilityBodyTests(unittest.TestCase):
    def _fixture(self, tmp: str, *, processes=None, windows=None):
        executable = Path(tmp) / "notepad.exe"
        executable.write_bytes(b"")
        process_rows = processes if processes is not None else []
        window_rows = windows if windows is not None else []
        process_provider = process_rows if callable(process_rows) else lambda: list(process_rows)
        window_provider = window_rows if callable(window_rows) else lambda: list(window_rows)
        graph = DeviceCapabilityGraph(
            inventory_provider=lambda: [
                ApplicationInventoryCandidate(
                    source="app_paths", source_id="notepad", display_name="Notepad",
                    executable_path=str(executable), identity_paths=(str(executable),),
                    launch_kind="executable", launch_target=str(executable),
                )
            ],
            process_provider=process_provider,
            window_provider=window_provider,
            cache_path=Path(tmp) / "apps.json", inventory_ttl_seconds=0,
        )
        app = graph.installed_applications(force_refresh=True)[0]
        store = KernelStore(Path(tmp) / "kernel.db")
        body = _RecordingBody(store=store, device_capabilities=graph)
        return store, body, app, executable

    @staticmethod
    def _process(executable: Path, pid: int = 55):
        return {"pid": pid, "name": "notepad.exe", "exe": str(executable)}

    @staticmethod
    def _window(*, hwnd=66, pid=55, visible=True, foreground=False):
        return {
            "hwnd": hwnd, "pid": pid, "title": "Untitled - Notepad",
            "class_name": "Notepad", "visible": visible, "foreground": foreground,
        }

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
            processes.append(self._process(executable))
            windows.append(self._window())
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
            processes.append(self._process(executable))
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

    def test_activation_public_authority_rejects_raw_native_targets_and_forged_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            store, body, app, executable = self._fixture(tmp, processes=processes, windows=windows)
            processes.append(self._process(executable))
            windows.append(self._window())
            try:
                forbidden = (
                    "hwnd", "window_handle", "pid", "process_id", "title", "class_name",
                    "executable", "path", "coordinates", "x", "y", "force",
                    body._ACTIVATE_DISPATCH_MARKER,
                )
                for index, key in enumerate(forbidden):
                    with self.subTest(key=key):
                        result = body.act(
                            "activate_application_window",
                            event_id=f"evt-raw-{index}",
                            application_id=app.app_id,
                            **{key: 66 if key != "force" else True},
                        )
                        self.assertFalse(result.success)
                        self.assertFalse(result.data["dispatch_sent"])
                        self.assertIn(key, result.data["rejected_arguments"])
                self.assertEqual(body.activations, [])
            finally:
                store.close()

    def test_activation_already_foreground_completes_without_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            store, body, app, executable = self._fixture(tmp, processes=processes, windows=windows)
            processes.append(self._process(executable))
            windows.append(self._window(foreground=True))
            try:
                result = body.act("activate_application_window", event_id="evt-fg", application_id=app.app_id)
                self.assertTrue(result.success)
                self.assertEqual(result.data["disposition"], "already_foreground")
                self.assertFalse(result.data["dispatch_sent"])
                self.assertEqual(result.data["window_handle"], 66)
                self.assertEqual(result.data["process_id"], 55)
                self.assertEqual(body.activations, [])
            finally:
                store.close()

    def test_unique_visible_background_window_is_identity_bound_and_guarded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            store, body, app, executable = self._fixture(tmp, processes=processes, windows=windows)
            processes.append(self._process(executable))
            windows.append(self._window())
            try:
                first = body.act("activate_application_window", event_id="evt-activate", application_id=app.app_id)
                self.assertTrue(first.success)
                self.assertTrue(first.data["dispatch_sent"])
                self.assertEqual(first.data["window_handle"], 66)
                self.assertEqual(first.data["process_id"], 55)
                self.assertEqual(body.activations, [(66, 55)])

                second = body.act("activate_application_window", event_id="evt-activate", application_id=app.app_id)
                self.assertFalse(second.success)
                self.assertTrue(second.data["replay_blocked"])
                self.assertEqual(body.activations, [(66, 55)])
            finally:
                store.close()

    def test_multiple_visible_background_windows_fail_ambiguous_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            store, body, app, executable = self._fixture(tmp, processes=processes, windows=windows)
            processes.append(self._process(executable))
            windows.extend([self._window(hwnd=66), self._window(hwnd=67)])
            try:
                result = body.act("activate_application_window", event_id="evt-ambiguous", application_id=app.app_id)
                self.assertFalse(result.success)
                self.assertEqual(result.data["disposition"], "ambiguous_visible_windows")
                self.assertFalse(result.data["dispatch_sent"])
                self.assertEqual(body.activations, [])
            finally:
                store.close()

    def test_activation_running_without_visible_window_fails_conservatively(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            store, body, app, executable = self._fixture(tmp, processes=processes)
            processes.append(self._process(executable))
            try:
                result = body.act("activate_application_window", event_id="evt-no-window", application_id=app.app_id)
                self.assertFalse(result.success)
                self.assertEqual(result.data["disposition"], "already_running_without_visible_window")
                self.assertFalse(result.data["dispatch_sent"])
                self.assertEqual(body.activations, [])
            finally:
                store.close()

    def test_exact_hwnd_disappearing_before_dispatch_fails_without_retarget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "notepad.exe"
            windows = _SequencedProvider([self._window(hwnd=66)], [])
            processes = [self._process(executable)]
            store, body, app, _ = self._fixture(tmp, processes=processes, windows=windows)
            try:
                result = body.act("activate_application_window", event_id="evt-stale", application_id=app.app_id)
                self.assertFalse(result.success)
                self.assertEqual(result.data["disposition"], "stale_window_handle")
                self.assertFalse(result.data["dispatch_sent"])
                self.assertEqual(body.activations, [])
            finally:
                store.close()

    def test_same_app_replacement_hwnd_fails_without_silent_retarget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "notepad.exe"
            windows = _SequencedProvider(
                [self._window(hwnd=66)],
                [self._window(hwnd=77)],
            )
            processes = [self._process(executable)]
            store, body, app, _ = self._fixture(tmp, processes=processes, windows=windows)
            try:
                result = body.act("activate_application_window", event_id="evt-replaced", application_id=app.app_id)
                self.assertFalse(result.success)
                self.assertEqual(result.data["window_handle"], 66)
                self.assertEqual(result.data["disposition"], "stale_window_handle")
                self.assertEqual(body.activations, [])
            finally:
                store.close()

    def test_exact_hwnd_changing_process_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "notepad.exe"
            process_rows = [self._process(executable, 55), self._process(executable, 99)]
            windows = _SequencedProvider(
                [self._window(hwnd=66, pid=55)],
                [self._window(hwnd=66, pid=99)],
            )
            store, body, app, _ = self._fixture(tmp, processes=process_rows, windows=windows)
            try:
                result = body.act("activate_application_window", event_id="evt-pid-drift", application_id=app.app_id)
                self.assertFalse(result.success)
                self.assertEqual(result.data["disposition"], "stale_window_process")
                self.assertEqual(result.data["observed_process_id"], 99)
                self.assertEqual(body.activations, [])
            finally:
                store.close()

    def test_exact_window_hidden_before_dispatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "notepad.exe"
            windows = _SequencedProvider(
                [self._window(visible=True)],
                [self._window(visible=False)],
            )
            store, body, app, _ = self._fixture(tmp, processes=[self._process(executable)], windows=windows)
            try:
                result = body.act("activate_application_window", event_id="evt-hidden-race", application_id=app.app_id)
                self.assertFalse(result.success)
                self.assertEqual(result.data["disposition"], "window_became_hidden")
                self.assertEqual(body.activations, [])
            finally:
                store.close()

    def test_exact_window_becoming_foreground_before_dispatch_skips_native_activation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "notepad.exe"
            windows = _SequencedProvider(
                [self._window(foreground=False)],
                [self._window(foreground=True)],
            )
            store, body, app, _ = self._fixture(tmp, processes=[self._process(executable)], windows=windows)
            try:
                result = body.act("activate_application_window", event_id="evt-fg-race", application_id=app.app_id)
                self.assertTrue(result.success)
                self.assertEqual(result.data["disposition"], "already_foreground_race")
                self.assertFalse(result.data["dispatch_sent"])
                self.assertEqual(body.activations, [])
            finally:
                store.close()

    def test_set_foreground_false_is_truthful_failure_with_dispatch_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            store, body, app, executable = self._fixture(tmp, processes=processes, windows=windows)
            processes.append(self._process(executable))
            windows.append(self._window())
            body.activation_result = {
                "success": False,
                "dispatch_sent": True,
                "was_minimized": False,
                "restore_requested": False,
                "restore_returned_true": False,
                "set_foreground_returned_true": False,
                "disposition": "foreground_policy_rejected",
                "error": "Windows foreground policy rejected activation",
            }
            try:
                result = body.act("activate_application_window", event_id="evt-policy", application_id=app.app_id)
                self.assertFalse(result.success)
                self.assertTrue(result.data["dispatch_sent"])
                self.assertFalse(result.data["set_foreground_returned_true"])
                self.assertEqual(body.activations, [(66, 55)])
            finally:
                store.close()

    def test_restore_then_foreground_failure_preserves_partial_side_effect_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            store, body, app, executable = self._fixture(tmp, processes=processes, windows=windows)
            processes.append(self._process(executable))
            windows.append(self._window())
            body.activation_result = {
                "success": False,
                "dispatch_sent": True,
                "was_minimized": True,
                "restore_requested": True,
                "restore_returned_true": True,
                "set_foreground_returned_true": False,
                "disposition": "foreground_policy_rejected",
                "error": "Windows foreground policy rejected activation",
            }
            try:
                result = body.act("activate_application_window", event_id="evt-partial", application_id=app.app_id)
                self.assertFalse(result.success)
                self.assertTrue(result.data["dispatch_sent"])
                self.assertTrue(result.data["was_minimized"])
                self.assertTrue(result.data["restore_requested"])
                self.assertTrue(result.data["restore_returned_true"])
                self.assertFalse(result.data["set_foreground_returned_true"])
            finally:
                store.close()

    def test_native_helper_non_minimized_validates_before_single_foreground_request(self) -> None:
        api = _FakeActivationApi(minimized=False)
        result = _activate_exact_application_window(66, 55, api=api)
        self.assertTrue(result["success"])
        self.assertFalse(result["restore_requested"])
        self.assertEqual(
            [call[0] for call in api.calls],
            ["IsWindow", "GetWindowThreadProcessId", "IsWindowVisible", "IsIconic", "SetForegroundWindow"],
        )

    def test_native_helper_minimized_restores_before_single_foreground_request(self) -> None:
        api = _FakeActivationApi(minimized=True)
        result = _activate_exact_application_window(66, 55, api=api)
        self.assertTrue(result["success"])
        self.assertTrue(result["restore_requested"])
        self.assertEqual(
            [call[0] for call in api.calls],
            [
                "IsWindow", "GetWindowThreadProcessId", "IsWindowVisible", "IsIconic",
                "ShowWindowAsync", "SetForegroundWindow",
            ],
        )
        self.assertEqual(api.calls[4], ("ShowWindowAsync", 66, api.SW_RESTORE))

    def test_native_helper_revalidates_pid_and_never_dispatches_on_mismatch(self) -> None:
        api = _FakeActivationApi(pid=99)
        result = _activate_exact_application_window(66, 55, api=api)
        self.assertFalse(result["success"])
        self.assertFalse(result["dispatch_sent"])
        self.assertEqual([call[0] for call in api.calls], ["IsWindow", "GetWindowThreadProcessId"])

    def test_native_helper_set_foreground_false_reports_failure_without_retry(self) -> None:
        api = _FakeActivationApi(minimized=True, foreground_result=False)
        result = _activate_exact_application_window(66, 55, api=api)
        self.assertFalse(result["success"])
        self.assertTrue(result["dispatch_sent"])
        self.assertTrue(result["restore_requested"])
        self.assertFalse(result["set_foreground_returned_true"])
        self.assertEqual(sum(call[0] == "SetForegroundWindow" for call in api.calls), 1)


if __name__ == "__main__":
    unittest.main()
