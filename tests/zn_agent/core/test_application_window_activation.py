from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.machine_capability import ApplicationInventoryCandidate, DeviceCapabilityGraph
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


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
        )
        application = graph.installed_applications(force_refresh=True)[0]
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )
        resident.device_capabilities = graph
        resident.body.device_capabilities = graph
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
    def _actions(resident, kind: str):
        return [action for action in resident.body.recent_actions(100) if action.kind == kind]

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
                activation_actions = self._actions(resident, "activate_application_window")
                self.assertEqual(len(activation_actions), 1)
                self.assertTrue(activation_actions[0].data["dispatch_sent"])
                self.assertEqual(activation_actions[0].data["window_handle"], 66)
                self.assertEqual(activation_actions[0].data["process_id"], 55)
                self.assertEqual(self._actions(resident, "launch_application"), [])
                verification = resident.store.get_working_state().data["native_verification_result"]
                self.assertTrue(verification["verified"])
                self.assertEqual(verification["expected_window_handle"], 66)
                self.assertEqual(verification["foreground_window_handle"], 66)
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
                self.assertEqual(len(self._actions(resident, "activate_application_window")), 1)
                verification = resident.store.get_working_state().data["native_verification_result"]
                self.assertFalse(verification["verified"])
                self.assertEqual(verification["observation_count"], 3)
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

            def activate(hwnd, pid):
                windows.append(self._window(hwnd=77, foreground=True))
                return self._native_success()

            resident.body._native_activate_exact_application_window = activate
            try:
                self._enqueue_open(resident, app)
                result = self._run_to_terminal(resident)
                self.assertFalse(result.success)
                verification = resident.store.get_working_state().data["native_verification_result"]
                self.assertEqual(verification["expected_window_handle"], 66)
                self.assertEqual(verification["foreground_window_handle"], 77)
                self.assertEqual(verification["foreground_application_id"], app.app_id)
                self.assertFalse(verification["verified"])
                self.assertEqual(len(self._actions(resident, "activate_application_window")), 1)
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
