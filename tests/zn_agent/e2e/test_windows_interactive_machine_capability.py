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
        resident = None
        launched_windows = ()
        preexisting_pids: set[int] = set()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                resident = build_resident_runtime(
                    config={"model": {}},
                    store_path=Path(tmp) / "kernel.db",
                )
                graph = resident.device_capabilities
                applications = graph.installed_applications(force_refresh=True)
                self.assertTrue(applications, "real Windows inventory returned no installed applications")
                self.assertEqual(len({app.app_id for app in applications}), len(applications))

                # Select only a known benign GUI application discovered from this
                # actual machine.  The test never assumes a path or package id.
                safe_names = ("Notepad", "Microsoft Paint")
                selected = None
                for name in safe_names:
                    resolution = graph.resolve_application(name)
                    if resolution.status != "resolved" or resolution.application is None:
                        continue
                    candidate = resolution.application
                    if not candidate.launchable:
                        continue
                    processes, windows = graph.application_runtime(candidate)
                    if not processes and not windows:
                        selected = candidate
                        break
                self.assertIsNotNone(
                    selected,
                    "zn-interactive must expose at least one discovered, launchable, non-running benign system GUI app",
                )

                before_processes, _ = graph.application_runtime(selected)
                preexisting_pids = {row.process_id for row in before_processes}
                event = resident.enqueue(
                    f"打开 {selected.canonical_name}",
                    kind="desktop_user_event",
                    payload={"model_policy": "never"},
                )
                result = self._run_to_terminal(resident)
                self.assertTrue(result.success, result)
                self.assertEqual(result.model_invocations, 0)

                after_processes, launched_windows = graph.application_runtime(selected)
                self.assertTrue(after_processes, "launch completion lacked a fresh matching process")
                self.assertTrue(
                    [window for window in launched_windows if window.visible],
                    "launch completion lacked a fresh matching visible top-level window",
                )
                first_pids = {row.process_id for row in after_processes}
                self.assertTrue(first_pids - preexisting_pids)

                # A second ordinary “open” request must observe the existing
                # instance and complete without dispatching another launch.
                resident.enqueue(
                    f"打开 {selected.canonical_name}",
                    kind="desktop_user_event",
                    payload={"model_policy": "never"},
                )
                second = self._run_to_terminal(resident)
                self.assertTrue(second.success, second)
                self.assertEqual(second.model_invocations, 0)
                second_processes, _ = graph.application_runtime(selected)
                self.assertEqual({row.process_id for row in second_processes}, first_pids)

                launch_actions = [
                    action for action in resident.body.recent_actions(30)
                    if action.kind == "launch_application"
                ]
                self.assertTrue(launch_actions)
                dispatched = [action for action in launch_actions if action.data.get("dispatch_sent")]
                self.assertEqual(len(dispatched), 1)
                self.assertTrue(any(
                    action.data.get("disposition") == "already_running" for action in launch_actions
                ))
                resident.store.close()
                resident = None
        finally:
            if resident is not None:
                resident.store.close()
            if launched_windows:
                self._close_new_windows(launched_windows, preexisting_pids)

    def test_real_machine_unknown_application_is_not_invented(self) -> None:
        self._require_input_desktop()
        with tempfile.TemporaryDirectory() as tmp:
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
