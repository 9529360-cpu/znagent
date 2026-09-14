from __future__ import annotations

import ctypes
import os
import tempfile
import time
import unittest
from ctypes import wintypes
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime


class WindowsInteractiveMachineCapabilityE2ETests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        if os.name != "nt":
            raise unittest.SkipTest("Windows machine capability E2E runs only on Windows")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        user32.OpenInputDesktop.restype = wintypes.HANDLE
        user32.SwitchDesktop.argtypes = [wintypes.HANDLE]
        user32.SwitchDesktop.restype = wintypes.BOOL
        user32.CloseDesktop.argtypes = [wintypes.HANDLE]
        user32.CloseDesktop.restype = wintypes.BOOL
        desktop = user32.OpenInputDesktop(0, False, 0x0001 | 0x0080 | 0x0100)
        if not desktop:
            raise AssertionError("zn-interactive runner cannot open the Windows input desktop")
        try:
            if not user32.SwitchDesktop(desktop):
                raise AssertionError("zn-interactive runner cannot switch to the Windows input desktop")
        finally:
            user32.CloseDesktop(desktop)

    @staticmethod
    def _run_to_terminal(resident, limit: int = 40):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
            time.sleep(0.10)
        raise AssertionError("resident did not reach a terminal result within bounded pulses")

    @staticmethod
    def _close_new_windows(windows, preexisting_pids: set[int]) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW.restype = wintypes.BOOL
        for window in windows:
            if int(window.process_id) not in preexisting_pids:
                user32.PostMessageW(int(window.hwnd), 0x0010, 0, 0)  # WM_CLOSE

    def test_real_inventory_launch_verify_and_already_running_no_duplicate(self) -> None:
        self._require_input_desktop()
        # Windows may retain a transient sqlite file handle for a few milliseconds
        # after the runtime is closed. Cleanup is not the product assertion here.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            launched_windows = ()
            preexisting_pids: set[int] = set()
            try:
                graph = resident.device_capabilities
                applications = graph.installed_applications(force_refresh=True)
                self.assertTrue(applications, "real Windows inventory returned no installed applications")
                self.assertEqual(len({app.app_id for app in applications}), len(applications))

                # Select only a known benign interactive application discovered
                # from this actual machine. The test never assumes an executable
                # path, package id or AUMID. The dedicated runner can legitimately
                # retain one shell app between jobs, so use several built-in
                # candidates while still requiring one real zero-instance launch.
                safe_names = (
                    "Notepad",
                    "Microsoft Paint",
                    "Command Prompt",
                    "Windows Terminal",
                )
                selected = None
                safe_diagnostics: list[str] = []
                for name in safe_names:
                    resolution = graph.resolve_application(name)
                    if resolution.status != "resolved" or resolution.application is None:
                        safe_diagnostics.append(f"{name}:resolution={resolution.status}")
                        continue
                    candidate = resolution.application
                    if not candidate.launchable:
                        safe_diagnostics.append(
                            f"{name}:app_id={candidate.app_id}:launchable=false"
                        )
                        continue
                    processes, windows = graph.application_runtime(candidate)
                    visible_windows = [window for window in windows if window.visible]
                    safe_diagnostics.append(
                        f"{name}:app_id={candidate.app_id}:processes={len(processes)}:"
                        f"visible_windows={len(visible_windows)}"
                    )
                    if not processes and not windows:
                        selected = candidate
                        break
                self.assertIsNotNone(
                    selected,
                    "zn-interactive must expose at least one discovered, launchable, "
                    "non-running benign system application; observations="
                    + "; ".join(safe_diagnostics),
                )

                before_processes, _ = graph.application_runtime(selected)
                preexisting_pids = {row.process_id for row in before_processes}
                resident.enqueue(
                    f"打开 {selected.canonical_name}",
                    kind="desktop_user_event",
                    payload={"model_policy": "never"},
                )
                result = self._run_to_terminal(resident)
                self.assertTrue(result.success, result)
                self.assertEqual(result.model_invocations, 0)

                after_processes, launched_windows = graph.application_runtime(selected)
                self.assertTrue(after_processes, "launch completion lacked a fresh matching process")
                visible_after_launch = [window for window in launched_windows if window.visible]
                self.assertEqual(
                    len(visible_after_launch),
                    1,
                    "the no-duplicate follow-up requires one exact visible launched window",
                )
                target_window = visible_after_launch[0]
                first_pids = {row.process_id for row in after_processes}
                self.assertTrue(first_pids - preexisting_pids)
                self.assertIn(int(target_window.process_id), first_pids)

                launch_actions_before = [
                    action for action in resident.body.recent_actions(30)
                    if action.kind == "launch_application"
                ]
                dispatched_before = [
                    action for action in launch_actions_before if action.data.get("dispatch_sent")
                ]
                self.assertEqual(len(dispatched_before), 1)

                # A second ordinary “open” request must never manufacture another
                # process. If the just-launched window is still foreground, fresh
                # machine facts may complete the request without Body movement. If
                # Windows has moved foreground elsewhere, Resident may request one
                # exact HWND/PID activation. Win32 explicitly permits foreground
                # policy to reject SetForegroundWindow, so that bounded fail-closed
                # outcome is valid here; the dedicated application-activation E2E
                # separately proves the success path under controlled entitlement.
                resident.enqueue(
                    f"打开 {selected.canonical_name}",
                    kind="desktop_user_event",
                    payload={"model_policy": "never"},
                )
                second = self._run_to_terminal(resident)
                self.assertEqual(second.model_invocations, 0)

                second_processes, second_windows = graph.application_runtime(selected)
                self.assertEqual({row.process_id for row in second_processes}, first_pids)
                exact_second_window = next(
                    (window for window in second_windows if window.hwnd == target_window.hwnd),
                    None,
                )
                self.assertIsNotNone(
                    exact_second_window,
                    "the exact launched window disappeared during the no-duplicate follow-up",
                )
                assert exact_second_window is not None
                self.assertEqual(exact_second_window.process_id, target_window.process_id)

                launch_actions_after = [
                    action for action in resident.body.recent_actions(30)
                    if action.kind == "launch_application"
                ]
                dispatched_after = [
                    action for action in launch_actions_after if action.data.get("dispatch_sent")
                ]
                self.assertEqual(len(dispatched_after), 1)
                self.assertEqual(len(launch_actions_after), len(launch_actions_before))

                activation_actions = [
                    action
                    for action in resident.body.recent_actions(30)
                    if action.kind == "activate_application_window"
                    and action.data.get("application_id") == selected.app_id
                ]
                self.assertLessEqual(
                    len(activation_actions),
                    1,
                    "the existing-window path must never replay foreground activation",
                )

                if second.success:
                    fresh_foreground = graph.foreground_application()
                    self.assertIsNotNone(
                        fresh_foreground,
                        "successful second open lacked a fresh foreground observation",
                    )
                    assert fresh_foreground is not None
                    self.assertEqual(fresh_foreground.window.hwnd, target_window.hwnd)
                    self.assertEqual(fresh_foreground.window.process_id, target_window.process_id)
                    self.assertIsNotNone(fresh_foreground.application)
                    self.assertEqual(fresh_foreground.application.app_id, selected.app_id)
                    if activation_actions:
                        activation = activation_actions[0]
                        self.assertTrue(activation.data.get("dispatch_sent"))
                        self.assertEqual(activation.data.get("window_handle"), target_window.hwnd)
                        self.assertEqual(activation.data.get("process_id"), target_window.process_id)
                else:
                    self.assertEqual(
                        len(activation_actions),
                        1,
                        "a failed second open is admissible here only as exact foreground-policy failure",
                    )
                    activation = activation_actions[0]
                    self.assertTrue(activation.data.get("dispatch_sent"))
                    self.assertEqual(activation.data.get("window_handle"), target_window.hwnd)
                    self.assertEqual(activation.data.get("process_id"), target_window.process_id)
                    self.assertIn(
                        activation.data.get("disposition"),
                        {"foreground_policy_rejected", "activation_requested"},
                    )
                    reason = str(second.reason or "")
                    self.assertIn("foreground", reason.lower())
                    self.assertIn("no duplicate launch", reason.lower())

                print(
                    "ZN_MACHINE_CAPABILITY_EXISTING_APP_EVIDENCE="
                    f"{{\"second_success\":{str(bool(second.success)).lower()},"
                    f"\"activation_count\":{len(activation_actions)},"
                    f"\"launch_dispatch_count\":{len(dispatched_after)},"
                    f"\"same_process_ids\":true}}",
                    flush=True,
                )
            finally:
                if launched_windows:
                    self._close_new_windows(launched_windows, preexisting_pids)
                    time.sleep(0.20)
                resident.store.close()

    def test_real_machine_unknown_application_is_not_invented(self) -> None:
        self._require_input_desktop()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                impossible = "ZN Definitely Missing Application 7f4f42d7"
                resolution = resident.device_capabilities.resolve_application(
                    impossible, force_refresh=True
                )
                self.assertEqual(resolution.status, "not_installed")
                self.assertIsNone(resolution.application)
                resident.enqueue(
                    f"打开 {impossible}",
                    kind="desktop_user_event",
                    payload={"model_policy": "never"},
                )
                result = self._run_to_terminal(resident)
                self.assertFalse(result.success)
                self.assertEqual(result.model_invocations, 0)
                self.assertIn("not installed", result.reason.lower())
                self.assertFalse(any(
                    action.kind == "launch_application"
                    for action in resident.body.recent_actions(20)
                ))
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
