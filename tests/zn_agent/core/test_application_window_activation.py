from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.device_capability_graph import DeviceCapabilityGraph
from zn_agent.core.machine_capability import ApplicationInventoryCandidate
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.windows_companion_context import NativeWindowsCompanionContextSense


class ApplicationWindowActivationResidentTests(unittest.TestCase):
    def _resident(self, tmp: str, *, processes: list[dict], windows: list[dict]):
        executable = Path(tmp) / "notepad.exe"
        executable.write_bytes(b"")
        graph = DeviceCapabilityGraph(
            inventory_provider=lambda: [
                ApplicationInventoryCandidate(
                    source="app_paths", source_id="notepad", display_name="Notepad",
                    executable_path=str(executable), identity_paths=(str(executable),),
                    launch_kind="executable", launch_target=str(executable),
                )
            ],
            process_provider=lambda: list(processes),
            window_provider=lambda: list(windows),
            cache_path=Path(tmp) / "apps.json", inventory_ttl_seconds=0,
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
        application = graph.installed_applications(force_refresh=True)[0]
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )
        resident.device_capabilities = graph
        resident.body.device_capabilities = graph
        resident.body._current_session_connection_state = lambda _session_id: "active"
        return resident, application, executable

    @staticmethod
    def _process(executable: Path, pid: int = 55, *, name: str = "notepad.exe"):
        return {"pid": pid, "name": name, "exe": str(executable)}

    @staticmethod
    def _window(*, hwnd=66, pid=55, visible=True, foreground=False, title="Untitled - Notepad"):
        return {
            "hwnd": hwnd, "pid": pid, "title": title,
            "class_name": "Notepad", "visible": visible, "foreground": foreground,
        }

    @staticmethod
    def _native_success(*, minimized=False):
        return {
            "success": True,
            "dispatch_sent": True,
            "was_minimized": minimized,
            "restore_requested": minimized,
            "restore_returned_true": minimized,
            "set_foreground_returned_true": True,
            "disposition": "activation_requested",
        }

    @staticmethod
    def _run_to_terminal(resident, limit: int = 80):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach a terminal result within bounded pulses")

    @staticmethod
    def _run_until_native_action(resident, limit: int = 40):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                raise AssertionError(f"resident terminated before native action admission: {result}")
            state = resident.store.get_working_state()
            if state.stage == "native_action":
                return state
        raise AssertionError("resident did not admit a native action within bounded pulses")

    @staticmethod
    def _actions(resident, kind: str):
        return [action for action in resident.body.recent_actions(100) if action.kind == kind]

    @staticmethod
    def _track_foreground_observations(resident):
        original = resident.device_capabilities.foreground_application
        observed_handles: list[int | None] = []

        def probe():
            observation = original()
            observed_handles.append(
                observation.window.hwnd if observation is not None else None
            )
            return observation

        resident.device_capabilities.foreground_application = probe
        return observed_handles

    def _enqueue_open(self, resident, application):
        return resident.enqueue(
            f"打开 {application.canonical_name}",
            kind="desktop_user_event",
            payload={"model_policy": "never"},
        )

    def test_already_foreground_completes_from_fresh_evidence_without_body_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            resident, app, executable = self._resident(tmp, processes=processes, windows=windows)
            processes.append(self._process(executable))
            windows.append(self._window(foreground=True))
            try:
                self._enqueue_open(resident, app)
                result = self._run_to_terminal(resident)
                self.assertTrue(result.success, result)
                self.assertEqual(result.model_invocations, 0)
                self.assertIn("foreground", result.response.lower())
                self.assertEqual(self._actions(resident, "activate_application_window"), [])
                self.assertEqual(self._actions(resident, "launch_application"), [])
            finally:
                resident.store.close()

    def test_one_visible_background_window_activates_once_then_requires_exact_foreground_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            resident, app, executable = self._resident(tmp, processes=processes, windows=windows)
            processes.append(self._process(executable))
            windows.append(self._window())
            native_calls: list[tuple[int, int]] = []
            foreground_observations = self._track_foreground_observations(resident)

            def activate(hwnd, pid):
                native_calls.append((hwnd, pid))
                windows[0]["foreground"] = True
                return self._native_success()

            resident.body._native_activate_exact_application_window = activate
            try:
                self._enqueue_open(resident, app)
                result = self._run_to_terminal(resident)
                self.assertTrue(result.success, result)
                self.assertEqual(result.model_invocations, 0)
                self.assertEqual(native_calls, [(66, 55)])
                self.assertEqual(foreground_observations, [66])
                self.assertIn("exact authority-bound hwnd/pid", result.reason.lower())
                activation_actions = self._actions(resident, "activate_application_window")
                self.assertEqual(len(activation_actions), 1)
                self.assertTrue(activation_actions[0].data["dispatch_sent"])
                self.assertEqual(activation_actions[0].data["window_handle"], 66)
                self.assertEqual(activation_actions[0].data["process_id"], 55)
                self.assertEqual(self._actions(resident, "launch_application"), [])
            finally:
                resident.store.close()

    def test_replacement_between_resident_admission_and_body_fails_before_native_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            resident, app, executable = self._resident(tmp, processes=processes, windows=windows)
            processes.append(self._process(executable, 55))
            windows.append(self._window(hwnd=66, pid=55))
            native_calls: list[tuple[int, int]] = []
            resident.body._native_activate_exact_application_window = lambda hwnd, pid: (
                native_calls.append((hwnd, pid)) or self._native_success()
            )
            try:
                self._enqueue_open(resident, app)
                state = self._run_until_native_action(resident)
                expected = state.data["native_action_intent"]["expected_outcome"]
                self.assertEqual((expected["expected_window_handle"], expected["expected_process_id"]), (66, 55))
                windows[:] = [self._window(hwnd=77, pid=55)]
                result = self._run_to_terminal(resident)
                self.assertFalse(result.success)
                self.assertEqual(native_calls, [])
                self.assertEqual(self._actions(resident, "launch_application"), [])
                self.assertNotIn((77, 55), native_calls)
            finally:
                resident.store.close()

    def test_pid_drift_between_resident_admission_and_body_fails_before_native_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            resident, app, executable = self._resident(tmp, processes=processes, windows=windows)
            processes.append(self._process(executable, 55))
            windows.append(self._window(hwnd=66, pid=55))
            native_calls: list[tuple[int, int]] = []
            resident.body._native_activate_exact_application_window = lambda hwnd, pid: (
                native_calls.append((hwnd, pid)) or self._native_success()
            )
            try:
                self._enqueue_open(resident, app)
                self._run_until_native_action(resident)
                processes[:] = [self._process(executable, 99)]
                windows[:] = [self._window(hwnd=66, pid=99)]
                result = self._run_to_terminal(resident)
                self.assertFalse(result.success)
                self.assertEqual(native_calls, [])
                self.assertEqual(self._actions(resident, "launch_application"), [])
            finally:
                resident.store.close()

    def test_new_sibling_after_resident_admission_fails_before_native_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            resident, app, executable = self._resident(tmp, processes=processes, windows=windows)
            processes.append(self._process(executable, 55))
            windows.append(self._window(hwnd=66, pid=55))
            native_calls: list[tuple[int, int]] = []
            resident.body._native_activate_exact_application_window = lambda hwnd, pid: (
                native_calls.append((hwnd, pid)) or self._native_success()
            )
            try:
                self._enqueue_open(resident, app)
                self._run_until_native_action(resident)
                windows.append(self._window(hwnd=77, pid=55))
                result = self._run_to_terminal(resident)
                self.assertFalse(result.success)
                self.assertEqual(native_calls, [])
                self.assertEqual(self._actions(resident, "launch_application"), [])
            finally:
                resident.store.close()

    def test_admitted_target_disappears_without_fallback_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            resident, app, executable = self._resident(tmp, processes=processes, windows=windows)
            processes.append(self._process(executable, 55))
            windows.append(self._window(hwnd=66, pid=55))
            native_calls: list[tuple[int, int]] = []
            resident.body._native_activate_exact_application_window = lambda hwnd, pid: (
                native_calls.append((hwnd, pid)) or self._native_success()
            )
            try:
                self._enqueue_open(resident, app)
                self._run_until_native_action(resident)
                windows.clear()
                result = self._run_to_terminal(resident)
                self.assertFalse(result.success)
                self.assertEqual(native_calls, [])
                self.assertEqual(self._actions(resident, "launch_application"), [])
            finally:
                resident.store.close()

    def test_exact_admitted_target_becoming_foreground_before_body_skips_native_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            resident, app, executable = self._resident(tmp, processes=processes, windows=windows)
            processes.append(self._process(executable, 55))
            windows.append(self._window(hwnd=66, pid=55))
            native_calls: list[tuple[int, int]] = []
            resident.body._native_activate_exact_application_window = lambda hwnd, pid: (
                native_calls.append((hwnd, pid)) or self._native_success()
            )
            try:
                self._enqueue_open(resident, app)
                self._run_until_native_action(resident)
                windows[0]["foreground"] = True
                result = self._run_to_terminal(resident)
                self.assertTrue(result.success, result)
                self.assertEqual(native_calls, [])
                activation_actions = self._actions(resident, "activate_application_window")
                self.assertEqual(len(activation_actions), 1)
                self.assertFalse(activation_actions[0].data["dispatch_sent"])
                self.assertEqual(activation_actions[0].data["window_handle"], 66)
                self.assertEqual(activation_actions[0].data["process_id"], 55)
                self.assertEqual(self._actions(resident, "launch_application"), [])
            finally:
                resident.store.close()

    def test_multiple_visible_background_windows_fail_ambiguous_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            resident, app, executable = self._resident(tmp, processes=processes, windows=windows)
            processes.append(self._process(executable))
            windows.extend([self._window(hwnd=66), self._window(hwnd=67)])
            try:
                self._enqueue_open(resident, app)
                result = self._run_to_terminal(resident)
                self.assertFalse(result.success)
                self.assertEqual(result.model_invocations, 0)
                self.assertIn("multiple visible", result.reason.lower())
                self.assertEqual(self._actions(resident, "activate_application_window"), [])
                self.assertEqual(self._actions(resident, "launch_application"), [])
            finally:
                resident.store.close()

    def test_process_without_visible_window_preserves_conservative_no_duplicate_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            resident, app, executable = self._resident(tmp, processes=processes, windows=windows)
            processes.append(self._process(executable))
            try:
                self._enqueue_open(resident, app)
                result = self._run_to_terminal(resident)
                self.assertFalse(result.success)
                self.assertEqual(result.model_invocations, 0)
                self.assertIn("no currently visible", result.reason.lower())
                self.assertEqual(self._actions(resident, "activate_application_window"), [])
                self.assertEqual(self._actions(resident, "launch_application"), [])
            finally:
                resident.store.close()

    def test_no_process_preserves_existing_launch_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            resident, app, executable = self._resident(tmp, processes=processes, windows=windows)
            launch_calls: list[str] = []

            def launch(application):
                launch_calls.append(application.app_id)
                processes.append(self._process(executable))
                windows.append(self._window(foreground=True))
                return 55

            resident.body._dispatch_resolved_application = launch
            try:
                self._enqueue_open(resident, app)
                result = self._run_to_terminal(resident)
                self.assertTrue(result.success, result)
                self.assertEqual(result.model_invocations, 0)
                self.assertEqual(launch_calls, [app.app_id])
                launch_actions = self._actions(resident, "launch_application")
                self.assertEqual(len(launch_actions), 1)
                self.assertTrue(launch_actions[0].data["dispatch_sent"])
                self.assertEqual(self._actions(resident, "activate_application_window"), [])
            finally:
                resident.store.close()

    def test_set_foreground_true_is_not_completion_and_bounded_verification_never_redispatches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            resident, app, executable = self._resident(tmp, processes=processes, windows=windows)
            resident._MAX_APPLICATION_VERIFICATION_OBSERVATIONS = 3
            processes.append(self._process(executable))
            windows.append(self._window(foreground=False))
            native_calls: list[tuple[int, int]] = []
            foreground_observations = self._track_foreground_observations(resident)

            def activate(hwnd, pid):
                native_calls.append((hwnd, pid))
                return self._native_success()

            resident.body._native_activate_exact_application_window = activate
            try:
                self._enqueue_open(resident, app)
                result = self._run_to_terminal(resident)
                self.assertFalse(result.success)
                self.assertEqual(result.model_invocations, 0)
                self.assertIn("foreground transition", result.reason.lower())
                self.assertEqual(native_calls, [(66, 55)])
                self.assertEqual(foreground_observations, [None, None, None])
                self.assertEqual(len(self._actions(resident, "activate_application_window")), 1)
                self.assertEqual(self._actions(resident, "launch_application"), [])
            finally:
                resident.store.close()

    def test_foreground_another_application_fails_exact_postcondition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            resident, app, executable = self._resident(tmp, processes=processes, windows=windows)
            resident._MAX_APPLICATION_VERIFICATION_OBSERVATIONS = 2
            other_executable = Path(tmp) / "other.exe"
            other_executable.write_bytes(b"")
            processes.extend([
                self._process(executable, 55),
                {"pid": 99, "name": "other.exe", "exe": str(other_executable)},
            ])
            windows.extend([
                self._window(hwnd=66, pid=55, foreground=False),
                {
                    "hwnd": 99,
                    "pid": 99,
                    "title": "Other App",
                    "class_name": "OtherWindow",
                    "visible": True,
                    "foreground": True,
                },
            ])
            native_calls: list[tuple[int, int]] = []
            foreground_observations = self._track_foreground_observations(resident)

            def activate(hwnd, pid):
                native_calls.append((hwnd, pid))
                return self._native_success()

            resident.body._native_activate_exact_application_window = activate
            try:
                self._enqueue_open(resident, app)
                result = self._run_to_terminal(resident)
                self.assertFalse(result.success)
                self.assertEqual(result.model_invocations, 0)
                self.assertIn("foreground transition", result.reason.lower())
                self.assertEqual(native_calls, [(66, 55)])
                self.assertEqual(foreground_observations, [99, 99])
                self.assertEqual(len(self._actions(resident, "activate_application_window")), 1)
                self.assertEqual(self._actions(resident, "launch_application"), [])
            finally:
                resident.store.close()

    def test_foreground_different_hwnd_of_same_app_fails_first_slice_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            resident, app, executable = self._resident(tmp, processes=processes, windows=windows)
            resident._MAX_APPLICATION_VERIFICATION_OBSERVATIONS = 2
            processes.append(self._process(executable))
            windows.append(self._window(hwnd=66, foreground=False))
            foreground_observations = self._track_foreground_observations(resident)

            def activate(hwnd, pid):
                windows.append(self._window(hwnd=77, foreground=True))
                return self._native_success()

            resident.body._native_activate_exact_application_window = activate
            try:
                self._enqueue_open(resident, app)
                result = self._run_to_terminal(resident)
                self.assertFalse(result.success)
                self.assertIn("foreground transition", result.reason.lower())
                self.assertEqual(foreground_observations, [77, 77])
                self.assertEqual(len(self._actions(resident, "activate_application_window")), 1)
                self.assertEqual(self._actions(resident, "launch_application"), [])
            finally:
                resident.store.close()

    def test_foreground_policy_refusal_fails_without_activation_replay_or_duplicate_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processes: list[dict] = []
            windows: list[dict] = []
            resident, app, executable = self._resident(tmp, processes=processes, windows=windows)
            processes.append(self._process(executable))
            windows.append(self._window())
            native_calls: list[tuple[int, int]] = []

            def activate(hwnd, pid):
                native_calls.append((hwnd, pid))
                return {
                    "success": False,
                    "dispatch_sent": True,
                    "was_minimized": False,
                    "restore_requested": False,
                    "restore_returned_true": False,
                    "set_foreground_returned_true": False,
                    "disposition": "foreground_policy_rejected",
                    "error": "Windows foreground policy rejected activation",
                }

            resident.body._native_activate_exact_application_window = activate
            try:
                self._enqueue_open(resident, app)
                result = self._run_to_terminal(resident)
                self.assertFalse(result.success)
                self.assertEqual(result.model_invocations, 0)
                self.assertIn("foreground policy", result.reason.lower())
                self.assertIn("no duplicate launch", result.reason.lower())
                self.assertEqual(native_calls, [(66, 55)])
                self.assertEqual(len(self._actions(resident, "activate_application_window")), 1)
                self.assertEqual(self._actions(resident, "launch_application"), [])
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
